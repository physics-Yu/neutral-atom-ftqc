"""Build and schedule the four-logical-qubit GHZ physical workload."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from compiler.compiler import expand_to_qec_protocol
from compiler.logical_ir import (
    CodeFamily, LogicalCircuitIR, LogicalInitialState, LogicalOp, LogicalOpKind,
    LogicalQubitDecl,
)
from compiler.lowering.neutral_atom import lower_to_neutral_atom_tasks
from compiler.physical_ir import PhysicalTaskGraph
from compiler.qec_ir import QECProtocolIR
from decoder.decoder import IdealSingleErrorDecoder
from hardware.zones import NeutralAtomTarget, build_reference_target
from hardware.hardware_state import MachineState
from qec.pauli_frame import PauliFrame
from qec.surface_code import SurfaceCodeSpec, generate_surface_code_layout
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest, TimedSchedule
from simulator.executor import DigitalTwinExecutor, ExecutionResult
from runtime.controller import RuntimeController, RuntimeCycleResult
from visualization import (
    VisualizationRun, build_visualization_bundle, build_visualization_run,
    write_visualization_artifact,
)


CONFIG_DIR = Path(__file__).with_name("config")


def build_profile_target(profile: str = "low") -> NeutralAtomTarget:
    """Apply an explicit demo resource profile without changing the physical DAG."""

    config_path = CONFIG_DIR / f"resources-{profile}.json"
    if not config_path.is_file():
        raise ValueError(f"unknown resource profile {profile!r}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    target = build_reference_target()
    capacities = data["resource_capacities"]
    resources = tuple(
        replace(item, capacity=capacities.get(item.resource_id, item.capacity))
        for item in target.machine.resources
    )
    return NeutralAtomTarget(replace(target.machine, machine_id=data["machine_config_id"], resources=resources), target.geometry, target.bindings)


def build_ghz_logical_circuit(
    distance: int = 3, include_measurements: bool = False, syndrome_rounds: int = 0,
) -> LogicalCircuitIR:
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
    if syndrome_rounds:
        if syndrome_rounds < 0:
            raise ValueError("syndrome_rounds must be non-negative")
        terminal = {"L0": "cx-L0-L2", "L1": "cx-L1-L3", "L2": "cx-L0-L2", "L3": "cx-L1-L3"}
        operations += tuple(
            LogicalOp(
                f"syndrome-{logical_id}", LogicalOpKind.SYNDROME_ROUND,
                (logical_id,), (predecessor,), logical_layer=3,
                params={"rounds": syndrome_rounds},
            )
            for logical_id, predecessor in terminal.items()
        )
    if include_measurements:
        predecessor = lambda logical_id, fallback: f"syndrome-{logical_id}" if syndrome_rounds else fallback
        operations += (
            LogicalOp("measure-L0", LogicalOpKind.MEASURE_LOGICAL, ("L0",), (predecessor("L0", "cx-L0-L2"),), logical_layer=4),
            LogicalOp("measure-L1", LogicalOpKind.MEASURE_LOGICAL, ("L1",), (predecessor("L1", "cx-L1-L3"),), logical_layer=4),
            LogicalOp("measure-L2", LogicalOpKind.MEASURE_LOGICAL, ("L2",), (predecessor("L2", "cx-L0-L2"),), logical_layer=4),
            LogicalOp("measure-L3", LogicalOpKind.MEASURE_LOGICAL, ("L3",), (predecessor("L3", "cx-L1-L3"),), logical_layer=4),
        )
    return LogicalCircuitIR(f"logical-ghz4-d{distance}", qubits, operations)


def build_ghz_qec_protocol(
    distance: int = 3, include_measurements: bool = False, syndrome_rounds: int = 0,
) -> QECProtocolIR:
    circuit = build_ghz_logical_circuit(distance, include_measurements, syndrome_rounds)
    layout = generate_surface_code_layout(SurfaceCodeSpec(distance))
    return expand_to_qec_protocol(
        circuit, {qubit.logical_qubit_id: layout for qubit in circuit.logical_qubits}
    )


def build_ghz_physical_graph(
    distance: int = 3, include_measurements: bool = False, syndrome_rounds: int = 0,
) -> PhysicalTaskGraph:
    return lower_to_neutral_atom_tasks(build_ghz_qec_protocol(distance, include_measurements, syndrome_rounds), build_reference_target())


def build_ghz_schedule(
    distance: int = 3, include_measurements: bool = False, profile: str = "low",
    syndrome_rounds: int = 0,
) -> TimedSchedule:
    target = build_profile_target(profile)
    graph = lower_to_neutral_atom_tasks(build_ghz_qec_protocol(distance, include_measurements, syndrome_rounds), target)
    return schedule_physical_tasks(ScheduleRequest(f"ghz-d{distance}", graph, target.machine))


def build_ghz_execution(
    distance: int = 3, include_measurements: bool = True, profile: str = "low",
    syndrome_rounds: int = 0,
) -> ExecutionResult:
    target = build_profile_target(profile)
    protocol = build_ghz_qec_protocol(distance, include_measurements, syndrome_rounds)
    graph = lower_to_neutral_atom_tasks(protocol, target)
    schedule = schedule_physical_tasks(ScheduleRequest(f"ghz-execution-d{distance}", graph, target.machine))
    initial_state = MachineState.from_protocol(protocol, target)
    return DigitalTwinExecutor(target).execute(f"ghz-d{distance}", graph, schedule, initial_state)


def build_ghz_visualization_run(
    distance: int, profile: str, syndrome_rounds: int = 0,
) -> VisualizationRun:
    target = build_profile_target(profile)
    protocol = build_ghz_qec_protocol(
        distance, include_measurements=True, syndrome_rounds=syndrome_rounds,
    )
    graph = lower_to_neutral_atom_tasks(protocol, target)
    schedule = schedule_physical_tasks(ScheduleRequest(f"ghz-visual-{profile}-d{distance}", graph, target.machine))
    result = DigitalTwinExecutor(target).execute(f"ghz-{profile}-d{distance}", graph, schedule, MachineState.from_protocol(protocol, target))
    return build_visualization_run(f"{profile.title()} resources · d={distance}", target, graph, schedule, result)


def run_ghz_qec_cycle(
    distance: int = 3, profile: str = "low", syndrome_rounds: int = 1,
) -> tuple[ExecutionResult, RuntimeCycleResult, TimedSchedule]:
    if syndrome_rounds <= 0:
        raise ValueError("a QEC cycle requires at least one syndrome round")
    target = build_profile_target(profile)
    protocol = build_ghz_qec_protocol(distance, include_measurements=False, syndrome_rounds=syndrome_rounds)
    graph = lower_to_neutral_atom_tasks(protocol, target)
    schedule = schedule_physical_tasks(ScheduleRequest(f"ghz-qec-d{distance}", graph, target.machine))
    result = DigitalTwinExecutor(target).execute(
        f"ghz-qec-d{distance}", graph, schedule, MachineState.from_protocol(protocol, target),
    )
    layout = generate_surface_code_layout(SurfaceCodeSpec(distance))
    controller = RuntimeController(IdealSingleErrorDecoder())
    cycle = controller.process_syndrome_batch(
        result.observations,
        {block.block_id: layout for block in protocol.blocks},
        PauliFrame.identity(tuple(block.logical_qubit_id for block in protocol.blocks)),
    )
    barrier = controller.build_feedback_barrier(cycle, target)
    release = schedule_physical_tasks(ScheduleRequest(
        f"ghz-qec-release-d{distance}", barrier, target.machine,
        not_before_ns=max(result.trace.ended_at_ns, cycle.ready_at_ns),
        condition_snapshot=cycle.condition_snapshot,
    ))
    return result, cycle, release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance", type=int, default=3)
    parser.add_argument("--execute", action="store_true", help="execute the complete scheduled digital-twin trace")
    parser.add_argument("--measure", action="store_true", help="append destructive logical-data readout")
    parser.add_argument("--profile", choices=("low", "high"), default="low", help="hardware resource profile")
    parser.add_argument("--visualize", type=Path, metavar="OUTPUT.html", help="write a standalone synchronized HTML and JSON artifact")
    parser.add_argument("--compare-resources", action="store_true", help="include low/high resource runs in the artifact")
    parser.add_argument("--syndrome-rounds", type=int, default=0, help="append this many explicit stabilizer-extraction rounds per block")
    parser.add_argument("--decode", action="store_true", help="decode syndrome observations and release a feedback barrier")
    args = parser.parse_args()
    if args.decode and args.syndrome_rounds <= 0:
        parser.error("--decode requires --syndrome-rounds >= 1")
    include_measurements = args.measure or args.visualize is not None
    protocol = build_ghz_qec_protocol(args.distance, include_measurements, args.syndrome_rounds)
    target = build_profile_target(args.profile)
    graph = lower_to_neutral_atom_tasks(protocol, target)
    schedule = schedule_physical_tasks(ScheduleRequest(f"ghz-d{args.distance}", graph, target.machine))
    cnot_ops = [op for op in protocol.operations if op.kind.value == "transversal_cnot"]
    print(
        f"Built {protocol.protocol_id}: {len(protocol.blocks)} blocks, "
        f"{len(protocol.operations)} QEC operations, "
        f"{len(cnot_ops[0].pairings)} physical pairs per transversal CNOT; "
        f"lowered to {len(graph.tasks)} physical tasks; "
        f"scheduled makespan {schedule.makespan_ns} ns."
    )
    if args.execute:
        result = build_ghz_execution(args.distance, include_measurements, args.profile, args.syndrome_rounds)
        print(
            f"Executed {len(result.trace.events)} trace events and emitted "
            f"{len(result.observations.observations)} observations; "
            f"final state digest {result.trace.snapshots[-1].state_digest[:12]}."
        )
    if args.visualize:
        profiles = ("low", "high") if args.compare_resources else (args.profile,)
        runs = tuple(
            build_ghz_visualization_run(args.distance, profile, args.syndrome_rounds)
            for profile in profiles
        )
        html_path, json_path = write_visualization_artifact(
            build_visualization_bundle(f"Four-block GHZ · distance {args.distance}", *runs),
            args.visualize,
        )
        print(f"Wrote standalone visualization {html_path} and data {json_path}.")
    if args.decode:
        _, cycle, release = run_ghz_qec_cycle(args.distance, args.profile, args.syndrome_rounds)
        statuses = ", ".join(item.decoder_result.status.value for item in cycle.feedbacks)
        print(
            f"Decoded {len(cycle.feedbacks)} block syndromes ({statuses}); "
            f"feedback barrier starts at {release.entries[0].start_ns} ns after explicit decoder latency."
        )


if __name__ == "__main__":
    main()


