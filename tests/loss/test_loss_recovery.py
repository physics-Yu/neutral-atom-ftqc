from __future__ import annotations

import pytest

from compiler.physical_ir import PhysicalTaskGraph
from contracts.events import AtomRole, Observation, ObservationBatch, ObservationKind
from examples.ghz_surface_code import (
    build_ghz_qec_protocol, build_profile_target, run_ghz_loss_recovery,
)
from hardware.hardware_state import MachineState
from loss import LossManager, RecoveryPlan, RecoveryStatus, build_refill_tasks
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest
from simulator.executor import DigitalTwinExecutor


@pytest.mark.parametrize("distance", [3, 5])
def test_deterministic_data_loss_closes_refill_qec_decoder_loop(distance: int) -> None:
    run = run_ghz_loss_recovery(distance)
    kinds = [item.kind for item in run.detection.observations.observations]

    assert kinds[-2:] == [ObservationKind.ATOM_PRESENCE, ObservationKind.ATOM_LOSS]
    assert run.detection.observations.observations[-2].payload["present"] is False
    assert run.plan.request.atom_role is AtomRole.DATA
    assert run.reschedule.graph.revision == 2
    assert run.reschedule.schedule.unscheduled == ()
    assert all(
        entry.start_ns >= run.detection.trace.ended_at_ns
        for entry in run.reschedule.schedule.entries
    )
    # The physical recovery trace ends with the erasure still known. Only the
    # later decoder decision mutates the returned machine state to resolved.
    assert run.recovery.trace.snapshots[-1].known_erasures == 1
    assert run.resolved_site_ids == ("block-L2/data-r1-c1",)
    site = run.recovery.final_state.sites[run.resolved_site_ids[0]]
    assert site.known_erasure is False
    assert run.recovery.final_state.atoms[site.atom_id].role is AtomRole.DATA


def test_refill_without_qec_and_decoder_does_not_clear_data_erasure() -> None:
    source = run_ghz_loss_recovery(3)
    state = source.detection.final_state.clone()
    target = build_profile_target("low")
    tasks = build_refill_tasks(source.plan, target)
    graph = PhysicalTaskGraph("refill-only", 0, tasks)
    schedule = schedule_physical_tasks(ScheduleRequest(
        "refill-only", graph, target.machine, not_before_ns=state.now_ns,
    ))
    result = DigitalTwinExecutor(target).execute("refill-only", graph, schedule, state)

    site = result.final_state.sites[source.plan.request.site_id]
    assert site.atom_id == source.plan.allocation.replacement_atom_id
    assert site.known_erasure is True
    assert result.trace.snapshots[-1].known_erasures == 1


def test_loss_manager_is_idempotent_and_reports_finite_reservoir_exhaustion() -> None:
    target = build_profile_target("low")
    protocol = build_ghz_qec_protocol(3)
    state = MachineState.from_protocol(protocol, target)
    atom_id = "block-L0/data-r1-c1"
    state.mark_atom_lost(atom_id)
    observation = Observation(
        "loss-no-spare", ObservationKind.ATOM_LOSS, 10, "image",
        {
            "atom_id": atom_id, "block_id": "block-L0", "site_id": atom_id,
            "atom_role": "data",
        },
    )
    batch = ObservationBatch("loss", "loss-batch", 10, (observation,))
    manager = LossManager(target)

    first = manager.process_observations(batch, state)
    second = manager.process_observations(batch, state)
    assert first == second
    assert first[0].status is RecoveryStatus.RESERVOIR_EXHAUSTED
    assert RecoveryPlan.from_json(first[0].to_json()) == first[0]


def test_ancilla_replacement_reset_resolves_without_data_qec_claim() -> None:
    target = build_profile_target("low")
    protocol = build_ghz_qec_protocol(3)
    state = MachineState.from_protocol(protocol, target)
    ancilla_id = next(
        site_id for site_id in state.blocks["block-L0"].site_ids
        if state.sites[site_id].role is AtomRole.ANCILLA
    )
    state.mark_atom_lost(ancilla_id)
    state.add_reservoir_atom("ancilla-spare", target)
    observation = Observation(
        "ancilla-loss", ObservationKind.ATOM_LOSS, 10, "image",
        {
            "atom_id": ancilla_id, "block_id": "block-L0", "site_id": ancilla_id,
            "atom_role": "ancilla",
        },
    )
    batch = ObservationBatch("ancilla", "ancilla-batch", 10, (observation,))
    plan = LossManager(target).process_observations(batch, state)[0]
    assert plan.request.requires_qec is False
    tasks = build_refill_tasks(plan, target)
    graph = PhysicalTaskGraph("ancilla-refill", 0, tasks)
    schedule = schedule_physical_tasks(ScheduleRequest("ancilla-refill", graph, target.machine))
    result = DigitalTwinExecutor(target).execute("ancilla-refill", graph, schedule, state)

    assert result.final_state.sites[ancilla_id].known_erasure is False
    assert result.final_state.atoms["ancilla-spare"].role is AtomRole.ANCILLA

