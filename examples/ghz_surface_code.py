"""Build and schedule the four-logical-qubit GHZ physical workload."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path

from compiler.compiler import expand_to_qec_protocol, syndrome_interactions_for_layout
from compiler.logical_ir import (
    CodeFamily, LogicalCircuitIR, LogicalInitialState, LogicalOp, LogicalOpKind,
    LogicalQubitDecl,
)
from compiler.lowering.neutral_atom import lower_to_neutral_atom_tasks
from compiler.physical_ir import (
    PhysicalInstruction, PhysicalOpcode, PhysicalTask, PhysicalTaskGraph,
    ResourceDemand, ResourceMode, ZoneDemand,
)
from compiler.qec_ir import QECOp, QECOpKind, QECProtocolIR
from decoder.decoder import IdealErasureAwareDecoder, IdealSingleErrorDecoder
from hardware.zones import NeutralAtomTarget, build_reference_target
from hardware.hardware_state import MachineState
from loss import (
    LossManager, RecoveryPlan, build_refill_tasks, retarget_replaced_atoms,
)
from qec.pauli_frame import PauliFrame
from qec.surface_code import SurfaceCodeSpec, generate_surface_code_layout
from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest, TimedSchedule
from simulator.executor import DigitalTwinExecutor, ExecutionResult
from runtime.controller import RuntimeController, RuntimeCycleResult
from runtime.mutation import DagMutation, RescheduleResult, reschedule_after_mutation
from simulator.benchmark import ExperimentSummary, run_noise_ensemble
from simulator.noise import (
    DeterministicLossModel, LossInjection, NoiseConfig, SeededNoiseModel,
)
from visualization import (
    VisualizationRun, build_visualization_bundle, build_visualization_run,
    combine_visualization_runs, write_visualization_artifact,
)


CONFIG_DIR = Path(__file__).with_name("config")


@dataclass(frozen=True, slots=True)
class LossRecoveryRun:
    target: NeutralAtomTarget
    detection_graph: PhysicalTaskGraph
    detection_schedule: TimedSchedule
    detection: ExecutionResult
    plan: RecoveryPlan
    reschedule: RescheduleResult
    recovery: ExecutionResult
    decoder_cycle: RuntimeCycleResult
    resolved_site_ids: tuple[str, ...]


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


def run_ghz_loss_recovery(
    distance: int = 3, profile: str = "low", *, reservoir_spares: int = 1,
) -> LossRecoveryRun:
    """Run the deterministic M7 data-loss/refill/QEC/reschedule scenario."""

    if reservoir_spares < 1:
        raise ValueError("the recoverable demo requires at least one reservoir spare")
    target = build_profile_target(profile)
    protocol = build_ghz_qec_protocol(distance, include_measurements=False, syndrome_rounds=0)
    base = lower_to_neutral_atom_tasks(protocol, target)
    lost_atom_id = "block-L2/data-r1-c1"
    if lost_atom_id not in {f"{block.block_id}/{site}" for block in protocol.blocks for site in block.data_site_ids}:
        raise ValueError("configured deterministic loss site is absent from this layout")
    depended_on = {parent for task in base.tasks for parent in task.predecessors}
    terminals = tuple(task.task_id for task in base.tasks if task.task_id not in depended_on)
    image_id = "m7-detect-loss-L2"
    detection_task = PhysicalTask(
        image_id,
        PhysicalInstruction(PhysicalOpcode.IMAGE_ATOMS, (lost_atom_id,), {
            "profile": "mid-circuit-loss-detection-v0.1",
        }),
        predecessors=terminals,
        resource_demands=(ResourceDemand(target.bindings.imaging_resource_id, mode=ResourceMode.SHARED),),
        zone_ids=(target.bindings.storage_zone_id,),
        zone_demands=(ZoneDemand(target.bindings.storage_zone_id, 1),),
    )
    graph = PhysicalTaskGraph(base.graph_id, base.revision + 1, base.tasks + (detection_task,))
    initial = MachineState.from_protocol(protocol, target)
    for index in range(reservoir_spares):
        initial.add_reservoir_atom(f"reservoir-spare-{index}", target)
    schedule = schedule_physical_tasks(ScheduleRequest("m7-detection", graph, target.machine))
    detection = DigitalTwinExecutor(
        target, loss_model=DeterministicLossModel((
            LossInjection("m7-loss-L2-center", image_id, lost_atom_id),
        )),
    ).execute("ghz-loss-detection", graph, schedule, initial)

    manager = LossManager(target)
    plans = manager.process_observations(detection.observations, detection.final_state)
    if len(plans) != 1 or plans[0].allocation is None:
        raise RuntimeError("deterministic recoverable scenario did not allocate one spare")
    plan = plans[0]
    refill = build_refill_tasks(plan, target)

    layout = generate_surface_code_layout(SurfaceCodeSpec(distance))
    block = next(item for item in protocol.blocks if item.block_id == plan.request.block_id)
    recovery_op = QECOp(
        "qec-m7-recovery-syndrome-L2", QECOpKind.SYNDROME_ROUND,
        (block.block_id,), (), "m7-recovery-L2",
        "eight_layer_erasure_recovery_v0.1", rounds=1,
        syndrome_interactions=syndrome_interactions_for_layout(layout),
    )
    recovery_protocol = QECProtocolIR(
        f"qec-m7-recovery-d{distance}", protocol.source_circuit_id,
        (block,), (recovery_op,),
    )
    syndrome_graph = lower_to_neutral_atom_tasks(recovery_protocol, target)
    verify_id = refill[-1].task_id
    syndrome_tasks = tuple(
        replace(task, predecessors=(verify_id,)) if not task.predecessors else task
        for task in syndrome_graph.tasks
    )
    syndrome_tasks = retarget_replaced_atoms(
        syndrome_tasks, {plan.request.atom_id: plan.allocation.replacement_atom_id},
    )
    mutation = DagMutation(
        "m7-loss-recovery", graph.graph_id, graph.revision,
        detection.trace.ended_at_ns,
        tuple(task.task_id for task in graph.tasks),
        inserted_tasks=refill + syndrome_tasks,
    )
    revised = reschedule_after_mutation(graph, mutation, target.machine)
    recovery = DigitalTwinExecutor(target).execute(
        "ghz-loss-recovery", revised.graph, revised.schedule,
        detection.final_state, completed_task_ids=mutation.completed_task_ids,
    )
    controller = RuntimeController(IdealErasureAwareDecoder())
    cycle = controller.process_syndrome_batch(
        recovery.observations, {block.block_id: layout},
        PauliFrame.identity(tuple(item.logical_qubit_id for item in protocol.blocks)),
        known_erasures_by_block={block.block_id: (plan.request.local_site_id,)},
    )
    resolved = controller.finalize_recovered_erasures(recovery.final_state, cycle)
    recovery.final_state.validate(target)
    return LossRecoveryRun(
        target, graph, schedule, detection, plan, revised, recovery, cycle, resolved,
    )


def build_ghz_loss_visualization_run(
    distance: int = 3, profile: str = "low",
) -> VisualizationRun:
    run = run_ghz_loss_recovery(distance, profile)
    detection = build_visualization_run(
        "Loss detection", run.target, run.detection_graph,
        run.detection_schedule, run.detection,
    )
    recovery = build_visualization_run(
        "Dynamic recovery", run.target, run.reschedule.graph,
        run.reschedule.schedule, run.recovery,
    )
    detected_at = run.plan.request.detected_at_ns
    ready_at = run.decoder_cycle.ready_at_ns
    resolved_at = run.recovery.final_state.now_ns
    runtime_events = (
        {"event_id": "runtime-01-loss-registered", "kind": "erasure_registered", "time_ns": detected_at},
        {"event_id": "runtime-02-reservoir-allocated", "kind": "reservoir_allocated", "time_ns": detected_at},
        {"event_id": "runtime-03-dag-mutated", "kind": "recovery_tasks_inserted", "time_ns": detected_at},
        {"event_id": "runtime-04-decoder-completed", "kind": "decoder_completed", "time_ns": ready_at},
        {"event_id": "runtime-05-erasure-resolved", "kind": "erasure_resolved", "time_ns": resolved_at},
    )
    state = run.recovery.final_state
    terminal_snapshot = {
        "time_ns": resolved_at,
        "block_locations": {
            block_id: block.zone_id or f"in_transit:{block.trajectory_id}"
            for block_id, block in state.blocks.items()
        },
        "zone_occupancy": state.zone_occupancy(run.target),
        "atoms_present": sum(atom.present for atom in state.atoms.values()),
        "known_erasures": sum(site.known_erasure for site in state.sites.values()),
        "aligned_pair_count": len(state.aligned_pairs),
        "state_digest": f"runtime-resolved-{run.plan.request.loss_event_id}",
    }
    return combine_visualization_runs(
        f"ghz-loss-recovery-d{distance}-{profile}",
        f"Recoverable loss · {profile} resources · d={distance}",
        detection, recovery, runtime_events=runtime_events,
        terminal_snapshot=terminal_snapshot,
    )


def build_ghz_noise_graph(
    distance: int = 3, profile: str = "low",
) -> tuple[NeutralAtomTarget, QECProtocolIR, PhysicalTaskGraph, MachineState]:
    """Build syndrome, logical readout, and final presence surveillance."""

    target = build_profile_target(profile)
    protocol = build_ghz_qec_protocol(
        distance, include_measurements=True, syndrome_rounds=1,
    )
    base = lower_to_neutral_atom_tasks(protocol, target)
    depended_on = {parent for task in base.tasks for parent in task.predecessors}
    terminals = tuple(task.task_id for task in base.tasks if task.task_id not in depended_on)
    atom_ids = tuple(
        f"{block.block_id}/{site_id}" for block in protocol.blocks
        for site_id in block.data_site_ids + block.ancilla_site_ids
    )
    surveillance = PhysicalTask(
        "m8-final-presence-surveillance",
        PhysicalInstruction(PhysicalOpcode.IMAGE_ATOMS, atom_ids, {
            "profile": "m8-final-presence-v0.1",
        }),
        predecessors=terminals,
        resource_demands=(ResourceDemand(target.bindings.imaging_resource_id, mode=ResourceMode.SHARED),),
        zone_ids=(target.bindings.storage_zone_id,),
        zone_demands=(ZoneDemand(target.bindings.storage_zone_id, len(atom_ids)),),
    )
    graph = PhysicalTaskGraph(base.graph_id, base.revision + 1, base.tasks + (surveillance,))
    return target, protocol, graph, MachineState.from_protocol(protocol, target)


def run_ghz_noise_benchmark(
    distance: int = 3, profile: str = "low", *,
    config: NoiseConfig | None = None, shots: int = 16, seed: int = 0,
) -> ExperimentSummary:
    if shots <= 0 or seed < 0:
        raise ValueError("noise benchmark requires positive shots and a non-negative seed")
    target, _, graph, state = build_ghz_noise_graph(distance, profile)
    _, summary = run_noise_ensemble(
        graph, target, state, config or NoiseConfig.ideal(),
        tuple(range(seed, seed + shots)), run_prefix=f"ghz-m8-d{distance}",
    )
    return summary


def build_ghz_noise_visualization_run(
    distance: int, profile: str, config: NoiseConfig, seed: int,
) -> VisualizationRun:
    target, _, graph, state = build_ghz_noise_graph(distance, profile)
    schedule = schedule_physical_tasks(ScheduleRequest(
        f"ghz-m8-visual-d{distance}", graph, target.machine,
    ))
    result = DigitalTwinExecutor(
        target, noise_model=SeededNoiseModel(config, seed),
    ).execute(f"ghz-m8-visual-d{distance}-s{seed}", graph, schedule, state)
    return build_visualization_run(
        f"{config.config_id} · seed={seed} · d={distance}",
        target, graph, schedule, result,
    )


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
    parser.add_argument("--inject-loss", action="store_true", help="run deterministic M7 data-loss recovery with one reservoir spare")
    parser.add_argument("--noise-config", type=Path, metavar="CONFIG.json", help="run the M8 seeded-noise ensemble using this explicit config")
    parser.add_argument("--shots", type=int, default=16, help="number of seeded M8 ensemble shots")
    parser.add_argument("--seed", type=int, default=0, help="first non-negative M8 ensemble seed")
    parser.add_argument("--noise-summary", type=Path, metavar="SUMMARY.json", help="write the M8 ensemble summary JSON")
    args = parser.parse_args()
    if args.decode and args.syndrome_rounds <= 0:
        parser.error("--decode requires --syndrome-rounds >= 1")
    if args.shots <= 0 or args.seed < 0:
        parser.error("--shots must be positive and --seed must be non-negative")
    if args.noise_summary and not args.noise_config:
        parser.error("--noise-summary requires --noise-config")
    noise_config = NoiseConfig.from_json(args.noise_config.read_text(encoding="utf-8")) if args.noise_config else None
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
        if args.inject_loss:
            runs = (build_ghz_loss_visualization_run(args.distance, args.profile),)
        elif noise_config is not None:
            runs = (build_ghz_noise_visualization_run(
                args.distance, args.profile, noise_config, args.seed,
            ),)
        else:
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
    if args.inject_loss:
        loss_run = run_ghz_loss_recovery(args.distance, args.profile)
        feedback = loss_run.decoder_cycle.feedbacks[0]
        print(
            f"Recovered deterministic loss {loss_run.plan.request.atom_id} with "
            f"{loss_run.plan.allocation.replacement_atom_id}; inserted "
            f"{len(loss_run.reschedule.mutation.inserted_tasks)} physical tasks in graph revision "
            f"{loss_run.reschedule.graph.revision}; decoder status "
            f"{feedback.decoder_result.status.value} at {feedback.available_at_ns} ns."
        )
    if args.noise_config:
        summary = run_ghz_noise_benchmark(
            args.distance, args.profile, config=noise_config,
            shots=args.shots, seed=args.seed,
        )
        print(
            f"M8 ensemble {summary.noise_config_id}: {len(summary.shots)} shots, "
            f"{summary.total_noise_events} sampled noise events, "
            f"{summary.runs_with_loss} run(s) with imaged atom loss; "
            f"parameters: {summary.parameter_source}."
        )
        if args.noise_summary:
            args.noise_summary.parent.mkdir(parents=True, exist_ok=True)
            args.noise_summary.write_text(summary.to_json() + "\n", encoding="utf-8")
            print(f"Wrote M8 statistical summary {args.noise_summary}.")


if __name__ == "__main__":
    main()


