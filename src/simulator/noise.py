"""Deterministic M7 atom-loss injection hooks.

Stochastic physics remains an M8 concern. M7 injections are named, replayable,
and fire immediately before one selected physical task starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from contracts.common import ContractValidationError, require_id


@dataclass(frozen=True, slots=True)
class LossInjection:
    injection_id: str
    trigger_task_id: str
    atom_id: str

    def __post_init__(self) -> None:
        require_id(self.injection_id, "loss injection ID")
        require_id(self.trigger_task_id, "loss trigger task ID")
        require_id(self.atom_id, "loss atom ID")


class LossModel(Protocol):
    def losses_at_task_start(self, task_id: str) -> tuple[LossInjection, ...]: ...


@dataclass(slots=True)
class NoLossModel:
    def losses_at_task_start(self, task_id: str) -> tuple[LossInjection, ...]:
        return ()


@dataclass(slots=True)
class DeterministicLossModel:
    injections: tuple[LossInjection, ...]
    _fired: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        if any(not isinstance(item, LossInjection) for item in self.injections):
            raise ContractValidationError("deterministic loss entries must be LossInjection values")
        ids = [item.injection_id for item in self.injections]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("loss injection IDs must be unique")

    def losses_at_task_start(self, task_id: str) -> tuple[LossInjection, ...]:
        require_id(task_id, "loss trigger task ID")
        result = tuple(
            item for item in self.injections
            if item.trigger_task_id == task_id and item.injection_id not in self._fired
        )
        self._fired.update(item.injection_id for item in result)
        return result

