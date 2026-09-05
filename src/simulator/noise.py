"""Replayable physical-noise contracts and seeded reference model.

M8 parameters are explicit illustrative inputs. They are not laboratory
calibrations and the model is not a full quantum trajectory simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any, Mapping, Protocol

from contracts.common import (
    ContractValidationError, canonical_json, parse_json, require_id, to_primitive,
)


class NoiseEventKind(StrEnum):
    PAULI_FAULT = "pauli_fault"
    MEASUREMENT_FLIP = "measurement_flip"
    SYNDROME_FLIP = "syndrome_flip"
    ATOM_LOSS = "atom_loss"


class PauliFaultKind(StrEnum):
    X = "X"
    Y = "Y"
    Z = "Z"


@dataclass(frozen=True, slots=True)
class NoiseConfig:
    config_id: str
    parameter_source: str
    one_qubit_error_probability: float = 0.0
    two_qubit_error_probability: float = 0.0
    reset_error_probability: float = 0.0
    measurement_flip_probability: float = 0.0
    syndrome_flip_probability: float = 0.0
    loss_probability_at_imaging: float = 0.0
    rydberg_crosstalk_probability_per_neighbor: float = 0.0

    def __post_init__(self) -> None:
        require_id(self.config_id, "noise config ID")
        require_id(self.parameter_source, "noise parameter source")
        for name in (
            "one_qubit_error_probability", "two_qubit_error_probability",
            "reset_error_probability", "measurement_flip_probability",
            "syndrome_flip_probability", "loss_probability_at_imaging",
            "rydberg_crosstalk_probability_per_neighbor",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= value <= 1.0:
                raise ContractValidationError(f"{name} must be a probability in [0, 1]")

    @classmethod
    def ideal(cls) -> "NoiseConfig":
        return cls("ideal-noise-v0.1", "software ideal: all probabilities are zero")

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NoiseConfig":
        return cls(
            config_id=data["config_id"], parameter_source=data["parameter_source"],
            one_qubit_error_probability=data.get("one_qubit_error_probability", 0.0),
            two_qubit_error_probability=data.get("two_qubit_error_probability", 0.0),
            reset_error_probability=data.get("reset_error_probability", 0.0),
            measurement_flip_probability=data.get("measurement_flip_probability", 0.0),
            syndrome_flip_probability=data.get("syndrome_flip_probability", 0.0),
            loss_probability_at_imaging=data.get("loss_probability_at_imaging", 0.0),
            rydberg_crosstalk_probability_per_neighbor=data.get(
                "rydberg_crosstalk_probability_per_neighbor", 0.0,
            ),
        )

    @classmethod
    def from_json(cls, payload: str) -> "NoiseConfig":
        return cls.from_dict(parse_json(payload))


@dataclass(frozen=True, slots=True)
class LossInjection:
    injection_id: str
    trigger_task_id: str
    atom_id: str

    def __post_init__(self) -> None:
        require_id(self.injection_id, "loss injection ID")
        require_id(self.trigger_task_id, "loss trigger task ID")
        require_id(self.atom_id, "loss atom ID")


@dataclass(frozen=True, slots=True)
class NoiseEvent:
    event_id: str
    kind: NoiseEventKind
    occurred_at_ns: int
    task_id: str
    target_id: str
    detail: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.event_id, "noise event ID"), (self.task_id, "noise task ID"),
            (self.target_id, "noise target ID"), (self.detail, "noise event detail"),
        ):
            require_id(value, name)
        if not isinstance(self.kind, NoiseEventKind):
            raise ContractValidationError("noise event kind is invalid")
        if not isinstance(self.occurred_at_ns, int) or isinstance(self.occurred_at_ns, bool) or self.occurred_at_ns < 0:
            raise ContractValidationError("noise event time must be non-negative")


@dataclass(frozen=True, slots=True)
class PauliFault:
    atom_id: str
    pauli: PauliFaultKind
    event: NoiseEvent


@dataclass(frozen=True, slots=True)
class NoiseReport:
    config: NoiseConfig
    seed: int
    events: tuple[NoiseEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.config, NoiseConfig):
            raise ContractValidationError("noise report requires a NoiseConfig")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ContractValidationError("noise seed must be a non-negative integer")
        if any(not isinstance(item, NoiseEvent) for item in self.events):
            raise ContractValidationError("noise report events are invalid")

    def count(self, kind: NoiseEventKind) -> int:
        return sum(item.kind is kind for item in self.events)

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_json(cls, payload: str) -> "NoiseReport":
        data = parse_json(payload)
        return cls(
            NoiseConfig.from_dict(data["config"]), data["seed"],
            tuple(NoiseEvent(
                item["event_id"], NoiseEventKind(item["kind"]),
                item["occurred_at_ns"], item["task_id"], item["target_id"],
                item["detail"],
            ) for item in data.get("events", ())),
        )


class NoiseModel(Protocol):
    config: NoiseConfig
    seed: int

    def losses_at_task_start(
        self, task_id: str, opcode: str = "", atom_ids: tuple[str, ...] = (),
    ) -> tuple[LossInjection, ...]: ...

    def pauli_faults(
        self, task_id: str, opcode: str, atom_ids: tuple[str, ...],
        occurred_at_ns: int, parallel_rydberg_neighbors: int = 0,
    ) -> tuple[PauliFault, ...]: ...

    def measurement_flip(
        self, task_id: str, target_id: str, occurred_at_ns: int,
    ) -> NoiseEvent | None: ...

    def syndrome_flip(
        self, task_id: str, check_id: str, occurred_at_ns: int,
    ) -> NoiseEvent | None: ...


@dataclass(slots=True)
class NoNoiseModel:
    config: NoiseConfig = field(default_factory=NoiseConfig.ideal)
    seed: int = 0

    def losses_at_task_start(self, task_id: str, opcode: str = "", atom_ids: tuple[str, ...] = ()) -> tuple[LossInjection, ...]:
        return ()

    def pauli_faults(self, task_id: str, opcode: str, atom_ids: tuple[str, ...], occurred_at_ns: int, parallel_rydberg_neighbors: int = 0) -> tuple[PauliFault, ...]:
        return ()

    def measurement_flip(self, task_id: str, target_id: str, occurred_at_ns: int) -> NoiseEvent | None:
        return None

    def syndrome_flip(self, task_id: str, check_id: str, occurred_at_ns: int) -> NoiseEvent | None:
        return None


# Backward-compatible M7 name.
NoLossModel = NoNoiseModel
LossModel = NoiseModel


@dataclass(slots=True)
class DeterministicLossModel:
    injections: tuple[LossInjection, ...] = ()
    config: NoiseConfig = field(default_factory=NoiseConfig.ideal, init=False)
    seed: int = 0
    _fired: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        if any(not isinstance(item, LossInjection) for item in self.injections):
            raise ContractValidationError("deterministic loss entries must be LossInjection values")
        ids = [item.injection_id for item in self.injections]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("loss injection IDs must be unique")

    def losses_at_task_start(self, task_id: str, opcode: str = "", atom_ids: tuple[str, ...] = ()) -> tuple[LossInjection, ...]:
        require_id(task_id, "loss trigger task ID")
        result = tuple(
            item for item in self.injections
            if item.trigger_task_id == task_id and item.injection_id not in self._fired
        )
        self._fired.update(item.injection_id for item in result)
        return result

    def pauli_faults(self, task_id: str, opcode: str, atom_ids: tuple[str, ...], occurred_at_ns: int, parallel_rydberg_neighbors: int = 0) -> tuple[PauliFault, ...]:
        return ()

    def measurement_flip(self, task_id: str, target_id: str, occurred_at_ns: int) -> NoiseEvent | None:
        return None

    def syndrome_flip(self, task_id: str, check_id: str, occurred_at_ns: int) -> NoiseEvent | None:
        return None


@dataclass(slots=True)
class SeededNoiseModel:
    config: NoiseConfig
    seed: int
    _lost: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.config, NoiseConfig):
            raise ContractValidationError("seeded noise requires a NoiseConfig")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ContractValidationError("noise seed must be a non-negative integer")

    def losses_at_task_start(self, task_id: str, opcode: str = "", atom_ids: tuple[str, ...] = ()) -> tuple[LossInjection, ...]:
        if opcode != "image_atoms":
            return ()
        result = []
        for atom_id in atom_ids:
            if atom_id not in self._lost and self._hit("loss", task_id, atom_id, self.config.loss_probability_at_imaging):
                self._lost.add(atom_id)
                result.append(LossInjection(f"stochastic-loss-{task_id}-{atom_id}", task_id, atom_id))
        return tuple(result)

    def pauli_faults(
        self, task_id: str, opcode: str, atom_ids: tuple[str, ...],
        occurred_at_ns: int, parallel_rydberg_neighbors: int = 0,
    ) -> tuple[PauliFault, ...]:
        probability = {
            "apply_1q_pulse": self.config.one_qubit_error_probability,
            "apply_2q_rydberg_gate": self.config.two_qubit_error_probability,
            "reset_atoms": self.config.reset_error_probability,
        }.get(opcode, 0.0)
        if opcode == "apply_2q_rydberg_gate" and parallel_rydberg_neighbors:
            crosstalk = self.config.rydberg_crosstalk_probability_per_neighbor
            probability = 1.0 - (1.0 - probability) * (1.0 - crosstalk) ** parallel_rydberg_neighbors
        result: list[PauliFault] = []
        for atom_id in atom_ids:
            if not self._hit("pauli", task_id, atom_id, probability):
                continue
            pauli = tuple(PauliFaultKind)[self._integer("pauli-kind", task_id, atom_id) % 3]
            event = NoiseEvent(
                f"noise-{task_id}-{atom_id}-pauli", NoiseEventKind.PAULI_FAULT,
                occurred_at_ns, task_id, atom_id, pauli.value,
            )
            result.append(PauliFault(atom_id, pauli, event))
        return tuple(result)

    def measurement_flip(self, task_id: str, target_id: str, occurred_at_ns: int) -> NoiseEvent | None:
        if not self._hit("measurement", task_id, target_id, self.config.measurement_flip_probability):
            return None
        return NoiseEvent(
            f"noise-{task_id}-{target_id}-measurement", NoiseEventKind.MEASUREMENT_FLIP,
            occurred_at_ns, task_id, target_id, "classical-bit-flip",
        )

    def syndrome_flip(self, task_id: str, check_id: str, occurred_at_ns: int) -> NoiseEvent | None:
        if not self._hit("syndrome", task_id, check_id, self.config.syndrome_flip_probability):
            return None
        return NoiseEvent(
            f"noise-{task_id}-{check_id}-syndrome", NoiseEventKind.SYNDROME_FLIP,
            occurred_at_ns, task_id, check_id, "reported-check-bit-flip",
        )

    def _hit(self, channel: str, task_id: str, target_id: str, probability: float) -> bool:
        return probability > 0.0 and self._integer(channel, task_id, target_id) / 2**64 < probability

    def _integer(self, channel: str, task_id: str, target_id: str) -> int:
        payload = f"{self.seed}:{self.config.config_id}:{channel}:{task_id}:{target_id}"
        return int.from_bytes(sha256(payload.encode()).digest()[:8], "big")

