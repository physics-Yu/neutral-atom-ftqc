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

The lowest executable layer must contain only operations that the experimental platform can actually issue. Logical operations such as `LOGICAL_CNOT` and `SYNDROME_ROUND` are compiler abstractions and must be lowered before scheduling/execution.

## Current status

Architecture/scaffolding phase. The immediate next task is to design **Physical ISA v0.1** and its resource/scheduling semantics before implementing the simulator stack.

See `AGENTS.md` for project-wide constraints and `docs/` for design notes.
