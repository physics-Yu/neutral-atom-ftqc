# Physical Experimental ISA v0.1

Status: **M2 Physical ISA v0.1 semantics frozen for the reference target**.

## Executable boundary

Only `PhysicalOpcode` values may cross into scheduling and digital-twin execution. Logical/QEC macros such as `LOGICAL_CNOT`, `LOGICAL_INIT`, `QEC_ROUND`, `SYNDROME_ROUND`, and `PREPARE_GHZ` are rejected at the physical boundary.

The v0.1 opcode set is:

| Opcode | Required operands/parameters | Legal zone kinds | Required resource class | State/observation effect |
| --- | --- | --- | --- | --- |
| `move_atoms` | one or more atoms; trajectory/source/destination | all | transport | atom positions change |
| `move_block` | one block; trajectory/source/destination | storage, entangling, readout | transport | block zone changes |
| `align_atoms` | atoms; explicit pairs/profile | entangling | transport | interaction geometry changes |
| `apply_1q_pulse` | atoms; operation/pulse ID | storage, entangling | one-qubit control | calibrated unitary |
| `apply_2q_rydberg_gate` | atoms; gate/pulse ID/pairs | entangling | Rydberg control | pairwise calibrated interaction |
| `image_atoms` | atoms; profile | storage, readout, reservoir | imaging | emits presence observations |
| `measure_atoms` | atoms; basis/profile | readout | readout | emits destructive qubit measurements |
| `reset_atoms` | atoms; state/profile/purpose | storage, readout, reservoir | reset | prepares configured basis state |
| `load_reservoir_atom` | one atom; profile | reservoir | reservoir loading | adds usable reservoir atom |
| `place_atom` | replacement and vacant site; destination/profile/trajectory/source/destination | storage, reservoir | transport | restores occupancy, not quantum data |
| `wait` | explicit positive duration | all | clock | retains subjects/resources |
| `emit_sync` | tag/channel | all | clock | emits synchronization marker |

`PLACE_ATOM` restores site occupancy only. It never restores lost data-qubit information or clears a known erasure. Reservoir allocation is a classical loss-manager decision, not an opcode.

## Contract types

- `compiler.logical_ir.LogicalCircuitIR`: logical-qubit declarations and logical-operation DAG.
- `compiler.physical_ir.PhysicalTaskGraph`: revisioned DAG containing physical instructions only.
- `contracts.machine.MachineConfig`: immutable zones, capacity resources, and calibration snapshot.
- `contracts.events.ObservationBatch`: replayable batches of measurement, presence, syndrome, loss, or resource-fault observations.

All top-level contracts use schema version `0.1`, immutable slotted dataclasses, stable identifiers, canonical JSON serialization, and validation on construction.

## Units and explicit physical assumptions

- All contract time values are integer nanoseconds and must be non-negative.
- Every executable opcode used by a graph must have a strictly positive calibrated duration. Unknown duration is an error, never an implicit zero.
- Geometry coordinates use micrometers (`um`) in v0.1. Additional units require a schema-compatible enum extension and conversion policy.
- The initial `MachineConfig` requires storage, entangling, readout, and reservoir zones. Every zone and resource has a finite positive integer capacity.
- `ResourceMode.EXCLUSIVE` locks an entire named resource for a half-open task interval. `SHARED` adds its quantity to the resource's finite capacity calendar.
- Every `zone_id` claim has a matching positive `ZoneDemand`; M3 arbitrates these quantities against finite zone capacity during active task intervals.
- `ConditionRef` supports the frozen M3 predicates `truthy` and `falsy`. `KEEP` permits reuse; `CONSUME` removes the message after the deterministically selected task is scheduled.
- `PHYSICAL_ISA` is the executable registry for opcode family, legal zone kinds, resource classes, state effects, and observation production. The generic mapping remains JSON-only, but opcode-specific required fields are validated at construction.
- A task has either a positive explicit `duration_ns` (used for configured transport trajectories) or a positive opcode duration in its calibration snapshot. Missing duration is an error.
- Every movement or placement trajectory declares one or more `transport_corridor` conflict groups. Lowering adds those finite-capacity resources to the task; the scheduler arbitrates them and the executor independently verifies them.

## Boundary validation

`LogicalCircuitIR` rejects duplicate IDs, unknown qubits/predecessors, cycles, invalid logical arity, and invalid surface-code distance. Distance is an odd integer at least three; contract tests cover both `d=3` and `d=5`.

`PhysicalTaskGraph` rejects duplicate IDs, unknown predecessors, self-dependencies, cycles, invalid time windows, and invalid resource quantities. `validate_against_machine()` additionally rejects unknown zones/resources, capacity overflow, and missing calibrated durations.

An atom-loss observation must include `atom_id`, `block_id`, `site_id`, and `atom_role`. This preserves known-erasure information before any future refill or decoder action.

## Example physical task graph fragment

```json
{
  "schema_version": "0.1",
  "graph_id": "ghz-physical",
  "revision": 0,
  "tasks": [
    {
      "task_id": "move-L0",
      "instruction": {
        "opcode": "move_block",
        "operands": ["L0"],
        "parameters": {
          "trajectory_id": "storage-to-entangling",
          "source_zone_id": "storage",
          "destination_zone_id": "entangling"
        }
      },
      "predecessors": [],
      "earliest_start_ns": 0,
      "deadline_ns": null,
      "priority": 0,
      "resource_demands": [
        {"resource_id": "aod-0", "quantity": 1, "mode": "exclusive"}
      ],
      "zone_ids": ["storage", "entangling"],
      "zone_demands": [
        {"zone_id": "storage", "quantity": 17},
        {"zone_id": "entangling", "quantity": 17}
      ],
      "conditions": [],
      "dispatch_group_id": null,
      "provenance": {"logical_op_ids": ["cx-01"], "qec_op_ids": ["tcx-01"]}
    }
  ]
}
```

## Intentionally deferred after M4

M4 does not implement continuous collision dynamics, automated path planning, device dispatch, stochastic loss/noise, decoder behavior, or visualization. Routing conflicts are conservative named-corridor constraints over configured waypoint paths; geometric intersection and minimum-separation analysis remain higher-fidelity work. The reference pulse, path, capacity, and timing values are explicit modeling inputs, not laboratory calibration claims.

## M4 definition of done

- All 12 opcodes have tested machine-state transitions or observation behavior.
- Transport has explicit in-transit state, endpoints, duration, and conflict groups.
- The executor rejects invalid layer crossings, schedule conflicts, subject overlap, route omissions, and persistent capacity overflow.
- Measured `d=3` and `d=5` GHZ workflows execute without state invariant violations and produce byte-stable traces.

