# M3 deterministic RESST-style scheduling

## Definition of done

M3 accepts physical tasks only and assigns non-preemptive half-open intervals without violating DAG dependencies, named-resource capacity, exclusive locks, active-zone capacity, fixed calendar intervals, release times, deadlines, policy horizon, or boolean message conditions. Identical serialized inputs produce byte-identical serialized schedules.

Acceptance coverage includes dependency order, shared capacity, exclusive conflicts, zone capacity, fixed maintenance, priority and stable tie-breaking, keep/consume messages, completed work, deadline/horizon failure, descendant failure, physical-only input enforcement, and full `d=3`/`d=5` GHZ scheduling. A low-capacity GHZ target serializes the second layer; a higher-capacity target overlaps it.

## Contracts

- `ScheduleRequest`: physical graph, exact machine/calibration, `not_before_ns`, completed task IDs, fixed intervals, condition snapshot, and policy.
- `ScheduledTask`: stable task ID, start/end, exact resource/zone assignments, and dispatch order.
- `UnscheduledTask`: stable task ID, enumerated reason, and diagnostic detail.
- `SchedulingDecision`: dependency readiness, selected start, wait categories, and blocking interval IDs.
- `TimedSchedule`: schedule/request/graph identity, entries, unscheduled tasks, decision log, and makespan.

The scheduler never examines GHZ, logical-gate, surface-code, or decoder semantics. Its only executable inputs are validated `PhysicalTaskGraph` nodes.

## Deterministic policy

Ready tasks are ordered by:

1. dependency-ready time;
2. descending integer priority;
3. original graph position;
4. task ID.

Each selected task is placed in its earliest feasible interval. An `EXCLUSIVE` resource conflicts with every overlapping claim. `SHARED` resource quantities and zone quantities may overlap up to configured capacity. Trajectory conflict groups are ordinary finite `transport_corridor` resources, so same-corridor movement serializes unless the configured corridor has multiple independently validated lanes. Tasks are indivisible and cannot be preempted in M3.

## Conditions and rescheduling boundary

Only `truthy` and `falsy` predicates are supported. Missing messages block. `KEEP` preserves a message; `CONSUME` removes it after one selected task uses it. `completed_task_ids`, `not_before_ns`, and fixed intervals allow a later runtime controller to submit the uncompleted graph after an event without rebuilding completed history.

M3 is static: it does not mutate a graph while scheduling, evaluate measurements, retry failed hardware, or execute instructions. Those responsibilities remain with the runtime controller and M4+ components.

## Explicit simplifications

- Zone quantities are active-interval capacity reservations, not a persistent occupancy simulation.
- Resource demands name concrete configured resources; class-to-device allocation is deferred.
- Fixed intervals are immutable reservations and are rejected if they already overbook capacity.
- There is no preemption, setup-time insertion, continuous acceleration/path planning, or stochastic duration. M8 geometry validation discovers segment intersections and requires shared conflict groups; execution separately samples overlap-dependent Rydberg crosstalk, but the scheduler does not optimize an expected-error objective.
- M2 reference timings remain illustrative inputs rather than laboratory calibration claims.

