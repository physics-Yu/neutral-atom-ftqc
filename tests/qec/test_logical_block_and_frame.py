from __future__ import annotations

import pytest

from contracts import ContractValidationError
from qec.logical_qubit import LogicalQubitBlock
from qec.pauli_frame import PauliFrame
from qec.surface_code import SurfaceCodeSpec, generate_surface_code_layout


def test_logical_block_qualifies_local_site_identity() -> None:
    block = LogicalQubitBlock("block-L0", "L0", generate_surface_code_layout(SurfaceCodeSpec(3)))
    assert block.physical_site_id("data-r0-c0") == "block-L0/data-r0-c0"
    with pytest.raises(ContractValidationError, match="unknown site"):
        block.physical_site_id("missing")


def test_pauli_frame_updates_compose_without_mutating_original() -> None:
    identity = PauliFrame.identity(("L0", "L1"))
    x_frame = identity.updated("L0", x=True)
    identity_again = x_frame.updated("L0", x=True)
    assert identity.get("L0").x is False
    assert x_frame.get("L0").x is True
    assert identity_again.get("L0").x is False
    with pytest.raises(ContractValidationError, match="unknown logical qubit"):
        identity.updated("L9", z=True)

