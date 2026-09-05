# M2 neutral-atom physical lowering

`NeutralAtomLowerer` converts `QECProtocolIR + NeutralAtomTarget` into a deterministic `PhysicalTaskGraph`. Every output node is a Physical ISA v0.1 instruction and carries both its source logical-operation ID and QEC-operation ID.

## Lowering rules

- `PREPARE_ZERO`: reset every data and ancilla atom in the storage zone.
- `PREPARE_PLUS`: perform the same reset, then apply a calibrated `Ry(pi/2)` seed pulse to data atoms.
- `TRANSVERSAL_CNOT`: move both blocks into the entangling zone, align every explicit data-site pair, apply target Hadamards, pairwise Rydberg CZ, target Hadamards, then move both blocks back to storage.
- `MEASURE_LOGICAL`: move the block to readout, destructively measure its data atoms in Z, then return the block to storage.
- `QEC_BARRIER`: emit a clock-backed synchronization marker.

A CNOT is represented as `H(target) · CZ(control,target) · H(target)` rather than pretending CNOT is a native Rydberg pulse. The `pairs` field of the CZ instruction is copied from the QEC transversal bijection, making every physical interaction traceable.

## Explicit v0.1 assumptions

- Zone capacity counts atoms. Storage must hold all blocks; entangling must hold two largest blocks; readout must hold one largest block.
- Zones are finite rectangles in integer micrometers. Transport uses named waypoint trajectories with fixed positive durations and explicit conflict-group resources.
- M3 prevents overlapping use beyond each conflict-group capacity, and M4 verifies the same binding. Collision freedom between different groups remains an input assertion; continuous paths are not simulated.
- A pair batch is one calibrated instruction. Resource capacity and the M3 scheduler decide whether batches or independent logical CNOTs overlap.
- Preparation produces an idealized physical seed, not a fault-tolerant encoded surface-code state. M6/M7 add explicit syndrome and deterministic loss-recovery control flow, but calibrated stochastic noise and full fault propagation remain M8 work.
- The reference target uses finite unit-capacity devices and illustrative timing values. It is a reproducible compiler target, not experimental calibration data.

## Failure behavior

Lowering fails before producing a graph if a required trajectory is absent, a binding has the wrong zone/resource class, finite zone capacity is insufficient, an instruction omits required semantics, or any task lacks a positive duration. Graph validation also rejects illegal zones, unknown resources, capacity overflow, and logical/QEC opcodes.

