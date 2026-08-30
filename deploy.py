import sys
import os
import json
import time
from datetime import datetime
from web3 import Web3

# -----------------------------------------------------------------
# CONTROLES DE ENTRADA Y SELECCIÓN DE CAPA (L1 / L2)
# -----------------------------------------------------------------
if len(sys.argv) < 2:
    print("[ERROR] Uso correcto: python3 deploy.py <L1 o L2>")
    sys.exit(1)

SELECCION_RED = sys.argv[1].upper()

if SELECCION_RED == "L1":
    RPC_URL = ""
    CHAIN_ID =
elif SELECCION_RED == "L2":
    RPC_URL = ""
    CHAIN_ID =
else:
    print(f"[ERROR] Red '{sys.argv[1]}' invalida. Use estrictamente 'L1' o 'L2'.")
    sys.exit(1)

# Configuraciones de Cuenta Básicas
PUBLIC_ADDRESS = ""
PRIVATE_KEY = ""  # Rellénala con tu clave privada real
JSON_LOG_FILE = "provider_deployment_log.json"

# Parámetros del Constructor (Firma exacta del ABI de tu NetworkSLA)
PARAM_PROVIDER = ""
PARAM_CONSUMER = ""
PARAM_ORACLES = [
    "",
    "",
    ""
]

CONTRACT_BYTECODE = ""
# -----------------------------------------------------------------
# 
# -----------------------------------------------------------------
CONTRACT_ABI = []

def registrar_costo_json(red, contract_addr, tx_hash, gas_used, eth_spent):
    """Guarda localmente en la VM del Provider las métricas de gasto de despliegue."""
    ahora = time.time()
    nuevo_registro = {
        "timestamp": ahora,
        "datetime": datetime.fromtimestamp(ahora).strftime('%Y-%m-%d %H:%M:%S'),
        "network": red,
        "contract_address": contract_addr,
        "tx_hash": tx_hash,
        "gas_used": gas_used,
        "eth_spent": eth_spent
    }

    data = []
    if os.path.exists(JSON_LOG_FILE):
        try:
            with open(JSON_LOG_FILE, 'r') as f:
                data = json.load(f)
        except Exception:
            data = []

    data.append(nuevo_registro)

    with open(JSON_LOG_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"[AUDITORÍA] Gasto guardado exitosamente en '{JSON_LOG_FILE}'.")

def despliegue_red_unificada():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))

    if not w3.is_connected():
        print(f"[ERROR] Imposible conectar al nodo RPC de {SELECCION_RED}.")
        sys.exit(1)

    addr_public = Web3.to_checksum_address(PUBLIC_ADDRESS)
    param_provider = Web3.to_checksum_address(PARAM_PROVIDER)
    param_consumer = Web3.to_checksum_address(PARAM_CONSUMER)
    param_oracles = [Web3.to_checksum_address(addr) for addr in PARAM_ORACLES]

    print(f"[INFO] Conectado a {SELECCION_RED}. Bloque actual: {w3.eth.block_number}")
    contrato = w3.eth.contract(abi=CONTRACT_ABI, bytecode=CONTRACT_BYTECODE)

    nonce = w3.eth.get_transaction_count(addr_public)

    try:
        base_fee = w3.eth.get_block('latest')['baseFeePerGas']
        priority_fee = w3.to_wei(1.5, 'gwei')
        max_fee = (base_fee * 2) + priority_fee
    except Exception:
        max_fee = w3.to_wei(25, 'gwei')
        priority_fee = w3.to_wei(2, 'gwei')

    tx_params = {
        'from': addr_public,
        'nonce': nonce,
        'chainId': CHAIN_ID,
        'value': 0,
        'maxFeePerGas': max_fee,
        'maxPriorityFeePerGas': priority_fee
    }

    tx_data = contrato.constructor(
        param_provider,
        param_consumer,
        param_oracles
    ).build_transaction(tx_params)

    print("[INFO] Estimando gas necesario...")
    try:
        gas_estimate = w3.eth.estimate_gas(tx_data)
        tx_data['gas'] = int(gas_estimate * 1.1)

        print(f"\n[INFO] Lanzando despliegue real en: {SELECCION_RED}...")
        tx_firmada = w3.eth.account.sign_transaction(tx_data, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(tx_firmada.raw_transaction)

        print(f"[INFO] Transaccion transmitida. Hash: {tx_hash.hex()}")
        print("[INFO] Esperando confirmacion del bloque...")
        recibo = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=240)

        gas_real_usado = recibo.gasUsed
        precio_gas_efectivo = recibo.get('effectiveGasPrice', max_fee)
        eth_total_gastado = float(w3.from_wei(gas_real_usado * precio_gas_efectivo, 'ether'))

        print("\n" + "="*50)
        print(f"¡CONTRATO DESPLEGADO EN {SELECCION_RED}!")
        print(f"Direccion: {recibo.contractAddress}")
        print(f"Gas Usado: {gas_real_usado}")
        print(f"Costo Total: {eth_total_gastado} ETH")
        print("="*50 + "\n")

        registrar_costo_json(
            red=SELECCION_RED,
            contract_addr=recibo.contractAddress,
            tx_hash=tx_hash.hex(),
            gas_used=gas_real_usado,
            eth_spent=eth_total_gastado
        )

    except Exception as e:
        print(f"\n[Fallo Critico de Ejecucion/Reversion]: {str(e)}")

if __name__ == "__main__":
    if PRIVATE_KEY == "TU_CLAVE_PRIVADA_AQUI" or len(PRIVATE_KEY) < 32:
        print("[ERROR] Configure la variable 'PRIVATE_KEY' con sus credenciales antes de continuar.")
        sys.exit(1)
    despliegue_red_unificada()