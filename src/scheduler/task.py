"""Versioned request and result contracts for static physical scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from compiler.physical_ir import (
    PhysicalTaskGraph, ResourceDemand, ResourceMode, ZoneDemand,
)
from contracts.common import (
    SCHEMA_VERSION, ContractValidationError, canonical_json, frozen_mapping,
    parse_json, require_id, require_schema, to_primitive,
)
from contracts.machine import MachineConfig


class UnscheduledReason(StrEnum):
    CONDITION_BLOCKED = "condition_blocked"
    PREDECESSOR_UNSCHEDULED = "predecessor_unscheduled"
    DEADLINE_MISSED = "deadline_missed"
    POLICY_HORIZON = "policy_horizon"


@dataclass(frozen=True, slots=True)
class SchedulingPolicy:
    preemptive: bool = False
    max_schedule_ns: int | None = None
    queue_policy: str = "dependency_ready_priority_submission_task_id"

    def __post_init__(self) -> None:
        if self.preemptive:
            raise ContractValidationError("M3 tasks are non-preemptive")
        if self.max_schedule_ns is not None:
            _positive_integer(self.max_schedule_ns, "max_schedule_ns")
        if self.queue_policy != "dependency_ready_priority_submission_task_id":
            raise ContractValidationError("unsupported scheduling queue policy")


@dataclass(frozen=True, slots=True)
class FixedInterval:
    interval_id: str
    start_ns: int
    end_ns: int
    resource_demands: tuple[ResourceDemand, ...] = ()
    zone_demands: tuple[ZoneDemand, ...] = ()

    def __post_init__(self) -> None:
        require_id(self.interval_id, "fixed interval ID")
        if not isinstance(self.start_ns, int) or isinstance(self.start_ns, bool) or self.start_ns < 0:
            raise ContractValidationError("fixed interval start_ns must be non-negative")
        if not isinstance(self.end_ns, int) or isinstance(self.end_ns, bool) or self.end_ns <= self.start_ns:
            raise ContractValidationError("fixed interval end_ns must be greater than start_ns")
        resource_ids = [demand.resource_id for demand in self.resource_demands]
        zone_ids = [demand.zone_id for demand in self.zone_demands]
        if len(resource_ids) != len(set(resource_ids)) or len(zone_ids) != len(set(zone_ids)):
            raise ContractValidationError("fixed interval demands must have unique resource and zone IDs")


@dataclass(frozen=True, slots=True)
class ScheduleRequest:
    request_id: str
    graph: PhysicalTaskGraph
    machine: MachineConfig
    not_before_ns: int = 0
    completed_task_ids: tuple[str, ...] = ()
    fixed_intervals: tuple[FixedInterval, ...] = ()
    condition_snapshot: Mapping[str, bool] = field(default_factory=dict)
    policy: SchedulingPolicy = field(default_factory=SchedulingPolicy)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        require_id(self.request_id, "schedule request ID")
        if not isinstance(self.graph, PhysicalTaskGraph) or not isinstance(self.machine, MachineConfig):
            raise ContractValidationError("schedule request requires a physical graph and machine")
        if not isinstance(self.not_before_ns, int) or isinstance(self.not_before_ns, bool) or self.not_before_ns < 0:
            raise ContractValidationError("not_before_ns must be non-negative")
        known = {task.task_id for task in self.graph.tasks}
        if set(self.completed_task_ids) - known:
            raise ContractValidationError("completed_task_ids references an unknown task")
        if len(self.completed_task_ids) != len(set(self.completed_task_ids)):
            raise ContractValidationError("completed_task_ids must be unique")
        by_id = {task.task_id: task for task in self.graph.tasks}
        completed = set(self.completed_task_ids)
        if any(set(by_id[task_id].predecessors) - completed for task_id in completed):
            raise ContractValidationError("completed_task_ids must be predecessor-closed")
        interval_ids = [interval.interval_id for interval in self.fixed_intervals]
        if len(interval_ids) != len(set(interval_ids)):
            raise ContractValidationError("fixed interval IDs must be unique")
        snapshot = dict(self.condition_snapshot)
        for message_id, value in snapshot.items():
            require_id(message_id, "condition message ID")
            if not isinstance(value, bool):
                raise ContractValidationError("condition snapshot values must be booleans")
        object.__setattr__(self, "condition_snapshot", frozen_mapping(snapshot))
        self.graph.validate_against_machine(self.machine)
        for task in self.graph.tasks:
            for condition in task.conditions:
                if condition.predicate not in {"truthy", "falsy"}:
                    raise ContractValidationError("M3 supports only truthy and falsy condition predicates")

    def to_json(self) -> str:
        return canonical_json(self)


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    task_id: str
    start_ns: int
    end_ns: int
    resource_assignments: tuple[ResourceDemand, ...]
    zone_assignments: tuple[ZoneDemand, ...]
    dispatch_order: int

    def __post_init__(self) -> None:
        require_id(self.task_id, "scheduled task ID")
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (self.start_ns, self.end_ns)) or self.start_ns < 0 or self.end_ns <= self.start_ns:
            raise ContractValidationError("scheduled task interval is invalid")
        if not isinstance(self.dispatch_order, int) or isinstance(self.dispatch_order, bool) or self.dispatch_order < 0:
            raise ContractValidationError("dispatch_order must be non-negative")


@dataclass(frozen=True, slots=True)
class UnscheduledTask:
    task_id: str
    reason: UnscheduledReason
    detail: str

    def __post_init__(self) -> None:
        require_id(self.task_id, "unscheduled task ID")
        if not isinstance(self.reason, UnscheduledReason):
            raise ContractValidationError("reason must be an UnscheduledReason")
        require_id(self.detail, "unscheduled detail")


@dataclass(frozen=True, slots=True)
class SchedulingDecision:
    task_id: str
    dependency_ready_ns: int
    selected_start_ns: int | None
    decision: str
    wait_reasons: tuple[str, ...] = ()
    blocking_interval_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_id(self.task_id, "decision task ID")
        if self.dependency_ready_ns < 0:
            raise ContractValidationError("dependency_ready_ns must be non-negative")
        if self.selected_start_ns is not None and self.selected_start_ns < self.dependency_ready_ns:
            raise ContractValidationError("selected start precedes dependency readiness")
        require_id(self.decision, "scheduling decision")


@dataclass(frozen=True, slots=True)
class TimedSchedule:
    schedule_id: str
    request_id: str
    graph_id: str
    graph_revision: int
    entries: tuple[ScheduledTask, ...]
    unscheduled: tuple[UnscheduledTask, ...]
    decision_log: tuple[SchedulingDecision, ...]
    makespan_ns: int
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        for value, name in ((self.schedule_id, "schedule_id"), (self.request_id, "request_id"), (self.graph_id, "graph_id")):
            require_id(value, name)
        if self.graph_revision < 0 or self.makespan_ns < 0:
            raise ContractValidationError("schedule revision and makespan must be non-negative")
        ids = [entry.task_id for entry in self.entries] + [item.task_id for item in self.unscheduled]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("a task may appear only once in a timed schedule")
        decision_ids = [item.task_id for item in self.decision_log]
        if len(decision_ids) != len(set(decision_ids)) or set(decision_ids) != set(ids):
            raise ContractValidationError("decision log must cover each scheduled or unscheduled task exactly once")

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_json(cls, payload: str) -> "TimedSchedule":
        data = parse_json(payload)
        return cls(
            schedule_id=data["schedule_id"], request_id=data["request_id"],
            graph_id=data["graph_id"], graph_revision=data["graph_revision"],
            entries=tuple(ScheduledTask(
                task_id=item["task_id"], start_ns=item["start_ns"], end_ns=item["end_ns"],
                resource_assignments=tuple(ResourceDemand(
                    value["resource_id"], value["quantity"], ResourceMode(value["mode"]),
                ) for value in item["resource_assignments"]),
                zone_assignments=tuple(ZoneDemand(value["zone_id"], value["quantity"]) for value in item["zone_assignments"]),
                dispatch_order=item["dispatch_order"],
            ) for item in data["entries"]),
            unscheduled=tuple(UnscheduledTask(
                item["task_id"], UnscheduledReason(item["reason"]), item["detail"],
            ) for item in data["unscheduled"]),
            decision_log=tuple(SchedulingDecision(
                task_id=item["task_id"], dependency_ready_ns=item["dependency_ready_ns"],
                selected_start_ns=item["selected_start_ns"], decision=item["decision"],
                wait_reasons=tuple(item["wait_reasons"]), blocking_interval_ids=tuple(item["blocking_interval_ids"]),
            ) for item in data["decision_log"]),
            makespan_ns=data["makespan_ns"], schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


def _positive_integer(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContractValidationError(f"{name} must be a positive integer")
