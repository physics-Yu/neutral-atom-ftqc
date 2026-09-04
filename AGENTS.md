# AGENTS.md

Project-wide instructions for Codex and other coding agents working in this repository. These rules apply to the entire repository unless a more specific nested `AGENTS.md` adds compatible local guidance.

## Mission and scope

Build a research-oriented **neutral-atom surface-code fault-tolerant quantum-computing runtime and digital twin**. The system must translate logical/QEC workloads into experimentally meaningful neutral-atom operations, schedule those operations under RESST-style resource constraints, execute them against a machine-state model, visualize the resulting trace, and eventually close the loop with syndrome decoding, atom-loss recovery, runtime feedback, and rescheduling.

The intended end-to-end stack is:

```text
Logical Circuit
  -> QEC-aware Compiler
  -> Physical Experimental IR / ISA
  -> RESST Scheduler
  -> Timed Physical Instructions
  -> Digital Twin / Executor
  -> Visualization and Runtime Observations
  -> QEC Decoder + Loss Manager + Runtime Controller
  -> Dynamic DAG Updates / Rescheduling
```

This is an execution-stack project, not merely a quantum-state simulator. Preserve the distinction between the logical program, QEC protocol, physical experimental commands, resource schedule, and evolving hardware state.

## Repository map and ownership

Respect the existing package boundaries:

- `src/compiler/`: logical IR, physical IR, and lowering from logical/QEC intent to physical experimental instruction DAGs. It decides **what** physical work is required, not final start times.
- `src/qec/`: surface-code geometry and logical-qubit/Pauli-frame abstractions. It must not own hardware scheduling or experimental execution.
- `src/decoder/`: interpretation of syndrome, measurement, and known-erasure observations. It returns correction/recovery information or Pauli-frame updates; it does not compile circuits or allocate hardware resources.
- `src/scheduler/`: RESST-style resource allocation, dependency handling, timing, conflicts, and rescheduling for physical tasks only.
- `src/hardware/`: atoms, zones, geometry, resources, capabilities, and mutable machine state.
- `src/simulator/`: execution of scheduled physical instructions, state transitions, observations/events, and noise models when enabled. This is the digital-twin boundary.
- `examples/`: user-facing end-to-end workloads, beginning with the four-logical-qubit GHZ example.
- `docs/`: architecture decisions, instruction semantics, execution assumptions, physics simplifications, and unresolved design questions.
- `tests/`: unit, contract, integration, and end-to-end tests mirroring the above boundaries.

Add a dedicated runtime-controller or loss-manager module when those responsibilities outgrow the current scaffolding; do not hide them inside the compiler, scheduler, decoder, or simulator for convenience.

## Non-negotiable architecture rules

### 1. The executable floor is the physical experimental ISA

The lowest executable instruction layer may contain only primitives corresponding to operations an experimental neutral-atom control platform can actually issue. Expected primitive families include explicit transport/rearrangement, physical one- and two-qubit control, measurement/imaging, atom loading/placement/reset where physically valid, waits/barriers, and necessary classical-control actions.

`LOGICAL_CNOT`, `LOGICAL_INIT`, `QEC_ROUND`, `SYNDROME_ROUND`, `PREPARE_GHZ`, and similar operations are **upper-layer macros**, never hardware opcodes. They must be lowered into physical primitives before scheduling or execution. Do not disguise a logical macro by placing it in the physical IR with a different name.

Every physical opcode must eventually define operands and typed parameters, legal zones/geometry, preconditions and state effects, required resources and conflicts, duration, permitted parallelism, emitted observations, and failure/loss semantics.

### 2. Components communicate through explicit contracts

Keep the QEC compiler, QEC decoder, RESST scheduler, runtime controller, loss manager, hardware model, and digital twin decoupled. Communicate through explicit IR nodes, DAG dependencies, schedules, events, observations, recovery requests, and state snapshots. Avoid hidden shared state, circular imports, back-channel mutation, and component-specific conditionals in generic layers.

In particular:

- the compiler must not choose final execution times;
- the decoder must not emit ad hoc scheduler mutations;
- the scheduler must not understand GHZ intent, logical gates, stabilizer meaning, or decoding policy;
- the digital twin must not accept logical gates or QEC rounds as executable commands;
- the loss manager must distinguish physical refill from logical-information recovery;
- the runtime controller coordinates components but must not absorb their domain logic.

### 3. RESST schedules physical work only

RESST ultimately consumes a DAG of physical experimental instructions annotated with dependencies, resource demands, zone/geometry constraints, durations, and classical conditions. It may insert or request scheduling-level movement, waits, or synchronization only under a documented contract. It must never directly schedule `LOGICAL_CNOT`, `QEC_ROUND`, or other algorithm/QEC macros.

Scheduling output must be traceable back to the physical input DAG and forward to digital-twin execution. Preserve stable instruction/task identifiers so visualization, diagnostics, and runtime feedback can correlate layers.

### 4. Movement and zones are explicit

The initial machine model has four conceptual zones:

1. **Storage** — idle logical blocks and atoms not currently acted upon.
2. **Entangling** — physical Rydberg-mediated entangling operations.
3. **Readout** — measurement, imaging, presence/loss detection, and physically valid reinitialization workflows.
4. **Atom Reservoir** — spare atoms available for replenishment.

Atoms and logical blocks cannot teleport between zones. Transport/rearrangement consumes time and hardware resources, changes occupancy, and must obey configured capacity, geometry, trajectory, and collision constraints at the fidelity currently modeled. Zone names, capacities, coordinates, and timings belong in configuration/data models, not scattered constants.

### 5. Atom loss is a known erasure, not a reset

Treat detected data-atom loss as a **known erasure**. Loading a fresh atom in `|0>` restores a physical site, not the lost encoded quantum information. A valid recovery path must preserve the distinction between:

```text
detect loss -> record erasure location -> allocate reservoir atom
-> transport/place/refill -> run required QEC operations
-> decode using erasure information -> update recovery/Pauli frame
```

Never mark a lost data qubit as recovered immediately after refill. Ancilla-loss handling may differ, but its assumptions and protocol must also be explicit. Propagate erasure metadata through observations, decoder inputs, runtime state, tests, and visualization where applicable.

### 6. Runtime execution is a dynamic DAG

The initial schedule may be static, but public interfaces must support an event-driven target model: measurement, syndrome, loss, resource failure, or conditional results can add, cancel, or unblock physical tasks and invalidate part of a provisional schedule. The runtime controller must be able to update the remaining DAG and ask RESST to reschedule without rebuilding unrelated completed history.

Design for deterministic replay: record instruction IDs, dependencies, scheduled/actual times, resource assignments, observations, decoder outputs, DAG mutations, and rescheduling reasons.

### 7. Surface-code distance is configurable

Start demonstrations at `d=3`, but never hard-code distance-three qubit counts, coordinate tables, loop bounds, stabilizers, transversal pairings, schedules, or expected event counts. Derive them from the code/layout model and validate parameters. Interfaces and tests must leave a credible path to `d=5`; when practical, include at least one construction, shape, or contract test at `d=5` even if full simulation remains expensive.

### 8. Physical assumptions must be visible

All physical simplifications must be explicit, reviewable, and replaceable. Document them in `docs/` near the relevant model and expose configuration points where appropriate. Examples include gate/motion duration, perfect parallel addressing, zone capacity, collision-free transport, all-to-all transversal alignment, readout/reset behavior, loss detectability, decoder latency, and omitted crosstalk or noise.

Do not silently convert an unknown quantity into zero cost, perfect fidelity, unlimited capacity, or unrestricted parallelism. Mark placeholder values and state what future model replaces them.

## First workload: four-logical-qubit surface-code GHZ

The first workload uses four surface-code logical qubits:

```text
L0 = |+_L>
L1 = |0_L>
L2 = |0_L>
L3 = |0_L>
```

Prepare `(|0000>_L + |1111>_L) / sqrt(2)` with the depth-two logical entangling tree:

```text
Layer 1: CNOT_L(L0, L1)
Layer 2: CNOT_L(L0, L2) || CNOT_L(L1, L3)
```

Use reconfigurable neutral-atom transport/alignment and **transversal logical CNOT** lowering between compatible surface-code blocks. Lattice surgery is not the first-version main path and must not be introduced as a shortcut for this workload. It may be explored later behind a separate strategy/interface and with its own design record.

The second logical layer is deliberately parallel at the logical level. Whether its physical operations overlap is decided only by actual zone capacity, geometry, hardware resources, and DAG dependencies.

## Implementation sequence

### Phase 1: minimal vertical slice

Build and keep runnable the smallest coherent path:

```text
Logical Circuit
  -> QEC Compiler
  -> Physical ISA / instruction DAG
  -> RESST
  -> Digital Twin
  -> Visualization
```

For this phase, deterministic idealized execution is acceptable. Do not block the vertical slice on a complete decoder, stochastic loss, or a high-fidelity noise model. However, preserve the interfaces and event boundaries needed to add them without collapsing component separation.

The slice must visibly demonstrate logical-to-physical lowering, explicit movement, resource/zone scheduling, timed execution, and a trace or visualization of machine-state evolution.

### Later phases

Add capabilities incrementally after the baseline is coherent:

1. explicit QEC/syndrome rounds and Pauli-frame handling;
2. decoder integration and runtime feedback;
3. deterministic known-loss scenarios, reservoir refill, and recovery;
4. dynamic DAG mutation and partial rescheduling;
5. configurable stochastic loss and physical noise;
6. higher-fidelity resource, geometry, and timing models;
7. distance scaling, including `d=5` validation.

Do not pull later-phase complexity into an earlier milestone unless it is required to keep an interface honest.

## Working rules for agents

Before changing code:

1. Read this file, `README.md`, and the directly relevant files in `docs/`.
2. Inspect existing interfaces and tests before proposing new abstractions.
3. State the layer being changed and verify that the change belongs there.
4. Identify every physical assumption introduced or altered.
5. Prefer the smallest end-to-end-compatible change over a broad rewrite.

While implementing:

- use typed, explicit data structures at component boundaries;
- keep logical/QEC IR types distinct from physical instruction types;
- keep configuration separate from mutable runtime state;
- inject clocks, randomness, policies, and hardware parameters when needed for deterministic tests;
- avoid GHZ-specific behavior in reusable compiler, scheduler, hardware, decoder, and simulator components;
- reject invalid layer crossings early with clear errors;
- preserve provenance from logical macro through physical instructions and scheduled execution;
- update documentation in the same change whenever an interface or physics assumption changes.

Do not perform unrelated refactors, dependency additions, or large generated-artifact updates. Do not commit, push, open a pull request, or modify remote GitHub state unless the user explicitly requests it.

## Tests and milestone definition of done

Every milestone must declare its **definition of done** before or alongside implementation. A milestone is not complete merely because a demo runs.

At minimum, definition of done must include:

- scope and intentionally deferred behavior;
- executable acceptance criteria;
- unit tests for new domain logic;
- contract tests across every changed component boundary;
- integration or end-to-end coverage for the milestone path;
- deterministic fixtures/seeds where simulation or scheduling can vary;
- validation of relevant invariants and failure cases;
- updated docs for APIs, architecture decisions, and physical assumptions;
- a reproducible command for tests and, when relevant, the demo/visualization;
- confirmation that existing tests still pass.

For scheduling changes, test dependency order, conflicts, capacity, legal parallelism, and deterministic tie-breaking. For loss/recovery changes, test that refill alone never restores logical state. For distance-dependent changes, test `d=3` and at least a lightweight `d=5` case. For physical-ISA changes, test that logical macros are rejected at the scheduler and executor boundaries.

The baseline repository test command is:

```text
pytest
```

If a milestone cannot yet be tested at full physical fidelity, use explicit idealized fixtures and document exactly what the test proves and omits.

## Review checklist

Before declaring work complete, verify:

- only physical experimental primitives reach RESST and the digital twin;
- compiler, decoder, scheduler, runtime controller, loss manager, and simulator responsibilities remain separated;
- all movement, zone occupancy, timing, and constrained resources are explicit at the modeled fidelity;
- data loss remains a known erasure through refill, QEC, and decoding;
- dynamic feedback and rescheduling are not precluded by static-only data structures;
- no `d=3` assumptions were hard-coded and a path to `d=5` remains;
- new physical simplifications are documented;
- tests and milestone definition of done are present;
- README/docs/examples remain consistent with the implementation;
- unrelated files and user changes were not modified.
