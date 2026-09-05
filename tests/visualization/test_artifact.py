from __future__ import annotations

import json

import pytest

from compiler.lowering.neutral_atom import lower_to_neutral_atom_tasks
from contracts import ContractValidationError
from examples.ghz_surface_code import build_ghz_qec_protocol, build_profile_target
from hardware.hardware_state import MachineState
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest
from simulator.executor import DigitalTwinExecutor
from visualization import build_visualization_bundle, build_visualization_run, write_visualization_artifact


def _run(profile: str = "low", distance: int = 3):
    target = build_profile_target(profile)
    protocol = build_ghz_qec_protocol(distance, include_measurements=True)
    graph = lower_to_neutral_atom_tasks(protocol, target)
    schedule = schedule_physical_tasks(ScheduleRequest(f"visual-{profile}", graph, target.machine))
    result = DigitalTwinExecutor(target).execute(
        f"visual-{profile}-d{distance}", graph, schedule,
        MachineState.from_protocol(protocol, target),
    )
    return target, graph, schedule, result


@pytest.mark.parametrize("distance", [3, 5])
def test_visualization_projection_has_synchronized_trace_contract(distance: int) -> None:
    target, graph, schedule, result = _run(distance=distance)
    run = build_visualization_run("Low", target, graph, schedule, result).to_dict()

    assert run["makespan_ns"] == schedule.makespan_ns == result.trace.ended_at_ns
    assert len(run["tasks"]) == len(graph.tasks)
    assert len(run["events"]) == len(result.trace.events)
    assert run["snapshots"][0]["time_ns"] == 0
    assert run["snapshots"][-1]["state_digest"] == result.trace.snapshots[-1].state_digest
    assert {item["zone_id"] for item in run["zones"]} == {"storage", "entangling", "readout", "reservoir"}
    assert all(item["conflict_group_ids"] for item in run["trajectories"])
    assert any(item["wait_ns"] > 0 and item["blocking_interval_ids"] for item in run["tasks"])


def test_visualization_rejects_mixed_schedule_and_trace() -> None:
    low = _run("low")
    high = _run("high")
    with pytest.raises(ContractValidationError, match="schedule"):
        build_visualization_run("mixed", low[0], low[1], low[2], high[3])


def test_standalone_artifact_embeds_data_and_has_no_network_dependency(tmp_path) -> None:
    low = _run("low")
    high = _run("high")
    runs = tuple(build_visualization_run(profile, *values) for profile, values in (("Low", low), ("High", high)))
    html_path, json_path = write_visualization_artifact(
        build_visualization_bundle("GHZ comparison", *runs), tmp_path / "ghz.html",
    )

    html = html_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "visualization-data" in html
    assert all(marker in html for marker in ("Spatial state", "Resource Gantt", "Event stream", 'id="time"'))
    assert "fetch(" not in html and "<script src=" not in html and "<link " not in html
    assert [run["label"] for run in data["runs"]] == ["Low", "High"]
    assert data["runs"][1]["makespan_ns"] < data["runs"][0]["makespan_ns"]
    assert data["runs"][1]["metrics"]["max_parallel_tasks"] > data["runs"][0]["metrics"]["max_parallel_tasks"]


def test_output_requires_html_suffix(tmp_path) -> None:
    values = _run()
    bundle = build_visualization_bundle("GHZ", build_visualization_run("Low", *values))
    with pytest.raises(ContractValidationError, match=r"\.html"):
        write_visualization_artifact(bundle, tmp_path / "ghz.txt")
