import sys, os, time, json, requests, threading, random
from flask import Flask, jsonify
from web3 import Web3
from datetime import datetime

if len(sys.argv) < 3:
    sys.exit("Uso: python3 consumer.py <NETWORK> <MODO_SIMULACION>")

NETWORK = sys.argv[1].upper()
MODO_SIMULACION = sys.argv[2].upper()

LOG_FILE = f"consumer_{NETWORK}_events.json"
DATA_FILE = 'latencies.json'
PROVIDER_URL = 'http://10.0.2.4:5000/ping'

app = Flask(__name__)
local_epoch_tracker = 0

if NETWORK == "L1":
    w3 = Web3(Web3.HTTPProvider(""))
    CONTRACT_ADDRESS = ""
else:
    w3 = Web3(Web3.HTTPProvider(""))
    CONTRACT_ADDRESS = ""

ABI = []
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=ABI)

def log_event(event_name, details=None):
    if details is None: details = {}
    now = time.time()
    entry = {
        "simulation_mode": MODO_SIMULACION,
        "network": NETWORK,
        "agent": "CONSUMER",
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

def ping_loop():
    global local_epoch_tracker
    print(f"[{NETWORK}] Control de ciclo de vida del SLA iniciado en modo {MODO_SIMULACION}.")

    # =================================================================
    # FASE DE ESPERA: Bloquea hasta que el contrato esté ACTIVE (1)
    # =================================================================
    print(f"[{NETWORK}] Sincronizando con el contrato inteligente en {CONTRACT_ADDRESS}...")
    ultimo_estado_impreso = None

    while True:
        try:
            state = contract.functions.currentState().call()

            if state == 1: # ACTIVE
                print(f"\n[{NETWORK}] ¡SLA ACTIVADO! Todos los actores han depositado correctamente. Iniciando telemetría...")
                log_event("CONSUMER_LIFECYCLE_ACTIVE")
                break

            elif state == 0: # SETUP
                if ultimo_estado_impreso != 0:
                    print(f"[{NETWORK}] Estado detectado: SETUP (0). Esperando a que el Provider, Consumer y Oráculos realicen sus depósitos...")
                    ultimo_estado_impreso = 0

            elif state in [2, 3]: # COMPLETED / FAILED
                print(f"\n[{NETWORK}] El contrato ya se encuentra en un estado final ({state}). Apagando agente.")
                os._exit(0)

        except Exception:
            # Captura de forma segura el fallo si el contrato aún no ha sido subido/desplegado a la red
            if ultimo_estado_impreso != "NOT_DEPLOYED":
                print(f"[{NETWORK}] Esperando a que el contrato sea desplegado en la blockchain... (Dirección: {CONTRACT_ADDRESS})")
                ultimo_estado_impreso = "NOT_DEPLOYED"

        time.sleep(5.0) # Consulta el nodo cada 5 segundos de forma calmada para evitar spam

    # =================================================================
    # BUCLE PRINCIPAL DE TELEMETRÍA (Solo se ejecuta si el contrato está ACTIVE)
    # =================================================================
    while True:
        try:
            state = contract.functions.currentState().call()
            if state in [2, 3]:
                log_event("CONSUMER_SHUTDOWN", {"final_state": state})
                print(f"\n[{NETWORK}] Contrato finalizado en la red (Estado: {state}). Deteniendo pings.")
                os._exit(0)

            if state == 0:
                # Salvaguarda por si ocurre una anomalía, volvemos a esperar
                time.sleep(5.0)
                continue

            epoch = contract.functions.currentEpoch().call()
            if epoch > local_epoch_tracker:
                log_event("CONSUMER_EPOCH_TRANSITION", {"new_epoch": epoch})
                # CORRECCIÓN: Se añade el argumento 'f' que faltaba
                with open(DATA_FILE, 'w') as f: json.dump([], f)
                local_epoch_tracker = epoch

            latency = 0
            if MODO_SIMULACION == "SIM_REAL":
                t_start = time.time()
                try:
                    res = requests.get(PROVIDER_URL, timeout=1.0)
                    latency = int((time.time() - t_start) * 1000) if res.status_code == 200 else 999
                except:
                    latency = 999
            else:
                latency = random.randint(3, 8) if MODO_SIMULACION == "SIM_HAPPY" else (random.randint(35, 55) if MODO_SIMULACION == "SIM_SOFT" else random.randint(155, 175))

            try:
                with open(DATA_FILE, 'r') as f: data = json.load(f)
            except:
                data = []
            data.append({"timestamp": int(time.time()), "ms": latency})
            with open(DATA_FILE, 'w') as f: json.dump(data, f)

        except Exception as e:
            print(f"[DEBUG CONSUMER] Error interno en ping_loop activo: {e}")

        time.sleep(1.0)

@app.route('/api/v1/metrics/current-epoch', methods=['GET'])
def get_metrics():
    try:
        with open(DATA_FILE, 'r') as f: historial = json.load(f)
        now = int(time.time())
        valid_pings = [i['ms'] for i in historial if i['timestamp'] >= (now - 180)]
        log_event("API_GET_METRICS_SERVED", {"points_served": len(valid_pings)})
        return jsonify({"latencies": valid_pings}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # CORRECCIÓN: Se añade el argumento 'f' que faltaba
    with open(DATA_FILE, 'w') as f: json.dump([], f)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w') as f: json.dump([], f)

    log_event("CONSUMER_START")
    threading.Thread(target=ping_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8000)