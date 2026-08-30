import sys, os, time, json, threading, signal
from flask import Flask, jsonify
from web3 import Web3
from datetime import datetime

if len(sys.argv) < 3:
    sys.exit("Uso: python3 provider.py <NETWORK> <MODO_SIMULACION>")

NETWORK = sys.argv[1].upper()
MODO_SIMULACION = sys.argv[2].upper()
LOG_FILE = f"provider_{NETWORK}_events.json"

app = Flask(__name__)

if NETWORK == "L1":
    RPC_URL = ""
    CONTRACT_ADDRESS = ""
else:
    RPC_URL = ""
    CONTRACT_ADDRESS = ""

w3 = Web3(Web3.HTTPProvider(RPC_URL))
ABI = []

contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=ABI)

def log_event(event_name, details=None):
    if details is None: details = {}
    now = time.time()
    entry = {
        "simulation_mode": MODO_SIMULACION,
        "network": NETWORK,
        "agent": "PROVIDER",
        "timestamp": now,
        "datetime": datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
        "event": event_name,
        "details": details
    }
    try:
        data = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f: data = json.load(f)
        data.append(entry)
        with open(LOG_FILE, 'w') as f: json.dump(data, f, indent=4)
    except:
        pass

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "online"}), 200

def monitor_lifecycle():
    estado_previo = -1
    while True:
        try:
            state = contract.functions.currentState().call()

            # Detectar activación (Pasa de estado SETUP=0 a ACTIVE=1)
            if state == 1 and estado_previo != 1:
                log_event("PROVIDER_LIFECYCLE_ACTIVE", {"contract_state": state})

            if state in [2, 3]:
                log_event("SLA_TERMINATION_INTERCEPTED", {"contract_state": state})
                time.sleep(1)
                os.kill(os.getpid(), signal.SIGTERM)

            estado_previo = state
        except:
            pass
        time.sleep(5)

if __name__ == '__main__':
    # CAMBIO: Solo inicializa si el archivo no existe para no borrar simulaciones pasadas
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w') as f: json.dump([], f)

    log_event("PROVIDER_START")
    threading.Thread(target=monitor_lifecycle, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)