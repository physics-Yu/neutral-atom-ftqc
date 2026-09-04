"""Physical Experimental ISA v0.1 and schedulable task-DAG contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from contracts.common import (
    SCHEMA_VERSION, ContractValidationError, canonical_json, frozen_mapping,
    parse_json, require_id, require_schema, to_primitive,
)
from contracts.machine import MachineConfig


class PhysicalOpcode(StrEnum):
    MOVE_ATOMS = "move_atoms"
    MOVE_BLOCK = "move_block"
    ALIGN_ATOMS = "align_atoms"
    APPLY_1Q_PULSE = "apply_1q_pulse"
    APPLY_2Q_RYDBERG_GATE = "apply_2q_rydberg_gate"
    IMAGE_ATOMS = "image_atoms"
    MEASURE_ATOMS = "measure_atoms"
    RESET_ATOMS = "reset_atoms"
    LOAD_RESERVOIR_ATOM = "load_reservoir_atom"
    PLACE_ATOM = "place_atom"
    WAIT = "wait"
    EMIT_SYNC = "emit_sync"


FORBIDDEN_LOGICAL_OPCODES = frozenset({
    "logical_cnot", "logical_init", "qec_round", "syndrome_round", "prepare_ghz"
})


class ResourceMode(StrEnum):
    EXCLUSIVE = "exclusive"
    SHARED = "shared"


class ConsumePolicy(StrEnum):
    KEEP = "keep"
    CONSUME = "consume"


@dataclass(frozen=True, slots=True)
class PhysicalInstruction:
    opcode: PhysicalOpcode
    operands: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.opcode, PhysicalOpcode):
            raise ContractValidationError("physical opcode must be a PhysicalOpcode")
        for operand in self.operands:
            require_id(operand, "physical operand")
        object.__setattr__(self, "parameters", frozen_mapping(self.parameters))


@dataclass(frozen=True, slots=True)
class ResourceDemand:
    resource_id: str
    quantity: int = 1
    mode: ResourceMode = ResourceMode.EXCLUSIVE

    def __post_init__(self) -> None:
        require_id(self.resource_id, "resource_id")
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool) or self.quantity <= 0:
            raise ContractValidationError("resource quantity must be a positive integer")
        if not isinstance(self.mode, ResourceMode):
            raise ContractValidationError("resource mode must be a ResourceMode")


@dataclass(frozen=True, slots=True)
class ConditionRef:
    message_id: str
    predicate: str = "truthy"
    consume_policy: ConsumePolicy = ConsumePolicy.KEEP

    def __post_init__(self) -> None:
        require_id(self.message_id, "message_id")
        require_id(self.predicate, "predicate")
        if not isinstance(self.consume_policy, ConsumePolicy):
            raise ContractValidationError("consume_policy must be a ConsumePolicy")


@dataclass(frozen=True, slots=True)
class Provenance:
    logical_op_ids: tuple[str, ...] = ()
    qec_op_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in self.logical_op_ids + self.qec_op_ids:
            require_id(value, "provenance ID")


@dataclass(frozen=True, slots=True)
class PhysicalTask:
    task_id: str
    instruction: PhysicalInstruction
    predecessors: tuple[str, ...] = ()
    earliest_start_ns: int = 0
    deadline_ns: int | None = None
    priority: int = 0
    resource_demands: tuple[ResourceDemand, ...] = ()
    zone_ids: tuple[str, ...] = ()
    conditions: tuple[ConditionRef, ...] = ()
    dispatch_group_id: str | None = None
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        require_id(self.task_id, "task_id")
        if not isinstance(self.instruction, PhysicalInstruction):
            raise ContractValidationError("instruction must be a PhysicalInstruction")
        if not isinstance(self.earliest_start_ns, int) or isinstance(self.earliest_start_ns, bool) or self.earliest_start_ns < 0:
            raise ContractValidationError("earliest_start_ns must be a non-negative integer")
        if self.deadline_ns is not None:
            if not isinstance(self.deadline_ns, int) or isinstance(self.deadline_ns, bool) or self.deadline_ns <= self.earliest_start_ns:
                raise ContractValidationError("deadline_ns must be greater than earliest_start_ns")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise ContractValidationError("priority must be an integer")
        for value in self.predecessors:
            require_id(value, "predecessor")
        for value in self.zone_ids:
            require_id(value, "zone_id")
        if self.dispatch_group_id is not None:
            require_id(self.dispatch_group_id, "dispatch_group_id")


@dataclass(frozen=True, slots=True)
class PhysicalTaskGraph:
    graph_id: str
    revision: int
    tasks: tuple[PhysicalTask, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        require_id(self.graph_id, "graph_id")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise ContractValidationError("revision must be a non-negative integer")
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ContractValidationError("physical task IDs must be unique")
        known = set(task_ids)
        edges: dict[str, tuple[str, ...]] = {}
        for task in self.tasks:
            unknown = set(task.predecessors) - known
            if unknown:
                raise ContractValidationError(f"task {task.task_id!r} references unknown predecessors")
            if task.task_id in task.predecessors:
                raise ContractValidationError(f"task {task.task_id!r} depends on itself")
            edges[task.task_id] = task.predecessors
        _reject_cycles(edges)

    def validate_against_machine(self, machine: MachineConfig) -> None:
        zone_ids = {zone.zone_id for zone in machine.zones}
        resources = {resource.resource_id: resource for resource in machine.resources}
        durations = machine.calibration.duration_by_opcode_ns
        for task in self.tasks:
            unknown_zones = set(task.zone_ids) - zone_ids
            if unknown_zones:
                raise ContractValidationError(f"task {task.task_id!r} references unknown zones")
            if task.instruction.opcode.value not in durations:
                raise ContractValidationError(
                    f"task {task.task_id!r} has no positive calibrated duration"
                )
            for demand in task.resource_demands:
                resource = resources.get(demand.resource_id)
                if resource is None:
                    raise ContractValidationError(f"task {task.task_id!r} references an unknown resource")
                if demand.quantity > resource.capacity:
                    raise ContractValidationError(f"task {task.task_id!r} exceeds resource capacity")

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicalTaskGraph":
        tasks = []
        for item in data["tasks"]:
            ins = item["instruction"]
            tasks.append(PhysicalTask(
                task_id=item["task_id"],
                instruction=physical_instruction_from_untrusted(ins),
                predecessors=tuple(item.get("predecessors", ())),
                earliest_start_ns=item.get("earliest_start_ns", 0),
                deadline_ns=item.get("deadline_ns"), priority=item.get("priority", 0),
                resource_demands=tuple(ResourceDemand(
                    resource_id=value["resource_id"], quantity=value.get("quantity", 1),
                    mode=ResourceMode(value.get("mode", "exclusive")),
                ) for value in item.get("resource_demands", ())),
                zone_ids=tuple(item.get("zone_ids", ())),
                conditions=tuple(ConditionRef(
                    message_id=value["message_id"], predicate=value.get("predicate", "truthy"),
                    consume_policy=ConsumePolicy(value.get("consume_policy", "keep")),
                ) for value in item.get("conditions", ())),
                dispatch_group_id=item.get("dispatch_group_id"),
                provenance=Provenance(
                    logical_op_ids=tuple(item.get("provenance", {}).get("logical_op_ids", ())),
                    qec_op_ids=tuple(item.get("provenance", {}).get("qec_op_ids", ())),
                ),
            ))
        return cls(graph_id=data["graph_id"], revision=data["revision"], tasks=tuple(tasks),
                   schema_version=data.get("schema_version", SCHEMA_VERSION))

    @classmethod
    def from_json(cls, payload: str) -> "PhysicalTaskGraph":
        return cls.from_dict(parse_json(payload))


def physical_instruction_from_untrusted(data: Mapping[str, Any]) -> PhysicalInstruction:
    raw_opcode = data.get("opcode")
    if isinstance(raw_opcode, str) and raw_opcode.lower() in FORBIDDEN_LOGICAL_OPCODES:
        raise ContractValidationError(f"logical/QEC macro {raw_opcode!r} cannot cross the physical boundary")
    try:
        opcode = PhysicalOpcode(raw_opcode)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"unknown physical opcode: {raw_opcode!r}") from exc
    return PhysicalInstruction(opcode, tuple(data.get("operands", ())), data.get("parameters", {}))


def _reject_cycles(edges: Mapping[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ContractValidationError(f"physical task graph contains a cycle at {node!r}")
        if node in visited:
            return
        visiting.add(node)
        for predecessor in edges[node]:
            visit(predecessor)
        visiting.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)

