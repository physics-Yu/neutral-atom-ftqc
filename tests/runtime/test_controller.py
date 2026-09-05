from __future__ import annotations

import pytest

from contracts.events import Observation, ObservationBatch, ObservationKind
from decoder.decoder import (
    DecoderStatus, IdealSingleErrorDecoder, PauliFrameDelta, PhysicalCorrection,
)
from decoder.syndrome import PauliError, simulate_single_pauli_syndrome
from examples.ghz_surface_code import build_profile_target, run_ghz_qec_cycle
from qec.pauli_frame import PauliFrame, PhysicalPauliFrame
from qec.surface_code import SurfaceCodeSpec, generate_surface_code_layout
from runtime.controller import RuntimeController, apply_pauli_frame_delta
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest, UnscheduledReason


@pytest.mark.parametrize("distance", [3, 5])
def test_ideal_ghz_syndrome_closes_decoder_feedback_loop(distance: int) -> None:
    execution, cycle, release = run_ghz_qec_cycle(distance, syndrome_rounds=1)
    syndromes = [item for item in execution.observations.observations if item.kind.value == "syndrome"]

    assert len(syndromes) == len(cycle.feedbacks) == 4
    assert all(not any(item.payload["bits"].values()) for item in syndromes)
    assert {item.decoder_result.status for item in cycle.feedbacks} == {DecoderStatus.CLEAN}
    assert cycle.physical_frame == PhysicalPauliFrame()
    assert release.unscheduled == ()
    assert release.entries[0].start_ns >= execution.trace.ended_at_ns
    assert release.entries[0].start_ns >= cycle.ready_at_ns


def test_feedback_barrier_remains_blocked_without_decoder_messages() -> None:
    _, cycle, _ = run_ghz_qec_cycle(3)
    target = build_profile_target("low")
    graph = RuntimeController.build_feedback_barrier(cycle, target)
    blocked = schedule_physical_tasks(ScheduleRequest("blocked", graph, target.machine))
    assert blocked.unscheduled[0].reason is UnscheduledReason.CONDITION_BLOCKED


def test_single_error_feedback_composes_in_sparse_physical_pauli_frame() -> None:
    layout = generate_surface_code_layout(SurfaceCodeSpec(3))
    sample = simulate_single_pauli_syndrome(
        layout, "block-L0", "L0", "data-r1-c1", PauliError.X,
        observed_at_ns=100,
    )
    observation = Observation(
        "syndrome", ObservationKind.SYNDROME, 100, "measure",
        {
            "block_id": sample.block_id, "logical_qubit_id": sample.logical_qubit_id,
            "layout_id": sample.layout_id, "round_index": sample.round_index,
            "bits": dict(sample.bits),
        },
    )
    batch = ObservationBatch("single-error", "batch", 100, (observation,))
    controller = RuntimeController(IdealSingleErrorDecoder())
    first = controller.process_syndrome_batch(
        batch, {"block-L0": layout}, PauliFrame.identity(("L0",)),
    )
    assert first.feedbacks[0].decoder_result.status is DecoderStatus.CORRECTED
    assert first.physical_frame.get("block-L0", "data-r1-c1").x is True
    assert first.logical_frame.get("L0").x is False

    second = controller.process_syndrome_batch(
        batch, {"block-L0": layout}, first.logical_frame, first.physical_frame,
    )
    assert second.physical_frame == PhysicalPauliFrame()


def test_logical_and_physical_frame_delta_compose_without_physical_gate() -> None:
    logical, physical = apply_pauli_frame_delta(
        PauliFrame.identity(("L0",)), PhysicalPauliFrame(),
        PauliFrameDelta(
            "L0", logical_z=True,
            physical_corrections=(PhysicalCorrection("block-L0", "data-r1-c1", PauliError.Y),),
        ),
    )
    assert logical.get("L0").z is True
    assert physical.get("block-L0", "data-r1-c1").x is True
    assert physical.get("block-L0", "data-r1-c1").z is True

