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

## M3 scheduling contract

`ScheduleRequest` contains a validated physical task graph, its exact machine/calibration configuration, a scheduling lower bound, completed task IDs, fixed resource/zone intervals, a boolean condition snapshot, and a non-preemptive policy. It produces a canonical `TimedSchedule` with scheduled entries, structured unscheduled reasons, and one decision record per remaining task.

The deterministic list order is dependency-ready time, descending task priority, original graph submission order, then task ID. Intervals are half-open `[start_ns, end_ns)`. Exclusive resource demands lock a complete resource; shared resource and zone demands sum against finite capacities. Fixed intervals use the same conflict rules.

Conditions support only `truthy` and `falsy` in v0.1. A kept message may release several tasks; a consumed message releases only the first task selected by the deterministic list order. Unknown messages block rather than defaulting to true.

Every delay is represented in `SchedulingDecision` as an earliest-start wait or capacity conflict, with the blocking task/fixed-interval IDs. Deadlines, policy horizons, false conditions, and descendants of unscheduled tasks produce structured `UnscheduledTask` records rather than silent indefinite waits.

Zone demands in M3 represent capacity occupied while an instruction is active. Persistent atom locations and transit state are not inferred by the scheduler; the M4 machine state will validate those across instruction boundaries. Configured M2 move tasks conservatively reserve both source and destination capacity during transit.

## M4 digital-twin execution

`DigitalTwinExecutor` independently validates the complete schedule before changing state. It checks graph/revision identity, task coverage, exact duration and assignments, DAG order, deadlines, resource/zone calendars, trajectory endpoint/duration/conflict-group bindings, unique dispatch order, and overlapping access to the same physical atom. A schedule produced or edited outside RESST cannot bypass these checks.

Movement is a two-event transition: task start moves atoms/blocks from a source zone into a named trajectory; task completion places them in the destination zone. Machine-state validation after every completion checks atom/site consistency, block location, configured zone capacity, and reservoir/erasure invariants. This catches accumulated persistent occupancy that an active-interval-only schedule cannot see.

Every start, completion, and emitted observation is correlated with task ID, physical opcode, planned interval, resource/zone assignments, trajectory, logical/QEC provenance, and a deterministic state digest. Snapshots include per-atom and per-block location, zone occupancy, symbolic qubit-label counts, reservoir inventory, known erasures, and aligned-pair count. Canonical JSON makes a run replay-comparable byte for byte.

The replaceable `StateBackend` boundary currently uses `DeterministicIdealBackend`. It tracks ideal symbolic labels for reset, H, `Ry(pi/2)`, X, and CZ and chooses reproducible X/Z measurement branches. It is deliberately not an amplitude/stabilizer/noise simulator and does not establish GHZ fidelity.

## M6 decoder feedback

Syndrome extraction is expressed as reset, pulse, movement, alignment, CZ, measurement, and sync instructions; no QEC macro reaches the executor. Syndrome observations are grouped into per-block history windows and passed to an explicit decoder interface. Decoder output carries completion time, status, diagnostics, and a `PauliFrameDelta` rather than scheduler mutations.

The runtime controller composes logical and sparse physical Pauli frames and publishes stable boolean message conditions. A follow-up physical sync task is both condition-gated and released no earlier than decoder completion. This establishes the feedback boundary without pretending that static M6 scheduling already supports live DAG mutation; preserving active intervals and rescheduling a changed graph remain M7 work.

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

