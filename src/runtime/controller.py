"""Coordinate observations, decoding, Pauli frames, and release conditions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from compiler.physical_ir import (
    ConditionRef, PhysicalInstruction, PhysicalOpcode, PhysicalTask,
    PhysicalTaskGraph, ResourceDemand, ResourceMode, ZoneDemand,
)
from contracts.common import ContractValidationError, frozen_mapping, require_id
from contracts.events import ObservationBatch
from decoder.decoder import Decoder, DecoderInput, DecoderResult, PauliFrameDelta
from decoder.syndrome import SyndromeHistory
from hardware.zones import NeutralAtomTarget
from qec.pauli_frame import PauliFrame, PhysicalPauliFrame
from qec.surface_code import SurfaceCodeLayout


@dataclass(frozen=True, slots=True)
class RuntimeFeedback:
    feedback_id: str
    decoder_result: DecoderResult
    condition_message_id: str
    available_at_ns: int

    def __post_init__(self) -> None:
        require_id(self.feedback_id, "runtime feedback ID")
        require_id(self.condition_message_id, "runtime condition message ID")
        if not isinstance(self.decoder_result, DecoderResult):
            raise ContractValidationError("runtime feedback requires a DecoderResult")
        if self.available_at_ns != self.decoder_result.completed_at_ns:
            raise ContractValidationError("feedback availability must equal decoder completion")


@dataclass(frozen=True, slots=True)
class RuntimeCycleResult:
    feedbacks: tuple[RuntimeFeedback, ...]
    logical_frame: PauliFrame
    physical_frame: PhysicalPauliFrame
    condition_snapshot: Mapping[str, bool]
    ready_at_ns: int

    def __post_init__(self) -> None:
        if not self.feedbacks:
            raise ContractValidationError("runtime cycle requires decoder feedback")
        expected = {item.condition_message_id for item in self.feedbacks}
        if set(self.condition_snapshot) != expected or not all(self.condition_snapshot.values()):
            raise ContractValidationError("runtime condition snapshot must release every feedback")
        if self.ready_at_ns != max(item.available_at_ns for item in self.feedbacks):
            raise ContractValidationError("runtime ready time must be the latest decoder completion")
        object.__setattr__(self, "condition_snapshot", frozen_mapping(self.condition_snapshot))


@dataclass(slots=True)
class RuntimeController:
    decoder: Decoder

    def process_syndrome_batch(
        self,
        batch: ObservationBatch,
        layouts_by_block: Mapping[str, SurfaceCodeLayout],
        logical_frame: PauliFrame,
        physical_frame: PhysicalPauliFrame | None = None,
        *,
        history_window: int = 2,
    ) -> RuntimeCycleResult:
        history = SyndromeHistory.from_observation_batch(batch)
        if not history.samples:
            raise ContractValidationError("runtime batch contains no syndrome observations")
        physical = physical_frame or PhysicalPauliFrame()
        logical = logical_frame
        feedbacks: list[RuntimeFeedback] = []
        block_ids = tuple(dict.fromkeys(item.block_id for item in history.samples))
        for block_id in block_ids:
            if block_id not in layouts_by_block:
                raise ContractValidationError(f"missing surface-code layout for {block_id!r}")
            block_history = history.for_block(block_id, last_rounds=history_window)
            latest = block_history.samples[-1]
            decoder_input = DecoderInput(
                f"decoder-{batch.run_id}-{block_id}-r{latest.round_index}",
                layouts_by_block[block_id], block_history, logical,
            )
            result = self.decoder.decode(decoder_input)
            logical, physical = apply_pauli_frame_delta(logical, physical, result.frame_delta)
            message_id = f"decoder-ready:{decoder_input.input_id}"
            feedbacks.append(RuntimeFeedback(
                f"feedback-{decoder_input.input_id}", result, message_id,
                result.completed_at_ns,
            ))
        snapshot = {item.condition_message_id: True for item in feedbacks}
        return RuntimeCycleResult(
            tuple(feedbacks), logical, physical, snapshot,
            max(item.available_at_ns for item in feedbacks),
        )

    @staticmethod
    def build_feedback_barrier(cycle: RuntimeCycleResult, target: NeutralAtomTarget) -> PhysicalTaskGraph:
        """Build a physical continuation released only after decoder latency."""

        task = PhysicalTask(
            task_id="runtime-decoder-feedback-sync",
            instruction=PhysicalInstruction(
                PhysicalOpcode.EMIT_SYNC, (),
                {"tag": "decoder-feedback-ready", "channel": "runtime"},
            ),
            earliest_start_ns=cycle.ready_at_ns,
            resource_demands=(ResourceDemand(target.bindings.clock_resource_id, mode=ResourceMode.SHARED),),
            zone_ids=(target.bindings.storage_zone_id,),
            conditions=tuple(ConditionRef(item.condition_message_id) for item in cycle.feedbacks),
            duration_ns=target.machine.calibration.duration_by_opcode_ns[PhysicalOpcode.EMIT_SYNC.value],
            zone_demands=(ZoneDemand(target.bindings.storage_zone_id, 1),),
        )
        graph = PhysicalTaskGraph("runtime-decoder-feedback", 0, (task,))
        graph.validate_against_machine(target.machine)
        return graph


def apply_pauli_frame_delta(
    logical: PauliFrame, physical: PhysicalPauliFrame, delta: PauliFrameDelta,
) -> tuple[PauliFrame, PhysicalPauliFrame]:
    logical = logical.updated(
        delta.logical_qubit_id, x=delta.logical_x, z=delta.logical_z,
    )
    for correction in delta.physical_corrections:
        physical = physical.updated(
            correction.block_id, correction.site_id,
            x=correction.pauli.value in {"X", "Y"},
            z=correction.pauli.value in {"Z", "Y"},
        )
    return logical, physical

