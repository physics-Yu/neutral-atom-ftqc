"""Digital-twin execution and replayable trace contracts."""

from .benchmark import ExperimentSummary, ShotMetrics, run_noise_ensemble
from .executor import DeterministicIdealBackend, DigitalTwinExecutor, ExecutionResult
from .experiment import run_experiment
from .noise import (
    DeterministicLossModel, LossInjection, LossModel, NoiseConfig, NoiseEvent,
    NoiseEventKind, NoiseReport, NoLossModel, NoNoiseModel, SeededNoiseModel,
)

__all__ = [
    "DeterministicIdealBackend", "DeterministicLossModel", "DigitalTwinExecutor",
    "ExecutionResult", "ExperimentSummary", "LossInjection", "LossModel",
    "NoiseConfig", "NoiseEvent", "NoiseEventKind", "NoiseReport", "NoLossModel",
    "NoNoiseModel", "SeededNoiseModel", "ShotMetrics", "run_experiment",
    "run_noise_ensemble",
]

