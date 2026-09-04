# Physical Experimental ISA v0.1

Status: **M0 contract surface frozen; device semantics are completed in M2**.

## Executable boundary

Only `PhysicalOpcode` values may cross into scheduling and digital-twin execution. Logical/QEC macros such as `LOGICAL_CNOT`, `LOGICAL_INIT`, `QEC_ROUND`, `SYNDROME_ROUND`, and `PREPARE_GHZ` are rejected at the physical boundary.

The v0.1 opcode set is:

| Family | Opcode | Purpose |
| --- | --- | --- |
| Transport | `move_atoms` | Move explicitly identified atoms along a configured trajectory. |
| Transport | `move_block` | Move a logical block as a configured rigid transform. |
| Transport | `align_atoms` | Create a configured physical interaction geometry. |
| Coherent control | `apply_1q_pulse` | Apply a physical single-atom pulse. |
| Coherent control | `apply_2q_rydberg_gate` | Apply physical pairwise Rydberg gates. |
| Observation | `image_atoms` | Produce atom-presence observations. |
| Observation | `measure_atoms` | Produce physical measurement observations. |
| Atom management | `reset_atoms` | Reinitialize atoms where a machine profile permits it. |
| Atom management | `load_reservoir_atom` | Physically load a reservoir atom. |
| Atom management | `place_atom` | Fill a vacant site with a replacement atom. |
| Timing | `wait` | Advance time while explicitly retaining configured subjects/resources. |
| Synchronization | `emit_sync` | Emit a device synchronization marker or trigger. |

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
- `ResourceMode.EXCLUSIVE` represents RESST lock behavior; `SHARED` represents a capacity claim. Arbitration is deferred to M3.
- `ConditionRef` records RESST-style message predicates and keep/consume behavior. Evaluation is deferred to M3/runtime work.
- Detailed pulse fields, trajectories, collision checks, legal-zone matrices, and opcode state effects remain M2 decisions. The generic `parameters` mapping is JSON-only so these fields can be prototyped without permitting arbitrary Python objects across the boundary.

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
        "parameters": {"trajectory_id": "storage-to-entangling"}
      },
      "predecessors": [],
      "earliest_start_ns": 0,
      "deadline_ns": null,
      "priority": 0,
      "resource_demands": [
        {"resource_id": "aod-0", "quantity": 1, "mode": "exclusive"}
      ],
      "zone_ids": ["storage", "entangling"],
      "conditions": [],
      "dispatch_group_id": null,
      "provenance": {"logical_op_ids": ["cx-01"], "qec_op_ids": ["tcx-01"]}
    }
  ]
}
```

## Intentionally deferred from M0

M0 does not implement lowering, scheduling, device dispatch, state transitions, quantum simulation, decoder behavior, or visualization. It does not claim that the provisional opcode parameter fields are experimentally complete. M2 must replace provisional parameter conventions with per-opcode typed semantics before the ISA is declared device-ready.

## M0 definition of done

- Logical and physical IRs are distinct importable types.
- The physical opcode enum contains no logical/QEC macro.
- Machine configuration and observation contracts are versioned and serializable.
- DAG, reference, unit, capacity, duration, and layer-crossing failures are executable tests.
- `d=3` and `d=5` contract construction paths pass.
- `pytest` passes without adding runtime dependencies.

