"""Auditable physical-DAG mutation and partial RESST rescheduling contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from compiler.physical_ir import PhysicalTask, PhysicalTaskGraph
from contracts.common import ContractValidationError, canonical_json, parse_json, require_id
from contracts.machine import MachineConfig
from scheduler.resst import schedule_physical_tasks
from scheduler.task import FixedInterval, ScheduleRequest, TimedSchedule


@dataclass(frozen=True, slots=True)
class DagMutation:
    mutation_id: str
    base_graph_id: str
    base_revision: int
    observed_at_ns: int
    completed_task_ids: tuple[str, ...]
    canceled_task_ids: tuple[str, ...] = ()
    inserted_tasks: tuple[PhysicalTask, ...] = ()

    def __post_init__(self) -> None:
        require_id(self.mutation_id, "DAG mutation ID")
        require_id(self.base_graph_id, "DAG mutation graph ID")
        if not isinstance(self.base_revision, int) or isinstance(self.base_revision, bool) or self.base_revision < 0:
            raise ContractValidationError("DAG mutation base revision must be non-negative")
        if not isinstance(self.observed_at_ns, int) or isinstance(self.observed_at_ns, bool) or self.observed_at_ns < 0:
            raise ContractValidationError("DAG mutation time must be non-negative")
        for task_id in self.completed_task_ids + self.canceled_task_ids:
            require_id(task_id, "DAG mutation task ID")
        if len(set(self.completed_task_ids)) != len(self.completed_task_ids):
            raise ContractValidationError("completed mutation tasks must be unique")
        if len(set(self.canceled_task_ids)) != len(self.canceled_task_ids):
            raise ContractValidationError("canceled mutation tasks must be unique")
        if set(self.completed_task_ids) & set(self.canceled_task_ids):
            raise ContractValidationError("a completed task cannot be canceled")

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_json(cls, payload: str) -> "DagMutation":
        data = parse_json(payload)
        inserted_data = tuple(data.get("inserted_tasks", ()))
        inserted_ids = {item["task_id"] for item in inserted_data}
        external_predecessors = sorted({
            predecessor for item in inserted_data
            for predecessor in item.get("predecessors", ())
            if predecessor not in inserted_ids
        })
        stubs = tuple({
            "task_id": task_id,
            "instruction": {
                "opcode": "emit_sync", "operands": (),
                "parameters": {"tag": "mutation-history", "channel": "runtime"},
            },
            "duration_ns": 1,
        } for task_id in external_predecessors)
        inserted = PhysicalTaskGraph.from_dict({
            "graph_id": data["base_graph_id"], "revision": data["base_revision"],
            "tasks": stubs + inserted_data,
        }).tasks[len(stubs):]
        return cls(
            data["mutation_id"], data["base_graph_id"], data["base_revision"],
            data["observed_at_ns"], tuple(data["completed_task_ids"]),
            tuple(data.get("canceled_task_ids", ())), inserted,
        )


@dataclass(frozen=True, slots=True)
class RescheduleResult:
    mutation: DagMutation
    graph: PhysicalTaskGraph
    schedule: TimedSchedule


def apply_dag_mutation(graph: PhysicalTaskGraph, mutation: DagMutation) -> PhysicalTaskGraph:
    if graph.graph_id != mutation.base_graph_id or graph.revision != mutation.base_revision:
        raise ContractValidationError("DAG mutation does not target this graph revision")
    existing = {task.task_id: task for task in graph.tasks}
    completed = set(mutation.completed_task_ids)
    canceled = set(mutation.canceled_task_ids)
    if (completed | canceled) - existing.keys():
        raise ContractValidationError("DAG mutation references an unknown existing task")
    if any(set(existing[task_id].predecessors) - completed for task_id in completed):
        raise ContractValidationError("completed mutation history must be predecessor-closed")
    inserted_ids = [task.task_id for task in mutation.inserted_tasks]
    if len(inserted_ids) != len(set(inserted_ids)) or set(inserted_ids) & (existing.keys() - canceled):
        raise ContractValidationError("inserted task IDs must be unique in the revised graph")
    retained = tuple(task for task in graph.tasks if task.task_id not in canceled)
    revised = PhysicalTaskGraph(
        graph.graph_id, graph.revision + 1, retained + mutation.inserted_tasks,
    )
    revised_by_id = {task.task_id: task for task in revised.tasks}
    if any(revised_by_id[task_id] != existing[task_id] for task_id in completed):
        raise ContractValidationError("DAG mutation changed completed history")
    return revised


def reschedule_after_mutation(
    graph: PhysicalTaskGraph,
    mutation: DagMutation,
    machine: MachineConfig,
    *,
    fixed_intervals: tuple[FixedInterval, ...] = (),
    condition_snapshot: Mapping[str, bool] | None = None,
) -> RescheduleResult:
    revised = apply_dag_mutation(graph, mutation)
    schedule = schedule_physical_tasks(ScheduleRequest(
        f"reschedule-{mutation.mutation_id}", revised, machine,
        not_before_ns=mutation.observed_at_ns,
        completed_task_ids=mutation.completed_task_ids,
        fixed_intervals=fixed_intervals,
        condition_snapshot=condition_snapshot or {},
    ))
    return RescheduleResult(mutation, revised, schedule)

