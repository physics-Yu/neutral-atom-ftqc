# M2 neutral-atom physical lowering

`NeutralAtomLowerer` converts `QECProtocolIR + NeutralAtomTarget` into a deterministic `PhysicalTaskGraph`. Every output node is a Physical ISA v0.1 instruction and carries both its source logical-operation ID and QEC-operation ID.

## Lowering rules

- `PREPARE_ZERO`: reset every data and ancilla atom in the storage zone.
- `PREPARE_PLUS`: perform the same reset, then apply a calibrated `Ry(pi/2)` seed pulse to data atoms.
- `TRANSVERSAL_CNOT`: move both blocks into the entangling zone, align every explicit data-site pair, apply target Hadamards, pairwise Rydberg CZ, target Hadamards, then move both blocks back to storage.
- `MEASURE_LOGICAL`: move the block to readout and destructively measure its data atoms in Z.
- `QEC_BARRIER`: emit a clock-backed synchronization marker.

A CNOT is represented as `H(target) · CZ(control,target) · H(target)` rather than pretending CNOT is a native Rydberg pulse. The `pairs` field of the CZ instruction is copied from the QEC transversal bijection, making every physical interaction traceable.

## Explicit v0.1 assumptions

- Zone capacity counts atoms. Storage must hold all blocks; entangling must hold two largest blocks; readout must hold one largest block.
- Zones are finite rectangles in integer micrometers. Transport uses named, prevalidated waypoint trajectories with fixed positive durations.
- Collision freedom inside a configured trajectory is an input assertion. M2 does not simulate continuous paths or concurrent collisions.
- A pair batch is one calibrated instruction. Resource capacity and the M3 scheduler decide whether batches or independent logical CNOTs overlap.
- Preparation produces an idealized physical seed, not a fault-tolerant encoded surface-code state. Stabilizer projection, repeated syndrome extraction, decoding, noise, and loss handling remain M6/M7 work.
- The reference target uses finite unit-capacity devices and illustrative timing values. It is a reproducible compiler target, not experimental calibration data.

## Failure behavior

Lowering fails before producing a graph if a required trajectory is absent, a binding has the wrong zone/resource class, finite zone capacity is insufficient, an instruction omits required semantics, or any task lacks a positive duration. Graph validation also rejects illegal zones, unknown resources, capacity overflow, and logical/QEC opcodes.
