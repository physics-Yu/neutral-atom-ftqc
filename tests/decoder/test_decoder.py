from __future__ import annotations

import pytest

from contracts import ContractValidationError
from decoder.decoder import (
    DecoderInput, DecoderResult, DecoderStatus, IdealErasureAwareDecoder,
    IdealSingleErrorDecoder,
)
from decoder.syndrome import (
    PauliError, SyndromeHistory, SyndromeSample, simulate_single_pauli_syndrome,
)
from qec.pauli_frame import PauliFrame
from qec.surface_code import SurfaceCodeSpec, generate_surface_code_layout


def _input(distance: int, site_id: str, error: PauliError) -> DecoderInput:
    layout = generate_surface_code_layout(SurfaceCodeSpec(distance))
    sample = simulate_single_pauli_syndrome(layout, "block-L0", "L0", site_id, error, observed_at_ns=100)
    return DecoderInput("decode-L0", layout, SyndromeHistory((sample,)), PauliFrame.identity(("L0",)))


@pytest.mark.parametrize("distance,site_id,error", [
    (3, "data-r1-c1", PauliError.X),
    (3, "data-r1-c1", PauliError.Z),
    (5, "data-r2-c2", PauliError.Y),
])
def test_reference_decoder_corrects_unique_single_pauli_signatures(distance: int, site_id: str, error: PauliError) -> None:
    result = IdealSingleErrorDecoder(latency_ns=30_000).decode(_input(distance, site_id, error))
    assert result.status is DecoderStatus.CORRECTED
    assert result.frame_delta.physical_corrections[0].site_id == site_id
    assert result.frame_delta.physical_corrections[0].pauli is error
    assert result.started_at_ns == 100
    assert result.completed_at_ns == 30_100
    assert DecoderResult.from_json(result.to_json()) == result


def test_history_window_uses_detection_event_between_rounds() -> None:
    layout = generate_surface_code_layout(SurfaceCodeSpec(3))
    error = simulate_single_pauli_syndrome(layout, "block-L0", "L0", "data-r1-c1", PauliError.X, round_index=0, observed_at_ns=10)
    repeated = simulate_single_pauli_syndrome(layout, "block-L0", "L0", "data-r1-c1", PauliError.X, round_index=1, observed_at_ns=20)
    history = SyndromeHistory((error, repeated))
    result = IdealSingleErrorDecoder().decode(DecoderInput("history", layout, history, PauliFrame.identity(("L0",))))
    assert result.status is DecoderStatus.CLEAN
    assert history.for_block("block-L0", last_rounds=1).samples == (repeated,)


def test_known_erasure_is_not_guessed_by_single_error_decoder() -> None:
    decoder_input = _input(3, "data-r1-c1", PauliError.X)
    erased = DecoderInput(
        decoder_input.input_id, decoder_input.layout, decoder_input.history,
        decoder_input.pauli_frame, ("data-r1-c1",),
    )
    assert IdealSingleErrorDecoder().decode(erased).status is DecoderStatus.NEEDS_RECOVERY


def test_ambiguous_boundary_signature_is_reported_without_guessing() -> None:
    result = IdealSingleErrorDecoder().decode(_input(3, "data-r0-c0", PauliError.Z))
    assert result.status is DecoderStatus.AMBIGUOUS
    assert result.frame_delta.physical_corrections == ()
    assert result.diagnostics["candidate_count"] == 2


def test_decoder_rejects_incomplete_check_history() -> None:
    decoder_input = _input(3, "data-r1-c1", PauliError.X)
    sample = decoder_input.history.samples[0]
    incomplete = type(sample)(
        sample.block_id, sample.logical_qubit_id, sample.layout_id,
        sample.round_index, sample.observed_at_ns,
        {next(iter(sample.bits)): 1}, sample.source_event_id,
    )
    with pytest.raises(ContractValidationError, match="every layout check"):
        DecoderInput("bad", decoder_input.layout, SyndromeHistory((incomplete,)), decoder_input.pauli_frame)


def test_erasure_aware_decoder_recovers_one_known_clean_erasure() -> None:
    layout = generate_surface_code_layout(SurfaceCodeSpec(3))
    sample = SyndromeSample(
        "block-L0", "L0", layout.layout_id, 0, 100,
        {check.check_id: 0 for check in layout.stabilizers}, "syndrome-clean",
    )
    result = IdealErasureAwareDecoder().decode(DecoderInput(
        "erasure", layout, SyndromeHistory((sample,)),
        PauliFrame.identity(("L0",)), ("data-r1-c1",),
    ))
    assert result.status is DecoderStatus.RECOVERED
    assert result.diagnostics["recovered_erasure_sites"] == ("data-r1-c1",)


def test_erasure_aware_decoder_refuses_distance_many_erasures() -> None:
    layout = generate_surface_code_layout(SurfaceCodeSpec(3))
    sample = SyndromeSample(
        "block-L0", "L0", layout.layout_id, 0, 100,
        {check.check_id: 0 for check in layout.stabilizers}, "syndrome-many",
    )
    result = IdealErasureAwareDecoder().decode(DecoderInput(
        "erasure", layout, SyndromeHistory((sample,)),
        PauliFrame.identity(("L0",)),
        ("data-r0-c0", "data-r0-c1", "data-r0-c2"),
    ))
    assert result.status is DecoderStatus.UNCORRECTABLE

