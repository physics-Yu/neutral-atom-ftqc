"""Build the four-logical-qubit GHZ logical and QEC protocol IRs."""

from __future__ import annotations

import argparse

from compiler.compiler import expand_to_qec_protocol
from compiler.logical_ir import (
    CodeFamily, LogicalCircuitIR, LogicalInitialState, LogicalOp, LogicalOpKind,
    LogicalQubitDecl,
)
from compiler.lowering.neutral_atom import lower_to_neutral_atom_tasks
from compiler.physical_ir import PhysicalTaskGraph
from compiler.qec_ir import QECProtocolIR
from hardware.zones import build_reference_target
from qec.surface_code import SurfaceCodeSpec, generate_surface_code_layout


def build_ghz_logical_circuit(distance: int = 3) -> LogicalCircuitIR:
    qubits = tuple(
        LogicalQubitDecl(
            f"L{index}", CodeFamily.ROTATED_SURFACE_CODE, distance,
            LogicalInitialState.PLUS if index == 0 else LogicalInitialState.ZERO,
        )
        for index in range(4)
    )
    operations = (
        LogicalOp("init-L0", LogicalOpKind.PREPARE_LOGICAL_PLUS, ("L0",), logical_layer=0),
        LogicalOp("init-L1", LogicalOpKind.PREPARE_LOGICAL_ZERO, ("L1",), logical_layer=0),
        LogicalOp("init-L2", LogicalOpKind.PREPARE_LOGICAL_ZERO, ("L2",), logical_layer=0),
        LogicalOp("init-L3", LogicalOpKind.PREPARE_LOGICAL_ZERO, ("L3",), logical_layer=0),
        LogicalOp(
            "cx-L0-L1", LogicalOpKind.LOGICAL_CNOT, ("L0", "L1"),
            ("init-L0", "init-L1"), logical_layer=1,
        ),
        LogicalOp(
            "cx-L0-L2", LogicalOpKind.LOGICAL_CNOT, ("L0", "L2"),
            ("cx-L0-L1", "init-L2"), logical_layer=2,
        ),
        LogicalOp(
            "cx-L1-L3", LogicalOpKind.LOGICAL_CNOT, ("L1", "L3"),
            ("cx-L0-L1", "init-L3"), logical_layer=2,
        ),
    )
    return LogicalCircuitIR(f"logical-ghz4-d{distance}", qubits, operations)


def build_ghz_qec_protocol(distance: int = 3) -> QECProtocolIR:
    circuit = build_ghz_logical_circuit(distance)
    layout = generate_surface_code_layout(SurfaceCodeSpec(distance))
    return expand_to_qec_protocol(
        circuit, {qubit.logical_qubit_id: layout for qubit in circuit.logical_qubits}
    )


def build_ghz_physical_graph(distance: int = 3) -> PhysicalTaskGraph:
    return lower_to_neutral_atom_tasks(build_ghz_qec_protocol(distance), build_reference_target())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance", type=int, default=3)
    args = parser.parse_args()
    protocol = build_ghz_qec_protocol(args.distance)
    graph = build_ghz_physical_graph(args.distance)
    cnot_ops = [op for op in protocol.operations if op.kind.value == "transversal_cnot"]
    print(
        f"Built {protocol.protocol_id}: {len(protocol.blocks)} blocks, "
        f"{len(protocol.operations)} QEC operations, "
        f"{len(cnot_ops[0].pairings)} physical pairs per transversal CNOT; "
        f"lowered to {len(graph.tasks)} physical tasks."
    )


if __name__ == "__main__":
    main()

