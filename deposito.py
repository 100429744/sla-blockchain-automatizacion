import json
import sys
import os
import time
from datetime import datetime
from web3 import Web3

# --- 1. CONFIGURACION ESPECIFICA DE LA VM ---
# CAMBIA ESTO SEGÚN LA RED: "L1" para Sepolia / "L2" para Arbitrum Sepolia
NETWORK = "L1"
# Pon la clave privada del agente que corresponde a esta VM
PRIVATE_KEY = ""
# CAMBIA ESTO SEGUN LA VM:
# Proveedor = 0.010 | Cliente = 0.015 | Oraculo = 0.005
CANTIDAD_ETH = 0.010

DEPOSIT_LOG_FILE = f"deposit_logs_{NETWORK}.json"

# --- SELECCIÓN DINÁMICA DE ENTORNO  ---
if NETWORK.upper() == "L1":
    RPC_URL = ""
    CHAIN_ID = 
    CONTRACT_ADDRESS = ""
else:
    RPC_URL = ""
    CHAIN_ID = 
    CONTRACT_ADDRESS = ""

# --- 2. INICIALIZACION ---
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    sys.exit(f"[ERROR CRITICO] Imposible conectar con el nodo RPC de {NETWORK}.")

SENDER_ADDRESS = w3.eth.account.from_key(PRIVATE_KEY).address

# Asegúrate de que "SLA_ABI.json" está en la misma carpeta que este script
with open("SLA_ABI.json", "r") as file:
    contract_abi = json.load(file)
contrato = w3.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)

def log_deposit(address, tx_hash, status, block, gas, cost, minado_sec):
    now = time.time()
    entry = {
        "network": NETWORK,
        "agent_address": address,
        "timestamp": now,
        "datetime": datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
        "event": "DEPOSIT_MINED",
        "details": {
            "tx_hash": tx_hash.hex(),
            "status": status,
            "blockNumber": block,
            "gas_used": gas,
            "eth_spent": cost,
            "mining_time_seconds": minado_sec
        }
    }
    data = []
    try:
        if os.path.exists(DEPOSIT_LOG_FILE):
            with open(DEPOSIT_LOG_FILE, 'r') as f: data = json.load(f)
    except: pass
    data.append(entry)
    with open(DEPOSIT_LOG_FILE, 'w') as f: json.dump(data, f, indent=4)

# --- 3. CONSTRUIR Y ENVIAR TRANSACCION ---
print(f"[INFO] Trabajando en la red: {NETWORK} (Chain ID: {CHAIN_ID})")
print(f"[INFO] VM configurada para la cuenta: {SENDER_ADDRESS}")
print(f"[INFO] Intentando depositar {CANTIDAD_ETH} ETH en el contrato {CONTRACT_ADDRESS}...")

# Calculamos el gas con margen de seguridad dinámico para soportar fluctuaciones de L1
try:
    bloque_actual = w3.eth.get_block('latest')
    base_fee = bloque_actual['baseFeePerGas']
    try:
        max_priority = w3.eth.max_priority_fee
    except:
        max_priority = w3.to_wei(1, 'gwei')

    # En L1 multiplicamos por 2 la base_fee por si hay picos repentinos de tráfico
    max_fee_segura = int(base_fee * 2) + max_priority
except Exception as e:
    print(f"[ADVERTENCIA] Error al calcular gas dinámico: {e}. Usando valores estáticos de emergencia.")
    max_fee_segura = w3.to_wei(25, 'gwei')
    max_priority = w3.to_wei(2, 'gwei')

# Construcción de la transacción inyectando explícitamente el chainId de la red elegida
tx = contrato.functions.deposit().build_transaction({
    'from': SENDER_ADDRESS,
    'value': w3.to_wei(CANTIDAD_ETH, 'ether'),
    'nonce': w3.eth.get_transaction_count(SENDER_ADDRESS),
    'gas': 300000,
    'maxFeePerGas': max_fee_segura,
    'maxPriorityFeePerGas': max_priority,
    'chainId': CHAIN_ID
})

tx_firmada = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)

print("[INFO] Enviando deposito...")
t_inicio = time.time()  # <-- INICIO CRONOMETRO
tx_hash = w3.eth.send_raw_transaction(tx_firmada.raw_transaction)

print(f"[INFO] Waiting for transaction {tx_hash.hex()} to be mined...")
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=240)
t_fin = time.time()     # <-- FIN CRONOMETRO
t_minado = round(t_fin - t_inicio, 3)

if receipt.status != 1:
    print(f"[ERROR] Transaction {tx_hash.hex()} was mined in block {receipt.blockNumber} but failed (status=0).")
    estado = "Reverted"
else:
    print(f"[EXITO] Transaction {tx_hash.hex()} successfully included in block {receipt.blockNumber} ({t_minado}s).")
    estado = "Success"

gas_usado = receipt.gasUsed
precio_efectivo = receipt.get('effectiveGasPrice', tx.get('maxFeePerGas'))
gasto_eth = float(w3.from_wei(gas_usado * precio_efectivo, 'ether'))

log_deposit(SENDER_ADDRESS, tx_hash, estado, receipt.blockNumber, gas_usado, gasto_eth, t_minado)