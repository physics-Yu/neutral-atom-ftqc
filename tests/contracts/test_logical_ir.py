from __future__ import annotations

import pytest

from compiler.logical_ir import (
    CodeFamily, LogicalCircuitIR, LogicalInitialState, LogicalOp, LogicalOpKind,
    LogicalQubitDecl,
)
from contracts import ContractValidationError


@pytest.mark.parametrize("distance", [3, 5])
def test_distance_three_and_five_round_trip(distance: int) -> None:
    circuit = LogicalCircuitIR(
        circuit_id=f"ghz-d{distance}",
        logical_qubits=(
            LogicalQubitDecl("L0", CodeFamily.ROTATED_SURFACE_CODE, distance, LogicalInitialState.PLUS),
            LogicalQubitDecl("L1", CodeFamily.ROTATED_SURFACE_CODE, distance, LogicalInitialState.ZERO),
        ),
        operations=(
            LogicalOp("init-0", LogicalOpKind.PREPARE_LOGICAL_PLUS, ("L0",), logical_layer=0),
            LogicalOp("init-1", LogicalOpKind.PREPARE_LOGICAL_ZERO, ("L1",), logical_layer=0),
            LogicalOp("cx", LogicalOpKind.LOGICAL_CNOT, ("L0", "L1"), ("init-0", "init-1"), 1),
        ),
    )
    assert LogicalCircuitIR.from_json(circuit.to_json()) == circuit


def test_invalid_distance_is_rejected() -> None:
    with pytest.raises(ContractValidationError, match="odd integer"):
        LogicalQubitDecl("L0", CodeFamily.ROTATED_SURFACE_CODE, 4)


def test_duplicate_ids_and_unknown_references_are_rejected() -> None:
    qubit = LogicalQubitDecl("L0", CodeFamily.ROTATED_SURFACE_CODE, 3)
    with pytest.raises(ContractValidationError, match="qubit IDs"):
        LogicalCircuitIR("bad", (qubit, qubit), ())
    with pytest.raises(ContractValidationError, match="unknown logical qubits"):
        LogicalCircuitIR("bad", (qubit,), (LogicalOp("m", LogicalOpKind.MEASURE_LOGICAL, ("L9",)),))


def test_logical_cycle_is_rejected() -> None:
    qubit = LogicalQubitDecl("L0", CodeFamily.ROTATED_SURFACE_CODE, 3)
    ops = (
        LogicalOp("a", LogicalOpKind.QEC_BARRIER, ("L0",), ("b",)),
        LogicalOp("b", LogicalOpKind.QEC_BARRIER, ("L0",), ("a",)),
    )
    with pytest.raises(ContractValidationError, match="cycle"):
        LogicalCircuitIR("bad", (qubit,), ops)

