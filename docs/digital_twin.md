# M4 deterministic digital twin

## Definition of done

M4 executes a complete `TimedSchedule` containing Physical ISA v0.1 tasks, maintains atom/site/block/zone invariants, emits observations, and produces a canonical replayable trace. It must reject logical/QEC input, incomplete or altered schedules, resource/zone/route conflicts, overlapping access to one atom, illegal movement, missing alignment, unknown subjects, and persistent capacity overflow.

Tests cover every opcode, route serialization and configurable lane capacity, route-group omission, same-atom overlap, persistent occupancy, erasure-preserving replacement, deterministic measurement, trace round-trip, provenance, monotonic time, and full measured GHZ runs at `d=3` and `d=5`.

## Routing-conflict model

Each `TrajectorySpec` contains fixed integer-micrometer waypoints, a positive duration, and one or more conflict-group IDs. Every group resolves to a finite `transport_corridor` resource in `MachineConfig`. A move reserves its transport device, both endpoint capacities during the active interval, and every corridor group.

The reference storage/entangling directions share one bidirectional corridor; storage/readout and reservoir/storage use separate corridors. Capacity one prohibits overlap. A capacity greater than one is only appropriate when the configured hardware model asserts that many collision-free lanes.

This is a conservative route-conflict graph, not a continuous multi-agent path planner. It catches declared shared corridors and the executor rejects missing declarations. It does not derive intersections from waypoint geometry, integrate acceleration, enforce minimum atom separation, or model AOD waveform/crosstalk. Those are explicit higher-fidelity extensions, not assumed collision-free behavior.

## Machine state and opcode effects

- Move start changes a block/atom location to `in_transit:<trajectory>`; completion changes it to the destination zone.
- Alignment records exact pairs; Rydberg CZ requires those pairs and present atoms in the entangling zone.
- Reset and supported one-/two-qubit operations update a replaceable state backend.
- Image emits presence observations, including false for a recorded lost atom.
- Measurement emits deterministic X/Z results and marks the atom measured.
- Reservoir load creates a spare atom. Placement moves it along a configured route into a recorded vacant erasure site while preserving the site's erasure flag.
- Wait changes only time; sync remains visible as a physical trace event.

The mutable `MachineState` is cloned at run start, so execution does not mutate the caller's initial state. It validates identity, occupancy, capacity, location coherence, trajectory state, and atom/site consistency after every completion.

## Trace contract

`ExecutionTrace` records scheduled and actual event time, opcode, task ID, resources, zones, trajectory, observation correlation, provenance, and state digest. `MachineSnapshot` records atom/block location, zone counts, symbolic state counts, reservoir inventory, known erasures, and aligned-pair count. `ObservationBatch` carries the existing versioned observation contract.

## Ideal-backend boundary

`StateBackend` isolates quantum-state semantics from machine execution. The M4 `DeterministicIdealBackend` is a symbolic Clifford-like label tracker with reproducible measurement branches. It is sufficient for state-transition and replay tests, but it is not a stabilizer/amplitude simulator, does not model Born statistics, and does not prove GHZ fidelity or fault tolerance. Syndrome extraction, decoding, Pauli-frame feedback, loss injection, and physical noise remain M6/M7+ work.
