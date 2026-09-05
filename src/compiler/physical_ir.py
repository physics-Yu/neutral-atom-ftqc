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


@dataclass(frozen=True, slots=True)
class InstructionSemantics:
    family: str
    allowed_zone_kinds: tuple[str, ...]
    required_resource_classes: tuple[str, ...]
    state_effect: str
    emits_observation: bool = False


PHYSICAL_ISA: Mapping[PhysicalOpcode, InstructionSemantics] = {
    PhysicalOpcode.MOVE_ATOMS: InstructionSemantics("transport", ("storage", "entangling", "readout", "reservoir"), ("transport",), "changes atom positions"),
    PhysicalOpcode.MOVE_BLOCK: InstructionSemantics("transport", ("storage", "entangling", "readout"), ("transport",), "changes the zone occupied by one encoded block"),
    PhysicalOpcode.ALIGN_ATOMS: InstructionSemantics("transport", ("entangling",), ("transport",), "places explicit atom pairs in an interaction geometry"),
    PhysicalOpcode.APPLY_1Q_PULSE: InstructionSemantics("coherent_control", ("storage", "entangling"), ("one_qubit_control",), "applies a calibrated one-atom unitary"),
    PhysicalOpcode.APPLY_2Q_RYDBERG_GATE: InstructionSemantics("coherent_control", ("entangling",), ("rydberg_control",), "applies calibrated pairwise Rydberg interactions"),
    PhysicalOpcode.IMAGE_ATOMS: InstructionSemantics("observation", ("storage", "readout", "reservoir"), ("imaging",), "observes atom presence without defining qubit readout", True),
    PhysicalOpcode.MEASURE_ATOMS: InstructionSemantics("observation", ("readout",), ("readout",), "destructively measures physical qubits", True),
    PhysicalOpcode.RESET_ATOMS: InstructionSemantics("atom_management", ("storage", "readout", "reservoir"), ("reset",), "prepares explicit atoms in a configured basis state"),
    PhysicalOpcode.LOAD_RESERVOIR_ATOM: InstructionSemantics("atom_management", ("reservoir",), ("reservoir_loading",), "creates a usable atom in the reservoir"),
    PhysicalOpcode.PLACE_ATOM: InstructionSemantics("atom_management", ("storage", "reservoir"), ("transport",), "moves one replacement atom into one vacant site"),
    PhysicalOpcode.WAIT: InstructionSemantics("timing", ("storage", "entangling", "readout", "reservoir"), ("clock",), "retains subjects and resources for an explicit interval"),
    PhysicalOpcode.EMIT_SYNC: InstructionSemantics("synchronization", ("storage", "entangling", "readout", "reservoir"), ("clock",), "emits a synchronization marker"),
}


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
        self.validate_semantics()

    def validate_semantics(self) -> None:
        parameters = self.parameters
        opcode = self.opcode
        if opcode in {PhysicalOpcode.MOVE_ATOMS, PhysicalOpcode.MOVE_BLOCK}:
            if opcode is PhysicalOpcode.MOVE_BLOCK:
                _require_operands(self, exactly=1)
            else:
                _require_operands(self, minimum=1)
            _require_parameters(parameters, "trajectory_id", "source_zone_id", "destination_zone_id")
        elif opcode is PhysicalOpcode.ALIGN_ATOMS:
            _require_operands(self, minimum=2)
            _validate_pairs(parameters, self.operands)
            _require_parameters(parameters, "alignment_profile")
        elif opcode is PhysicalOpcode.APPLY_1Q_PULSE:
            _require_operands(self, minimum=1)
            _require_parameters(parameters, "operation", "pulse_id")
        elif opcode is PhysicalOpcode.APPLY_2Q_RYDBERG_GATE:
            _require_operands(self, minimum=2)
            _require_parameters(parameters, "gate", "pulse_id")
            _validate_pairs(parameters, self.operands)
        elif opcode is PhysicalOpcode.IMAGE_ATOMS:
            _require_operands(self, minimum=1)
            _require_parameters(parameters, "profile")
        elif opcode is PhysicalOpcode.MEASURE_ATOMS:
            _require_operands(self, minimum=1)
            _require_parameters(parameters, "basis", "profile")
        elif opcode is PhysicalOpcode.RESET_ATOMS:
            _require_operands(self, minimum=1)
            _require_parameters(parameters, "state", "profile", "purpose")
        elif opcode is PhysicalOpcode.LOAD_RESERVOIR_ATOM:
            _require_operands(self, exactly=1)
            _require_parameters(parameters, "profile")
        elif opcode is PhysicalOpcode.PLACE_ATOM:
            _require_operands(self, exactly=2)
            _require_parameters(
                parameters, "destination_site_id", "profile", "trajectory_id",
                "source_zone_id", "destination_zone_id",
            )
        elif opcode is PhysicalOpcode.WAIT:
            _require_parameters(parameters, "duration_ns")
            _require_positive_integer(parameters["duration_ns"], "wait duration_ns")
        elif opcode is PhysicalOpcode.EMIT_SYNC:
            _require_parameters(parameters, "tag", "channel")


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
class ZoneDemand:
    zone_id: str
    quantity: int

    def __post_init__(self) -> None:
        require_id(self.zone_id, "zone demand ID")
        _require_positive_integer(self.quantity, "zone demand quantity")


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
    duration_ns: int | None = None
    zone_demands: tuple[ZoneDemand, ...] = ()

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
        if self.duration_ns is not None:
            _require_positive_integer(self.duration_ns, "duration_ns")
        demand_resource_ids = [demand.resource_id for demand in self.resource_demands]
        if len(demand_resource_ids) != len(set(demand_resource_ids)):
            raise ContractValidationError("resource demands must contain unique resource IDs")
        demand_zone_ids = [demand.zone_id for demand in self.zone_demands]
        if len(demand_zone_ids) != len(set(demand_zone_ids)):
            raise ContractValidationError("zone demands must contain unique zone IDs")

    def resolved_duration_ns(self, machine: MachineConfig) -> int:
        if self.duration_ns is not None:
            return self.duration_ns
        duration = machine.calibration.duration_by_opcode_ns.get(self.instruction.opcode.value)
        if duration is None:
            raise ContractValidationError(f"task {self.task_id!r} has no positive calibrated duration")
        return duration


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
        zones = {zone.zone_id: zone for zone in machine.zones}
        for task in self.tasks:
            unknown_zones = set(task.zone_ids) - zone_ids
            if unknown_zones:
                raise ContractValidationError(f"task {task.task_id!r} references unknown zones")
            task.resolved_duration_ns(machine)
            semantics = PHYSICAL_ISA[task.instruction.opcode]
            task_zone_kinds = {zone.kind.value for zone in machine.zones if zone.zone_id in task.zone_ids}
            if task_zone_kinds - set(semantics.allowed_zone_kinds):
                raise ContractValidationError(f"task {task.task_id!r} uses an illegal zone for {task.instruction.opcode.value}")
            if set(task.zone_ids) != {demand.zone_id for demand in task.zone_demands}:
                raise ContractValidationError(f"task {task.task_id!r} must explicitly quantify every zone claim")
            for demand in task.zone_demands:
                if demand.quantity > zones[demand.zone_id].capacity:
                    raise ContractValidationError(f"task {task.task_id!r} exceeds zone capacity")
            if task.instruction.opcode in {PhysicalOpcode.MOVE_ATOMS, PhysicalOpcode.MOVE_BLOCK, PhysicalOpcode.PLACE_ATOM}:
                endpoints = {
                    task.instruction.parameters["source_zone_id"],
                    task.instruction.parameters["destination_zone_id"],
                }
                if endpoints != set(task.zone_ids):
                    raise ContractValidationError(f"task {task.task_id!r} zone claims do not match movement endpoints")
            for demand in task.resource_demands:
                resource = resources.get(demand.resource_id)
                if resource is None:
                    raise ContractValidationError(f"task {task.task_id!r} references an unknown resource")
                if demand.quantity > resource.capacity:
                    raise ContractValidationError(f"task {task.task_id!r} exceeds resource capacity")
            provided_classes = {resources[demand.resource_id].resource_class for demand in task.resource_demands}
            if not set(semantics.required_resource_classes).issubset(provided_classes):
                raise ContractValidationError(f"task {task.task_id!r} lacks a required resource class")

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
                duration_ns=item.get("duration_ns"),
                zone_demands=tuple(ZoneDemand(
                    zone_id=value["zone_id"], quantity=value["quantity"],
                ) for value in item.get("zone_demands", ())),
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


def _require_operands(instruction: PhysicalInstruction, *, minimum: int | None = None, exactly: int | None = None) -> None:
    count = len(instruction.operands)
    if exactly is not None and count != exactly:
        raise ContractValidationError(f"{instruction.opcode.value} requires exactly {exactly} operand(s)")
    if minimum is not None and count < minimum:
        raise ContractValidationError(f"{instruction.opcode.value} requires at least {minimum} operand(s)")


def _require_parameters(parameters: Mapping[str, Any], *names: str) -> None:
    missing = [name for name in names if name not in parameters]
    if missing:
        raise ContractValidationError(f"missing physical instruction parameters: {', '.join(missing)}")
    for name in names:
        if name != "duration_ns":
            require_id(parameters[name], f"instruction parameter {name}")


def _require_positive_integer(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContractValidationError(f"{name} must be a positive integer")


def _validate_pairs(parameters: Mapping[str, Any], operands: tuple[str, ...]) -> None:
    if "pairs" not in parameters:
        raise ContractValidationError("missing physical instruction parameters: pairs")
    pairs = parameters["pairs"]
    if not isinstance(pairs, tuple) or not pairs:
        raise ContractValidationError("pairs must be a non-empty sequence")
    operand_set = set(operands)
    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2 or any(value not in operand_set for value in pair):
            raise ContractValidationError("each pair must contain two declared operands")


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

