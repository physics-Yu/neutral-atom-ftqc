from __future__ import annotations

import pytest

from contracts import (
    CalibrationSnapshot, ContractValidationError, CoordinateUnit, MachineConfig,
    ResourceSpec, ZoneKind, ZoneSpec,
)


def machine() -> MachineConfig:
    return MachineConfig(
        machine_id="machine-1",
        zones=tuple(ZoneSpec(kind.value, kind, 32) for kind in ZoneKind),
        resources=(ResourceSpec("aod-0", "transport", 1),),
        calibration=CalibrationSnapshot("cal-1", {"move_atoms": 1000}),
    )


def test_machine_config_round_trip() -> None:
    value = machine()
    assert MachineConfig.from_json(value.to_json()) == value


def test_all_four_initial_zones_are_required() -> None:
    with pytest.raises(ContractValidationError, match="missing required zones"):
        MachineConfig(
            "bad", (ZoneSpec("storage", ZoneKind.STORAGE, 1),), (),
            CalibrationSnapshot("cal", {}),
        )


def test_capacity_duration_and_coordinate_units_are_explicit() -> None:
    with pytest.raises(ContractValidationError, match="positive integer"):
        ResourceSpec("laser", "rydberg", 0)
    with pytest.raises(ContractValidationError, match="nanoseconds"):
        CalibrationSnapshot("cal", {"move_atoms": 0})
    with pytest.raises(ValueError):
        CoordinateUnit("meters")


def test_unknown_schema_version_is_rejected() -> None:
    data = machine().to_dict()
    data["schema_version"] = "9.9"
    with pytest.raises(ContractValidationError, match="unsupported schema_version"):
        MachineConfig.from_dict(data)

