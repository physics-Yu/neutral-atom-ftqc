from __future__ import annotations

from compiler.physical_ir import PhysicalInstruction, PhysicalOpcode, PhysicalTask, PhysicalTaskGraph, ResourceDemand
from hardware.zones import build_reference_target


def test_all_physical_opcodes_have_executable_reference_target_bindings() -> None:
    target = build_reference_target()
    pairs = (("a", "b"),)
    cases = (
        (PhysicalOpcode.MOVE_ATOMS, ("a",), {"trajectory_id": "t", "source_zone_id": "storage", "destination_zone_id": "entangling"}, ("storage", "entangling"), "aod-0"),
        (PhysicalOpcode.MOVE_BLOCK, ("block",), {"trajectory_id": "t", "source_zone_id": "storage", "destination_zone_id": "entangling"}, ("storage", "entangling"), "aod-0"),
        (PhysicalOpcode.ALIGN_ATOMS, ("a", "b"), {"pairs": pairs, "alignment_profile": "p"}, ("entangling",), "aod-0"),
        (PhysicalOpcode.APPLY_1Q_PULSE, ("a",), {"operation": "x", "pulse_id": "p"}, ("storage",), "oneq-0"),
        (PhysicalOpcode.APPLY_2Q_RYDBERG_GATE, ("a", "b"), {"gate": "cz", "pulse_id": "p", "pairs": pairs}, ("entangling",), "rydberg-0"),
        (PhysicalOpcode.IMAGE_ATOMS, ("a",), {"profile": "p"}, ("storage",), "camera-0"),
        (PhysicalOpcode.MEASURE_ATOMS, ("a",), {"basis": "z", "profile": "p"}, ("readout",), "readout-0"),
        (PhysicalOpcode.RESET_ATOMS, ("a",), {"state": "zero", "profile": "p", "purpose": "test"}, ("storage",), "reset-0"),
        (PhysicalOpcode.LOAD_RESERVOIR_ATOM, ("a",), {"profile": "p"}, ("reservoir",), "loader-0"),
        (PhysicalOpcode.PLACE_ATOM, ("replacement", "vacancy"), {"destination_site_id": "vacancy", "profile": "p"}, ("storage",), "aod-0"),
        (PhysicalOpcode.WAIT, (), {"duration_ns": 10}, ("storage",), "clock-0"),
        (PhysicalOpcode.EMIT_SYNC, (), {"tag": "t", "channel": "c"}, ("storage",), "clock-0"),
    )
    tasks = tuple(
        PhysicalTask(
            f"task-{opcode.value}", PhysicalInstruction(opcode, operands, parameters),
            resource_demands=(ResourceDemand(resource),), zone_ids=zones,
        )
        for opcode, operands, parameters, zones, resource in cases
    )
    graph = PhysicalTaskGraph("all-opcodes", 0, tasks)
    graph.validate_against_machine(target.machine)
