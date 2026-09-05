"""Explicit decoder contracts and a deterministic single-error reference decoder."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol

from contracts.common import ContractValidationError, canonical_json, frozen_mapping, parse_json, require_id, to_primitive
from qec.pauli_frame import PauliFrame
from qec.surface_code import SurfaceCodeLayout

from .syndrome import PauliError, SyndromeHistory, simulate_single_pauli_syndrome


class DecoderStatus(StrEnum):
    CLEAN = "clean"
    CORRECTED = "corrected"
    AMBIGUOUS = "ambiguous"
    NEEDS_RECOVERY = "needs_recovery"


@dataclass(frozen=True, slots=True)
class PhysicalCorrection:
    block_id: str
    site_id: str
    pauli: PauliError

    def __post_init__(self) -> None:
        require_id(self.block_id, "correction block_id")
        require_id(self.site_id, "correction site_id")
        if not isinstance(self.pauli, PauliError):
            raise ContractValidationError("physical correction must name a Pauli error")


@dataclass(frozen=True, slots=True)
class PauliFrameDelta:
    logical_qubit_id: str
    logical_x: bool = False
    logical_z: bool = False
    physical_corrections: tuple[PhysicalCorrection, ...] = ()

    def __post_init__(self) -> None:
        require_id(self.logical_qubit_id, "frame-delta logical_qubit_id")
        if not isinstance(self.logical_x, bool) or not isinstance(self.logical_z, bool):
            raise ContractValidationError("logical frame delta flags must be booleans")
        if any(not isinstance(item, PhysicalCorrection) for item in self.physical_corrections):
            raise ContractValidationError("frame delta corrections must be PhysicalCorrection values")
        keys = [(item.block_id, item.site_id) for item in self.physical_corrections]
        if len(keys) != len(set(keys)):
            raise ContractValidationError("frame delta cannot correct one physical site twice")


@dataclass(frozen=True, slots=True)
class DecoderInput:
    input_id: str
    layout: SurfaceCodeLayout
    history: SyndromeHistory
    pauli_frame: PauliFrame
    known_erasures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_id(self.input_id, "decoder input ID")
        if not isinstance(self.layout, SurfaceCodeLayout) or not isinstance(self.history, SyndromeHistory) or not isinstance(self.pauli_frame, PauliFrame):
            raise ContractValidationError("decoder input types are invalid")
        if not self.history.samples:
            raise ContractValidationError("decoder input requires syndrome history")
        logical_ids = {item.logical_qubit_id for item in self.history.samples}
        layout_ids = {item.layout_id for item in self.history.samples}
        block_ids = {item.block_id for item in self.history.samples}
        if len(logical_ids) != 1 or len(layout_ids) != 1 or len(block_ids) != 1:
            raise ContractValidationError("one decoder input must describe one encoded block")
        if layout_ids != {self.layout.layout_id}:
            raise ContractValidationError("decoder layout does not match syndrome history")
        if next(iter(logical_ids)) not in {entry.logical_qubit_id for entry in self.pauli_frame.entries}:
            raise ContractValidationError("decoder logical qubit is absent from its Pauli frame")
        checks = {check.check_id for check in self.layout.stabilizers}
        if any(set(item.bits) != checks for item in self.history.samples):
            raise ContractValidationError("syndrome samples must cover every layout check exactly once")
        data_sites = {site.site_id for site in self.layout.data_sites}
        if set(self.known_erasures) - data_sites:
            raise ContractValidationError("known erasure references a non-data site")
        if len(self.known_erasures) != len(set(self.known_erasures)):
            raise ContractValidationError("known erasures must be unique")


@dataclass(frozen=True, slots=True)
class DecoderResult:
    input_id: str
    status: DecoderStatus
    frame_delta: PauliFrameDelta
    started_at_ns: int
    completed_at_ns: int
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_id(self.input_id, "decoder result input ID")
        if not isinstance(self.status, DecoderStatus):
            raise ContractValidationError("decoder status is invalid")
        if not isinstance(self.frame_delta, PauliFrameDelta):
            raise ContractValidationError("decoder result requires a PauliFrameDelta")
        if self.started_at_ns < 0 or self.completed_at_ns < self.started_at_ns:
            raise ContractValidationError("decoder times are invalid")
        object.__setattr__(self, "diagnostics", frozen_mapping(self.diagnostics))

    @property
    def latency_ns(self) -> int:
        return self.completed_at_ns - self.started_at_ns

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_json(cls, payload: str) -> "DecoderResult":
        data = parse_json(payload)
        delta = data["frame_delta"]
        return cls(
            input_id=data["input_id"], status=DecoderStatus(data["status"]),
            frame_delta=PauliFrameDelta(
                logical_qubit_id=delta["logical_qubit_id"],
                logical_x=delta.get("logical_x", False), logical_z=delta.get("logical_z", False),
                physical_corrections=tuple(PhysicalCorrection(
                    item["block_id"], item["site_id"], PauliError(item["pauli"]),
                ) for item in delta.get("physical_corrections", ())),
            ),
            started_at_ns=data["started_at_ns"], completed_at_ns=data["completed_at_ns"],
            diagnostics=data.get("diagnostics", {}),
        )


class Decoder(Protocol):
    def decode(self, decoder_input: DecoderInput) -> DecoderResult: ...


@dataclass(frozen=True, slots=True)
class IdealSingleErrorDecoder:
    """Exact lookup for clean or one-data-site Pauli syndromes."""

    latency_ns: int = 25_000

    def __post_init__(self) -> None:
        if not isinstance(self.latency_ns, int) or isinstance(self.latency_ns, bool) or self.latency_ns <= 0:
            raise ContractValidationError("decoder latency_ns must be positive")

    def decode(self, decoder_input: DecoderInput) -> DecoderResult:
        latest = decoder_input.history.samples[-1]
        started = latest.observed_at_ns
        logical_id = latest.logical_qubit_id
        if decoder_input.known_erasures:
            return DecoderResult(
                decoder_input.input_id, DecoderStatus.NEEDS_RECOVERY,
                PauliFrameDelta(logical_id), started, started + self.latency_ns,
                {"reason": "known erasures require the M7 erasure-aware decoder"},
            )
        previous = decoder_input.history.samples[-2].bits if len(decoder_input.history.samples) > 1 else {}
        defects = {
            check_id: bit ^ previous.get(check_id, 0)
            for check_id, bit in latest.bits.items()
        }
        active = tuple(sorted(check_id for check_id, bit in defects.items() if bit))
        if not active:
            return DecoderResult(
                decoder_input.input_id, DecoderStatus.CLEAN, PauliFrameDelta(logical_id),
                started, started + self.latency_ns, {"active_checks": []},
            )

        candidates: list[PhysicalCorrection] = []
        for site in decoder_input.layout.data_sites:
            for pauli in PauliError:
                signature = simulate_single_pauli_syndrome(
                    decoder_input.layout, latest.block_id, logical_id,
                    site.site_id, pauli,
                )
                signature_active = tuple(sorted(key for key, value in signature.bits.items() if value))
                if signature_active == active:
                    candidates.append(PhysicalCorrection(latest.block_id, site.site_id, pauli))
        if len(candidates) != 1:
            return DecoderResult(
                decoder_input.input_id, DecoderStatus.AMBIGUOUS, PauliFrameDelta(logical_id),
                started, started + self.latency_ns,
                {"active_checks": active, "candidate_count": len(candidates)},
            )
        correction = candidates[0]
        return DecoderResult(
            decoder_input.input_id, DecoderStatus.CORRECTED,
            PauliFrameDelta(logical_id, physical_corrections=(correction,)),
            started, started + self.latency_ns,
            {"active_checks": active, "matched_model": "single_data_pauli"},
        )

