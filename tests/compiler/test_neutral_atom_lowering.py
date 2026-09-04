from __future__ import annotations

from dataclasses import replace

import pytest

from compiler.lowering.neutral_atom import lower_to_neutral_atom_tasks
from compiler.physical_ir import PhysicalOpcode, PhysicalTaskGraph
from contracts import ContractValidationError
from examples.ghz_surface_code import build_ghz_qec_protocol
from hardware.zones import NeutralAtomTarget, build_reference_target


@pytest.mark.parametrize("distance", [3, 5])
def test_ghz_lowers_to_a_complete_physical_dag(distance: int) -> None:
    protocol = build_ghz_qec_protocol(distance)
    target = build_reference_target()
    graph = lower_to_neutral_atom_tasks(protocol, target)

    assert len(graph.tasks) == 29
    assert all(isinstance(task.instruction.opcode, PhysicalOpcode) for task in graph.tasks)
    assert all(task.resolved_duration_ns(target.machine) > 0 for task in graph.tasks)
    assert PhysicalTaskGraph.from_json(graph.to_json()) == graph
    graph.validate_against_machine(target.machine)

    rydberg_tasks = [
        task for task in graph.tasks
        if task.instruction.opcode is PhysicalOpcode.APPLY_2Q_RYDBERG_GATE
    ]
    cnot_ops = [op for op in protocol.operations if op.kind.value == "transversal_cnot"]
    assert len(rydberg_tasks) == len(cnot_ops) == 3
    for task, operation in zip(rydberg_tasks, cnot_ops, strict=True):
        expected = tuple(
            (f"{pair.control.block_id}/{pair.control.site_id}", f"{pair.target.block_id}/{pair.target.site_id}")
            for pair in operation.pairings
        )
        assert task.instruction.parameters["gate"] == "cz"
        assert task.instruction.parameters["pairs"] == expected
        assert task.provenance.qec_op_ids == (operation.qec_op_id,)
        assert task.provenance.logical_op_ids == (operation.logical_op_id,)


def test_cnot_lowering_orders_transport_alignment_h_cz_h_and_return() -> None:
    graph = lower_to_neutral_atom_tasks(build_ghz_qec_protocol(3), build_reference_target())
    tasks = {task.task_id: task for task in graph.tasks}
    prefix = "phy-qec-cx-L0-L1"
    assert tasks[f"{prefix}-align"].predecessors == (
        f"{prefix}-move-control-in", f"{prefix}-move-target-in",
    )
    assert tasks[f"{prefix}-target-h-before"].predecessors == (f"{prefix}-align",)
    assert tasks[f"{prefix}-rydberg-cz"].predecessors == (f"{prefix}-target-h-before",)
    assert tasks[f"{prefix}-target-h-after"].predecessors == (f"{prefix}-rydberg-cz",)
    assert tasks[f"{prefix}-move-control-out"].predecessors == (f"{prefix}-target-h-after",)
    assert tasks[f"{prefix}-move-target-out"].predecessors == (f"{prefix}-target-h-after",)


def test_finite_zone_capacity_is_checked_before_lowering() -> None:
    target = build_reference_target()
    small_storage = replace(target.machine.zones[0], capacity=1)
    machine = replace(target.machine, zones=(small_storage,) + target.machine.zones[1:])
    undersized = NeutralAtomTarget(machine, target.geometry, target.bindings)
    with pytest.raises(ContractValidationError, match="storage-zone"):
        lower_to_neutral_atom_tasks(build_ghz_qec_protocol(3), undersized)
