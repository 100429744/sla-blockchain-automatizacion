import sys, os, time, json, statistics, requests
from web3 import Web3
from datetime import datetime

if len(sys.argv) < 6:
    print("Uso correcto: python3 oracle.py <PRIVATE_KEY> <PUBLIC_ADDRESS> <ORACLE_ID> <NETWORK> <MODO_SIMULACION>")
    sys.exit(1)

PRIVATE_KEY, PUBLIC_ADDRESS, ORACLE_ID, NETWORK, MODO_SIMULACION = sys.argv[1:6]
NETWORK = NETWORK.upper()
MODO_SIMULACION = MODO_SIMULACION.upper()
AGENT_NAME = f"ORACLE_{ORACLE_ID}"

LOG_FILE = f"oracle_{ORACLE_ID}_{NETWORK}_events.json"
GAS_LOG_FILE = f"oracle_{ORACLE_ID}_{NETWORK}_gas.json" if ORACLE_ID == "1" else None
CONSUMER_API = "http://10.0.2.5:8000/api/v1/metrics/current-epoch"

print(f"[{AGENT_NAME}] [INFO] Iniciando secuencia de arranque en modo {MODO_SIMULACION}...")

if NETWORK == "L1":
    RPC_URL = ""
    CHAIN_ID = 
    CONTRACT_ADDRESS = ""
else:
    RPC_URL = ""
    CHAIN_ID = 
    CONTRACT_ADDRESS = ""

ABI = []

w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    sys.exit(f"[{AGENT_NAME}] [ERROR CRITICO] Imposible conectar con nodo RPC.")

contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=ABI)
print(f"[{AGENT_NAME}] [INFO] Conexion exitosa al contrato.")

def log_event(epoch, event_name, details=None):
    if details is None: details = {}
    now = time.time()
    entry = {"epoch": epoch, "simulation_mode": MODO_SIMULACION, "network": NETWORK, "agent": AGENT_NAME, "timestamp": now, "datetime": datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], "event": event_name, "details": details}
    try:
        data = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f: data = json.load(f)
        data.append(entry)
        with open(LOG_FILE, 'w') as f: json.dump(data, f, indent=4)
    except: pass

def log_gas_metric(epoch, tx_type, tx_hash, status, block_number, gas_used, eth_spent, minado_sec):
    if not GAS_LOG_FILE: return
    now = time.time()
    entry = {"epoch": epoch, "simulation_mode": MODO_SIMULACION, "network": NETWORK, "agent": AGENT_NAME, "timestamp": now, "datetime": datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], "transaction_type": tx_type, "tx_hash": tx_hash, "status": status, "block_number": block_number, "gas_used": gas_used, "eth_spent": eth_spent, "mining_time_seconds": minado_sec}
    try:
        data = []
        if os.path.exists(GAS_LOG_FILE):
            with open(GAS_LOG_FILE, 'r') as f: data = json.load(f)
        data.append(entry)
        with open(GAS_LOG_FILE, 'w') as f: json.dump(data, f, indent=4)
        print(f"[{AGENT_NAME}] [AUDITORIA] Metrica de gas registrada.")
    except Exception as e: print(f"[{AGENT_NAME}] [ERROR] Fallo en reporte gas: {e}")

def send_signed_tx(tx_data, event_prefix, current_epoch):
    print(f"[{AGENT_NAME}] [TX] Preparando transaccion {event_prefix} en blockchain...")
    tx_data['nonce'] = w3.eth.get_transaction_count(PUBLIC_ADDRESS)
    tx_data['chainId'] = CHAIN_ID

    try:
        base_fee = w3.eth.get_block('latest')['baseFeePerGas']
        priority_fee = w3.to_wei(1, 'gwei')
        max_fee = (base_fee * 2) + priority_fee
        tx_data['maxFeePerGas'] = max_fee
        tx_data['maxPriorityFeePerGas'] = priority_fee
    except Exception as e:
        print(f"[{AGENT_NAME}] [TX] Advertencia al calcular gas dinamico: {e}")
        tx_data['maxFeePerGas'] = w3.to_wei(25, 'gwei')
        tx_data['maxPriorityFeePerGas'] = w3.to_wei(2, 'gwei')

    signed = w3.eth.account.sign_transaction(tx_data, PRIVATE_KEY)

    # ⏱️ CRONÓMETRO INICIA
    t_inicio = time.time()
    log_event(current_epoch, f"{event_prefix}_BROADCAST")
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    print(f"[{AGENT_NAME}] [TX] Waiting for transaction {tx_hash.hex()} to be mined...")

    # ESPERAMOS RECIBO
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

    # ⏱️ CRONÓMETRO TERMINA
    t_fin = time.time()
    segundos_minado = round(t_fin - t_inicio, 3)

    # VERIFICACIÓN DE STATUS SOLICITADA
    if receipt.status != 1:
        print(f"[{AGENT_NAME}] [TX] Transaction {tx_hash.hex()} was mined in block {receipt.blockNumber} but failed (status=0).")
        tx_status = "Reverted"
    else:
        print(f"[{AGENT_NAME}] [TX] Transaction {tx_hash.hex()} successfully included in block {receipt.blockNumber} ({segundos_minado}s).")
        tx_status = "Success"

    gas_used = receipt.get('gasUsed', 0)
    bloque_minado = receipt.get('blockNumber', 0)
    effective_gas_price = receipt.get('effectiveGasPrice', tx_data.get('maxFeePerGas', 0))
    eth_spent = float(w3.from_wei(gas_used * effective_gas_price, 'ether'))

    print(f"[{AGENT_NAME}] [TX] MINADA en Bloque {bloque_minado} | Estado: {tx_status} | Gas Usado: {gas_used}")

    log_event(current_epoch, f"{event_prefix}_MINED", {
        "status": tx_status,
        "blockNumber": bloque_minado,
        "mining_time_seconds": segundos_minado
    })

    if GAS_LOG_FILE:
        log_gas_metric(current_epoch, event_prefix, tx_hash.hex(), tx_status, bloque_minado, gas_used, eth_spent, segundos_minado)

    if tx_status == "Reverted":
        raise Exception(f"Transaccion revertida por el contrato inteligente: {tx_hash.hex()}")

    return receipt

def oracle_loop():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w') as f: json.dump([], f)
    if GAS_LOG_FILE and not os.path.exists(GAS_LOG_FILE):
        with open(GAS_LOG_FILE, 'w') as f: json.dump([], f)

    log_event(0, "ORACLE_START")

    while True:
        try:
            state = contract.functions.currentState().call()
            if state in [2, 3]:
                print(f"[{AGENT_NAME}] [SISTEMA] El contrato finalizo su ciclo (Estado {state}). Finalizando operacion.")
                log_event(0, "ORACLE_SHUTDOWN", {"final_state": state})
                break

            if state == 0:
                print(f"[{AGENT_NAME}] [MONITOR] Contrato en fase SETUP (Estado 0). Esperando que todos los participantes depositen...")
                time.sleep(10)
                continue

            epoch = contract.functions.currentEpoch().call()
            start_time = contract.functions.lastEpochStartTime().call()
            now_time = w3.eth.get_block('latest')['timestamp']
            elapsed = now_time - start_time

            if elapsed < 180:
                print(f"[{AGENT_NAME}] [MONITOR] Epoca {epoch} en curso. Recolectando metricas... ({elapsed}s / 180s)")
                time.sleep(10)
                continue

            ya_reportado = contract.functions.epochMetrics(epoch, PUBLIC_ADDRESS).call()
            if ya_reportado == 0:
                print(f"[{AGENT_NAME}] [LOGICA] Ventana finalizada. Solicitando datos a la API del consumidor...")
                res = requests.get(CONSUMER_API, timeout=5)
                if res.status_code == 200:
                    lats = res.json().get("latencies", [])
                    if not lats:
                        print(f"[{AGENT_NAME}] [ADVERTENCIA] Lista vacia recibida de la API. Asignando 999ms.")
                        mediana = 999
                    else:
                        mediana = int(statistics.median(lats))
                        if mediana == 0: mediana = 1

                    print(f"[{AGENT_NAME}] [LOGICA] Mediana calculada: {mediana} ms. Generando submitLatency...")
                    log_event(epoch, "DATA_FETCHED", {"median": mediana})
                    tx = contract.functions.submitLatency(epoch, mediana).build_transaction({'from': PUBLIC_ADDRESS, 'gas': 400000})
                    send_signed_tx(tx, "TX_SUBMIT", epoch)
                else:
                    print(f"[{AGENT_NAME}] [ERROR] API fallo con HTTP {res.status_code}")
            else:
                print(f"[{AGENT_NAME}] [MONITOR] Reporte enviado. Esperando resolucion de consenso de otros oraculos...")
                if elapsed >= 240:
                    print(f"[{AGENT_NAME}] [SLA] Tolerancia superada (> 240s). Forzando timeout de consenso...")
                    tx = contract.functions.forceConsensoTimeout(epoch).build_transaction({'from': PUBLIC_ADDRESS, 'gas': 200000})
                    send_signed_tx(tx, "TX_TIMEOUT", epoch)

        except requests.exceptions.RequestException as req_err:
             print(f"[{AGENT_NAME}] [ERROR DE RED] No se conecto a la API: {req_err}")
        except Exception as e:
            print(f"[{AGENT_NAME}] [EXCEPCION GENERAL] {str(e)}")
        time.sleep(10)

if __name__ == '__main__':
    oracle_loop()