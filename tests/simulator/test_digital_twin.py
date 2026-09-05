from __future__ import annotations

from dataclasses import replace

import pytest

from compiler.lowering.neutral_atom import lower_to_neutral_atom_tasks
from compiler.physical_ir import (
    PhysicalInstruction, PhysicalOpcode, PhysicalTask, PhysicalTaskGraph,
    ResourceDemand, ResourceMode, ZoneDemand,
)
from contracts import ContractValidationError, ZoneKind
from examples.ghz_surface_code import build_ghz_execution, build_ghz_qec_protocol
from hardware.atom import QubitLabel
from hardware.hardware_state import MachineState
from hardware.zones import NeutralAtomTarget, build_reference_target
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest, TimedSchedule
from simulator.events import ExecutionTrace
from simulator.executor import DigitalTwinExecutor


@pytest.mark.parametrize("distance", [3, 5])
def test_measured_ghz_executes_to_a_replayable_trace(distance: int) -> None:
    first = build_ghz_execution(distance, include_measurements=True)
    second = build_ghz_execution(distance, include_measurements=True)

    assert len(first.observations.observations) == 4 * distance**2
    assert all(value.block_id.startswith("block-L") for value in first.final_state.blocks.values())
    assert {value.zone_id for value in first.final_state.blocks.values()} == {"storage"}
    assert sum(atom.qubit_label is QubitLabel.MEASURED for atom in first.final_state.atoms.values()) == 4 * distance**2
    assert first.trace.to_json() == second.trace.to_json()
    assert first.observations.to_json() == second.observations.to_json()
    assert ExecutionTrace.from_json(first.trace.to_json()) == first.trace
    assert first.trace.snapshots[0].captured_at_ns == 0
    assert first.trace.snapshots[-1].captured_at_ns == first.trace.ended_at_ns
    assert all(event.provenance.logical_op_ids and event.provenance.qec_op_ids for event in first.trace.events)
    assert any(event.trajectory_id for event in first.trace.events)
    assert len(first.trace.snapshots[-1].atom_locations) == 4 * (2 * distance**2 - 1)


def test_route_corridor_capacity_serializes_conflicting_transport() -> None:
    target = build_reference_target()
    protocol = build_ghz_qec_protocol(3)
    graph = lower_to_neutral_atom_tasks(protocol, target)
    schedule = schedule_physical_tasks(ScheduleRequest("route-low", graph, target.machine))
    entries = {entry.task_id: entry for entry in schedule.entries}
    left = entries["phy-qec-cx-L0-L1-move-control-in"]
    right = entries["phy-qec-cx-L0-L1-move-target-in"]
    assert left.end_ns <= right.start_ns or right.end_ns <= left.start_ns
    delayed = right if right.start_ns else left
    decision = next(item for item in schedule.decision_log if item.task_id == delayed.task_id)
    assert decision.blocking_interval_ids

    resources = tuple(
        replace(item, capacity=2) if item.resource_id in {"aod-0", "corridor-storage-entangling"} else item
        for item in target.machine.resources
    )
    high = replace(target.machine, resources=resources)
    parallel = schedule_physical_tasks(ScheduleRequest("route-high", graph, high))
    high_entries = {entry.task_id: entry for entry in parallel.entries}
    assert high_entries[left.task_id].start_ns == high_entries[right.task_id].start_ns


def test_executor_rejects_a_route_group_omitted_from_the_physical_graph() -> None:
    target = build_reference_target()
    protocol = build_ghz_qec_protocol(3)
    graph = lower_to_neutral_atom_tasks(protocol, target)
    changed = []
    for task in graph.tasks:
        if task.instruction.opcode is PhysicalOpcode.MOVE_BLOCK:
            changed.append(replace(task, resource_demands=tuple(
                demand for demand in task.resource_demands
                if demand.resource_id != "corridor-storage-entangling"
            )))
        else:
            changed.append(task)
    unsafe_graph = PhysicalTaskGraph(graph.graph_id, graph.revision, tuple(changed))
    schedule = schedule_physical_tasks(ScheduleRequest("unsafe-route", unsafe_graph, target.machine))
    state = MachineState.from_protocol(protocol, target)
    with pytest.raises(ContractValidationError, match="omits a trajectory conflict group"):
        DigitalTwinExecutor(target).execute("unsafe-route", unsafe_graph, schedule, state)


def test_executor_detects_persistent_zone_occupancy_not_visible_to_static_intervals() -> None:
    target = build_reference_target()
    zones = tuple(
        replace(zone, capacity=100) if zone.kind is ZoneKind.ENTANGLING else zone
        for zone in target.machine.zones
    )
    narrow = NeutralAtomTarget(replace(target.machine, zones=zones), target.geometry, target.bindings)
    protocol = build_ghz_qec_protocol(5)
    graph = lower_to_neutral_atom_tasks(protocol, narrow)
    schedule = schedule_physical_tasks(ScheduleRequest("narrow", graph, narrow.machine))
    state = MachineState.from_protocol(protocol, narrow)
    with pytest.raises(ContractValidationError, match="persistent machine-state zone capacity"):
        DigitalTwinExecutor(narrow).execute("narrow", graph, schedule, state)


def test_auxiliary_physical_opcodes_update_state_and_preserve_erasure() -> None:
    target = build_reference_target()
    protocol = build_ghz_qec_protocol(3)
    state = MachineState.from_protocol(protocol, target)
    lost_site = state.blocks["block-L3"].site_ids[0]
    state.mark_atom_lost(lost_site)
    moving_atom = state.blocks["block-L2"].site_ids[0]
    spare = "reservoir-spare-0"

    tasks = (
        _task("load", PhysicalOpcode.LOAD_RESERVOIR_ATOM, (spare,), {"profile": "ideal-loader"}, (), ("reservoir",), (1,), ("loader-0",), 1_000),
        _task("place", PhysicalOpcode.PLACE_ATOM, (spare, lost_site), {
            "destination_site_id": lost_site, "profile": "ideal-place",
            "trajectory_id": "reservoir-to-storage", "source_zone_id": "reservoir", "destination_zone_id": "storage",
        }, ("load",), ("reservoir", "storage"), (1, 1), ("aod-0", "corridor-reservoir-storage"), 40_000),
        _task("move-out", PhysicalOpcode.MOVE_ATOMS, (moving_atom,), {
            "trajectory_id": "storage-to-entangling", "source_zone_id": "storage", "destination_zone_id": "entangling",
        }, ("place",), ("storage", "entangling"), (1, 1), ("aod-0", "corridor-storage-entangling"), 50_000),
        _task("move-back", PhysicalOpcode.MOVE_ATOMS, (moving_atom,), {
            "trajectory_id": "entangling-to-storage", "source_zone_id": "entangling", "destination_zone_id": "storage",
        }, ("move-out",), ("entangling", "storage"), (1, 1), ("aod-0", "corridor-storage-entangling"), 50_000),
        _task("image", PhysicalOpcode.IMAGE_ATOMS, (lost_site, spare), {"profile": "presence"}, ("move-back",), ("storage",), (2,), ("camera-0",), 1_000),
        _task("wait", PhysicalOpcode.WAIT, (), {"duration_ns": 500}, ("image",), ("storage",), (1,), ("clock-0",), 500),
        _task("sync", PhysicalOpcode.EMIT_SYNC, (), {"tag": "done", "channel": "test"}, ("wait",), ("storage",), (1,), ("clock-0",), 100),
    )
    graph = PhysicalTaskGraph("auxiliary-opcodes", 0, tasks)
    schedule = schedule_physical_tasks(ScheduleRequest("auxiliary", graph, target.machine))
    result = DigitalTwinExecutor(target).execute("auxiliary", graph, schedule, state)

    assert result.final_state.sites[lost_site].atom_id == spare
    assert result.final_state.sites[lost_site].known_erasure is True
    assert result.final_state.atoms[lost_site].present is False
    assert result.final_state.atoms[spare].role.value == "replacement"
    assert spare not in state.atoms
    presence = [item.payload["present"] for item in result.observations.observations]
    assert presence == [False, True]

    ghz_opcodes = {
        event.opcode for event in build_ghz_execution(3, include_measurements=True).trace.events
    }
    auxiliary_opcodes = {task.instruction.opcode for task in tasks}
    assert ghz_opcodes | auxiliary_opcodes == set(PhysicalOpcode)


def test_executor_rejects_overlapping_operations_on_one_atom() -> None:
    target = build_reference_target()
    protocol = build_ghz_qec_protocol(3)
    state = MachineState.from_protocol(protocol, target)
    atom_id = state.blocks["block-L0"].site_ids[0]
    resources = tuple(
        replace(item, capacity=2) if item.resource_id == "oneq-0" else item
        for item in target.machine.resources
    )
    high = NeutralAtomTarget(replace(target.machine, resources=resources), target.geometry, target.bindings)
    tasks = tuple(
        _task(task_id, PhysicalOpcode.APPLY_1Q_PULSE, (atom_id,), {"operation": "hadamard", "pulse_id": task_id}, (), ("storage",), (1,), ("oneq-0",), 500)
        for task_id in ("pulse-a", "pulse-b")
    )
    graph = PhysicalTaskGraph("same-atom", 0, tasks)
    schedule = schedule_physical_tasks(ScheduleRequest("same-atom", graph, high.machine))
    assert schedule.entries[0].start_ns == schedule.entries[1].start_ns
    with pytest.raises(ContractValidationError, match="same atom"):
        DigitalTwinExecutor(high).execute("same-atom", graph, schedule, state)


def test_executor_rejects_qec_layer_input() -> None:
    target = build_reference_target()
    protocol = build_ghz_qec_protocol(3)
    graph = lower_to_neutral_atom_tasks(protocol, target)
    schedule = schedule_physical_tasks(ScheduleRequest("physical", graph, target.machine))
    with pytest.raises(ContractValidationError, match="only a physical graph"):
        DigitalTwinExecutor(target).execute(  # type: ignore[arg-type]
            "bad-layer", protocol, schedule, MachineState.from_protocol(protocol, target),
        )


def _task(
    task_id: str, opcode: PhysicalOpcode, operands: tuple[str, ...], parameters: dict[str, object],
    predecessors: tuple[str, ...], zones: tuple[str, ...], zone_quantities: tuple[int, ...],
    resources: tuple[str, ...], duration_ns: int,
) -> PhysicalTask:
    return PhysicalTask(
        task_id, PhysicalInstruction(opcode, operands, parameters), predecessors=predecessors,
        resource_demands=tuple(ResourceDemand(item, mode=ResourceMode.SHARED) for item in resources),
        zone_ids=zones, duration_ns=duration_ns,
        zone_demands=tuple(ZoneDemand(zone, quantity) for zone, quantity in zip(zones, zone_quantities, strict=True)),
    )
