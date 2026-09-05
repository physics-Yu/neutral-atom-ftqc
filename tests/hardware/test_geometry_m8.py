from __future__ import annotations

import pytest

from contracts import ContractValidationError
from hardware.geometry import MachineGeometry, Point2D, TrajectorySpec, ZoneGeometry
from hardware.zones import build_reference_target


def _zones() -> tuple[ZoneGeometry, ...]:
    return tuple(
        ZoneGeometry(name, Point2D(index * 20, 0), 10, 10)
        for index, name in enumerate(("a", "b", "c", "d"))
    )


def test_trajectory_rejects_speed_above_configured_limit() -> None:
    with pytest.raises(ContractValidationError, match="maximum speed"):
        TrajectorySpec(
            "too-fast", "a", "b", (Point2D(0, 0), Point2D(100, 0)),
            1_000, ("corridor",), 5.0, 10.0,
        )


def test_intersecting_trajectories_require_common_conflict_group() -> None:
    left = TrajectorySpec(
        "left", "a", "b", (Point2D(0, 0), Point2D(20, 20)),
        20_000, ("left-corridor",),
    )
    right = TrajectorySpec(
        "right", "c", "d", (Point2D(0, 20), Point2D(20, 0)),
        20_000, ("right-corridor",),
    )
    with pytest.raises(ContractValidationError, match="intersecting trajectories"):
        MachineGeometry(_zones(), (left, right))


def test_reference_shared_path_has_clearance_speed_and_conflict_binding() -> None:
    geometry = build_reference_target().geometry
    storage_readout = geometry.trajectory("storage", "readout")
    storage_entangling = geometry.trajectory("storage", "entangling")

    assert storage_readout.minimum_clearance_um == 5.0
    assert storage_readout.max_speed_um_per_us == 4.0
    assert set(storage_readout.conflict_group_ids) & set(storage_entangling.conflict_group_ids)

