"""Replayable digital-twin execution events and machine snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from compiler.physical_ir import PhysicalOpcode, Provenance
from contracts.common import (
    SCHEMA_VERSION, ContractValidationError, canonical_json, frozen_mapping,
    parse_json, require_id, require_schema, to_primitive,
)


class TraceEventKind(StrEnum):
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    OBSERVATION_EMITTED = "observation_emitted"


@dataclass(frozen=True, slots=True)
class MachineSnapshot:
    snapshot_id: str
    captured_at_ns: int
    zone_occupancy: Mapping[str, int]
    block_locations: Mapping[str, str]
    atom_locations: Mapping[str, str]
    qubit_label_counts: Mapping[str, int]
    atoms_present: int
    known_erasures: int
    reservoir_inventory: int
    aligned_pair_count: int
    state_digest: str

    def __post_init__(self) -> None:
        require_id(self.snapshot_id, "snapshot ID")
        require_id(self.state_digest, "state digest")
        if self.captured_at_ns < 0 or min(self.atoms_present, self.known_erasures, self.reservoir_inventory, self.aligned_pair_count) < 0:
            raise ContractValidationError("snapshot counts and time must be non-negative")
        object.__setattr__(self, "zone_occupancy", frozen_mapping(self.zone_occupancy))
        object.__setattr__(self, "block_locations", frozen_mapping(self.block_locations))
        object.__setattr__(self, "atom_locations", frozen_mapping(self.atom_locations))
        object.__setattr__(self, "qubit_label_counts", frozen_mapping(self.qubit_label_counts))


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    event_id: str
    kind: TraceEventKind
    occurred_at_ns: int
    task_id: str
    opcode: PhysicalOpcode
    scheduled_start_ns: int
    scheduled_end_ns: int
    resource_ids: tuple[str, ...]
    zone_ids: tuple[str, ...]
    trajectory_id: str | None
    observation_id: str | None
    provenance: Provenance
    state_digest: str

    def __post_init__(self) -> None:
        for value, name in ((self.event_id, "trace event ID"), (self.task_id, "trace task ID"), (self.state_digest, "trace state digest")):
            require_id(value, name)
        if not isinstance(self.kind, TraceEventKind) or not isinstance(self.opcode, PhysicalOpcode):
            raise ContractValidationError("trace kind and opcode must be physical enums")
        if self.occurred_at_ns < 0 or self.scheduled_end_ns <= self.scheduled_start_ns:
            raise ContractValidationError("trace event times are invalid")
        if self.kind is TraceEventKind.TASK_STARTED and self.occurred_at_ns != self.scheduled_start_ns:
            raise ContractValidationError("task-start event must occur at its scheduled start")
        if self.kind is not TraceEventKind.TASK_STARTED and self.occurred_at_ns != self.scheduled_end_ns:
            raise ContractValidationError("completion/observation event must occur at scheduled end")
        if self.observation_id is not None:
            require_id(self.observation_id, "trace observation ID")


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    run_id: str
    schedule_id: str
    graph_id: str
    started_at_ns: int
    ended_at_ns: int
    events: tuple[ExecutionEvent, ...]
    snapshots: tuple[MachineSnapshot, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        for value, name in ((self.run_id, "trace run ID"), (self.schedule_id, "trace schedule ID"), (self.graph_id, "trace graph ID")):
            require_id(value, name)
        if self.started_at_ns < 0 or self.ended_at_ns < self.started_at_ns:
            raise ContractValidationError("trace time range is invalid")
        if any(left.occurred_at_ns > right.occurred_at_ns for left, right in zip(self.events, self.events[1:])):
            raise ContractValidationError("trace event time must be monotonic")
        if any(left.captured_at_ns > right.captured_at_ns for left, right in zip(self.snapshots, self.snapshots[1:])):
            raise ContractValidationError("snapshot time must be monotonic")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ContractValidationError("trace event IDs must be unique")
        if len({snapshot.snapshot_id for snapshot in self.snapshots}) != len(self.snapshots):
            raise ContractValidationError("snapshot IDs must be unique")

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_json(cls, payload: str) -> "ExecutionTrace":
        data = parse_json(payload)
        return cls(
            run_id=data["run_id"], schedule_id=data["schedule_id"], graph_id=data["graph_id"],
            started_at_ns=data["started_at_ns"], ended_at_ns=data["ended_at_ns"],
            events=tuple(ExecutionEvent(
                event_id=item["event_id"], kind=TraceEventKind(item["kind"]),
                occurred_at_ns=item["occurred_at_ns"], task_id=item["task_id"],
                opcode=PhysicalOpcode(item["opcode"]), scheduled_start_ns=item["scheduled_start_ns"],
                scheduled_end_ns=item["scheduled_end_ns"], resource_ids=tuple(item["resource_ids"]),
                zone_ids=tuple(item["zone_ids"]), trajectory_id=item["trajectory_id"],
                observation_id=item.get("observation_id"),
                provenance=Provenance(tuple(item["provenance"]["logical_op_ids"]), tuple(item["provenance"]["qec_op_ids"])),
                state_digest=item["state_digest"],
            ) for item in data["events"]),
            snapshots=tuple(MachineSnapshot(
                snapshot_id=item["snapshot_id"], captured_at_ns=item["captured_at_ns"],
                zone_occupancy=item["zone_occupancy"], block_locations=item["block_locations"],
                atom_locations=item["atom_locations"], qubit_label_counts=item["qubit_label_counts"], atoms_present=item["atoms_present"],
                known_erasures=item["known_erasures"], reservoir_inventory=item["reservoir_inventory"],
                aligned_pair_count=item["aligned_pair_count"], state_digest=item["state_digest"],
            ) for item in data["snapshots"]),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )
