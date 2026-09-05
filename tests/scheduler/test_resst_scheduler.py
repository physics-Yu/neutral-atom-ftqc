from __future__ import annotations

from dataclasses import replace

import pytest

from compiler.physical_ir import (
    ConditionRef, ConsumePolicy, PhysicalInstruction, PhysicalOpcode, PhysicalTask,
    PhysicalTaskGraph, ResourceDemand, ResourceMode, ZoneDemand,
)
from contracts import CalibrationSnapshot, ContractValidationError, MachineConfig, ResourceSpec, ZoneKind, ZoneSpec
from examples.ghz_surface_code import build_ghz_physical_graph, build_ghz_qec_protocol
from scheduler.resst import schedule_physical_tasks
from scheduler.task import (
    FixedInterval, ScheduleRequest, SchedulingPolicy, TimedSchedule, UnscheduledReason,
)


def machine(*, resource_capacity: int = 1, storage_capacity: int = 8) -> MachineConfig:
    return MachineConfig(
        "scheduler-machine",
        tuple(ZoneSpec(kind.value, kind, storage_capacity if kind is ZoneKind.STORAGE else 8) for kind in ZoneKind),
        (ResourceSpec("clock", "clock", resource_capacity),),
        CalibrationSnapshot("scheduler-cal", {"wait": 10}),
    )


def wait_task(
    task_id: str, *, predecessors: tuple[str, ...] = (), priority: int = 0,
    mode: ResourceMode = ResourceMode.SHARED, quantity: int = 1,
    zone_quantity: int = 1, duration_ns: int = 10,
    conditions: tuple[ConditionRef, ...] = (), deadline_ns: int | None = None,
    earliest_start_ns: int = 0,
) -> PhysicalTask:
    return PhysicalTask(
        task_id=task_id,
        instruction=PhysicalInstruction(PhysicalOpcode.WAIT, parameters={"duration_ns": duration_ns}),
        predecessors=predecessors,
        earliest_start_ns=earliest_start_ns,
        deadline_ns=deadline_ns,
        priority=priority,
        resource_demands=(ResourceDemand("clock", quantity, mode),),
        zone_ids=("storage",),
        conditions=conditions,
        duration_ns=duration_ns,
        zone_demands=(ZoneDemand("storage", zone_quantity),),
    )


def request(*tasks: PhysicalTask, configured_machine: MachineConfig | None = None, **kwargs: object) -> ScheduleRequest:
    graph = PhysicalTaskGraph("scheduler-graph", 0, tasks)
    return ScheduleRequest("request", graph, configured_machine or machine(), **kwargs)


def entries_by_id(schedule: TimedSchedule) -> dict[str, object]:
    return {entry.task_id: entry for entry in schedule.entries}


def assert_capacity_safe(schedule: TimedSchedule, configured_machine: MachineConfig) -> None:
    resources = {item.resource_id: item.capacity for item in configured_machine.resources}
    zones = {item.zone_id: item.capacity for item in configured_machine.zones}
    points = sorted({entry.start_ns for entry in schedule.entries})
    for point in points:
        active = [entry for entry in schedule.entries if entry.start_ns <= point < entry.end_ns]
        for resource_id, capacity in resources.items():
            demands = [demand for entry in active for demand in entry.resource_assignments if demand.resource_id == resource_id]
            assert not (any(demand.mode is ResourceMode.EXCLUSIVE for demand in demands) and len(demands) > 1)
            assert sum(demand.quantity for demand in demands) <= capacity
        for zone_id, capacity in zones.items():
            assert sum(demand.quantity for entry in active for demand in entry.zone_assignments if demand.zone_id == zone_id) <= capacity


def test_dependencies_and_release_times_are_respected() -> None:
    schedule = schedule_physical_tasks(request(
        wait_task("parent", duration_ns=7),
        wait_task("child", predecessors=("parent",), earliest_start_ns=20),
    ))
    entries = entries_by_id(schedule)
    assert entries["parent"].start_ns == 0
    assert entries["child"].start_ns == 20
    decision = next(item for item in schedule.decision_log if item.task_id == "child")
    assert decision.wait_reasons == ("earliest_start",)


def test_shared_capacity_allows_parallelism_and_serializes_overflow() -> None:
    schedule = schedule_physical_tasks(request(
        wait_task("a"), wait_task("b"), wait_task("c"),
        configured_machine=machine(resource_capacity=2, storage_capacity=2),
    ))
    entries = entries_by_id(schedule)
    assert (entries["a"].start_ns, entries["b"].start_ns, entries["c"].start_ns) == (0, 0, 10)
    assert "capacity_conflict" in next(item for item in schedule.decision_log if item.task_id == "c").wait_reasons


def test_exclusive_mode_locks_whole_resource_even_when_capacity_is_larger() -> None:
    schedule = schedule_physical_tasks(request(
        wait_task("a", mode=ResourceMode.EXCLUSIVE),
        wait_task("b", mode=ResourceMode.EXCLUSIVE),
        configured_machine=machine(resource_capacity=4),
    ))
    assert [(entry.task_id, entry.start_ns) for entry in schedule.entries] == [("a", 0), ("b", 10)]


def test_zone_capacity_is_arbitrated_independently_of_device_capacity() -> None:
    schedule = schedule_physical_tasks(request(
        wait_task("a"), wait_task("b"),
        configured_machine=machine(resource_capacity=2, storage_capacity=1),
    ))
    assert [entry.start_ns for entry in schedule.entries] == [0, 10]


def test_priority_then_submission_order_is_a_stable_tie_break() -> None:
    schedule = schedule_physical_tasks(request(
        wait_task("submitted-first", priority=1),
        wait_task("high", priority=9),
        wait_task("submitted-third", priority=1),
    ))
    assert [entry.task_id for entry in schedule.entries] == ["high", "submitted-first", "submitted-third"]


def test_fixed_calendar_interval_explains_wait() -> None:
    fixed = FixedInterval(
        "maintenance", 0, 7,
        resource_demands=(ResourceDemand("clock", mode=ResourceMode.EXCLUSIVE),),
    )
    schedule = schedule_physical_tasks(request(wait_task("a"), fixed_intervals=(fixed,)))
    assert schedule.entries[0].start_ns == 7
    assert schedule.decision_log[0].blocking_interval_ids == ("maintenance",)


def test_keep_and_consume_conditions_have_deterministic_behavior() -> None:
    keep = ConditionRef("ready", consume_policy=ConsumePolicy.KEEP)
    kept = schedule_physical_tasks(request(
        wait_task("a", conditions=(keep,)), wait_task("b", conditions=(keep,)),
        configured_machine=machine(resource_capacity=2, storage_capacity=2),
        condition_snapshot={"ready": True},
    ))
    assert len(kept.entries) == 2

    consume = ConditionRef("token", consume_policy=ConsumePolicy.CONSUME)
    consumed = schedule_physical_tasks(request(
        wait_task("low", priority=0, conditions=(consume,)),
        wait_task("high", priority=1, conditions=(consume,)),
        condition_snapshot={"token": True},
    ))
    assert [entry.task_id for entry in consumed.entries] == ["high"]
    assert consumed.unscheduled[0].task_id == "low"
    assert consumed.unscheduled[0].reason is UnscheduledReason.CONDITION_BLOCKED


def test_deadline_and_descendant_failure_are_structured() -> None:
    schedule = schedule_physical_tasks(request(
        wait_task("late", duration_ns=10, deadline_ns=5),
        wait_task("child", predecessors=("late",)),
    ))
    reasons = {item.task_id: item.reason for item in schedule.unscheduled}
    assert reasons == {
        "late": UnscheduledReason.DEADLINE_MISSED,
        "child": UnscheduledReason.PREDECESSOR_UNSCHEDULED,
    }


def test_policy_horizon_completed_tasks_and_contract_round_trip() -> None:
    req = request(
        wait_task("done"), wait_task("next", predecessors=("done",)),
        not_before_ns=30, completed_task_ids=("done",),
        policy=SchedulingPolicy(max_schedule_ns=35),
    )
    schedule = schedule_physical_tasks(req)
    assert schedule.entries == ()
    assert schedule.unscheduled[0].reason is UnscheduledReason.POLICY_HORIZON
    assert TimedSchedule.from_json(schedule.to_json()) == schedule
    assert schedule.to_json() == schedule_physical_tasks(req).to_json()


def test_completed_task_set_must_be_predecessor_closed() -> None:
    with pytest.raises(ContractValidationError, match="predecessor-closed"):
        request(
            wait_task("parent"), wait_task("child", predecessors=("parent",)),
            completed_task_ids=("child",),
        )


def test_scheduler_rejects_non_physical_input_contract() -> None:
    with pytest.raises(ContractValidationError, match="physical graph"):
        ScheduleRequest("bad", build_ghz_qec_protocol(3), machine())  # type: ignore[arg-type]


@pytest.mark.parametrize("distance", [3, 5])
def test_complete_ghz_graph_is_scheduled_deterministically(distance: int) -> None:
    graph = build_ghz_physical_graph(distance)
    from hardware.zones import build_reference_target
    target = build_reference_target()
    req = ScheduleRequest(f"ghz-d{distance}", graph, target.machine)
    first = schedule_physical_tasks(req)
    second = schedule_physical_tasks(req)
    assert len(first.entries) == len(graph.tasks) == 29
    assert first.unscheduled == ()
    assert first.to_json() == second.to_json()
    ends = {entry.task_id: entry.end_ns for entry in first.entries}
    starts = {entry.task_id: entry.start_ns for entry in first.entries}
    assert all(starts[task.task_id] >= max((ends[item] for item in task.predecessors), default=0) for task in graph.tasks)
    assert_capacity_safe(first, target.machine)
    decisions = {item.task_id: item for item in first.decision_log}
    assert all(
        decisions[entry.task_id].wait_reasons
        for entry in first.entries
        if entry.start_ns > max(
            [ends[item] for item in next(task for task in graph.tasks if task.task_id == entry.task_id).predecessors],
            default=0,
        )
    )


def test_ghz_second_layer_serializes_or_overlaps_from_actual_capacity() -> None:
    from hardware.zones import build_reference_target
    target = build_reference_target()
    graph = build_ghz_physical_graph(3)
    low = schedule_physical_tasks(ScheduleRequest("low", graph, target.machine))

    capacities = {"aod-0": 4, "oneq-0": 2, "rydberg-0": 2}
    resources = tuple(replace(item, capacity=capacities.get(item.resource_id, item.capacity)) for item in target.machine.resources)
    high_machine = replace(target.machine, resources=resources)
    high = schedule_physical_tasks(ScheduleRequest("high", graph, high_machine))
    assert_capacity_safe(low, target.machine)
    assert_capacity_safe(high, high_machine)

    def cz_intervals(schedule: TimedSchedule) -> tuple[tuple[int, int], tuple[int, int]]:
        entries = entries_by_id(schedule)
        a = entries["phy-qec-cx-L0-L2-rydberg-cz"]
        b = entries["phy-qec-cx-L1-L3-rydberg-cz"]
        return (a.start_ns, a.end_ns), (b.start_ns, b.end_ns)

    low_a, low_b = cz_intervals(low)
    high_a, high_b = cz_intervals(high)
    assert low_a[1] <= low_b[0] or low_b[1] <= low_a[0]
    assert high_a == high_b


def test_overbooked_fixed_intervals_are_rejected() -> None:
    fixed = (
        FixedInterval("one", 0, 10, resource_demands=(ResourceDemand("clock"),)),
        FixedInterval("two", 5, 15, resource_demands=(ResourceDemand("clock"),)),
    )
    with pytest.raises(ContractValidationError, match="overbooks"):
        schedule_physical_tasks(request(wait_task("a"), fixed_intervals=fixed))
