"""Lower one reservoir allocation into physical refill primitives."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from compiler.physical_ir import (
    PhysicalInstruction, PhysicalOpcode, PhysicalTask, ResourceDemand,
    ResourceMode, ZoneDemand,
)
from contracts.common import ContractValidationError
from hardware.zones import NeutralAtomTarget
from loss.contracts import RecoveryPlan, RecoveryStatus


def build_refill_tasks(plan: RecoveryPlan, target: NeutralAtomTarget) -> tuple[PhysicalTask, ...]:
    if plan.status is not RecoveryStatus.READY or plan.allocation is None:
        raise ContractValidationError("only a ready recovery plan can produce refill tasks")
    request = plan.request
    replacement = plan.allocation.replacement_atom_id
    if request.block_id == "" or request.site_id == "":  # contract exhaustiveness guard
        raise ContractValidationError("recovery identity is incomplete")
    trajectory = target.geometry.trajectory(
        target.bindings.reservoir_zone_id, target.bindings.storage_zone_id,
    )
    stem = plan.plan_id
    place_id = f"{stem}-place"
    place = PhysicalTask(
        place_id,
        PhysicalInstruction(PhysicalOpcode.PLACE_ATOM, (replacement, request.site_id), {
            "destination_site_id": request.site_id,
            "profile": "erasure-refill-v0.1",
            "trajectory_id": trajectory.trajectory_id,
            "source_zone_id": target.bindings.reservoir_zone_id,
            "destination_zone_id": target.bindings.storage_zone_id,
        }),
        earliest_start_ns=request.detected_at_ns,
        resource_demands=(
            ResourceDemand(target.bindings.transport_resource_id, mode=ResourceMode.SHARED),
            *(ResourceDemand(item, mode=ResourceMode.SHARED) for item in trajectory.conflict_group_ids),
        ),
        zone_ids=(target.bindings.reservoir_zone_id, target.bindings.storage_zone_id),
        duration_ns=trajectory.duration_ns,
        zone_demands=(
            ZoneDemand(target.bindings.reservoir_zone_id, 1),
            ZoneDemand(target.bindings.storage_zone_id, 1),
        ),
    )
    reset_id = f"{stem}-reset"
    reset = PhysicalTask(
        reset_id,
        PhysicalInstruction(PhysicalOpcode.RESET_ATOMS, (replacement,), {
            "state": "zero", "profile": "replacement-reset-v0.1",
            "purpose": f"{request.atom_role.value}-loss-replacement",
        }),
        predecessors=(place_id,), resource_demands=(
            ResourceDemand(target.bindings.reset_resource_id, mode=ResourceMode.SHARED),
        ), zone_ids=(target.bindings.storage_zone_id,),
        zone_demands=(ZoneDemand(target.bindings.storage_zone_id, 1),),
    )
    image_id = f"{stem}-verify"
    verify = PhysicalTask(
        image_id,
        PhysicalInstruction(PhysicalOpcode.IMAGE_ATOMS, (replacement,), {
            "profile": "replacement-presence-v0.1",
        }),
        predecessors=(reset_id,), resource_demands=(
            ResourceDemand(target.bindings.imaging_resource_id, mode=ResourceMode.SHARED),
        ), zone_ids=(target.bindings.storage_zone_id,),
        zone_demands=(ZoneDemand(target.bindings.storage_zone_id, 1),),
    )
    return place, reset, verify


def retarget_replaced_atoms(
    tasks: tuple[PhysicalTask, ...], replacements: Mapping[str, str],
) -> tuple[PhysicalTask, ...]:
    """Rewrite future physical operands/metadata to allocated atom identities."""

    if not replacements:
        return tasks

    def rewrite(value: Any) -> Any:
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, tuple):
            return tuple(rewrite(item) for item in value)
        if isinstance(value, Mapping):
            return {key: rewrite(item) for key, item in value.items()}
        return value

    return tuple(replace(
        task,
        instruction=PhysicalInstruction(
            task.instruction.opcode,
            tuple(replacements.get(item, item) for item in task.instruction.operands),
            rewrite(task.instruction.parameters),
        ),
    ) for task in tasks)

