"""Versioned logical/QEC intent IR; never executable by physical backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from contracts.common import (
    SCHEMA_VERSION,
    ContractValidationError,
    canonical_json,
    frozen_mapping,
    parse_json,
    require_id,
    require_schema,
    to_primitive,
)


class CodeFamily(StrEnum):
    ROTATED_SURFACE_CODE = "rotated_surface_code"
    PLANAR_SURFACE_CODE = "planar_surface_code"


class LogicalInitialState(StrEnum):
    ZERO = "zero"
    PLUS = "plus"
    UNINITIALIZED = "uninitialized"


class LogicalOpKind(StrEnum):
    PREPARE_LOGICAL_ZERO = "prepare_logical_zero"
    PREPARE_LOGICAL_PLUS = "prepare_logical_plus"
    LOGICAL_CNOT = "logical_cnot"
    MEASURE_LOGICAL = "measure_logical"
    QEC_BARRIER = "qec_barrier"
    SYNDROME_ROUND = "syndrome_round"


@dataclass(frozen=True, slots=True)
class LogicalQubitDecl:
    logical_qubit_id: str
    code_family: CodeFamily
    distance: int
    initial_state: LogicalInitialState = LogicalInitialState.UNINITIALIZED

    def __post_init__(self) -> None:
        require_id(self.logical_qubit_id, "logical_qubit_id")
        if not isinstance(self.code_family, CodeFamily):
            raise ContractValidationError("code_family must be a CodeFamily")
        if not isinstance(self.distance, int) or isinstance(self.distance, bool):
            raise ContractValidationError("distance must be an integer")
        if self.distance < 3 or self.distance % 2 == 0:
            raise ContractValidationError("surface-code distance must be an odd integer >= 3")
        if not isinstance(self.initial_state, LogicalInitialState):
            raise ContractValidationError("initial_state must be a LogicalInitialState")


@dataclass(frozen=True, slots=True)
class LogicalOp:
    op_id: str
    kind: LogicalOpKind
    operands: tuple[str, ...]
    predecessors: tuple[str, ...] = ()
    logical_layer: int = 0
    params: Mapping[str, Any] = field(default_factory=dict)
    source_span: str | None = None

    def __post_init__(self) -> None:
        require_id(self.op_id, "op_id")
        if not isinstance(self.kind, LogicalOpKind):
            raise ContractValidationError("kind must be a LogicalOpKind")
        if not isinstance(self.logical_layer, int) or isinstance(self.logical_layer, bool) or self.logical_layer < 0:
            raise ContractValidationError("logical_layer must be a non-negative integer")
        for operand in self.operands:
            require_id(operand, "operand")
        for predecessor in self.predecessors:
            require_id(predecessor, "predecessor")
        expected = {
            LogicalOpKind.PREPARE_LOGICAL_ZERO: 1,
            LogicalOpKind.PREPARE_LOGICAL_PLUS: 1,
            LogicalOpKind.LOGICAL_CNOT: 2,
            LogicalOpKind.MEASURE_LOGICAL: 1,
            LogicalOpKind.SYNDROME_ROUND: 1,
        }.get(self.kind)
        if expected is not None and len(self.operands) != expected:
            raise ContractValidationError(f"{self.kind.value} requires {expected} operand(s)")
        if self.kind is LogicalOpKind.LOGICAL_CNOT and self.operands[0] == self.operands[1]:
            raise ContractValidationError("logical_cnot control and target must differ")
        if self.kind is LogicalOpKind.QEC_BARRIER and not self.operands:
            raise ContractValidationError("qec_barrier requires at least one logical qubit")
        if self.kind is LogicalOpKind.SYNDROME_ROUND:
            rounds = self.params.get("rounds", 1)
            if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds <= 0:
                raise ContractValidationError("syndrome_round rounds must be a positive integer")
        object.__setattr__(self, "params", frozen_mapping(self.params))


@dataclass(frozen=True, slots=True)
class LogicalCircuitIR:
    circuit_id: str
    logical_qubits: tuple[LogicalQubitDecl, ...]
    operations: tuple[LogicalOp, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        require_id(self.circuit_id, "circuit_id")
        qubit_ids = [item.logical_qubit_id for item in self.logical_qubits]
        op_ids = [item.op_id for item in self.operations]
        if len(qubit_ids) != len(set(qubit_ids)):
            raise ContractValidationError("logical qubit IDs must be unique")
        if len(op_ids) != len(set(op_ids)):
            raise ContractValidationError("logical operation IDs must be unique")
        known_qubits = set(qubit_ids)
        known_ops = set(op_ids)
        for op in self.operations:
            unknown_qubits = set(op.operands) - known_qubits
            if unknown_qubits:
                raise ContractValidationError(f"operation {op.op_id!r} references unknown logical qubits")
            unknown_predecessors = set(op.predecessors) - known_ops
            if unknown_predecessors:
                raise ContractValidationError(f"operation {op.op_id!r} references unknown predecessors")
            if op.op_id in op.predecessors:
                raise ContractValidationError(f"operation {op.op_id!r} depends on itself")
        _reject_cycles({op.op_id: op.predecessors for op in self.operations}, "logical operation")

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicalCircuitIR":
        return cls(
            circuit_id=data["circuit_id"],
            logical_qubits=tuple(
                LogicalQubitDecl(
                    logical_qubit_id=item["logical_qubit_id"],
                    code_family=CodeFamily(item["code_family"]),
                    distance=item["distance"],
                    initial_state=LogicalInitialState(item.get("initial_state", "uninitialized")),
                ) for item in data["logical_qubits"]
            ),
            operations=tuple(
                LogicalOp(
                    op_id=item["op_id"], kind=LogicalOpKind(item["kind"]),
                    operands=tuple(item["operands"]),
                    predecessors=tuple(item.get("predecessors", ())),
                    logical_layer=item.get("logical_layer", 0),
                    params=item.get("params", {}), source_span=item.get("source_span"),
                ) for item in data["operations"]
            ),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, payload: str) -> "LogicalCircuitIR":
        return cls.from_dict(parse_json(payload))


def _reject_cycles(edges: Mapping[str, tuple[str, ...]], label: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ContractValidationError(f"{label} graph contains a cycle at {node!r}")
        if node in visited:
            return
        visiting.add(node)
        for predecessor in edges[node]:
            visit(predecessor)
        visiting.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)


