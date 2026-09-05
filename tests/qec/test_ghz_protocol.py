from __future__ import annotations

import pytest

from compiler.compiler import expand_to_qec_protocol
from compiler.qec_ir import QECOpKind, QECProtocolIR
from contracts import ContractValidationError
from examples.ghz_surface_code import build_ghz_logical_circuit, build_ghz_qec_protocol
from qec.surface_code import SurfaceCodeSpec, generate_surface_code_layout


@pytest.mark.parametrize("distance", [3, 5])
def test_ghz_logical_layers_and_transversal_pairings(distance: int) -> None:
    circuit = build_ghz_logical_circuit(distance)
    protocol = build_ghz_qec_protocol(distance)
    cnot_logical = [op for op in circuit.operations if op.kind.value == "logical_cnot"]
    cnot_qec = [op for op in protocol.operations if op.kind is QECOpKind.TRANSVERSAL_CNOT]

    assert len(circuit.logical_qubits) == 4
    assert len(protocol.blocks) == 4
    assert len(cnot_logical) == len(cnot_qec) == 3
    assert {op.op_id for op in cnot_logical if op.logical_layer == 2} == {"cx-L0-L2", "cx-L1-L3"}
    assert "cx-L1-L3" not in next(op for op in cnot_logical if op.op_id == "cx-L0-L2").predecessors
    assert "cx-L0-L2" not in next(op for op in cnot_logical if op.op_id == "cx-L1-L3").predecessors
    assert all(len(op.pairings) == distance**2 for op in cnot_qec)
    assert all(len({pair.control.site_id for pair in op.pairings}) == distance**2 for op in cnot_qec)
    assert QECProtocolIR.from_json(protocol.to_json()) == protocol


def test_transversal_cnot_rejects_incompatible_distance() -> None:
    circuit = build_ghz_logical_circuit(3)
    layouts = {
        qubit.logical_qubit_id: generate_surface_code_layout(SurfaceCodeSpec(3))
        for qubit in circuit.logical_qubits
    }
    layouts["L3"] = generate_surface_code_layout(SurfaceCodeSpec(5))
    with pytest.raises(ContractValidationError, match="layout distance"):
        expand_to_qec_protocol(circuit, layouts)


def test_layout_mapping_must_be_exact() -> None:
    circuit = build_ghz_logical_circuit(3)
    layout = generate_surface_code_layout(SurfaceCodeSpec(3))
    with pytest.raises(ContractValidationError, match="exactly once"):
        expand_to_qec_protocol(circuit, {"L0": layout})


@pytest.mark.parametrize("distance,edge_count", [(3, 24), (5, 80)])
def test_syndrome_round_has_eight_collision_free_interaction_layers(distance: int, edge_count: int) -> None:
    circuit = build_ghz_logical_circuit(distance, syndrome_rounds=2)
    protocol = build_ghz_qec_protocol(distance, syndrome_rounds=2)
    logical_rounds = [op for op in circuit.operations if op.kind.value == "syndrome_round"]
    qec_rounds = [op for op in protocol.operations if op.kind is QECOpKind.SYNDROME_ROUND]

    assert len(logical_rounds) == len(qec_rounds) == 4
    assert all(op.rounds == 2 for op in qec_rounds)
    assert all(len(op.syndrome_interactions) == edge_count for op in qec_rounds)
    for operation in qec_rounds:
        assert {item.layer for item in operation.syndrome_interactions} == set(range(8))
        for layer in range(8):
            subjects = [
                subject
                for item in operation.syndrome_interactions if item.layer == layer
                for subject in (item.ancilla_site_id, item.data_site_id)
            ]
            assert len(subjects) == len(set(subjects))
    assert QECProtocolIR.from_json(protocol.to_json()) == protocol


