"""Versioned, standalone visualization artifacts for M5 execution results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from compiler.physical_ir import PhysicalTaskGraph
from contracts.common import (
    SCHEMA_VERSION, ContractValidationError, canonical_json, frozen_mapping,
    require_id, to_primitive,
)
from hardware.zones import NeutralAtomTarget
from scheduler.task import TimedSchedule
from simulator.executor import ExecutionResult

from .html import render_standalone_html


@dataclass(frozen=True, slots=True)
class VisualizationRun:
    """A compact, read-only projection of one scheduled physical run."""

    run_id: str
    label: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        require_id(self.run_id, "visualization run ID")
        require_id(self.label, "visualization run label")
        object.__setattr__(self, "payload", frozen_mapping(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "label": self.label, **dict(self.payload)}


@dataclass(frozen=True, slots=True)
class VisualizationBundle:
    """Versioned collection of one or more comparable execution runs."""

    title: str
    runs: tuple[VisualizationRun, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_id(self.title, "visualization title")
        if not self.runs:
            raise ContractValidationError("visualization bundle requires at least one run")
        ids = [run.run_id for run in self.runs]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("visualization run IDs must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "runs": [run.to_dict() for run in self.runs],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def build_visualization_run(
    label: str,
    target: NeutralAtomTarget,
    graph: PhysicalTaskGraph,
    schedule: TimedSchedule,
    result: ExecutionResult,
) -> VisualizationRun:
    """Validate and project M2-M4 contracts without mutating any source object."""

    if schedule.graph_id != graph.graph_id or result.trace.graph_id != graph.graph_id:
        raise ContractValidationError("visualization inputs must refer to the same physical graph")
    if result.trace.schedule_id != schedule.schedule_id:
        raise ContractValidationError("visualization trace must refer to the supplied schedule")
    if schedule.unscheduled:
        raise ContractValidationError("visualization requires a complete schedule")

    tasks = {task.task_id: task for task in graph.tasks}
    decisions = {item.task_id: item for item in schedule.decision_log}
    task_rows: list[dict[str, Any]] = []
    for entry in sorted(schedule.entries, key=lambda item: (item.start_ns, item.dispatch_order)):
        task = tasks[entry.task_id]
        decision = decisions[entry.task_id]
        task_rows.append({
            "task_id": task.task_id,
            "opcode": task.instruction.opcode.value,
            "operands": list(task.instruction.operands),
            "predecessors": list(task.predecessors),
            "start_ns": entry.start_ns,
            "end_ns": entry.end_ns,
            "resources": [item.resource_id for item in entry.resource_assignments],
            "zones": [item.zone_id for item in entry.zone_assignments],
            "trajectory_id": task.instruction.parameters.get("trajectory_id"),
            "logical_op_ids": list(task.provenance.logical_op_ids),
            "qec_op_ids": list(task.provenance.qec_op_ids),
            "dependency_ready_ns": decision.dependency_ready_ns,
            "wait_ns": entry.start_ns - decision.dependency_ready_ns,
            "wait_reasons": list(decision.wait_reasons),
            "blocking_interval_ids": list(decision.blocking_interval_ids),
        })

    observation_by_id = {
        item.event_id: item for item in result.observations.observations
    }
    events = [{
        "event_id": item.event_id,
        "kind": item.kind.value,
        "time_ns": item.occurred_at_ns,
        "task_id": item.task_id,
        "opcode": item.opcode.value,
        "observation_id": item.observation_id,
        "observation_kind": (
            observation_by_id[item.observation_id].kind.value
            if item.observation_id is not None else None
        ),
        "logical_op_ids": list(item.provenance.logical_op_ids),
    } for item in result.trace.events]
    events.extend({
        "event_id": item.event_id,
        "kind": f"noise_{item.kind.value}",
        "time_ns": item.occurred_at_ns,
        "task_id": item.task_id,
        "opcode": tasks[item.task_id].instruction.opcode.value,
        "observation_id": None,
        "observation_kind": None,
        "logical_op_ids": list(tasks[item.task_id].provenance.logical_op_ids),
        "noise_target_id": item.target_id,
        "noise_detail": item.detail,
    } for item in result.noise_report.events)
    events.sort(key=lambda item: (item["time_ns"], item["event_id"]))
    snapshots = [{
        "time_ns": item.captured_at_ns,
        "block_locations": dict(item.block_locations),
        "zone_occupancy": dict(item.zone_occupancy),
        "atoms_present": item.atoms_present,
        "known_erasures": item.known_erasures,
        "aligned_pair_count": item.aligned_pair_count,
        "state_digest": item.state_digest,
    } for item in result.trace.snapshots]
    observations = [{
        "event_id": item.event_id,
        "kind": item.kind.value,
        "time_ns": item.observed_at_ns,
        "task_id": item.task_id,
        "payload": to_primitive(item.payload),
    } for item in result.observations.observations]

    resources = [{
        "resource_id": item.resource_id,
        "resource_class": item.resource_class,
        "capacity": item.capacity,
    } for item in target.machine.resources]
    zones = [{
        "zone_id": zone.zone_id,
        "kind": next(item.kind.value for item in target.machine.zones if item.zone_id == zone.zone_id),
        "capacity": next(item.capacity for item in target.machine.zones if item.zone_id == zone.zone_id),
        "x_um": zone.lower_left.x_um,
        "y_um": zone.lower_left.y_um,
        "width_um": zone.width_um,
        "height_um": zone.height_um,
    } for zone in target.geometry.zones]
    trajectories = [{
        "trajectory_id": item.trajectory_id,
        "source_zone_id": item.source_zone_id,
        "destination_zone_id": item.destination_zone_id,
        "waypoints": [[point.x_um, point.y_um] for point in item.waypoints],
        "conflict_group_ids": list(item.conflict_group_ids),
    } for item in target.geometry.trajectories]

    return VisualizationRun(
        result.trace.run_id,
        label,
        {
            "graph_id": graph.graph_id,
            "schedule_id": schedule.schedule_id,
            "machine_config_id": target.machine.machine_id,
            "noise_config_id": result.noise_report.config.config_id,
            "noise_seed": result.noise_report.seed,
            "noise_parameter_source": result.noise_report.config.parameter_source,
            "makespan_ns": schedule.makespan_ns,
            "metrics": {
                "task_count": len(task_rows),
                "event_count": len(events),
                "observation_count": len(observations),
                "noise_event_count": len(result.noise_report.events),
                "total_wait_ns": sum(item["wait_ns"] for item in task_rows),
                "max_parallel_tasks": _max_parallelism(task_rows),
                "final_state_digest": result.trace.snapshots[-1].state_digest,
            },
            "resources": resources,
            "zones": zones,
            "trajectories": trajectories,
            "tasks": task_rows,
            "events": events,
            "snapshots": snapshots,
            "observations": observations,
        },
    )


def build_visualization_bundle(title: str, *runs: VisualizationRun) -> VisualizationBundle:
    return VisualizationBundle(title, tuple(runs))


def combine_visualization_runs(
    run_id: str, label: str, *segments: VisualizationRun,
    runtime_events: tuple[Mapping[str, Any], ...] = (),
    terminal_snapshot: Mapping[str, Any] | None = None,
) -> VisualizationRun:
    """Merge absolute-time execution segments into one M7 runtime timeline."""

    require_id(run_id, "combined visualization run ID")
    require_id(label, "combined visualization label")
    if not segments:
        raise ContractValidationError("combined visualization requires at least one segment")
    machine_ids = {item.payload["machine_config_id"] for item in segments}
    if len(machine_ids) != 1:
        raise ContractValidationError("combined visualization segments require one machine")
    tasks = [to_primitive(task) for segment in segments for task in segment.payload["tasks"]]
    events = [to_primitive(event) for segment in segments for event in segment.payload["events"]]
    for event in runtime_events:
        values = dict(event)
        for name in ("event_id", "kind", "time_ns"):
            if name not in values:
                raise ContractValidationError(f"runtime visualization event lacks {name}")
        events.append({
            "task_id": "runtime", "opcode": "emit_sync", "observation_id": None,
            "observation_kind": None, "logical_op_ids": [], **values,
        })
    snapshots = [to_primitive(item) for segment in segments for item in segment.payload["snapshots"]]
    if terminal_snapshot is not None:
        snapshots.append(to_primitive(terminal_snapshot))
    observations = [to_primitive(item) for segment in segments for item in segment.payload["observations"]]
    events.sort(key=lambda item: (item["time_ns"], item["event_id"]))
    snapshots.sort(key=lambda item: item["time_ns"])
    makespan = max(
        max((task["end_ns"] for task in tasks), default=0),
        max((event["time_ns"] for event in events), default=0),
    )
    first = segments[0].payload
    return VisualizationRun(run_id, label, {
        "graph_id": "+".join(str(item.payload["graph_id"]) for item in segments),
        "schedule_id": "+".join(str(item.payload["schedule_id"]) for item in segments),
        "machine_config_id": next(iter(machine_ids)), "makespan_ns": makespan,
        "metrics": {
            "task_count": len(tasks), "event_count": len(events),
            "observation_count": len(observations),
            "total_wait_ns": sum(task["wait_ns"] for task in tasks),
            "max_parallel_tasks": _max_parallelism(tasks),
            "final_state_digest": snapshots[-1]["state_digest"],
        },
        "resources": to_primitive(first["resources"]),
        "zones": to_primitive(first["zones"]),
        "trajectories": to_primitive(first["trajectories"]), "tasks": tasks,
        "events": events, "snapshots": snapshots, "observations": observations,
    })


def write_visualization_artifact(bundle: VisualizationBundle, output_path: str | Path) -> tuple[Path, Path]:
    """Write a standalone HTML artifact plus its inspectable JSON sidecar."""

    html_path = Path(output_path)
    if html_path.suffix.lower() != ".html":
        raise ContractValidationError("visualization output path must end in .html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = html_path.with_suffix(".json")
    payload = bundle.to_json()
    html_path.write_text(render_standalone_html(bundle.title, payload), encoding="utf-8")
    json_path.write_text(payload + "\n", encoding="utf-8")
    return html_path, json_path


def _max_parallelism(tasks: list[dict[str, Any]]) -> int:
    points = [(task["start_ns"], 1) for task in tasks] + [(task["end_ns"], -1) for task in tasks]
    active = maximum = 0
    for _, delta in sorted(points, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum

