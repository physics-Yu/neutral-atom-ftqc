"""Finite neutral-atom zone geometry and prevalidated transport trajectories."""

from __future__ import annotations

from dataclasses import dataclass

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

    def __post_init__(self) -> None:
        for value, name in ((self.trajectory_id, "trajectory_id"), (self.source_zone_id, "source_zone_id"), (self.destination_zone_id, "destination_zone_id")):
            require_id(value, name)
        if self.source_zone_id == self.destination_zone_id:
            raise ContractValidationError("trajectory endpoints must be distinct zones")
        if len(self.waypoints) < 2 or any(not isinstance(point, Point2D) for point in self.waypoints):
            raise ContractValidationError("trajectory must contain at least two Point2D waypoints")
        if not isinstance(self.duration_ns, int) or isinstance(self.duration_ns, bool) or self.duration_ns <= 0:
            raise ContractValidationError("trajectory duration_ns must be positive")


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

    def trajectory(self, source_zone_id: str, destination_zone_id: str) -> TrajectorySpec:
        for item in self.trajectories:
            if item.source_zone_id == source_zone_id and item.destination_zone_id == destination_zone_id:
                return item
        raise ContractValidationError(f"no configured trajectory from {source_zone_id!r} to {destination_zone_id!r}")
