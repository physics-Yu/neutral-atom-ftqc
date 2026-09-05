"""Finite neutral-atom zone geometry and prevalidated transport trajectories."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from contracts.common import ContractValidationError, require_id


@dataclass(frozen=True, slots=True)
class Point2D:
    x_um: int
    y_um: int

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (self.x_um, self.y_um)):
            raise ContractValidationError("geometry coordinates must be integer micrometers")


@dataclass(frozen=True, slots=True)
class ZoneGeometry:
    zone_id: str
    lower_left: Point2D
    width_um: int
    height_um: int

    def __post_init__(self) -> None:
        require_id(self.zone_id, "zone geometry ID")
        if not isinstance(self.lower_left, Point2D):
            raise ContractValidationError("zone lower_left must be a Point2D")
        for value in (self.width_um, self.height_um):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ContractValidationError("zone dimensions must be positive integer micrometers")


@dataclass(frozen=True, slots=True)
class TrajectorySpec:
    trajectory_id: str
    source_zone_id: str
    destination_zone_id: str
    waypoints: tuple[Point2D, ...]
    duration_ns: int
    conflict_group_ids: tuple[str, ...]
    minimum_clearance_um: float = 0.0
    max_speed_um_per_us: float | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.trajectory_id, "trajectory_id"), (self.source_zone_id, "source_zone_id"), (self.destination_zone_id, "destination_zone_id")):
            require_id(value, name)
        if self.source_zone_id == self.destination_zone_id:
            raise ContractValidationError("trajectory endpoints must be distinct zones")
        if len(self.waypoints) < 2 or any(not isinstance(point, Point2D) for point in self.waypoints):
            raise ContractValidationError("trajectory must contain at least two Point2D waypoints")
        if not isinstance(self.duration_ns, int) or isinstance(self.duration_ns, bool) or self.duration_ns <= 0:
            raise ContractValidationError("trajectory duration_ns must be positive")
        if not self.conflict_group_ids:
            raise ContractValidationError("trajectory must declare at least one routing conflict group")
        if len(self.conflict_group_ids) != len(set(self.conflict_group_ids)):
            raise ContractValidationError("trajectory conflict groups must be unique")
        for group_id in self.conflict_group_ids:
            require_id(group_id, "trajectory conflict group ID")
        if not isinstance(self.minimum_clearance_um, (int, float)) or isinstance(self.minimum_clearance_um, bool) or self.minimum_clearance_um < 0:
            raise ContractValidationError("trajectory minimum clearance must be non-negative")
        if self.max_speed_um_per_us is not None:
            if not isinstance(self.max_speed_um_per_us, (int, float)) or isinstance(self.max_speed_um_per_us, bool) or self.max_speed_um_per_us <= 0:
                raise ContractValidationError("trajectory maximum speed must be positive")
            distance_um = sum(
                hypot(right.x_um - left.x_um, right.y_um - left.y_um)
                for left, right in zip(self.waypoints, self.waypoints[1:])
            )
            actual_speed = distance_um / (self.duration_ns / 1_000)
            if actual_speed > self.max_speed_um_per_us:
                raise ContractValidationError("trajectory exceeds its configured maximum speed")


@dataclass(frozen=True, slots=True)
class MachineGeometry:
    zones: tuple[ZoneGeometry, ...]
    trajectories: tuple[TrajectorySpec, ...]

    def __post_init__(self) -> None:
        zone_ids = [zone.zone_id for zone in self.zones]
        trajectory_ids = [item.trajectory_id for item in self.trajectories]
        if len(zone_ids) != len(set(zone_ids)):
            raise ContractValidationError("zone geometry IDs must be unique")
        if len(trajectory_ids) != len(set(trajectory_ids)):
            raise ContractValidationError("trajectory IDs must be unique")
        known = set(zone_ids)
        for item in self.trajectories:
            if {item.source_zone_id, item.destination_zone_id} - known:
                raise ContractValidationError("trajectory references an unknown geometry zone")
        for index, left in enumerate(self.trajectories):
            for right in self.trajectories[index + 1:]:
                if _trajectories_intersect(left, right) and not (
                    set(left.conflict_group_ids) & set(right.conflict_group_ids)
                ):
                    raise ContractValidationError(
                        "intersecting trajectories must share a routing conflict group"
                    )

    def trajectory(self, source_zone_id: str, destination_zone_id: str) -> TrajectorySpec:
        for item in self.trajectories:
            if item.source_zone_id == source_zone_id and item.destination_zone_id == destination_zone_id:
                return item
        raise ContractValidationError(f"no configured trajectory from {source_zone_id!r} to {destination_zone_id!r}")

    def trajectory_by_id(self, trajectory_id: str) -> TrajectorySpec:
        for item in self.trajectories:
            if item.trajectory_id == trajectory_id:
                return item
        raise ContractValidationError(f"unknown trajectory {trajectory_id!r}")


def _trajectories_intersect(left: TrajectorySpec, right: TrajectorySpec) -> bool:
    return any(
        _segments_intersect(a, b, c, d)
        for a, b in zip(left.waypoints, left.waypoints[1:])
        for c, d in zip(right.waypoints, right.waypoints[1:])
    )


def _segments_intersect(a: Point2D, b: Point2D, c: Point2D, d: Point2D) -> bool:
    def orientation(p: Point2D, q: Point2D, r: Point2D) -> int:
        value = (q.y_um - p.y_um) * (r.x_um - q.x_um) - (q.x_um - p.x_um) * (r.y_um - q.y_um)
        return (value > 0) - (value < 0)

    def on_segment(p: Point2D, q: Point2D, r: Point2D) -> bool:
        return (
            min(p.x_um, r.x_um) <= q.x_um <= max(p.x_um, r.x_um)
            and min(p.y_um, r.y_um) <= q.y_um <= max(p.y_um, r.y_um)
        )

    o1, o2 = orientation(a, b, c), orientation(a, b, d)
    o3, o4 = orientation(c, d, a), orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and on_segment(a, c, b))
        or (o2 == 0 and on_segment(a, d, b))
        or (o3 == 0 and on_segment(c, a, d))
        or (o4 == 0 and on_segment(c, b, d))
    )

