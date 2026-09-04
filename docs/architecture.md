# Architecture

## Purpose

This project models a neutral-atom FTQC execution stack rather than only a quantum circuit.

The intended module flow is:

```text
Logical Program
    |
    v
QEC-aware Compiler
    |
    v
Physical Experimental IR
    |
    v
RESST Scheduler
    |
    v
Timed Physical Instruction Stream
    |
    v
Digital Twin / Executor
    |
    +--> measurement / syndrome / atom-loss events
             |
             v
        QEC Decoder / Loss Manager
             |
             v
        Runtime feedback / new physical tasks
```

## Module responsibilities

### `qec/`
Owns surface-code structure, logical-qubit abstractions, and Pauli-frame state. It must not own hardware scheduling.

### `compiler/`
Owns lowering from logical/QEC operations toward physical experimental instructions. It determines what physical operations are required, not their final execution times.

### `hardware/`
Owns atoms, zones, machine geometry, and current hardware state.

### `scheduler/`
Owns resource-constrained execution planning. The scheduler should only reason about physical tasks, dependencies, timing, zones, capacities, and hardware resources.

### `decoder/`
Owns interpretation of syndrome/loss observations and production of correction/Pauli-frame information. It is separate from compilation.

### `simulator/`
Owns execution of scheduled physical instructions and production of runtime observations/events.

## Initial machine zones

The first architecture model contains four conceptual zones:

1. **Storage Zone** — holds idle logical blocks.
2. **Entangling Zone** — executes physical two-qubit Rydberg operations.
3. **Readout Zone** — performs measurement, imaging, loss detection, and related reinitialization operations.
4. **Reservoir Zone** — stores spare atoms used for replenishment.

The exact geometry, capacities, and hardware-resource model remain configuration/design questions for Physical ISA v0.1.

## First workload

The first vertical slice is four-logical-qubit surface-code GHZ preparation. It is intentionally simple at the logical level so that compilation, movement, scheduling, and execution behavior are visible.

No large-scale implementation should precede agreement on the physical ISA and machine/resource semantics.
