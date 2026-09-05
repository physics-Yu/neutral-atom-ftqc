"""Lower QEC protocol operations into the Physical Experimental ISA v0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compiler.physical_ir import (
    PhysicalInstruction, PhysicalOpcode, PhysicalTask, PhysicalTaskGraph,
    Provenance, ResourceDemand, ResourceMode, ZoneDemand,
)
from compiler.qec_ir import EncodedBlock, QECOp, QECOpKind, QECProtocolIR
from contracts.common import ContractValidationError
from hardware.zones import NeutralAtomTarget


def _atom(block_id: str, site_id: str) -> str:
    return f"{block_id}/{site_id}"


@dataclass(slots=True)
class NeutralAtomLowerer:
    target: NeutralAtomTarget
    _tasks: list[PhysicalTask] = field(default_factory=list, init=False)
    _terminals: dict[str, tuple[str, ...]] = field(default_factory=dict, init=False)
    _block_sizes: dict[str, int] = field(default_factory=dict, init=False)

    def lower(self, protocol: QECProtocolIR) -> PhysicalTaskGraph:
        self.target.validate_protocol_capacity(protocol)
        self._tasks = []
        self._terminals = {}
        blocks = {block.block_id: block for block in protocol.blocks}
        self._block_sizes = {
            block.block_id: len(block.data_site_ids) + len(block.ancilla_site_ids)
            for block in protocol.blocks
        }
        for operation in protocol.operations:
            predecessors = tuple(
                task_id for predecessor in operation.predecessors
                for task_id in self._terminals[predecessor]
            )
            if operation.kind in {QECOpKind.PREPARE_ZERO, QECOpKind.PREPARE_PLUS}:
                terminals = self._lower_prepare(operation, blocks[operation.block_ids[0]], predecessors)
            elif operation.kind is QECOpKind.TRANSVERSAL_CNOT:
                terminals = self._lower_transversal_cnot(operation, predecessors)
            elif operation.kind is QECOpKind.MEASURE_LOGICAL:
                terminals = self._lower_measure(operation, blocks[operation.block_ids[0]], predecessors)
            elif operation.kind is QECOpKind.SYNDROME_ROUND:
                terminals = self._lower_syndrome(operation, blocks[operation.block_ids[0]], predecessors)
            elif operation.kind is QECOpKind.QEC_BARRIER:
                terminals = self._lower_barrier(operation, predecessors)
            else:  # pragma: no cover - enum exhaustiveness guard
                raise ContractValidationError(f"unsupported QEC operation {operation.kind!r}")
            self._terminals[operation.qec_op_id] = terminals
        graph = PhysicalTaskGraph(f"physical-{protocol.protocol_id}", 0, tuple(self._tasks))
        graph.validate_against_machine(self.target.machine)
        return graph

    def _lower_prepare(self, op: QECOp, block: EncodedBlock, predecessors: tuple[str, ...]) -> tuple[str, ...]:
        atoms = tuple(_atom(block.block_id, site) for site in block.data_site_ids + block.ancilla_site_ids)
        reset_id = f"phy-{op.qec_op_id}-reset"
        self._add(
            reset_id, PhysicalOpcode.RESET_ATOMS, atoms,
            {"state": "zero", "profile": "surface-code-block-reset", "purpose": "initialization_seed"},
            predecessors, {self.target.bindings.storage_zone_id: self._block_sizes[block.block_id]},
            self.target.bindings.reset_resource_id, op,
        )
        if op.kind is QECOpKind.PREPARE_ZERO:
            return (reset_id,)
        pulse_id = f"phy-{op.qec_op_id}-plus-pulse"
        data_atoms = tuple(_atom(block.block_id, site) for site in block.data_site_ids)
        self._add(
            pulse_id, PhysicalOpcode.APPLY_1Q_PULSE, data_atoms,
            {"operation": "ry_pi_over_2", "pulse_id": "logical-plus-seed"},
            (reset_id,), {self.target.bindings.storage_zone_id: self._block_sizes[block.block_id]},
            self.target.bindings.one_qubit_resource_id, op,
        )
        return (pulse_id,)

    def _lower_transversal_cnot(self, op: QECOp, predecessors: tuple[str, ...]) -> tuple[str, ...]:
        control_id, target_id = op.block_ids
        move_control = self._move(op, control_id, "storage", "entangling", predecessors, "move-control-in")
        move_target = self._move(op, target_id, "storage", "entangling", predecessors, "move-target-in")
        pairs = tuple(
            (_atom(pair.control.block_id, pair.control.site_id), _atom(pair.target.block_id, pair.target.site_id))
            for pair in op.pairings
        )
        operands = tuple(atom for pair in pairs for atom in pair)
        entangling_occupancy = self._block_sizes[control_id] + self._block_sizes[target_id]
        align_id = f"phy-{op.qec_op_id}-align"
        self._add(
            align_id, PhysicalOpcode.ALIGN_ATOMS, operands,
            {"pairs": pairs, "alignment_profile": "pairwise-rydberg-v0.1"},
            (move_control, move_target), {self.target.bindings.entangling_zone_id: entangling_occupancy},
            self.target.bindings.transport_resource_id, op,
        )
        targets = tuple(pair[1] for pair in pairs)
        pre_h = f"phy-{op.qec_op_id}-target-h-before"
        self._add(
            pre_h, PhysicalOpcode.APPLY_1Q_PULSE, targets,
            {"operation": "hadamard", "pulse_id": "calibrated-h-v0.1"},
            (align_id,), {self.target.bindings.entangling_zone_id: entangling_occupancy},
            self.target.bindings.one_qubit_resource_id, op,
        )
        cz_id = f"phy-{op.qec_op_id}-rydberg-cz"
        self._add(
            cz_id, PhysicalOpcode.APPLY_2Q_RYDBERG_GATE, operands,
            {"gate": "cz", "pulse_id": "parallel-cz-v0.1", "pairs": pairs},
            (pre_h,), {self.target.bindings.entangling_zone_id: entangling_occupancy},
            self.target.bindings.rydberg_resource_id, op,
        )
        post_h = f"phy-{op.qec_op_id}-target-h-after"
        self._add(
            post_h, PhysicalOpcode.APPLY_1Q_PULSE, targets,
            {"operation": "hadamard", "pulse_id": "calibrated-h-v0.1"},
            (cz_id,), {self.target.bindings.entangling_zone_id: entangling_occupancy},
            self.target.bindings.one_qubit_resource_id, op,
        )
        return (
            self._move(op, control_id, "entangling", "storage", (post_h,), "move-control-out"),
            self._move(op, target_id, "entangling", "storage", (post_h,), "move-target-out"),
        )

    def _lower_measure(self, op: QECOp, block: EncodedBlock, predecessors: tuple[str, ...]) -> tuple[str, ...]:
        move = self._move(op, block.block_id, "storage", "readout", predecessors, "move-to-readout")
        task_id = f"phy-{op.qec_op_id}-measure"
        atoms = tuple(_atom(block.block_id, site) for site in block.data_site_ids)
        self._add(
            task_id, PhysicalOpcode.MEASURE_ATOMS, atoms,
            {"basis": "z", "profile": "logical-data-readout-v0.1"},
            (move,), {self.target.bindings.readout_zone_id: self._block_sizes[block.block_id]},
            self.target.bindings.readout_resource_id, op,
        )
        return (self._move(op, block.block_id, "readout", "storage", (task_id,), "move-from-readout"),)

    def _lower_syndrome(self, op: QECOp, block: EncodedBlock, predecessors: tuple[str, ...]) -> tuple[str, ...]:
        data_atoms = tuple(_atom(block.block_id, site) for site in block.data_site_ids)
        ancilla_atoms = tuple(_atom(block.block_id, site) for site in block.ancilla_site_ids)
        current = predecessors
        for round_index in range(op.rounds):
            prefix = f"r{round_index}"
            reset_id = f"phy-{op.qec_op_id}-{prefix}-reset-ancillas"
            self._add(
                reset_id, PhysicalOpcode.RESET_ATOMS, ancilla_atoms,
                {"state": "zero", "profile": "syndrome-ancilla-reset-v0.1", "purpose": "syndrome_extraction"},
                current, {self.target.bindings.storage_zone_id: self._block_sizes[block.block_id]},
                self.target.bindings.reset_resource_id, op,
            )
            prepare_id = f"phy-{op.qec_op_id}-{prefix}-prepare-ancillas-x"
            self._add(
                prepare_id, PhysicalOpcode.APPLY_1Q_PULSE, ancilla_atoms,
                {"operation": "hadamard", "pulse_id": "syndrome-ancilla-h-v0.1"},
                (reset_id,), {self.target.bindings.storage_zone_id: self._block_sizes[block.block_id]},
                self.target.bindings.one_qubit_resource_id, op,
            )
            move_in = self._move(op, block.block_id, "storage", "entangling", (prepare_id,), f"{prefix}-move-in")
            current = (move_in,)
            for layer in range(4):
                current = self._lower_syndrome_layer(op, block, round_index, layer, current)

            data_h_before = f"phy-{op.qec_op_id}-{prefix}-data-h-before-x-checks"
            self._add(
                data_h_before, PhysicalOpcode.APPLY_1Q_PULSE, data_atoms,
                {"operation": "hadamard", "pulse_id": "syndrome-data-h-v0.1"},
                current, {self.target.bindings.entangling_zone_id: self._block_sizes[block.block_id]},
                self.target.bindings.one_qubit_resource_id, op,
            )
            current = (data_h_before,)
            for layer in range(4, 8):
                current = self._lower_syndrome_layer(op, block, round_index, layer, current)

            data_h_after = f"phy-{op.qec_op_id}-{prefix}-data-h-after-x-checks"
            self._add(
                data_h_after, PhysicalOpcode.APPLY_1Q_PULSE, data_atoms,
                {"operation": "hadamard", "pulse_id": "syndrome-data-h-v0.1"},
                current, {self.target.bindings.entangling_zone_id: self._block_sizes[block.block_id]},
                self.target.bindings.one_qubit_resource_id, op,
            )
            ancilla_h = f"phy-{op.qec_op_id}-{prefix}-ancilla-h-before-readout"
            self._add(
                ancilla_h, PhysicalOpcode.APPLY_1Q_PULSE, ancilla_atoms,
                {"operation": "hadamard", "pulse_id": "syndrome-ancilla-h-v0.1"},
                (data_h_after,), {self.target.bindings.entangling_zone_id: self._block_sizes[block.block_id]},
                self.target.bindings.one_qubit_resource_id, op,
            )
            move_out = self._move(op, block.block_id, "entangling", "storage", (ancilla_h,), f"{prefix}-move-out")
            move_readout = self._move(op, block.block_id, "storage", "readout", (move_out,), f"{prefix}-move-to-readout")
            measure_id = f"phy-{op.qec_op_id}-{prefix}-measure-syndrome"
            checks: dict[str, dict[str, Any]] = {}
            for item in op.syndrome_interactions:
                check = checks.setdefault(item.check_id, {
                    "basis": item.basis.value,
                    "ancilla_atom_id": _atom(block.block_id, item.ancilla_site_id),
                    "data_atom_ids": [],
                })
                check["data_atom_ids"].append(_atom(block.block_id, item.data_site_id))
            self._add(
                measure_id, PhysicalOpcode.MEASURE_ATOMS, ancilla_atoms,
                {
                    "basis": "z", "profile": "syndrome-readout-v0.1",
                    "block_id": block.block_id, "logical_qubit_id": block.logical_qubit_id,
                    "layout_id": block.layout_id, "round_index": round_index,
                    "checks": checks,
                },
                (move_readout,), {self.target.bindings.readout_zone_id: self._block_sizes[block.block_id]},
                self.target.bindings.readout_resource_id, op,
            )
            current = (self._move(op, block.block_id, "readout", "storage", (measure_id,), f"{prefix}-move-from-readout"),)
        return current

    def _lower_syndrome_layer(
        self, op: QECOp, block: EncodedBlock, round_index: int, layer: int,
        predecessors: tuple[str, ...],
    ) -> tuple[str, ...]:
        interactions = tuple(item for item in op.syndrome_interactions if item.layer == layer)
        if not interactions:
            return predecessors
        pairs = tuple(
            (_atom(block.block_id, item.data_site_id), _atom(block.block_id, item.ancilla_site_id))
            for item in interactions
        )
        operands = tuple(atom for pair in pairs for atom in pair)
        stem = f"phy-{op.qec_op_id}-r{round_index}-layer-{layer}"
        align_id = f"{stem}-align"
        self._add(
            align_id, PhysicalOpcode.ALIGN_ATOMS, operands,
            {"pairs": pairs, "alignment_profile": "surface-code-check-layer-v0.1"},
            predecessors, {self.target.bindings.entangling_zone_id: self._block_sizes[block.block_id]},
            self.target.bindings.transport_resource_id, op,
        )
        gate_id = f"{stem}-cz"
        self._add(
            gate_id, PhysicalOpcode.APPLY_2Q_RYDBERG_GATE, operands,
            {"gate": "cz", "pulse_id": "syndrome-cz-v0.1", "pairs": pairs},
            (align_id,), {self.target.bindings.entangling_zone_id: self._block_sizes[block.block_id]},
            self.target.bindings.rydberg_resource_id, op,
        )
        return (gate_id,)

    def _lower_barrier(self, op: QECOp, predecessors: tuple[str, ...]) -> tuple[str, ...]:
        task_id = f"phy-{op.qec_op_id}-sync"
        self._add(
            task_id, PhysicalOpcode.EMIT_SYNC, op.block_ids,
            {"tag": op.qec_op_id, "channel": "qec"}, predecessors,
            {self.target.bindings.storage_zone_id: sum(self._block_sizes[item] for item in op.block_ids)},
            self.target.bindings.clock_resource_id, op,
        )
        return (task_id,)

    def _move(self, op: QECOp, block_id: str, source: str, destination: str, predecessors: tuple[str, ...], suffix: str) -> str:
        source_id = getattr(self.target.bindings, f"{source}_zone_id")
        destination_id = getattr(self.target.bindings, f"{destination}_zone_id")
        trajectory = self.target.geometry.trajectory(source_id, destination_id)
        task_id = f"phy-{op.qec_op_id}-{suffix}"
        self._add(
            task_id, PhysicalOpcode.MOVE_BLOCK, (block_id,),
            {"trajectory_id": trajectory.trajectory_id, "source_zone_id": source_id, "destination_zone_id": destination_id},
            predecessors, {source_id: self._block_sizes[block_id], destination_id: self._block_sizes[block_id]},
            self.target.bindings.transport_resource_id, op,
            duration_ns=trajectory.duration_ns,
            extra_resource_ids=trajectory.conflict_group_ids,
        )
        return task_id

    def _add(
        self, task_id: str, opcode: PhysicalOpcode, operands: tuple[str, ...],
        parameters: Mapping[str, Any], predecessors: tuple[str, ...],
        zone_quantities: Mapping[str, int], resource_id: str, op: QECOp,
        *, duration_ns: int | None = None, extra_resource_ids: tuple[str, ...] = (),
    ) -> None:
        zone_demands = tuple(ZoneDemand(zone_id, quantity) for zone_id, quantity in zone_quantities.items())
        self._tasks.append(PhysicalTask(
            task_id=task_id,
            instruction=PhysicalInstruction(opcode, operands, parameters),
            predecessors=predecessors,
            resource_demands=(
                ResourceDemand(resource_id, mode=ResourceMode.SHARED),
                *(ResourceDemand(item, mode=ResourceMode.SHARED) for item in extra_resource_ids),
            ),
            zone_ids=tuple(zone_quantities),
            dispatch_group_id=op.qec_op_id,
            provenance=Provenance((op.logical_op_id,), (op.qec_op_id,)),
            duration_ns=duration_ns,
            zone_demands=zone_demands,
        ))


def lower_to_neutral_atom_tasks(protocol: QECProtocolIR, target: NeutralAtomTarget) -> PhysicalTaskGraph:
    return NeutralAtomLowerer(target).lower(protocol)

