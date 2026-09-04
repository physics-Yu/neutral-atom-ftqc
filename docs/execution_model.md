# Execution Model

## Goal

Execution is event-driven and eventually dynamic. The initial schedule is provisional because measurement, syndrome, and atom-loss events may alter future work.

## Static baseline

The first milestone may execute a fully known physical instruction DAG:

```text
logical workload
-> compiler lowering
-> physical instruction DAG
-> RESST schedule
-> digital-twin execution
```

This establishes the compiler/scheduler/executor boundary before runtime feedback is added.

## Dynamic runtime target

The target runtime loop is conceptually:

```text
while unfinished work exists:
    identify ready physical tasks
    schedule available resources
    execute scheduled instructions
    collect observations/events

    if syndrome/measurement data are available:
        invoke decoder

    if atom loss is detected:
        invoke loss/recovery manager

    update Pauli frame and machine state
    insert recovery/refill tasks when required
    reschedule remaining work
```

## Ownership rules

- Compiler creates physical requirements and dependencies.
- Scheduler assigns physical resources and times.
- Executor changes machine state and emits observations.
- Decoder interprets QEC observations.
- Recovery logic may inject new physical tasks.

These responsibilities should communicate through explicit data structures rather than hidden cross-module state.

## Atom-loss semantics

Ancilla loss and data loss are different.

- Lost ancilla: refill/reset/reuse may be sufficient.
- Lost data atom: mark a known erasure, physically replace the atom, then use later QEC/decoding to recover encoded information when possible.

A replacement atom must never be treated as automatically restoring the lost quantum state.
