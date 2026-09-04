"""Versioned observations emitted by the future digital twin."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
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


class ObservationKind(StrEnum):
    MEASUREMENT = "measurement"
    ATOM_PRESENCE = "atom_presence"
    SYNDROME = "syndrome"
    ATOM_LOSS = "atom_loss"
    RESOURCE_FAULT = "resource_fault"


class AtomRole(StrEnum):
    DATA = "data"
    ANCILLA = "ancilla"
    REPLACEMENT = "replacement"
    RESERVOIR = "reservoir"


@dataclass(frozen=True, slots=True)
class Observation:
    event_id: str
    kind: ObservationKind
    observed_at_ns: int
    task_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_id(self.event_id, "event_id")
        require_id(self.task_id, "task_id")
        if not isinstance(self.kind, ObservationKind):
            raise ContractValidationError("kind must be an ObservationKind")
        if not isinstance(self.observed_at_ns, int) or isinstance(self.observed_at_ns, bool) or self.observed_at_ns < 0:
            raise ContractValidationError("observed_at_ns must be a non-negative integer")
        values = dict(self.payload)
        if self.kind is ObservationKind.ATOM_LOSS:
            required = {"atom_id", "block_id", "site_id", "atom_role"}
            missing = required - values.keys()
            if missing:
                raise ContractValidationError(
                    f"atom_loss payload is missing: {', '.join(sorted(missing))}"
                )
            try:
                AtomRole(values["atom_role"])
            except ValueError as exc:
                raise ContractValidationError("atom_loss atom_role is invalid") from exc
        object.__setattr__(self, "payload", frozen_mapping(values))


@dataclass(frozen=True, slots=True)
class ObservationBatch:
    run_id: str
    batch_id: str
    observed_at_ns: int
    observations: tuple[Observation, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        require_id(self.run_id, "run_id")
        require_id(self.batch_id, "batch_id")
        if not isinstance(self.observed_at_ns, int) or isinstance(self.observed_at_ns, bool) or self.observed_at_ns < 0:
            raise ContractValidationError("observed_at_ns must be a non-negative integer")
        ids = [item.event_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("observation event IDs must be unique")
        if any(item.observed_at_ns > self.observed_at_ns for item in self.observations):
            raise ContractValidationError("batch time cannot precede an observation time")

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObservationBatch":
        observations = tuple(
            Observation(
                event_id=item["event_id"],
                kind=ObservationKind(item["kind"]),
                observed_at_ns=item["observed_at_ns"],
                task_id=item["task_id"],
                payload=item.get("payload", {}),
            )
            for item in data["observations"]
        )
        return cls(
            run_id=data["run_id"],
            batch_id=data["batch_id"],
            observed_at_ns=data["observed_at_ns"],
            observations=observations,
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, payload: str) -> "ObservationBatch":
        return cls.from_dict(parse_json(payload))

