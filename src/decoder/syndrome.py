"""Typed syndrome samples, history windows, and deterministic test oracles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from contracts.common import ContractValidationError, frozen_mapping, require_id
from contracts.events import Observation, ObservationBatch, ObservationKind
from qec.surface_code import PauliBasis, SurfaceCodeLayout


class PauliError(StrEnum):
    X = "X"
    Y = "Y"
    Z = "Z"


@dataclass(frozen=True, slots=True)
class SyndromeSample:
    block_id: str
    logical_qubit_id: str
    layout_id: str
    round_index: int
    observed_at_ns: int
    bits: Mapping[str, int]
    source_event_id: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.block_id, "syndrome block_id"),
            (self.logical_qubit_id, "syndrome logical_qubit_id"),
            (self.layout_id, "syndrome layout_id"),
            (self.source_event_id, "syndrome source_event_id"),
        ):
            require_id(value, name)
        if not isinstance(self.round_index, int) or isinstance(self.round_index, bool) or self.round_index < 0:
            raise ContractValidationError("syndrome round_index must be non-negative")
        if not isinstance(self.observed_at_ns, int) or isinstance(self.observed_at_ns, bool) or self.observed_at_ns < 0:
            raise ContractValidationError("syndrome observation time must be non-negative")
        if not self.bits or any(bit not in (0, 1) or isinstance(bit, bool) for bit in self.bits.values()):
            raise ContractValidationError("syndrome bits must be non-empty integer zero/one values")
        for check_id in self.bits:
            require_id(check_id, "syndrome check ID")
        object.__setattr__(self, "bits", frozen_mapping(self.bits))

    @classmethod
    def from_observation(cls, observation: Observation) -> "SyndromeSample":
        if observation.kind is not ObservationKind.SYNDROME:
            raise ContractValidationError("only syndrome observations form SyndromeSample values")
        payload = observation.payload
        return cls(
            payload["block_id"], payload["logical_qubit_id"], payload["layout_id"],
            payload["round_index"], observation.observed_at_ns, payload["bits"],
            observation.event_id,
        )


@dataclass(frozen=True, slots=True)
class SyndromeHistory:
    samples: tuple[SyndromeSample, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(item, SyndromeSample) for item in self.samples):
            raise ContractValidationError("syndrome history requires typed samples")
        keys = [(item.block_id, item.round_index) for item in self.samples]
        if len(keys) != len(set(keys)):
            raise ContractValidationError("syndrome history cannot duplicate a block round")
        if any(left.observed_at_ns > right.observed_at_ns for left, right in zip(self.samples, self.samples[1:])):
            raise ContractValidationError("syndrome history time must be monotonic")
        rounds_by_block: dict[str, list[int]] = {}
        for sample in self.samples:
            rounds_by_block.setdefault(sample.block_id, []).append(sample.round_index)
        if any(any(left >= right for left, right in zip(rounds, rounds[1:])) for rounds in rounds_by_block.values()):
            raise ContractValidationError("syndrome rounds must increase within each block")

    @classmethod
    def from_observation_batch(cls, batch: ObservationBatch) -> "SyndromeHistory":
        return cls(tuple(
            SyndromeSample.from_observation(item)
            for item in batch.observations if item.kind is ObservationKind.SYNDROME
        ))

    def for_block(self, block_id: str, *, last_rounds: int | None = None) -> "SyndromeHistory":
        selected = tuple(item for item in self.samples if item.block_id == block_id)
        if last_rounds is not None:
            if not isinstance(last_rounds, int) or isinstance(last_rounds, bool) or last_rounds <= 0:
                raise ContractValidationError("last_rounds must be positive")
            selected = selected[-last_rounds:]
        return SyndromeHistory(selected)


def simulate_single_pauli_syndrome(
    layout: SurfaceCodeLayout, block_id: str, logical_qubit_id: str,
    site_id: str, error: PauliError, *, round_index: int = 0,
    observed_at_ns: int = 0,
) -> SyndromeSample:
    """Return the exact stabilizer signature for one injected data-site Pauli."""

    if site_id not in {site.site_id for site in layout.data_sites}:
        raise ContractValidationError("single-Pauli syndrome site must be a data site")
    if not isinstance(error, PauliError):
        raise ContractValidationError("error must be a PauliError")
    bits = {
        check.check_id: int(
            site_id in check.data_site_ids
            and ((error in {PauliError.X, PauliError.Y} and check.basis is PauliBasis.Z)
                 or (error in {PauliError.Z, PauliError.Y} and check.basis is PauliBasis.X))
        )
        for check in layout.stabilizers
    }
    return SyndromeSample(
        block_id, logical_qubit_id, layout.layout_id, round_index,
        observed_at_ns, bits, f"synthetic-{block_id}-r{round_index}-{site_id}-{error.value}",
    )

