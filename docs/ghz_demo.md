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

## M5 implementation status

`examples/ghz_surface_code.py` now builds `LogicalCircuitIR`, `QECProtocolIR`, and a complete `PhysicalTaskGraph`. The QEC expansion creates four encoded rotated-planar blocks and an explicit `d^2`-pair bijection for every transversal logical CNOT. The two layer-two CNOTs retain no dependency on one another.

Each transversal CNOT lowers to two block moves, pair alignment, target Hadamard, pairwise Rydberg CZ, target Hadamard, and two return moves. The `d=3` and `d=5` demo graphs each contain 29 physical tasks; pair widths scale with `d^2`.

M3 assigns deterministic non-preemptive start/end times under explicit resource, active-zone, and trajectory-corridor capacity claims. M4 executes those times against atom/site/block state, represents transport as an in-transit interval, independently rechecks conflicts, and emits replayable start/completion/observation events plus machine snapshots.

With `--measure`, four logical-data readouts are appended and each block returns to storage after measurement. The `d=3` baseline executes 41 physical tasks and emits 36 measurements; `d=5` executes the same task shape with wider batches and emits 100 measurements. The symbolic ideal backend proves the execution/state contracts, not encoded GHZ fidelity.

M5 projects the validated physical graph, timed schedule, execution trace, observations, target geometry, and scheduler wait diagnostics into a standalone artifact. Its spatial view animates block locations along configured trajectories, its Gantt view shows every claimed hardware/corridor resource, and its event stream follows the same integer-nanosecond cursor. The viewer is read-only and cannot modify the schedule or machine state.

Run:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --execute --measure
```

Generate the low/high resource comparison:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --visualize artifacts/ghz-d3.html --compare-resources
```

Both profiles execute the same 41-task measured graph. The reference low profile has a 1,266,400 ns makespan and serializes conflicting layer-two Rydberg gates; the higher-capacity profile has a 466,400 ns makespan and overlaps them. These are deterministic software-model results, not laboratory performance claims.

M6 can append explicit syndrome rounds instead of final logical-data readout:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --syndrome-rounds 1 --decode
```

For `d=3`, one round on each of four blocks produces a 133-task physical graph and four syndrome observations. The ideal backend reports all checks as zero. The runtime invokes the decoder, composes its frame delta without applying correction pulses, publishes one ready condition per block, and schedules a physical feedback sync no earlier than both decoder completion and the completed execution trace.

## First vertical slice

The first executable GHZ milestone omits stochastic noise, atom loss, and full decoding. It proves that:

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


