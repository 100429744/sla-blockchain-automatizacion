// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract NetworkSLA {
    enum State { SETUP, ACTIVE, COMPLETED, FAILED }
    State public currentState;

    address public provider;
    address public consumer;
    address[3] public oracles;

    uint256 public constant PROVIDER_INITIAL_STAKE = 0.010 ether;
    uint256 public constant CONSUMER_TOTAL_PAYMENT = 0.015 ether;
    uint256 public constant ORACLE_STAKE = 0.005 ether;

    uint256 public constant TOTAL_EPOCHS = 3;
    uint256 public constant EPOCH_DURATION = 3 minutes;
    uint256 public constant VOTING_WINDOW = 1 minutes;

    uint256 public providerStakeRemaining;
    uint256 public lastEpochStartTime;
    uint256 public currentEpoch;
    uint256 public accumulatedOracleFees;
    uint256 public lastPenaltyDeducted;

    mapping(address => bool) public hasDeposited;
    mapping(uint256 => mapping(address => uint256)) public epochMetrics;
    mapping(uint256 => address[]) public epochReports;
    
    // --- NUEVO: ALMACENAMIENTO PARA COMPARATIVA DE GAS ---
    mapping(uint256 => mapping(address => string)) public epochRawJson;

    event EpochProcessed(uint256 indexed epoch, uint256 latency, string status);
    event SoftPenaltyApplied(uint256 indexed epoch, uint256 penaltyAmount);
    event StateChanged(State newState);

    modifier inState(State _state) { require(currentState == _state, "Estado invalido"); _; }
    
    modifier onlyOracle() {
        bool isOracle = false;
        for(uint i = 0; i < 3; i++) { if(oracles[i] == msg.sender) isOracle = true; }
        require(isOracle, "Solo oraculos");
        _;
    }

    constructor(address _provider, address _consumer, address[3] memory _oracles) {
        provider = _provider;
        consumer = _consumer;
        oracles = _oracles;
        currentState = State.SETUP;
    }

    function deposit() external payable inState(State.SETUP) {
        require(!hasDeposited[msg.sender], "Ya depositado");
        if (msg.sender == provider) { 
            require(msg.value == PROVIDER_INITIAL_STAKE, "Monto incorrecto"); 
            providerStakeRemaining = msg.value; 
        }
        else if (msg.sender == consumer) { 
            require(msg.value == CONSUMER_TOTAL_PAYMENT, "Monto incorrecto"); 
        }
        else {
            bool isOracle = false;
            for(uint i=0; i<3; i++) { if (msg.sender == oracles[i]) isOracle = true; }
            require(isOracle, "No autorizado");
            require(msg.value == ORACLE_STAKE, "Monto incorrecto");
        }
        
        hasDeposited[msg.sender] = true;
        if (hasDeposited[provider] && hasDeposited[consumer] && hasDeposited[oracles[0]] && hasDeposited[oracles[1]] && hasDeposited[oracles[2]]) {
            currentState = State.ACTIVE;
            lastEpochStartTime = block.timestamp;
            emit StateChanged(State.ACTIVE);
        }
    }

    function submitLatency(uint256 _epoch, uint256 _latencyMs, string calldata _rawJson) external inState(State.ACTIVE) onlyOracle {
        require(_epoch == currentEpoch, "Epoca incorrecta");
        require(block.timestamp >= lastEpochStartTime + EPOCH_DURATION, "Muestreo en curso");
        require(epochMetrics[_epoch][msg.sender] == 0, "Ya reportado");

        epochMetrics[_epoch][msg.sender] = _latencyMs;
        epochRawJson[_epoch][msg.sender] = _rawJson; // Operación de alto coste de Gas
        
        epochReports[_epoch].push(msg.sender);

        if (epochReports[_epoch].length == 3) {
            procesarConsenso(_epoch);
        }
    }

    function forceConsensoTimeout(uint256 _epoch) external inState(State.ACTIVE) {
        require(_epoch == currentEpoch, "Epoca incorrecta");
        require(block.timestamp >= lastEpochStartTime + EPOCH_DURATION + VOTING_WINDOW, "Ventana de gracia activa");
        uint256 vCount = epochReports[_epoch].length;
        require(vCount >= 2 && vCount < 3, "Quorum inviable");

        uint256 voteA = epochMetrics[_epoch][epochReports[_epoch][0]];
        uint256 voteB = epochMetrics[_epoch][epochReports[_epoch][1]];
        uint256 simulatedMedian = (voteA + voteB) / 2;
        
        epochReports[_epoch].push(address(0)); 
        epochMetrics[_epoch][address(0)] = simulatedMedian;
        
        procesarConsenso(_epoch);
    }

    function procesarConsenso(uint256 _epoch) internal {
        uint256 m1 = epochMetrics[_epoch][epochReports[_epoch][0]];
        uint256 m2 = epochMetrics[_epoch][epochReports[_epoch][1]];
        uint256 m3 = epochMetrics[_epoch][epochReports[_epoch][2]];
        
        uint256 finalMedian = calculateMedian(m1, m2, m3);
        
        if (finalMedian > 150) {
            ejecutarHardSlashing();
            return;
        } else if (finalMedian > 30) {
            uint256 penalty = 0.001 ether;
            if (providerStakeRemaining >= penalty) {
                providerStakeRemaining -= penalty;
                payable(consumer).transfer(penalty);
                lastPenaltyDeducted = penalty;
                emit SoftPenaltyApplied(_epoch, penalty);
                emit EpochProcessed(_epoch, finalMedian, "SOFT_SLA_VIOLATION");
            } else {
                ejecutarHardSlashing();
                return;
            }
        } else {
            lastPenaltyDeducted = 0;
            emit EpochProcessed(_epoch, finalMedian, "SLA_MET");
        }

        uint256 oracleFee = 0.005 ether / TOTAL_EPOCHS;
        accumulatedOracleFees += oracleFee;
        
        currentEpoch++;
        if (currentEpoch >= TOTAL_EPOCHS) {
            currentState = State.COMPLETED;
            emit StateChanged(State.COMPLETED);
            ejecutarCierreExitoso();
        } else {
            lastEpochStartTime = block.timestamp;
        }
    }

    function calculateMedian(uint256 a, uint256 b, uint256 c) internal pure returns (uint256) {
        if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
        if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
        return c;
    }

    function ejecutarHardSlashing() internal {
        currentState = State.FAILED;
        emit StateChanged(State.FAILED);
        
        accumulatedOracleFees += 0.001 ether;
        uint256 futureEpochs = TOTAL_EPOCHS - currentEpoch - 1;
        uint256 consumerRefund = providerStakeRemaining + 0.004 ether + (futureEpochs * 0.005 ether);
        providerStakeRemaining = 0;

        if (consumerRefund > 0) payable(consumer).transfer(consumerRefund);

        uint256 oraclePayout = ORACLE_STAKE + (accumulatedOracleFees / 3);
        for(uint i = 0; i < 3; i++) { payable(oracles[i]).transfer(oraclePayout); }
    }

    function ejecutarCierreExitoso() internal {
        if (providerStakeRemaining > 0) {
            uint256 extraBonus = 0.001 ether;
            payable(provider).transfer(providerStakeRemaining + extraBonus);
        }
        
        uint256 consumerRefund = 0.004 ether;
        if (consumerRefund > 0) payable(consumer).transfer(consumerRefund);

        uint256 oraclePayout = ORACLE_STAKE + (accumulatedOracleFees / 3);
        for(uint i = 0; i < 3; i++) { payable(oracles[i]).transfer(oraclePayout); }
    }
}
