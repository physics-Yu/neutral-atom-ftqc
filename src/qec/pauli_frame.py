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


@dataclass(frozen=True, slots=True)
class PhysicalPauliFrameEntry:
    block_id: str
    site_id: str
    x: bool = False
    z: bool = False

    def __post_init__(self) -> None:
        require_id(self.block_id, "physical-frame block_id")
        require_id(self.site_id, "physical-frame site_id")
        if not isinstance(self.x, bool) or not isinstance(self.z, bool):
            raise ContractValidationError("physical Pauli-frame flags must be booleans")

    def compose(self, *, x: bool = False, z: bool = False) -> "PhysicalPauliFrameEntry":
        return replace(self, x=self.x ^ x, z=self.z ^ z)


@dataclass(frozen=True, slots=True)
class PhysicalPauliFrame:
    """Sparse physical correction frame; entries never imply immediate pulses."""

    entries: tuple[PhysicalPauliFrameEntry, ...] = ()

    def __post_init__(self) -> None:
        if any(not isinstance(entry, PhysicalPauliFrameEntry) for entry in self.entries):
            raise ContractValidationError("physical Pauli frame requires typed entries")
        keys = [(entry.block_id, entry.site_id) for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ContractValidationError("physical Pauli-frame sites must be unique per block")

    def get(self, block_id: str, site_id: str) -> PhysicalPauliFrameEntry:
        for entry in self.entries:
            if (entry.block_id, entry.site_id) == (block_id, site_id):
                return entry
        return PhysicalPauliFrameEntry(block_id, site_id)

    def updated(self, block_id: str, site_id: str, *, x: bool = False, z: bool = False) -> "PhysicalPauliFrame":
        current = self.get(block_id, site_id)
        changed = current.compose(x=x, z=z)
        remaining = [entry for entry in self.entries if (entry.block_id, entry.site_id) != (block_id, site_id)]
        if changed.x or changed.z:
            remaining.append(changed)
        return PhysicalPauliFrame(tuple(sorted(remaining, key=lambda item: (item.block_id, item.site_id))))


