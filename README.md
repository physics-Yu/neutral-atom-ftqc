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

M0 is complete: schema-v0.1 logical IR, physical task-DAG, machine-configuration, and observation contracts are implemented with validation, canonical JSON round trips, and contract tests. Physical opcode parameter semantics remain intentionally deferred to M2.

The next implementation milestone is **M1: surface-code model and GHZ logical/QEC IR**.

See `AGENTS.md` for project-wide constraints and `docs/architecture_and_implementation_plan.md` for the milestone plan.

