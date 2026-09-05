"""Deterministic, non-preemptive RESST-style list scheduler."""

from __future__ import annotations

from compiler.physical_ir import ConsumePolicy, PhysicalTask
from scheduler.resources import CapacityCalendar
from scheduler.task import (
    ScheduleRequest, ScheduledTask, SchedulingDecision, TimedSchedule,
    UnscheduledReason, UnscheduledTask,
)


def schedule_physical_tasks(request: ScheduleRequest) -> TimedSchedule:
    tasks = {task.task_id: task for task in request.graph.tasks}
    submission_order = {task.task_id: index for index, task in enumerate(request.graph.tasks)}
    calendar = CapacityCalendar(request.machine, request.fixed_intervals)
    condition_values = dict(request.condition_snapshot)
    end_by_task = {task_id: request.not_before_ns for task_id in request.completed_task_ids}
    pending = {task_id for task_id in tasks if task_id not in end_by_task}
    scheduled: list[ScheduledTask] = []
    unscheduled: list[UnscheduledTask] = []
    decisions: list[SchedulingDecision] = []

    while pending:
        ready: list[tuple[int, int, int, str, PhysicalTask]] = []
        for task_id in pending:
            task = tasks[task_id]
            if not all(predecessor in end_by_task for predecessor in task.predecessors):
                continue
            if not _conditions_hold(task, condition_values):
                continue
            dependency_ready = max(
                (end_by_task[predecessor] for predecessor in task.predecessors),
                default=request.not_before_ns,
            )
            ready.append((dependency_ready, -task.priority, submission_order[task_id], task_id, task))

        if not ready:
            break

        dependency_ready, _, _, task_id, task = min(ready)
        pending.remove(task_id)
        duration = task.resolved_duration_ns(request.machine)
        release_ns = max(request.not_before_ns, dependency_ready, task.earliest_start_ns)
        start_ns, blockers = calendar.earliest_slot(
            release_ns, duration, task.resource_demands, task.zone_demands,
        )
        end_ns = start_ns + duration
        wait_reasons: list[str] = []
        if release_ns > dependency_ready:
            wait_reasons.append("earliest_start")
        if start_ns > release_ns:
            wait_reasons.append("capacity_conflict")
        if task.deadline_ns is not None and end_ns > task.deadline_ns:
            unscheduled.append(UnscheduledTask(task_id, UnscheduledReason.DEADLINE_MISSED, "earliest feasible interval misses deadline"))
            decisions.append(SchedulingDecision(task_id, dependency_ready, None, "unscheduled_deadline", tuple(wait_reasons), blockers))
            continue
        if request.policy.max_schedule_ns is not None and end_ns > request.policy.max_schedule_ns:
            unscheduled.append(UnscheduledTask(task_id, UnscheduledReason.POLICY_HORIZON, "earliest feasible interval exceeds policy horizon"))
            decisions.append(SchedulingDecision(task_id, dependency_ready, None, "unscheduled_horizon", tuple(wait_reasons), blockers))
            continue
        calendar.reserve(task_id, start_ns, end_ns, task.resource_demands, task.zone_demands)
        scheduled.append(ScheduledTask(
            task_id, start_ns, end_ns, task.resource_demands, task.zone_demands, len(scheduled),
        ))
        end_by_task[task_id] = end_ns
        _consume_conditions(task, condition_values)
        decisions.append(SchedulingDecision(task_id, dependency_ready, start_ns, "scheduled", tuple(wait_reasons), blockers))

    for task_id in sorted(pending, key=lambda value: (submission_order[value], value)):
        task = tasks[task_id]
        missing_predecessors = tuple(item for item in task.predecessors if item not in end_by_task)
        if missing_predecessors:
            reason = UnscheduledReason.PREDECESSOR_UNSCHEDULED
            detail = f"predecessors were not scheduled: {', '.join(missing_predecessors)}"
        else:
            blocked = tuple(condition.message_id for condition in task.conditions if not _condition_holds(condition.predicate, condition_values.get(condition.message_id)))
            reason = UnscheduledReason.CONDITION_BLOCKED
            detail = f"conditions are not satisfied: {', '.join(blocked)}"
        unscheduled.append(UnscheduledTask(task_id, reason, detail))
        dependency_ready = max((end_by_task[item] for item in task.predecessors if item in end_by_task), default=request.not_before_ns)
        decisions.append(SchedulingDecision(task_id, dependency_ready, None, f"unscheduled_{reason.value}"))

    makespan = max((entry.end_ns for entry in scheduled), default=request.not_before_ns)
    return TimedSchedule(
        schedule_id=f"schedule-{request.request_id}", request_id=request.request_id,
        graph_id=request.graph.graph_id, graph_revision=request.graph.revision,
        entries=tuple(scheduled), unscheduled=tuple(unscheduled),
        decision_log=tuple(decisions), makespan_ns=makespan,
    )


def _conditions_hold(task: PhysicalTask, values: dict[str, bool]) -> bool:
    return all(_condition_holds(condition.predicate, values.get(condition.message_id)) for condition in task.conditions)


def _condition_holds(predicate: str, value: bool | None) -> bool:
    if value is None:
        return False
    return value if predicate == "truthy" else not value


def _consume_conditions(task: PhysicalTask, values: dict[str, bool]) -> None:
    for condition in task.conditions:
        if condition.consume_policy is ConsumePolicy.CONSUME:
            values.pop(condition.message_id, None)
