"""Build and schedule the four-logical-qubit GHZ physical workload."""

from __future__ import annotations

import argparse

from compiler.compiler import expand_to_qec_protocol
from compiler.logical_ir import (
    CodeFamily, LogicalCircuitIR, LogicalInitialState, LogicalOp, LogicalOpKind,
    LogicalQubitDecl,
)
from compiler.lowering.neutral_atom import lower_to_neutral_atom_tasks
from compiler.physical_ir import PhysicalTaskGraph
from compiler.qec_ir import QECProtocolIR
from hardware.zones import build_reference_target
from hardware.hardware_state import MachineState
from qec.surface_code import SurfaceCodeSpec, generate_surface_code_layout
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest, TimedSchedule
from simulator.executor import DigitalTwinExecutor, ExecutionResult


def build_ghz_logical_circuit(distance: int = 3, include_measurements: bool = False) -> LogicalCircuitIR:
    qubits = tuple(
        LogicalQubitDecl(
            f"L{index}", CodeFamily.ROTATED_SURFACE_CODE, distance,
            LogicalInitialState.PLUS if index == 0 else LogicalInitialState.ZERO,
        )
        for index in range(4)
    )
    operations = (
        LogicalOp("init-L0", LogicalOpKind.PREPARE_LOGICAL_PLUS, ("L0",), logical_layer=0),
        LogicalOp("init-L1", LogicalOpKind.PREPARE_LOGICAL_ZERO, ("L1",), logical_layer=0),
        LogicalOp("init-L2", LogicalOpKind.PREPARE_LOGICAL_ZERO, ("L2",), logical_layer=0),
        LogicalOp("init-L3", LogicalOpKind.PREPARE_LOGICAL_ZERO, ("L3",), logical_layer=0),
        LogicalOp(
            "cx-L0-L1", LogicalOpKind.LOGICAL_CNOT, ("L0", "L1"),
            ("init-L0", "init-L1"), logical_layer=1,
        ),
        LogicalOp(
            "cx-L0-L2", LogicalOpKind.LOGICAL_CNOT, ("L0", "L2"),
            ("cx-L0-L1", "init-L2"), logical_layer=2,
        ),
        LogicalOp(
            "cx-L1-L3", LogicalOpKind.LOGICAL_CNOT, ("L1", "L3"),
            ("cx-L0-L1", "init-L3"), logical_layer=2,
        ),
    )
    if include_measurements:
        operations += (
            LogicalOp("measure-L0", LogicalOpKind.MEASURE_LOGICAL, ("L0",), ("cx-L0-L2",), logical_layer=3),
            LogicalOp("measure-L1", LogicalOpKind.MEASURE_LOGICAL, ("L1",), ("cx-L1-L3",), logical_layer=3),
            LogicalOp("measure-L2", LogicalOpKind.MEASURE_LOGICAL, ("L2",), ("cx-L0-L2",), logical_layer=3),
            LogicalOp("measure-L3", LogicalOpKind.MEASURE_LOGICAL, ("L3",), ("cx-L1-L3",), logical_layer=3),
        )
    return LogicalCircuitIR(f"logical-ghz4-d{distance}", qubits, operations)


def build_ghz_qec_protocol(distance: int = 3, include_measurements: bool = False) -> QECProtocolIR:
    circuit = build_ghz_logical_circuit(distance, include_measurements)
    layout = generate_surface_code_layout(SurfaceCodeSpec(distance))
    return expand_to_qec_protocol(
        circuit, {qubit.logical_qubit_id: layout for qubit in circuit.logical_qubits}
    )


def build_ghz_physical_graph(distance: int = 3, include_measurements: bool = False) -> PhysicalTaskGraph:
    return lower_to_neutral_atom_tasks(build_ghz_qec_protocol(distance, include_measurements), build_reference_target())


def build_ghz_schedule(distance: int = 3, include_measurements: bool = False) -> TimedSchedule:
    target = build_reference_target()
    graph = lower_to_neutral_atom_tasks(build_ghz_qec_protocol(distance, include_measurements), target)
    return schedule_physical_tasks(ScheduleRequest(f"ghz-d{distance}", graph, target.machine))


def build_ghz_execution(distance: int = 3, include_measurements: bool = True) -> ExecutionResult:
    target = build_reference_target()
    protocol = build_ghz_qec_protocol(distance, include_measurements)
    graph = lower_to_neutral_atom_tasks(protocol, target)
    schedule = schedule_physical_tasks(ScheduleRequest(f"ghz-execution-d{distance}", graph, target.machine))
    initial_state = MachineState.from_protocol(protocol, target)
    return DigitalTwinExecutor(target).execute(f"ghz-d{distance}", graph, schedule, initial_state)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance", type=int, default=3)
    parser.add_argument("--execute", action="store_true", help="execute the complete scheduled digital-twin trace")
    parser.add_argument("--measure", action="store_true", help="append destructive logical-data readout")
    args = parser.parse_args()
    protocol = build_ghz_qec_protocol(args.distance, args.measure)
    graph = build_ghz_physical_graph(args.distance, args.measure)
    schedule = build_ghz_schedule(args.distance, args.measure)
    cnot_ops = [op for op in protocol.operations if op.kind.value == "transversal_cnot"]
    print(
        f"Built {protocol.protocol_id}: {len(protocol.blocks)} blocks, "
        f"{len(protocol.operations)} QEC operations, "
        f"{len(cnot_ops[0].pairings)} physical pairs per transversal CNOT; "
        f"lowered to {len(graph.tasks)} physical tasks; "
        f"scheduled makespan {schedule.makespan_ns} ns."
    )
    if args.execute:
        result = build_ghz_execution(args.distance, args.measure)
        print(
            f"Executed {len(result.trace.events)} trace events and emitted "
            f"{len(result.observations.observations)} observations; "
            f"final state digest {result.trace.snapshots[-1].state_digest[:12]}."
        )


if __name__ == "__main__":
    main()

