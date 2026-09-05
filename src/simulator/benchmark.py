"""Small reproducible M8 ensemble runner and statistical summaries."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from compiler.physical_ir import PhysicalTaskGraph
from contracts.common import (
    ContractValidationError, canonical_json, parse_json, require_id, to_primitive,
)
from hardware.hardware_state import MachineState
from hardware.zones import NeutralAtomTarget
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest
from simulator.executor import DigitalTwinExecutor, ExecutionResult
from simulator.noise import NoiseConfig, NoiseEventKind, SeededNoiseModel


@dataclass(frozen=True, slots=True)
class ShotMetrics:
    run_id: str
    seed: int
    noise_event_count: int
    pauli_fault_count: int
    measurement_flip_count: int
    syndrome_flip_count: int
    atom_loss_count: int
    final_known_erasures: int

    def __post_init__(self) -> None:
        require_id(self.run_id, "shot run ID")
        values = (
            self.seed, self.noise_event_count, self.pauli_fault_count,
            self.measurement_flip_count, self.syndrome_flip_count,
            self.atom_loss_count, self.final_known_erasures,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            raise ContractValidationError("shot metrics must be non-negative integers")


@dataclass(frozen=True, slots=True)
class ExperimentSummary:
    noise_config_id: str
    parameter_source: str
    graph_id: str
    graph_revision: int
    schedule_makespan_ns: int
    shots: tuple[ShotMetrics, ...]

    def __post_init__(self) -> None:
        for value, name in (
            (self.noise_config_id, "summary noise config ID"),
            (self.parameter_source, "summary parameter source"),
            (self.graph_id, "summary graph ID"),
        ):
            require_id(value, name)
        if not self.shots:
            raise ContractValidationError("experiment summary requires at least one shot")

    @property
    def total_noise_events(self) -> int:
        return sum(item.noise_event_count for item in self.shots)

    @property
    def runs_with_loss(self) -> int:
        return sum(item.atom_loss_count > 0 for item in self.shots)

    @property
    def mean_noise_events(self) -> float:
        return mean(item.noise_event_count for item in self.shots)

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_json(cls, payload: str) -> "ExperimentSummary":
        data = parse_json(payload)
        return cls(
            data["noise_config_id"], data["parameter_source"], data["graph_id"],
            data["graph_revision"], data["schedule_makespan_ns"],
            tuple(ShotMetrics(**item) for item in data["shots"]),
        )


def run_noise_ensemble(
    graph: PhysicalTaskGraph,
    target: NeutralAtomTarget,
    initial_state: MachineState,
    config: NoiseConfig,
    seeds: tuple[int, ...],
    *,
    run_prefix: str = "noise-shot",
) -> tuple[tuple[ExecutionResult, ...], ExperimentSummary]:
    if not seeds or len(seeds) != len(set(seeds)):
        raise ContractValidationError("ensemble seeds must be non-empty and unique")
    schedule = schedule_physical_tasks(ScheduleRequest(
        f"{run_prefix}-schedule", graph, target.machine,
    ))
    results = tuple(
        DigitalTwinExecutor(
            target, noise_model=SeededNoiseModel(config, seed),
        ).execute(f"{run_prefix}-{seed}", graph, schedule, initial_state)
        for seed in seeds
    )
    shots = tuple(
        ShotMetrics(
            result.trace.run_id, result.noise_report.seed,
            len(result.noise_report.events),
            result.noise_report.count(NoiseEventKind.PAULI_FAULT),
            result.noise_report.count(NoiseEventKind.MEASUREMENT_FLIP),
            result.noise_report.count(NoiseEventKind.SYNDROME_FLIP),
            result.noise_report.count(NoiseEventKind.ATOM_LOSS),
            sum(site.known_erasure for site in result.final_state.sites.values()),
        )
        for result in results
    )
    return results, ExperimentSummary(
        config.config_id, config.parameter_source, graph.graph_id, graph.revision,
        schedule.makespan_ns, shots,
    )

