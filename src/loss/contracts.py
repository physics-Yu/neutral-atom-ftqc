"""Explicit atom-loss and reservoir-allocation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from contracts.common import (
    ContractValidationError, canonical_json, parse_json, require_id, to_primitive,
)
from contracts.events import AtomRole, Observation, ObservationKind


class RecoveryStatus(StrEnum):
    READY = "ready"
    RESERVOIR_EXHAUSTED = "reservoir_exhausted"


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    loss_event_id: str
    atom_id: str
    block_id: str
    site_id: str
    atom_role: AtomRole
    detected_at_ns: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.loss_event_id, "loss event ID"), (self.atom_id, "lost atom ID"),
            (self.block_id, "loss block ID"), (self.site_id, "loss site ID"),
        ):
            require_id(value, name)
        if not isinstance(self.atom_role, AtomRole) or self.atom_role not in {AtomRole.DATA, AtomRole.ANCILLA}:
            raise ContractValidationError("recovery request role must be data or ancilla")
        if not isinstance(self.detected_at_ns, int) or isinstance(self.detected_at_ns, bool) or self.detected_at_ns < 0:
            raise ContractValidationError("loss detection time must be non-negative")
        if not self.site_id.startswith(f"{self.block_id}/"):
            raise ContractValidationError("loss site must be qualified by its block ID")

    @property
    def local_site_id(self) -> str:
        return self.site_id.split("/", 1)[1]

    @property
    def requires_qec(self) -> bool:
        return self.atom_role is AtomRole.DATA

    @classmethod
    def from_observation(cls, observation: Observation) -> "RecoveryRequest":
        if observation.kind is not ObservationKind.ATOM_LOSS:
            raise ContractValidationError("recovery requests require atom-loss observations")
        values = observation.payload
        return cls(
            observation.event_id, values["atom_id"], values["block_id"],
            values["site_id"], AtomRole(values["atom_role"]), observation.observed_at_ns,
        )


@dataclass(frozen=True, slots=True)
class ReservoirAllocation:
    allocation_id: str
    loss_event_id: str
    replacement_atom_id: str
    allocated_at_ns: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.allocation_id, "allocation ID"), (self.loss_event_id, "allocation loss event ID"),
            (self.replacement_atom_id, "replacement atom ID"),
        ):
            require_id(value, name)
        if not isinstance(self.allocated_at_ns, int) or isinstance(self.allocated_at_ns, bool) or self.allocated_at_ns < 0:
            raise ContractValidationError("allocation time must be non-negative")


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    plan_id: str
    request: RecoveryRequest
    status: RecoveryStatus
    allocation: ReservoirAllocation | None = None

    def __post_init__(self) -> None:
        require_id(self.plan_id, "recovery plan ID")
        if not isinstance(self.request, RecoveryRequest) or not isinstance(self.status, RecoveryStatus):
            raise ContractValidationError("recovery plan types are invalid")
        if (self.status is RecoveryStatus.READY) != (self.allocation is not None):
            raise ContractValidationError("ready recovery plans require exactly one allocation")
        if self.allocation is not None and self.allocation.loss_event_id != self.request.loss_event_id:
            raise ContractValidationError("allocation and recovery request loss IDs differ")

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_json(cls, payload: str) -> "RecoveryPlan":
        data: Mapping[str, Any] = parse_json(payload)
        request = data["request"]
        allocation = data.get("allocation")
        return cls(
            data["plan_id"],
            RecoveryRequest(
                request["loss_event_id"], request["atom_id"], request["block_id"],
                request["site_id"], AtomRole(request["atom_role"]), request["detected_at_ns"],
            ),
            RecoveryStatus(data["status"]),
            None if allocation is None else ReservoirAllocation(
                allocation["allocation_id"], allocation["loss_event_id"],
                allocation["replacement_atom_id"], allocation["allocated_at_ns"],
            ),
        )

