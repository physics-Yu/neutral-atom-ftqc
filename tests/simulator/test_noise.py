from __future__ import annotations

from compiler.lowering.neutral_atom import lower_to_neutral_atom_tasks
from examples.ghz_surface_code import (
    build_ghz_noise_graph, build_ghz_qec_protocol, build_profile_target,
)
from hardware.hardware_state import MachineState
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest
from simulator.benchmark import ExperimentSummary, run_noise_ensemble
from simulator.executor import DigitalTwinExecutor
from simulator.noise import (
    NoiseConfig, NoiseEventKind, NoiseReport, SeededNoiseModel,
)


def _illustrative(**overrides: float) -> NoiseConfig:
    values = {
        "config_id": "test-noise-v0.1",
        "parameter_source": "synthetic test parameters",
        **overrides,
    }
    return NoiseConfig(**values)


def test_zero_noise_preserves_ideal_trace_and_observations() -> None:
    target, _, graph, state = build_ghz_noise_graph(3)
    schedule = schedule_physical_tasks(ScheduleRequest("ideal-noise", graph, target.machine))
    baseline = DigitalTwinExecutor(target).execute("ideal", graph, schedule, state)
    explicit = DigitalTwinExecutor(
        target, noise_model=SeededNoiseModel(NoiseConfig.ideal(), 0),
    ).execute("ideal", graph, schedule, state)

    assert explicit.trace.to_json() == baseline.trace.to_json()
    assert explicit.observations.to_json() == baseline.observations.to_json()
    assert explicit.noise_report.events == ()


def test_nonzero_noise_is_seed_replayable_and_serializable() -> None:
    target, _, graph, state = build_ghz_noise_graph(3)
    schedule = schedule_physical_tasks(ScheduleRequest("seeded", graph, target.machine))
    config = _illustrative(
        one_qubit_error_probability=0.2,
        two_qubit_error_probability=0.2,
        measurement_flip_probability=0.2,
        syndrome_flip_probability=0.2,
    )
    first = DigitalTwinExecutor(target, noise_model=SeededNoiseModel(config, 91)).execute(
        "seeded", graph, schedule, state,
    )
    second = DigitalTwinExecutor(target, noise_model=SeededNoiseModel(config, 91)).execute(
        "seeded", graph, schedule, state,
    )

    assert first.trace.to_json() == second.trace.to_json()
    assert first.observations.to_json() == second.observations.to_json()
    assert first.noise_report.to_json() == second.noise_report.to_json()
    assert first.noise_report.events
    assert NoiseReport.from_json(first.noise_report.to_json()) == first.noise_report
    assert first.trace.noise_config_id == config.config_id
    assert first.trace.noise_seed == 91


def test_seeded_probability_distribution_has_basic_sanity() -> None:
    config = _illustrative(measurement_flip_probability=0.2)
    flips = sum(
        SeededNoiseModel(config, seed).measurement_flip("measure", "atom", 10) is not None
        for seed in range(1_000)
    )
    assert 150 <= flips <= 250


def test_crosstalk_faults_require_parallel_rydberg_neighbors() -> None:
    protocol = build_ghz_qec_protocol(3)
    low = build_profile_target("low")
    high = build_profile_target("high")
    graph = lower_to_neutral_atom_tasks(protocol, low)
    low_schedule = schedule_physical_tasks(ScheduleRequest("low-x-talk", graph, low.machine))
    high_schedule = schedule_physical_tasks(ScheduleRequest("high-x-talk", graph, high.machine))
    config = _illustrative(rydberg_crosstalk_probability_per_neighbor=1.0)
    low_result = DigitalTwinExecutor(low, noise_model=SeededNoiseModel(config, 1)).execute(
        "low-x-talk", graph, low_schedule, MachineState.from_protocol(protocol, low),
    )
    high_result = DigitalTwinExecutor(high, noise_model=SeededNoiseModel(config, 1)).execute(
        "high-x-talk", graph, high_schedule, MachineState.from_protocol(protocol, high),
    )

    assert low_result.noise_report.count(NoiseEventKind.PAULI_FAULT) == 0
    assert high_result.noise_report.count(NoiseEventKind.PAULI_FAULT) > 0


def test_imaging_boundary_loss_is_explicit_and_finite() -> None:
    target, _, graph, state = build_ghz_noise_graph(3)
    schedule = schedule_physical_tasks(ScheduleRequest("forced-loss", graph, target.machine))
    config = _illustrative(loss_probability_at_imaging=1.0)
    result = DigitalTwinExecutor(target, noise_model=SeededNoiseModel(config, 7)).execute(
        "forced-loss", graph, schedule, state,
    )

    expected = 4 * (2 * 3**2 - 1)
    assert result.noise_report.count(NoiseEventKind.ATOM_LOSS) == expected
    assert sum(site.known_erasure for site in result.final_state.sites.values()) == expected


def test_d5_ensemble_has_stable_schedule_and_summary_round_trip() -> None:
    target, _, graph, state = build_ghz_noise_graph(5, "high")
    results, summary = run_noise_ensemble(
        graph, target, state, NoiseConfig.ideal(), (20, 21), run_prefix="d5-scale",
    )

    assert len(graph.tasks) == 146
    assert len(results) == len(summary.shots) == 2
    assert summary.graph_revision == 1
    assert summary.total_noise_events == 0
    assert ExperimentSummary.from_json(summary.to_json()) == summary

