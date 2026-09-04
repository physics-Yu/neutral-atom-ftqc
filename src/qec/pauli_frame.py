"""Immutable logical Pauli-frame state; no physical correction is implied."""

from __future__ import annotations

from dataclasses import dataclass, replace

from contracts.common import ContractValidationError, require_id


@dataclass(frozen=True, slots=True)
class PauliFrameEntry:
    logical_qubit_id: str
    x: bool = False
    z: bool = False

    def __post_init__(self) -> None:
        require_id(self.logical_qubit_id, "logical_qubit_id")
        if not isinstance(self.x, bool) or not isinstance(self.z, bool):
            raise ContractValidationError("Pauli-frame x and z flags must be booleans")

    def compose(self, *, x: bool = False, z: bool = False) -> "PauliFrameEntry":
        return replace(self, x=self.x ^ x, z=self.z ^ z)


@dataclass(frozen=True, slots=True)
class PauliFrame:
    entries: tuple[PauliFrameEntry, ...]

    def __post_init__(self) -> None:
        ids = [entry.logical_qubit_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("Pauli-frame logical qubit IDs must be unique")

    @classmethod
    def identity(cls, logical_qubit_ids: tuple[str, ...]) -> "PauliFrame":
        return cls(tuple(PauliFrameEntry(item) for item in logical_qubit_ids))

    def get(self, logical_qubit_id: str) -> PauliFrameEntry:
        for entry in self.entries:
            if entry.logical_qubit_id == logical_qubit_id:
                return entry
        raise ContractValidationError(f"unknown logical qubit {logical_qubit_id!r} in Pauli frame")

    def updated(self, logical_qubit_id: str, *, x: bool = False, z: bool = False) -> "PauliFrame":
        self.get(logical_qubit_id)
        return PauliFrame(tuple(
            entry.compose(x=x, z=z) if entry.logical_qubit_id == logical_qubit_id else entry
            for entry in self.entries
        ))

