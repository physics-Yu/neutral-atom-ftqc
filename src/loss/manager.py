"""Loss policy and finite reservoir allocation; no scheduling logic lives here."""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts.common import ContractValidationError
from contracts.events import AtomRole, ObservationBatch, ObservationKind
from hardware.hardware_state import MachineState
from hardware.zones import NeutralAtomTarget
from loss.contracts import (
    RecoveryPlan, RecoveryRequest, RecoveryStatus, ReservoirAllocation,
)


@dataclass(slots=True)
class LossManager:
    target: NeutralAtomTarget
    _plans_by_event: dict[str, RecoveryPlan] = field(default_factory=dict, init=False)
    _reserved_atoms: set[str] = field(default_factory=set, init=False)

    def process_observations(
        self, batch: ObservationBatch, state: MachineState,
    ) -> tuple[RecoveryPlan, ...]:
        plans: list[RecoveryPlan] = []
        for observation in batch.observations:
            if observation.kind is not ObservationKind.ATOM_LOSS:
                continue
            if observation.event_id in self._plans_by_event:
                plans.append(self._plans_by_event[observation.event_id])
                continue
            request = RecoveryRequest.from_observation(observation)
            site = state.sites.get(request.site_id)
            if site is None or site.block_id != request.block_id or site.role is not request.atom_role:
                raise ContractValidationError("loss observation does not match machine-state site identity")
            if not site.known_erasure or site.atom_id is not None:
                raise ContractValidationError("loss observation must reference a vacant known erasure")
            available = sorted(
                atom.atom_id for atom in state.atoms.values()
                if atom.present and atom.role is AtomRole.RESERVOIR
                and atom.zone_id == self.target.bindings.reservoir_zone_id
                and atom.atom_id not in self._reserved_atoms
            )
            if available:
                replacement = available[0]
                self._reserved_atoms.add(replacement)
                allocation = ReservoirAllocation(
                    f"allocation-{observation.event_id}", observation.event_id,
                    replacement, observation.observed_at_ns,
                )
                plan = RecoveryPlan(
                    f"recovery-{observation.event_id}", request,
                    RecoveryStatus.READY, allocation,
                )
            else:
                plan = RecoveryPlan(
                    f"recovery-{observation.event_id}", request,
                    RecoveryStatus.RESERVOIR_EXHAUSTED,
                )
            self._plans_by_event[observation.event_id] = plan
            plans.append(plan)
        return tuple(plans)

