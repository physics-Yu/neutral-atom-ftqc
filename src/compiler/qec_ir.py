"""QEC protocol IR between logical intent and physical experimental lowering."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from contracts.common import (
    SCHEMA_VERSION, ContractValidationError, canonical_json, parse_json,
    require_id, require_schema, to_primitive,
)


class QECOpKind(StrEnum):
    PREPARE_ZERO = "prepare_zero"
    PREPARE_PLUS = "prepare_plus"
    TRANSVERSAL_CNOT = "transversal_cnot"
    MEASURE_LOGICAL = "measure_logical"
    QEC_BARRIER = "qec_barrier"


@dataclass(frozen=True, slots=True)
class EncodedBlock:
    block_id: str
    logical_qubit_id: str
    layout_id: str
    distance: int
    data_site_ids: tuple[str, ...]
    ancilla_site_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, name in (
            (self.block_id, "block_id"), (self.logical_qubit_id, "logical_qubit_id"),
            (self.layout_id, "layout_id"),
        ):
            require_id(value, name)
        if not isinstance(self.distance, int) or isinstance(self.distance, bool):
            raise ContractValidationError("encoded-block distance must be an integer")
        if self.distance < 3 or self.distance % 2 == 0:
            raise ContractValidationError("encoded-block distance must be an odd integer >= 3")
        if len(self.data_site_ids) != self.distance**2:
            raise ContractValidationError("encoded block must expose d^2 data sites")
        if len(self.ancilla_site_ids) != self.distance**2 - 1:
            raise ContractValidationError("encoded block must expose d^2-1 ancilla sites")
        if len(set(self.data_site_ids + self.ancilla_site_ids)) != len(self.data_site_ids) + len(self.ancilla_site_ids):
            raise ContractValidationError("encoded-block site IDs must be unique")
        for site_id in self.data_site_ids + self.ancilla_site_ids:
            require_id(site_id, "encoded-block site_id")


@dataclass(frozen=True, slots=True)
class PhysicalQubitRef:
    block_id: str
    site_id: str

    def __post_init__(self) -> None:
        require_id(self.block_id, "block_id")
        require_id(self.site_id, "site_id")


@dataclass(frozen=True, slots=True)
class TransversalPair:
    control: PhysicalQubitRef
    target: PhysicalQubitRef

    def __post_init__(self) -> None:
        if not isinstance(self.control, PhysicalQubitRef) or not isinstance(self.target, PhysicalQubitRef):
            raise ContractValidationError("transversal endpoints must be PhysicalQubitRef values")
        if self.control.block_id == self.target.block_id:
            raise ContractValidationError("a transversal pair must span two blocks")


@dataclass(frozen=True, slots=True)
class QECOp:
    qec_op_id: str
    kind: QECOpKind
    block_ids: tuple[str, ...]
    predecessors: tuple[str, ...]
    logical_op_id: str
    strategy: str
    pairings: tuple[TransversalPair, ...] = ()
    rounds: int = 1

    def __post_init__(self) -> None:
        require_id(self.qec_op_id, "qec_op_id")
        require_id(self.logical_op_id, "logical_op_id")
        require_id(self.strategy, "strategy")
        if not isinstance(self.kind, QECOpKind):
            raise ContractValidationError("kind must be a QECOpKind")
        for block_id in self.block_ids:
            require_id(block_id, "block_id")
        for predecessor in self.predecessors:
            require_id(predecessor, "predecessor")
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ContractValidationError("QEC operation block IDs must be unique")
        if not isinstance(self.rounds, int) or isinstance(self.rounds, bool) or self.rounds <= 0:
            raise ContractValidationError("rounds must be a positive integer")
        if self.kind is QECOpKind.TRANSVERSAL_CNOT and len(self.block_ids) != 2:
            raise ContractValidationError("transversal_cnot requires control and target blocks")
        if self.kind in {QECOpKind.PREPARE_ZERO, QECOpKind.PREPARE_PLUS, QECOpKind.MEASURE_LOGICAL} and len(self.block_ids) != 1:
            raise ContractValidationError(f"{self.kind.value} requires exactly one block")
        if self.kind is QECOpKind.QEC_BARRIER and not self.block_ids:
            raise ContractValidationError("qec_barrier requires at least one block")
        if self.kind is QECOpKind.TRANSVERSAL_CNOT and not self.pairings:
            raise ContractValidationError("transversal_cnot requires explicit physical pairings")
        if self.kind is not QECOpKind.TRANSVERSAL_CNOT and self.pairings:
            raise ContractValidationError("only transversal_cnot may contain pairings")


@dataclass(frozen=True, slots=True)
class QECProtocolIR:
    protocol_id: str
    source_circuit_id: str
    blocks: tuple[EncodedBlock, ...]
    operations: tuple[QECOp, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        require_id(self.protocol_id, "protocol_id")
        require_id(self.source_circuit_id, "source_circuit_id")
        block_ids = [block.block_id for block in self.blocks]
        logical_ids = [block.logical_qubit_id for block in self.blocks]
        op_ids = [op.qec_op_id for op in self.operations]
        if len(block_ids) != len(set(block_ids)) or len(logical_ids) != len(set(logical_ids)):
            raise ContractValidationError("encoded block IDs and logical-qubit mappings must be unique")
        if len(op_ids) != len(set(op_ids)):
            raise ContractValidationError("QEC operation IDs must be unique")
        blocks = {block.block_id: block for block in self.blocks}
        known_ops = set(op_ids)
        for op in self.operations:
            if set(op.block_ids) - blocks.keys():
                raise ContractValidationError(f"QEC operation {op.qec_op_id!r} references an unknown block")
            if set(op.predecessors) - known_ops:
                raise ContractValidationError(f"QEC operation {op.qec_op_id!r} references an unknown predecessor")
            if op.qec_op_id in op.predecessors:
                raise ContractValidationError(f"QEC operation {op.qec_op_id!r} depends on itself")
            if op.kind is QECOpKind.TRANSVERSAL_CNOT:
                _validate_pairings(op, blocks)
        _reject_cycles({op.qec_op_id: op.predecessors for op in self.operations})

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QECProtocolIR":
        blocks = tuple(EncodedBlock(
            block_id=item["block_id"], logical_qubit_id=item["logical_qubit_id"],
            layout_id=item["layout_id"], distance=item["distance"],
            data_site_ids=tuple(item["data_site_ids"]), ancilla_site_ids=tuple(item["ancilla_site_ids"]),
        ) for item in data["blocks"])
        operations = tuple(QECOp(
            qec_op_id=item["qec_op_id"], kind=QECOpKind(item["kind"]),
            block_ids=tuple(item["block_ids"]), predecessors=tuple(item["predecessors"]),
            logical_op_id=item["logical_op_id"], strategy=item["strategy"], rounds=item.get("rounds", 1),
            pairings=tuple(TransversalPair(
                PhysicalQubitRef(pair["control"]["block_id"], pair["control"]["site_id"]),
                PhysicalQubitRef(pair["target"]["block_id"], pair["target"]["site_id"]),
            ) for pair in item.get("pairings", ())),
        ) for item in data["operations"])
        return cls(
            protocol_id=data["protocol_id"], source_circuit_id=data["source_circuit_id"],
            blocks=blocks, operations=operations,
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, payload: str) -> "QECProtocolIR":
        return cls.from_dict(parse_json(payload))


def _validate_pairings(op: QECOp, blocks: Mapping[str, EncodedBlock]) -> None:
    control_id, target_id = op.block_ids
    control_sites = set(blocks[control_id].data_site_ids)
    target_sites = set(blocks[target_id].data_site_ids)
    seen_control: set[str] = set()
    seen_target: set[str] = set()
    for pair in op.pairings:
        if pair.control.block_id != control_id or pair.control.site_id not in control_sites:
            raise ContractValidationError("transversal pair has an invalid control reference")
        if pair.target.block_id != target_id or pair.target.site_id not in target_sites:
            raise ContractValidationError("transversal pair has an invalid target reference")
        seen_control.add(pair.control.site_id)
        seen_target.add(pair.target.site_id)
    if seen_control != control_sites or seen_target != target_sites or len(op.pairings) != len(control_sites):
        raise ContractValidationError("transversal pairings must be a bijection over all data sites")


def _reject_cycles(edges: Mapping[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ContractValidationError(f"QEC operation graph contains a cycle at {node!r}")
        if node in visited:
            return
        visiting.add(node)
        for predecessor in edges[node]:
            visit(predecessor)
        visiting.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)

