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

## M4 implementation status

`examples/ghz_surface_code.py` now builds `LogicalCircuitIR`, `QECProtocolIR`, and a complete `PhysicalTaskGraph`. The QEC expansion creates four encoded rotated-planar blocks and an explicit `d^2`-pair bijection for every transversal logical CNOT. The two layer-two CNOTs retain no dependency on one another.

Each transversal CNOT lowers to two block moves, pair alignment, target Hadamard, pairwise Rydberg CZ, target Hadamard, and two return moves. The `d=3` and `d=5` demo graphs each contain 29 physical tasks; pair widths scale with `d^2`.

M3 assigns deterministic non-preemptive start/end times under explicit resource, active-zone, and trajectory-corridor capacity claims. M4 executes those times against atom/site/block state, represents transport as an in-transit interval, independently rechecks conflicts, and emits replayable start/completion/observation events plus machine snapshots.

With `--measure`, four logical-data readouts are appended and each block returns to storage after measurement. The `d=3` baseline executes 41 physical tasks and emits 36 measurements; `d=5` executes the same task shape with wider batches and emits 100 measurements. The symbolic ideal backend proves the execution/state contracts, not encoded GHZ fidelity.

Run:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --execute --measure
```

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

