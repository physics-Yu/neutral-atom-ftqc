# Physical Experimental ISA

Status: **design draft / not yet frozen**.

## Core rule

The lowest executable instruction layer must contain only operations that correspond to commands an experimental neutral-atom platform can actually issue.

Therefore the following are **not** physical ISA instructions:

```text
LOGICAL_CNOT
LOGICAL_INIT
SYNDROME_ROUND
PREPARE_GHZ
```

They are compiler/QEC macros that must be lowered further.

## Candidate primitive families

Physical ISA v0.1 will be designed from four hardware-action families:

1. **Transport**
   - atom/block movement;
   - rearrangement/alignment.

2. **Coherent control**
   - physical one-qubit control;
   - physical two-qubit Rydberg interactions.

3. **Measurement**
   - qubit measurement;
   - atom-presence imaging/loss detection.

4. **Atom management**
   - reservoir allocation/loading;
   - placement;
   - reset/reinitialization where physically appropriate.

Synchronization/classical-control primitives may be added only where they correspond to execution-system requirements.

## What must be specified for every opcode

Before ISA v0.1 is frozen, every physical opcode must have explicit:

- operands;
- allowed zones/geometry;
- required hardware resources;
- preconditions;
- duration/timing model;
- state transition/effect;
- observation/event output, if any;
- failure/loss semantics;
- scheduling conflicts;
- whether parallel execution is permitted.

## Design test

ISA v0.1 is acceptable only if the following can be expressed entirely by composing its primitives:

1. surface-code logical initialization;
2. neutral-atom-enabled transversal logical CNOT;
3. one surface-code syndrome-extraction round;
4. readout/loss detection;
5. reservoir refill after atom loss;
6. the four-logical-qubit GHZ demo.

Do not implement detailed opcodes until these semantics are reviewed.
