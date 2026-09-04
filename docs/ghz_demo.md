# GHZ Surface-Code Demo

## Logical workload

Use four surface-code logical qubits:

```text
L0 = |+_L>
L1 = |0_L>
L2 = |0_L>
L3 = |0_L>
```

Generate GHZ using a depth-two logical entangling tree:

```text
Layer 1:
    CNOT_L(L0, L1)

Layer 2 (logically parallel):
    CNOT_L(L0, L2)
    CNOT_L(L1, L3)
```

Ideal target:

```text
(|0000>_L + |1111>_L) / sqrt(2)
```

## Why this workload

The logical algorithm is intentionally small. The demo is intended to expose the execution stack:

- logical/QEC compilation;
- surface-code block representation;
- atom/block transport;
- transversal physical inter-block interactions;
- RESST resource conflicts;
- zone occupancy;
- machine-state evolution;
- later: syndrome/QEC feedback and atom-loss recovery.

## First vertical slice

The first executable GHZ milestone should omit stochastic noise, atom loss, and full decoding. It should prove that:

```text
Logical GHZ circuit
-> physical instruction DAG
-> RESST schedule
-> digital-twin machine trace
-> visualization
```

is coherent end-to-end.

The second logical layer is an explicit scheduling test: its two CNOTs are logically independent, but the physical scheduler may run them in parallel or serialize them depending on entangling-zone and hardware-resource capacity.

## Later extension

After the baseline works, insert explicit QEC rounds and then deterministic atom-loss scenarios with reservoir refill and dynamic rescheduling.
