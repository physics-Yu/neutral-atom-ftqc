from __future__ import annotations

import json

from examples.ghz_surface_code import build_ghz_visualization_run
from visualization import build_visualization_bundle, write_visualization_artifact


def test_one_artifact_compares_serial_and_parallel_ghz_runs(tmp_path) -> None:
    low = build_ghz_visualization_run(3, "low")
    high = build_ghz_visualization_run(3, "high")
    html_path, json_path = write_visualization_artifact(
        build_visualization_bundle("Four-block GHZ · distance 3", low, high),
        tmp_path / "ghz-d3.html",
    )

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert html_path.stat().st_size > 10_000
    assert len(data["runs"]) == 2
    assert all(run["metrics"]["task_count"] == 41 for run in data["runs"])
    assert all(run["metrics"]["observation_count"] == 36 for run in data["runs"])
    assert data["runs"][0]["makespan_ns"] == 1_266_400
    assert data["runs"][1]["makespan_ns"] == 466_400

    def interval(profile: int, task_id: str) -> tuple[int, int]:
        task = next(item for item in data["runs"][profile]["tasks"] if item["task_id"] == task_id)
        return task["start_ns"], task["end_ns"]

    low_a = interval(0, "phy-qec-cx-L0-L2-rydberg-cz")
    low_b = interval(0, "phy-qec-cx-L1-L3-rydberg-cz")
    high_a = interval(1, "phy-qec-cx-L0-L2-rydberg-cz")
    high_b = interval(1, "phy-qec-cx-L1-L3-rydberg-cz")
    assert low_a[1] <= low_b[0] or low_b[1] <= low_a[0]
    assert high_a == high_b
