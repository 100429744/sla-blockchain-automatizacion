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

def log_event(epoch, event_name, details=None):
    if details is None: details = {}
    now = w3.eth.get_block('latest').timestamp
    entry = {"epoch": epoch, "simulation_mode": MODO_SIMULACION, "network": NETWORK, "agent": AGENT_NAME, "timestamp": now, "datetime": datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], "event": event_name, "details": details}
    try:
        data = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f: data = json.load(f)
        data.append(entry)
        with open(LOG_FILE, 'w') as f: json.dump(data, f, indent=4)
    except: pass

def log_gas_metric(epoch, tx_type, tx_hash, status, block_number, gas_used, eth_spent):
    if not GAS_LOG_FILE: return
    now = time.time()
    entry = {"epoch": epoch, "simulation_mode": MODO_SIMULACION, "network": NETWORK, "agent": AGENT_NAME, "timestamp": now, "datetime": datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], "transaction_type": tx_type, "tx_hash": tx_hash, "status": status, "block_number": block_number, "gas_used": gas_used, "eth_spent": eth_spent}
    try:
        data = []
        if os.path.exists(GAS_LOG_FILE):
            with open(GAS_LOG_FILE, 'r') as f: data = json.load(f)
        data.append(entry)
        with open(GAS_LOG_FILE, 'w') as f: json.dump(data, f, indent=4)
        print(f"[{AGENT_NAME}] [AUDITORIA] Metrica de gas registrada.")
    except Exception as e:
        print(f"[{AGENT_NAME}] [ERROR] Fallo en reporte gas: {e}")

def send_signed_tx(tx_data, event_prefix, current_epoch):
    print(f"[{AGENT_NAME}] [TX] Preparando transaccion {event_prefix} en blockchain...")
    tx_data['nonce'] = w3.eth.get_transaction_count(PUBLIC_ADDRESS,'pending')
    time.sleep(2)
    tx_data['chainId'] = CHAIN_ID
    try:
        base_fee = w3.eth.get_block('latest')['baseFeePerGas']
        priority_fee = w3.to_wei(1, 'gwei')
        max_fee = (base_fee * 2) + priority_fee
        tx_data['maxFeePerGas'] = max_fee
        tx_data['maxPriorityFeePerGas'] = priority_fee
    except Exception as e:
        tx_data['maxFeePerGas'] = w3.to_wei(25, 'gwei')
        tx_data['maxPriorityFeePerGas'] = w3.to_wei(2, 'gwei')

    signed = w3.eth.account.sign_transaction(tx_data, PRIVATE_KEY)
    log_event(current_epoch, f"{event_prefix}_BROADCAST")
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"[{AGENT_NAME}] [TX] Transaccion enviada. Hash: {tx_hash.hex()}")
    print(f"[{AGENT_NAME}] [TX] Esperando confirmacion (timeout 180s)...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    tx_status = "Success" if receipt.get('status') == 1 else "Reverted"
    gas_used = receipt.get('gasUsed', 0)
    bloque_minado = receipt.get('blockNumber', 0)
    effective_gas_price = receipt.get('effectiveGasPrice', tx_data.get('maxFeePerGas', 0))
    eth_spent = float(w3.from_wei(gas_used * effective_gas_price, 'ether'))

    print(f"[{AGENT_NAME}] [TX] MINADA en Bloque {bloque_minado} | Estado: {tx_status} | Gas Usado: {gas_used}")
    log_event(current_epoch, f"{event_prefix}_CONFIRMED", {"status": tx_status, "gas_used": gas_used, "eth_spent": eth_spent, "block": bloque_minado})
    log_gas_metric(current_epoch, event_prefix, tx_hash.hex(), tx_status, bloque_minado, gas_used, eth_spent)
    return receipt

def oracle_loop():
    while True:
        try:
            state = contract.functions.currentState().call()
            if state in [2, 3]:
                print(f"[{AGENT_NAME}] [INFO] El contrato inteligente finalizó (Estado: {state}). Apagando oráculo.")
                sys.exit(0)
            if state == 0:
                time.sleep(5)
                continue

            epoch = contract.functions.currentEpoch().call()
            start_time = contract.functions.lastEpochStartTime().call()
            duration = contract.functions.EPOCH_DURATION().call()
            now = int(time.time())
            elapsed = now - start_time

            if elapsed < duration:
                faltan = duration - elapsed
                print(f"[{AGENT_NAME}] [ESPERA] Época {epoch} en curso. Faltan {faltan} segundos para solicitar datos...")
                time.sleep(15)
                continue

            ya_reportado = contract.functions.epochMetrics(epoch, PUBLIC_ADDRESS).call()
            if ya_reportado == 0:
                print(f"[{AGENT_NAME}] [LOGICA] Ventana finalizada. Solicitando datos a la API del consumidor...")
                res = requests.get(CONSUMER_API, timeout=5)

                if res.status_code == 200:
                    raw_json_str = res.text  # EXTRACCIÓN DEL JSON CRUDO
                    lats = res.json().get("latencies", [])

                    if not lats:
                        print(f"[{AGENT_NAME}] [ADVERTENCIA] Lista vacia. Asignando 999ms.")
                        mediana = 999
                    else:
                        mediana = int(statistics.median(lats))
                        if mediana == 0: mediana = 1

                    print(f"[{AGENT_NAME}] [LOGICA] Mediana calculada: {mediana} ms. Generando submitLatency...")
                    log_event(epoch, "DATA_FETCHED", {"median": mediana})

                    # GAS INCREMENTADO MASIVAMENTE (3811 bytes en calldata + SSTORE)
                    tx = contract.functions.submitLatency(epoch, mediana, raw_json_str).build_transaction({
                        'from': PUBLIC_ADDRESS,
                        'gas': 4500000
                    })

                    send_signed_tx(tx, "TX_SUBMIT", epoch)
                else:
                    print(f"[{AGENT_NAME}] [ERROR] API fallo con HTTP {res.status_code}")
            else:
                print(f"[{AGENT_NAME}] [MONITOR] Reporte enviado. Esperando resolucion de consenso...")
                if elapsed >= duration + 60:  # Umbral modificado ligeramente si quieres
                    print(f"[{AGENT_NAME}] [SLA] Tolerancia superada. Forzando timeout de consenso...")
                    tx = contract.functions.forceConsensoTimeout(epoch).build_transaction({'from': PUBLIC_ADDRESS, 'gas': 300000})
                    send_signed_tx(tx, "TX_TIMEOUT", epoch)

        except Exception as e:
            print(f"[{AGENT_NAME}] [EXCEPCION] {str(e)}")

        time.sleep(10)

if __name__ == '__main__':
    oracle_loop()