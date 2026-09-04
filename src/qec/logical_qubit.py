"""Encoded logical-block identities independent of placement and scheduling."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.common import ContractValidationError, require_id
from qec.surface_code import SurfaceCodeLayout


@dataclass(frozen=True, slots=True)
class LogicalQubitBlock:
    block_id: str
    logical_qubit_id: str
    layout: SurfaceCodeLayout

    def __post_init__(self) -> None:
        require_id(self.block_id, "block_id")
        require_id(self.logical_qubit_id, "logical_qubit_id")
        if not isinstance(self.layout, SurfaceCodeLayout):
            raise ContractValidationError("layout must be a SurfaceCodeLayout")

    def physical_site_id(self, local_site_id: str) -> str:
        require_id(local_site_id, "local_site_id")
        if local_site_id not in {site.site_id for site in self.layout.sites}:
            raise ContractValidationError(f"unknown site {local_site_id!r} in block {self.block_id!r}")
        return f"{self.block_id}/{local_site_id}"

