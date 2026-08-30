# sla-blockchain-automatizacion
# NetworkSLA: Automatización de Acuerdos de Nivel de Servicio

Este repositorio contiene la arquitectura distribuida para gobernar un SLA mediante contratos inteligentes (`NetworkSLA.sol`), orquestando penalizaciones y pagos de forma automatizada y sin intermediarios.

<img width="1360" height="810" alt="CAPAS_FINAL drawio" src="https://github.com/user-attachments/assets/a0549f03-f9b9-4e4c-a535-f3dcb1fda1e7" />


## Arquitectura y Entorno de Ejecución (VirtualBox)

El sistema se despliega sobre un host Windows con Oracle VirtualBox, orquestando tres Máquinas Virtuales (VMs) aisladas. Estas VMs se interconectan mediante una red NAT con servidor DHCP y reglas de reenvío de puertos (*Port Forwarding*), permitiendo controlar todos los servicios vía SSH desde el CMD del host local. 

Para la identidad digital, intervienen cinco carteras de MetaMask operando a través de Infura como pasarela RPC hacia Ethereum Sepolia (L1) o Arbitrum Sepolia (L2).

| Máquina Virtual | Dominio | Sistema Base | Librerías Clave (Dependencias) | Software Adicional |
| :--- | :--- | :--- | :--- | :--- |
| **VM Proveedor** | `Dominio_Provider` | Python 3.12.3 | `web3 7.16.0`, `Flask 3.1.3`, `eth-account 0.13.7`, `requests 2.34.2` | --- |
| **VM Consumidor** | `Dominio_Consumer` | Python 3.12.3 | Mismo conjunto de librerías | --- |
| **VM Oráculos** | `Dominio_Oracle` | Python 3.12.3 | Mismo conjunto de librerías | Nodo IPFS (Kubo) v0.28.0 |

## Guía de Ejecución Paso a Paso

> **Aviso:** Antes de ejecutar los scripts de interacción con la blockchain, es indispensable copiar la dirección del contrato inteligente desplegado y pegarla en la variable `CONTRACT_ADDRESS` de **todos** los archivos `.py`.

### 1. Inicialización de IPFS (VM Oráculos)

Para que los oráculos puedan subir el registro de latencias (JSON) a la red descentralizada IPFS antes de enviar el hash a la blockchain, debes arrancar el demonio de Kubo en la máquina de los oráculos:

```bash
ipfs daemon
```

### 2. Despliegue del Contrato (VM Proveedor)

El ciclo de vida del SLA comienza cuando el Proveedor ejecuta el script de despliegue. Durante la ejecución, se selecciona dinámicamente la red de destino (L1 o L2) y el constructor registra las direcciones públicas e inmutables de los cinco agentes, estableciendo el estado inicial en SETUP.

```bash
python3 deploy.py
```

### 3. Fondeo Inicial y Activación (En cada VM)

En la fase SETUP, cada participante interactúa individualmente con el contrato invocando la función `payable deposit()`. Cada VM debe tener su propio script configurado con sus respectivas claves privadas:

* **En la VM Proveedor:** Aporta una fianza colateral de seguridad.
```bash
python3 deposit.py # Deposita 0.010 ETH
```

* **En la VM Consumidor:** Deposita el pago total por adelantado.
```bash
python3 deposit.py # Deposita 0.015 ETH
```

* **En la VM Oráculos:** Tres scripts independientes, depositando 0.005 ETH cada uno. Al verificar la recepción del pozo total de 0.040 ETH, el contrato cambia automáticamente al estado ACTIVE.
```bash
python3 deposit_oracle_1.py # Deposita 0.005 ETH
python3 deposit_oracle_2.py # Deposita 0.005 ETH
python3 deposit_oracle_3.py # Deposita 0.005 ETH
```

### 4. Monitorización y Telemetría

Al activarse el contrato, comienza la monitorización activa del RTT entre los nodos locales:

* **En la VM Proveedor:** Ejecuta de fondo el servidor web Flask en el puerto 5000.
```bash
python3 provider.py <NETWORK> <MODO_SIMULACION>
```

* **En la VM Consumidor:** Un agente lanza peticiones HTTP GET continuas cada segundo hacia la IP del Proveedor, almacena el histórico y expone la API pública en el puerto 8000.
```bash
python3 consumer.py <NETWORK> <MODO_SIMULACION>
```

### 5. Consenso de Oráculos (VM Oráculos)

El acuerdo se evalúa en ciclos de tres épocas de 180 segundos. Los oráculos leen la API, calculan la mediana estadística pura e invocan `submitLatency()`. Cada instancia requiere cinco parámetros obligatorios.

```bash
python3 oracle_ipfs.py <PRIVATE_KEY_1> <PUBLIC_ADDRESS_1> 1 L1 SIM_REAL
python3 oracle_ipfs.py <PRIVATE_KEY_2> <PUBLIC_ADDRESS_2> 2 L1 SIM_REAL
python3 oracle_ipfs.py <PRIVATE_KEY_3> <PUBLIC_ADDRESS_3> 3 L1 SIM_REAL
```

**Mecanismo de tolerancia a fallos:** Si un oráculo se cae, cualquier agente puede invocar `forceConsensoTimeout(epoch)` transcurridos 240 segundos para promediar los votos existentes.

## Resolución Financiera Determinista

El contrato liquida cada época on-chain basándose en la mediana (**M**) consensuada:

* **Servicio Óptimo (M < 10 ms):** El Proveedor percibe 0.004 ETH y se reservan 0.001 ETH en la bolsa de honorarios de los oráculos.
* **Degradación / Soft Penalty (10 ms ≤ M < 150 ms):** Se aplica una multa proporcional según la siguiente ecuación, restándose de la fianza del Proveedor para compensar al Consumidor:

> **Penalización = ((M - 10) × PROVIDER_INITIAL_STAKE) / 140**

* **Fallo Crítico / Hard Slashing (M ≥ 150 ms):** Si la mediana alcanza el umbral de 150 ms, o si una multa previa agota la fianza del Proveedor, el estado cambia a FAILED. Se confisca el colateral restante del Proveedor para el Consumidor y se devuelve íntegramente la fianza inicial de 0.005 ETH a cada oráculo.
