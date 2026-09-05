"""Thin orchestration for a compiled, scheduled digital-twin experiment."""

from __future__ import annotations

from compiler.physical_ir import PhysicalTaskGraph
from hardware.hardware_state import MachineState
from hardware.zones import NeutralAtomTarget
from scheduler.task import ScheduleRequest
from scheduler.resst import schedule_physical_tasks
from simulator.executor import DigitalTwinExecutor, ExecutionResult, StateBackend


def run_experiment(
    run_id: str, graph: PhysicalTaskGraph, target: NeutralAtomTarget,
    initial_state: MachineState, backend: StateBackend | None = None,
) -> ExecutionResult:
    schedule = schedule_physical_tasks(ScheduleRequest(run_id, graph, target.machine))
    return DigitalTwinExecutor(target, backend).execute(run_id, graph, schedule, initial_state)
