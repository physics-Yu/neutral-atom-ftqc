"""Logical-to-QEC expansion; physical lowering remains an M2 responsibility."""

from __future__ import annotations

from typing import Mapping

from compiler.logical_ir import CodeFamily, LogicalCircuitIR, LogicalOpKind
from compiler.qec_ir import (
    EncodedBlock, PhysicalQubitRef, QECOp, QECOpKind, QECProtocolIR, TransversalPair,
)
from contracts.common import ContractValidationError
from qec.surface_code import SiteRole, SurfaceCodeLayout


def expand_to_qec_protocol(
    circuit: LogicalCircuitIR,
    layouts: Mapping[str, SurfaceCodeLayout],
) -> QECProtocolIR:
    """Expand logical operations to explicit encoded blocks and QEC protocol macros."""

    declarations = {item.logical_qubit_id: item for item in circuit.logical_qubits}
    if set(layouts) != set(declarations):
        raise ContractValidationError("layouts must map every declared logical qubit exactly once")

    blocks: list[EncodedBlock] = []
    block_by_logical: dict[str, EncodedBlock] = {}
    layout_by_block: dict[str, SurfaceCodeLayout] = {}
    for logical_id, declaration in declarations.items():
        layout = layouts[logical_id]
        if not isinstance(layout, SurfaceCodeLayout):
            raise ContractValidationError(f"layout for {logical_id!r} must be a SurfaceCodeLayout")
        if declaration.code_family is not CodeFamily.ROTATED_SURFACE_CODE:
            raise ContractValidationError("M1 supports only rotated surface-code logical qubits")
        if layout.spec.distance != declaration.distance:
            raise ContractValidationError(f"layout distance does not match declaration for {logical_id!r}")
        block_id = f"block-{logical_id}"
        block = EncodedBlock(
            block_id=block_id,
            logical_qubit_id=logical_id,
            layout_id=layout.layout_id,
            distance=layout.spec.distance,
            data_site_ids=tuple(site.site_id for site in layout.data_sites),
            ancilla_site_ids=tuple(site.site_id for site in layout.ancilla_sites),
        )
        blocks.append(block)
        block_by_logical[logical_id] = block
        layout_by_block[block_id] = layout

    operations: list[QECOp] = []
    for logical_op in circuit.operations:
        block_ids = tuple(block_by_logical[item].block_id for item in logical_op.operands)
        qec_id = f"qec-{logical_op.op_id}"
        predecessors = tuple(f"qec-{item}" for item in logical_op.predecessors)
        if logical_op.kind is LogicalOpKind.PREPARE_LOGICAL_ZERO:
            kind, strategy, pairings = QECOpKind.PREPARE_ZERO, "surface_code_prepare_zero", ()
        elif logical_op.kind is LogicalOpKind.PREPARE_LOGICAL_PLUS:
            kind, strategy, pairings = QECOpKind.PREPARE_PLUS, "surface_code_prepare_plus", ()
        elif logical_op.kind is LogicalOpKind.LOGICAL_CNOT:
            kind, strategy = QECOpKind.TRANSVERSAL_CNOT, "transversal"
            pairings = _transversal_pairings(
                block_by_logical[logical_op.operands[0]],
                block_by_logical[logical_op.operands[1]],
                layout_by_block,
            )
        elif logical_op.kind is LogicalOpKind.MEASURE_LOGICAL:
            kind, strategy, pairings = QECOpKind.MEASURE_LOGICAL, "surface_code_measure", ()
        else:
            kind, strategy, pairings = QECOpKind.QEC_BARRIER, "dependency_barrier", ()
        operations.append(QECOp(
            qec_op_id=qec_id, kind=kind, block_ids=block_ids,
            predecessors=predecessors, logical_op_id=logical_op.op_id,
            strategy=strategy, pairings=pairings,
        ))

    return QECProtocolIR(
        protocol_id=f"qec-{circuit.circuit_id}", source_circuit_id=circuit.circuit_id,
        blocks=tuple(blocks), operations=tuple(operations),
    )


def _transversal_pairings(
    control: EncodedBlock,
    target: EncodedBlock,
    layouts: Mapping[str, SurfaceCodeLayout],
) -> tuple[TransversalPair, ...]:
    if control.distance != target.distance:
        raise ContractValidationError("transversal CNOT requires equal-distance blocks")
    control_layout = layouts[control.block_id]
    target_layout = layouts[target.block_id]
    control_by_coordinate = {
        site.coordinate: site.site_id for site in control_layout.sites if site.role is SiteRole.DATA
    }
    target_by_coordinate = {
        site.coordinate: site.site_id for site in target_layout.sites if site.role is SiteRole.DATA
    }
    if control_by_coordinate.keys() != target_by_coordinate.keys():
        raise ContractValidationError("transversal CNOT requires coordinate-compatible data layouts")
    return tuple(
        TransversalPair(
            PhysicalQubitRef(control.block_id, control_by_coordinate[coordinate]),
            PhysicalQubitRef(target.block_id, target_by_coordinate[coordinate]),
        )
        for coordinate in sorted(control_by_coordinate, key=lambda item: (item.y, item.x))
    )

