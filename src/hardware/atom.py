"""Mutable digital-twin atom/site records with explicit erasure state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from contracts.common import ContractValidationError, require_id
from contracts.events import AtomRole


class QubitLabel(StrEnum):
    ZERO = "zero"
    ONE = "one"
    PLUS = "plus"
    MINUS = "minus"
    ENTANGLED = "entangled"
    MEASURED = "measured"
    LOST = "lost"


@dataclass(slots=True)
class AtomState:
    atom_id: str
    role: AtomRole
    zone_id: str | None
    block_id: str | None = None
    site_id: str | None = None
    present: bool = True
    known_erasure: bool = False
    qubit_label: QubitLabel = QubitLabel.ZERO
    trajectory_id: str | None = None

    def __post_init__(self) -> None:
        require_id(self.atom_id, "atom ID")
        if not isinstance(self.role, AtomRole):
            raise ContractValidationError("atom role must be an AtomRole")
        for value, name in ((self.zone_id, "atom zone ID"), (self.block_id, "atom block ID"), (self.site_id, "atom site ID"), (self.trajectory_id, "atom trajectory ID")):
            if value is not None:
                require_id(value, name)
        if not isinstance(self.qubit_label, QubitLabel):
            raise ContractValidationError("qubit label must be a QubitLabel")


@dataclass(slots=True)
class SiteState:
    site_id: str
    block_id: str
    role: AtomRole
    atom_id: str | None
    known_erasure: bool = False

    def __post_init__(self) -> None:
        require_id(self.site_id, "site ID")
        require_id(self.block_id, "site block ID")
        if self.atom_id is not None:
            require_id(self.atom_id, "site atom ID")


@dataclass(slots=True)
class BlockState:
    block_id: str
    site_ids: tuple[str, ...]
    zone_id: str | None
    trajectory_id: str | None = None

    def __post_init__(self) -> None:
        require_id(self.block_id, "block ID")
        for site_id in self.site_ids:
            require_id(site_id, "block site ID")
