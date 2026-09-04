"""Immutable neutral-atom machine configuration contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from .common import (
    SCHEMA_VERSION,
    ContractValidationError,
    canonical_json,
    frozen_mapping,
    parse_json,
    require_id,
    require_schema,
    to_primitive,
)


class ZoneKind(StrEnum):
    STORAGE = "storage"
    ENTANGLING = "entangling"
    READOUT = "readout"
    RESERVOIR = "reservoir"


class CoordinateUnit(StrEnum):
    MICROMETER = "um"


@dataclass(frozen=True, slots=True)
class ZoneSpec:
    zone_id: str
    kind: ZoneKind
    capacity: int
    coordinate_unit: CoordinateUnit = CoordinateUnit.MICROMETER
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_id(self.zone_id, "zone_id")
        if not isinstance(self.kind, ZoneKind):
            raise ContractValidationError("kind must be a ZoneKind")
        if not isinstance(self.capacity, int) or isinstance(self.capacity, bool) or self.capacity <= 0:
            raise ContractValidationError("zone capacity must be a positive integer")
        if not isinstance(self.coordinate_unit, CoordinateUnit):
            raise ContractValidationError("coordinate_unit must be a supported CoordinateUnit")
        object.__setattr__(self, "metadata", frozen_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    resource_id: str
    resource_class: str
    capacity: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_id(self.resource_id, "resource_id")
        require_id(self.resource_class, "resource_class")
        if not isinstance(self.capacity, int) or isinstance(self.capacity, bool) or self.capacity <= 0:
            raise ContractValidationError("resource capacity must be a positive integer")
        object.__setattr__(self, "metadata", frozen_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class CalibrationSnapshot:
    calibration_id: str
    duration_by_opcode_ns: Mapping[str, int]

    def __post_init__(self) -> None:
        require_id(self.calibration_id, "calibration_id")
        durations = dict(self.duration_by_opcode_ns)
        for opcode, duration in durations.items():
            require_id(opcode, "opcode")
            if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
                raise ContractValidationError(
                    f"duration for {opcode!r} must be a positive integer number of nanoseconds"
                )
        object.__setattr__(self, "duration_by_opcode_ns", MappingProxyType(durations))


@dataclass(frozen=True, slots=True)
class MachineConfig:
    machine_id: str
    zones: tuple[ZoneSpec, ...]
    resources: tuple[ResourceSpec, ...]
    calibration: CalibrationSnapshot
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        require_id(self.machine_id, "machine_id")
        zone_ids = [zone.zone_id for zone in self.zones]
        resource_ids = [resource.resource_id for resource in self.resources]
        if len(zone_ids) != len(set(zone_ids)):
            raise ContractValidationError("zone IDs must be unique")
        if len(resource_ids) != len(set(resource_ids)):
            raise ContractValidationError("resource IDs must be unique")
        missing = set(ZoneKind) - {zone.kind for zone in self.zones}
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ContractValidationError(f"machine is missing required zones: {names}")

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MachineConfig":
        zones = tuple(
            ZoneSpec(
                zone_id=item["zone_id"],
                kind=ZoneKind(item["kind"]),
                capacity=item["capacity"],
                coordinate_unit=CoordinateUnit(item.get("coordinate_unit", "um")),
                metadata=item.get("metadata", {}),
            )
            for item in data["zones"]
        )
        resources = tuple(
            ResourceSpec(
                resource_id=item["resource_id"],
                resource_class=item["resource_class"],
                capacity=item["capacity"],
                metadata=item.get("metadata", {}),
            )
            for item in data["resources"]
        )
        cal = data["calibration"]
        return cls(
            machine_id=data["machine_id"],
            zones=zones,
            resources=resources,
            calibration=CalibrationSnapshot(
                calibration_id=cal["calibration_id"],
                duration_by_opcode_ns=cal["duration_by_opcode_ns"],
            ),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, payload: str) -> "MachineConfig":
        return cls.from_dict(parse_json(payload))

