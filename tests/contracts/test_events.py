from __future__ import annotations

import pytest

from contracts import ContractValidationError
from contracts.events import AtomRole, Observation, ObservationBatch, ObservationKind


def test_observation_batch_round_trip_preserves_erasure_information() -> None:
    event = Observation(
        "loss-1", ObservationKind.ATOM_LOSS, 50, "image-1",
        {"atom_id": "a7", "block_id": "L0", "site_id": "d2", "atom_role": AtomRole.DATA.value},
    )
    batch = ObservationBatch("run-1", "batch-1", 50, (event,))
    assert ObservationBatch.from_json(batch.to_json()) == batch


def test_atom_loss_requires_explicit_identity_role_and_location() -> None:
    with pytest.raises(ContractValidationError, match="missing"):
        Observation("loss", ObservationKind.ATOM_LOSS, 1, "image", {"atom_id": "a"})


def test_duplicate_events_and_time_travel_are_rejected() -> None:
    event = Observation("e", ObservationKind.MEASUREMENT, 5, "measure", {"bit": 0})
    with pytest.raises(ContractValidationError, match="unique"):
        ObservationBatch("run", "batch", 5, (event, event))
    with pytest.raises(ContractValidationError, match="cannot precede"):
        ObservationBatch("run", "batch", 4, (event,))

