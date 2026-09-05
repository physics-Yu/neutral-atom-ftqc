# neutral-atom-ftqc

Research-oriented prototype for compiling, scheduling, simulating, and visualizing fault-tolerant quantum-computing workflows on reconfigurable neutral-atom hardware.

The first target demonstration is logical GHZ-state preparation with surface-code logical qubits. The project will connect logical/QEC compilation to experimentally meaningful neutral-atom operations, RESST-style resource scheduling, a machine-level digital twin, QEC decoding, and atom-loss recovery.

## Intended execution stack

```text
Logical circuit
  -> QEC-aware compiler
  -> physical experimental IR / ISA
  -> RESST scheduler
  -> timed experimental instructions
  -> digital-twin execution
  -> syndrome / measurement / atom-loss events
  -> decoder + runtime feedback
```

The lowest executable layer contains only operations that an experimental platform can issue. Logical operations such as `LOGICAL_CNOT` and `SYNDROME_ROUND` are compiler abstractions and must be lowered before scheduling or execution.

## Current status

M0 through M6 are complete. The repository includes schema-v0.1 boundary contracts, a distance-parameterized rotated planar surface-code layout, immutable logical and physical Pauli frames, a QEC protocol IR, validated Physical ISA semantics, finite zone/resource bindings, conflict-grouped transport trajectories, deterministic physical lowering, a non-preemptive RESST-style scheduler, a replayable idealized digital twin, a standalone synchronized viewer, explicit stabilizer-extraction rounds, a reference single-error decoder, and decoder-conditioned runtime feedback. Contract and model tests cover both `d=3` and `d=5`.

The next implementation milestone is **M7: deterministic atom loss, refill, recovery, and partial rescheduling**.

Run the complete measured baseline with `python examples/ghz_surface_code.py --distance 3 --execute --measure` after setting `PYTHONPATH=src;.` on Windows.

Generate the complete offline M5 comparison artifact with:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --visualize artifacts/ghz-d3.html --compare-resources
```

Open `artifacts/ghz-d3.html` directly in a browser. It embeds all data and code; `artifacts/ghz-d3.json` is emitted alongside it for inspection.

Run one explicit ideal syndrome/decoder cycle with:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --syndrome-rounds 1 --decode
```

See `AGENTS.md` for project-wide constraints and `docs/architecture_and_implementation_plan.md` for the milestone plan.



