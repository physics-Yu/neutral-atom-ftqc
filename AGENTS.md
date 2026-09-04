# AGENTS.md

Project-wide instructions for coding agents working in this repository.

## Project goal

Build a neutral-atom FTQC runtime/digital-twin prototype that lowers logical QEC workloads to experimentally meaningful neutral-atom operations, schedules them under RESST-style resource constraints, executes them in a machine simulator, and later supports QEC/loss feedback.

## Non-negotiable architecture rules

1. **The lowest executable instruction layer contains only physical experimental operations.**
   - `LOGICAL_CNOT`, `LOGICAL_INIT`, `SYNDROME_ROUND`, etc. are compiler-level abstractions.
   - They must not be scheduled/executed as indivisible hardware operations.

2. **Compiler and QEC decoder are separate systems.**
   - Compiler: intended logical/QEC operations -> physical experimental instruction DAG.
   - Decoder: syndrome/measurement/loss observations -> error estimate, recovery information, Pauli-frame update.

3. **Scheduler operates on physical tasks/resources, not algorithm semantics.**
   - RESST should reason about dependencies, zones, motion, laser/control resources, readout, capacity, and timing.
   - It should not contain GHZ-specific or surface-code-decoding logic.

4. **The digital twin executes scheduled physical instructions only.**
   - It must not receive high-level GHZ or logical-CNOT commands directly.

5. **Movement is explicit.**
   - Atoms/blocks cannot teleport between zones.
   - Transport consumes time/resources and must obey geometry/collision constraints as the model is refined.

6. **Atom loss is an erasure, not an automatic reset.**
   - Replacing a lost data atom does not restore its previous quantum state.
   - Recovery must use known-erasure information plus subsequent QEC/decoding.

7. **Do not hard-code distance 3.**
   - Initial demos may use `d=3`, but interfaces should permit larger surface-code distances.

8. **Do not introduce lattice surgery into the first GHZ implementation.**
   - Initial logical entanglement uses neutral-atom-enabled transversal inter-block CNOT lowering.

9. **Do not silently make unresolved physics assumptions.**
   - Record them in `docs/` and mark interfaces/configuration points explicitly.

10. **Prefer small vertical milestones with tests.**
    - Do not attempt the entire runtime in a single change.

## Current project phase

Architecture/scaffolding. Before substantial implementation, finalize:

- Physical ISA v0.1;
- machine/resource model v0.1;
- lowering rules for initialization and transversal logical CNOT;
- minimal four-logical-qubit GHZ vertical slice.

## First demo workload

Prepare

```text
L0 = |+_L>
L1 = |0_L>
L2 = |0_L>
L3 = |0_L>
```

then execute a depth-two logical entangling tree:

```text
CNOT_L(L0, L1)
CNOT_L(L0, L2) || CNOT_L(L1, L3)
```

The second layer is logically parallel; actual physical parallelism is decided by resource availability.
