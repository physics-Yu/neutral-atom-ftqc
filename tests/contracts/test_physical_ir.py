from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from compiler.physical_ir import (
    PhysicalInstruction, PhysicalOpcode, PhysicalTask, PhysicalTaskGraph,
    ResourceDemand, physical_instruction_from_untrusted,
)
from contracts import CalibrationSnapshot, ContractValidationError, MachineConfig, ResourceSpec, ZoneKind, ZoneSpec


def machine() -> MachineConfig:
    return MachineConfig(
        "m", tuple(ZoneSpec(kind.value, kind, 16) for kind in ZoneKind),
        (ResourceSpec("aod", "transport", 1),),
        CalibrationSnapshot("cal", {"move_atoms": 10}),
    )


def task(task_id: str, predecessors: tuple[str, ...] = ()) -> PhysicalTask:
    return PhysicalTask(
        task_id, PhysicalInstruction(PhysicalOpcode.MOVE_ATOMS, ("a0",), {"target_um": [1, 2]}),
        predecessors=predecessors, resource_demands=(ResourceDemand("aod"),),
        zone_ids=("storage",),
    )


def test_physical_graph_round_trip_and_machine_validation() -> None:
    graph = PhysicalTaskGraph("g", 0, (task("move-1"), task("move-2", ("move-1",))))
    restored = PhysicalTaskGraph.from_json(graph.to_json())
    assert restored == graph
    restored.validate_against_machine(machine())


def test_contracts_are_deeply_immutable() -> None:
    instruction = PhysicalInstruction(
        PhysicalOpcode.MOVE_ATOMS, ("a0",), {"target_um": [1, 2]}
    )
    with pytest.raises(TypeError):
        instruction.parameters["new"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        instruction.parameters["target_um"][0] = 9  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        instruction.operands = ()  # type: ignore[misc]


def test_unknown_dependency_duplicate_id_and_cycle_are_rejected() -> None:
    with pytest.raises(ContractValidationError, match="unknown predecessors"):
        PhysicalTaskGraph("g", 0, (task("a", ("missing",)),))
    duplicate = task("same")
    with pytest.raises(ContractValidationError, match="task IDs"):
        PhysicalTaskGraph("g", 0, (duplicate, duplicate))
    with pytest.raises(ContractValidationError, match="cycle"):
        PhysicalTaskGraph("g", 0, (task("a", ("b",)), task("b", ("a",))))


@pytest.mark.parametrize("opcode", ["logical_cnot", "logical_init", "qec_round", "syndrome_round", "prepare_ghz"])
def test_logical_macros_cannot_cross_physical_boundary(opcode: str) -> None:
    with pytest.raises(ContractValidationError, match="cannot cross"):
        physical_instruction_from_untrusted({"opcode": opcode})


def test_serialized_logical_macro_cannot_enter_a_physical_graph() -> None:
    data = PhysicalTaskGraph("g", 0, (task("move"),)).to_dict()
    data["tasks"][0]["instruction"]["opcode"] = "logical_cnot"
    with pytest.raises(ContractValidationError, match="cannot cross"):
        PhysicalTaskGraph.from_dict(data)


def test_unknown_zone_resource_capacity_and_missing_duration_are_rejected() -> None:
    with pytest.raises(ContractValidationError, match="unknown zones"):
        PhysicalTaskGraph("g", 0, (PhysicalTask("t", PhysicalInstruction(PhysicalOpcode.MOVE_ATOMS), zone_ids=("moon",)),)).validate_against_machine(machine())
    with pytest.raises(ContractValidationError, match="unknown resource"):
        PhysicalTaskGraph("g", 0, (PhysicalTask("t", PhysicalInstruction(PhysicalOpcode.MOVE_ATOMS), resource_demands=(ResourceDemand("missing"),)),)).validate_against_machine(machine())
    with pytest.raises(ContractValidationError, match="exceeds resource capacity"):
        PhysicalTaskGraph("g", 0, (PhysicalTask("t", PhysicalInstruction(PhysicalOpcode.MOVE_ATOMS), resource_demands=(ResourceDemand("aod", 2),)),)).validate_against_machine(machine())
    with pytest.raises(ContractValidationError, match="no positive calibrated duration"):
        PhysicalTaskGraph("g", 0, (PhysicalTask("t", PhysicalInstruction(PhysicalOpcode.WAIT)),)).validate_against_machine(machine())

