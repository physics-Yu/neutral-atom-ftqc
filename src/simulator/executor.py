"""Deterministic executor for scheduled Physical ISA v0.1 instructions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from compiler.physical_ir import PhysicalOpcode, PhysicalTask, PhysicalTaskGraph
from contracts.common import ContractValidationError, canonical_json, require_id
from contracts.events import AtomRole, Observation, ObservationBatch, ObservationKind
from hardware.atom import AtomState, QubitLabel
from hardware.hardware_state import MachineState
from hardware.zones import NeutralAtomTarget
from scheduler.resources import CapacityCalendar
from scheduler.task import ScheduledTask, TimedSchedule
from simulator.events import ExecutionEvent, ExecutionTrace, MachineSnapshot, TraceEventKind
from simulator.noise import (
    LossModel, NoiseEvent, NoiseEventKind, NoiseModel, NoiseReport,
    NoNoiseModel, PauliFaultKind,
)


class StateBackend(Protocol):
    def reset(self, atom: AtomState, state: str) -> None: ...
    def apply_1q(self, atom: AtomState, operation: str) -> None: ...
    def apply_2q(self, control: AtomState, target: AtomState, gate: str) -> None: ...
    def measure(self, atom: AtomState, basis: str) -> int: ...
    def syndrome_bit(self, check_id: str, basis: str, data_atom_ids: tuple[str, ...]) -> int: ...


@dataclass(slots=True)
class DeterministicIdealBackend:
    """Symbolic ideal state labels with deterministic measurement branching."""

    seed: int = 0

    def reset(self, atom: AtomState, state: str) -> None:
        if state not in {"zero", "one"}:
            raise ContractValidationError("the M4 ideal backend supports only zero/one reset")
        atom.qubit_label = QubitLabel.ZERO if state == "zero" else QubitLabel.ONE

    def apply_1q(self, atom: AtomState, operation: str) -> None:
        if atom.qubit_label in {QubitLabel.MEASURED, QubitLabel.LOST}:
            raise ContractValidationError("measured or lost atom must be reset before coherent control")
        transitions = {
            "hadamard": {
                QubitLabel.ZERO: QubitLabel.PLUS, QubitLabel.ONE: QubitLabel.MINUS,
                QubitLabel.PLUS: QubitLabel.ZERO, QubitLabel.MINUS: QubitLabel.ONE,
            },
            "ry_pi_over_2": {
                QubitLabel.ZERO: QubitLabel.PLUS, QubitLabel.ONE: QubitLabel.MINUS,
            },
            "x": {QubitLabel.ZERO: QubitLabel.ONE, QubitLabel.ONE: QubitLabel.ZERO},
        }
        if operation not in transitions:
            raise ContractValidationError(f"unsupported ideal one-qubit operation {operation!r}")
        atom.qubit_label = transitions.get(operation, {}).get(atom.qubit_label, atom.qubit_label)

    def apply_2q(self, control: AtomState, target: AtomState, gate: str) -> None:
        if gate != "cz":
            raise ContractValidationError("the M4 ideal backend supports only physical CZ")
        if any(atom.qubit_label in {QubitLabel.MEASURED, QubitLabel.LOST} for atom in (control, target)):
            raise ContractValidationError("measured or lost atoms cannot participate in a Rydberg gate")
        if control.qubit_label in {QubitLabel.PLUS, QubitLabel.MINUS, QubitLabel.ENTANGLED} or target.qubit_label in {QubitLabel.PLUS, QubitLabel.MINUS, QubitLabel.ENTANGLED}:
            control.qubit_label = target.qubit_label = QubitLabel.ENTANGLED

    def measure(self, atom: AtomState, basis: str) -> int:
        if basis not in {"x", "z"}:
            raise ContractValidationError("the M4 ideal backend supports only X/Z measurement")
        if atom.qubit_label is QubitLabel.LOST:
            raise ContractValidationError("lost atom cannot be measured as a present qubit")
        deterministic = int.from_bytes(sha256(f"{self.seed}:{atom.atom_id}:{basis}".encode()).digest()[:1], "big") & 1
        if basis == "z" and atom.qubit_label in {QubitLabel.ZERO, QubitLabel.PLUS}:
            deterministic = 0
        elif basis == "z" and atom.qubit_label in {QubitLabel.ONE, QubitLabel.MINUS}:
            deterministic = 1
        atom.qubit_label = QubitLabel.MEASURED
        return deterministic

    def syndrome_bit(self, check_id: str, basis: str, data_atom_ids: tuple[str, ...]) -> int:
        """Return the ideal no-error stabilizer eigenvalue bit."""

        return 0


@dataclass(slots=True)
class ExecutionResult:
    final_state: MachineState
    trace: ExecutionTrace
    observations: ObservationBatch
    noise_report: NoiseReport


class DigitalTwinExecutor:
    def __init__(
        self, target: NeutralAtomTarget, backend: StateBackend | None = None,
        loss_model: LossModel | None = None, noise_model: NoiseModel | None = None,
    ) -> None:
        if loss_model is not None and noise_model is not None:
            raise ContractValidationError("provide either loss_model or noise_model, not both")
        self.target = target
        self.backend = backend or DeterministicIdealBackend()
        self.noise_model = noise_model or loss_model or NoNoiseModel()
        self._noise_events: list[NoiseEvent] = []
        self._parallel_rydberg_neighbors: dict[str, int] = {}

    def execute(
        self, run_id: str, graph: PhysicalTaskGraph, schedule: TimedSchedule,
        initial_state: MachineState, *, completed_task_ids: tuple[str, ...] = (),
    ) -> ExecutionResult:
        require_id(run_id, "execution run ID")
        if not isinstance(graph, PhysicalTaskGraph) or not isinstance(schedule, TimedSchedule) or not isinstance(initial_state, MachineState):
            raise ContractValidationError("executor accepts only a physical graph, timed schedule, and machine state")
        state = initial_state.clone()
        state.validate(self.target)
        tasks = {task.task_id: task for task in graph.tasks}
        entries = {entry.task_id: entry for entry in schedule.entries}
        self._validate_schedule(graph, schedule, state, completed_task_ids)
        self._noise_events = []
        rydberg_entries = [
            entry for entry in schedule.entries
            if tasks[entry.task_id].instruction.opcode is PhysicalOpcode.APPLY_2Q_RYDBERG_GATE
        ]
        self._parallel_rydberg_neighbors = {
            entry.task_id: sum(
                other.task_id != entry.task_id
                and entry.start_ns < other.end_ns and other.start_ns < entry.end_ns
                for other in rydberg_entries
            )
            for entry in rydberg_entries
        }
        events: list[ExecutionEvent] = []
        snapshots: list[MachineSnapshot] = [self._snapshot("snapshot-0000", state)]
        observations: list[Observation] = []
        timeline = []
        for entry in schedule.entries:
            timeline.append((entry.start_ns, 1, entry.dispatch_order, entry, True))
            timeline.append((entry.end_ns, 0, entry.dispatch_order, entry, False))
        started_at = state.now_ns
        for occurred_at, _, _, entry, is_start in sorted(timeline):
            state.now_ns = occurred_at
            task = tasks[entry.task_id]
            if is_start:
                subjects = tuple(sorted(self._subject_atoms(task, state)))
                for injection in self.noise_model.losses_at_task_start(
                    task.task_id, task.instruction.opcode.value, subjects,
                ):
                    if injection.atom_id not in subjects:
                        raise ContractValidationError("loss injection atom must be a subject of its trigger task")
                    state.mark_atom_lost(injection.atom_id, detected=False)
                    self._noise_events.append(NoiseEvent(
                        f"noise-{injection.injection_id}", NoiseEventKind.ATOM_LOSS,
                        occurred_at, task.task_id, injection.atom_id, "atom-removed-before-task",
                    ))
                self._start_task(task, entry, state)
                state.validate(self.target)
                kind = TraceEventKind.TASK_STARTED
                emitted: tuple[Observation, ...] = ()
            else:
                emitted = self._complete_task(task, entry, state, run_id, len(observations))
                observations.extend(emitted)
                state.validate(self.target)
                kind = TraceEventKind.TASK_COMPLETED
            snapshot = self._snapshot(f"snapshot-{len(snapshots):04d}", state)
            snapshots.append(snapshot)
            events.append(self._event(f"trace-{len(events):04d}", kind, occurred_at, task, entry, snapshot.state_digest))
            for observation in emitted:
                events.append(self._event(
                    f"trace-{len(events):04d}", TraceEventKind.OBSERVATION_EMITTED,
                    occurred_at, task, entry, snapshot.state_digest, observation.event_id,
                ))
        ended_at = max((entry.end_ns for entry in schedule.entries), default=state.now_ns)
        trace = ExecutionTrace(
            run_id, schedule.schedule_id, graph.graph_id, started_at, ended_at,
            tuple(events), tuple(snapshots), self.noise_model.config.config_id,
            self.noise_model.seed,
        )
        batch = ObservationBatch(run_id, f"observations-{run_id}", ended_at, tuple(observations))
        report = NoiseReport(
            self.noise_model.config, self.noise_model.seed, tuple(self._noise_events),
        )
        return ExecutionResult(state, trace, batch, report)

    def _validate_schedule(
        self, graph: PhysicalTaskGraph, schedule: TimedSchedule, state: MachineState,
        completed_task_ids: tuple[str, ...],
    ) -> None:
        graph.validate_against_machine(self.target.machine)
        if schedule.graph_id != graph.graph_id or schedule.graph_revision != graph.revision:
            raise ContractValidationError("schedule does not target this physical graph revision")
        tasks = {task.task_id: task for task in graph.tasks}
        entries = {entry.task_id: entry for entry in schedule.entries}
        completed = set(completed_task_ids)
        if completed - tasks.keys():
            raise ContractValidationError("completed execution task is absent from the graph")
        if any(set(tasks[task_id].predecessors) - completed for task_id in completed):
            raise ContractValidationError("completed execution tasks must be predecessor-closed")
        expected = set(tasks) - completed
        if schedule.unscheduled or set(entries) != expected:
            raise ContractValidationError("schedule must cover every unfinished physical task exactly once")
        if len({entry.dispatch_order for entry in schedule.entries}) != len(schedule.entries):
            raise ContractValidationError("schedule dispatch orders must be unique")
        calendar = CapacityCalendar(self.target.machine)
        for entry in sorted(schedule.entries, key=lambda item: (item.start_ns, item.dispatch_order, item.task_id)):
            task = tasks[entry.task_id]
            if entry.start_ns < state.now_ns or entry.end_ns - entry.start_ns != task.resolved_duration_ns(self.target.machine):
                raise ContractValidationError("scheduled interval does not match task release or duration")
            if entry.resource_assignments != task.resource_demands or entry.zone_assignments != task.zone_demands:
                raise ContractValidationError("scheduled assignments differ from physical task demands")
            if task.deadline_ns is not None and entry.end_ns > task.deadline_ns:
                raise ContractValidationError("scheduled task misses its deadline")
            if any(
                parent not in completed and entries[parent].end_ns > entry.start_ns
                for parent in task.predecessors
            ):
                raise ContractValidationError("schedule violates a physical DAG dependency")
            blockers = calendar.conflicts(entry.start_ns, entry.end_ns, entry.resource_assignments, entry.zone_assignments)
            if blockers:
                raise ContractValidationError("schedule contains a resource, zone, or routing conflict")
            calendar.reserve(entry.task_id, entry.start_ns, entry.end_ns, entry.resource_assignments, entry.zone_assignments)
            self._validate_route_binding(task, entry)
        ordered = list(schedule.entries)
        for index, left in enumerate(ordered):
            left_atoms = self._subject_atoms(tasks[left.task_id], state)
            for right in ordered[index + 1:]:
                if left.start_ns < right.end_ns and right.start_ns < left.end_ns:
                    if left_atoms & self._subject_atoms(tasks[right.task_id], state):
                        raise ContractValidationError("overlapping tasks act on the same atom")

    def _validate_route_binding(self, task: PhysicalTask, entry: ScheduledTask) -> None:
        if task.instruction.opcode not in {PhysicalOpcode.MOVE_ATOMS, PhysicalOpcode.MOVE_BLOCK, PhysicalOpcode.PLACE_ATOM}:
            return
        parameters = task.instruction.parameters
        trajectory = self.target.geometry.trajectory_by_id(parameters["trajectory_id"])
        if (trajectory.source_zone_id, trajectory.destination_zone_id) != (parameters["source_zone_id"], parameters["destination_zone_id"]):
            raise ContractValidationError("movement trajectory endpoints do not match the instruction")
        if entry.end_ns - entry.start_ns != trajectory.duration_ns:
            raise ContractValidationError("movement duration does not match its trajectory")
        assigned = {item.resource_id for item in entry.resource_assignments}
        if set(trajectory.conflict_group_ids) - assigned:
            raise ContractValidationError("movement schedule omits a trajectory conflict group")

    def _subject_atoms(self, task: PhysicalTask, state: MachineState) -> set[str]:
        if task.instruction.opcode is PhysicalOpcode.MOVE_BLOCK:
            block = state.blocks.get(task.instruction.operands[0])
            return {
                state.sites[site_id].atom_id for site_id in block.site_ids
                if state.sites[site_id].atom_id is not None
            } if block else set()
        result: set[str] = set()
        for operand in task.instruction.operands:
            if operand in state.atoms:
                result.add(operand)
            elif operand in state.sites and state.sites[operand].atom_id is not None:
                result.add(state.sites[operand].atom_id)
        return result

    def _start_task(self, task: PhysicalTask, entry: ScheduledTask, state: MachineState) -> None:
        opcode = task.instruction.opcode
        parameters = task.instruction.parameters
        if opcode is PhysicalOpcode.MOVE_BLOCK:
            block = self._block(task.instruction.operands[0], state)
            if block.zone_id != parameters["source_zone_id"]:
                raise ContractValidationError("block movement source does not match machine state")
            block.zone_id = None
            block.trajectory_id = parameters["trajectory_id"]
            for site_id in block.site_ids:
                atom_id = state.sites[site_id].atom_id
                if atom_id is not None:
                    state.atoms[atom_id].zone_id = None
                    state.atoms[atom_id].trajectory_id = parameters["trajectory_id"]
            self._clear_alignment({
                atom_id for site_id in block.site_ids
                if (atom_id := state.sites[site_id].atom_id) is not None
            }, state)
        elif opcode is PhysicalOpcode.MOVE_ATOMS:
            atoms = self._present_atoms(task.instruction.operands, state)
            if any(atom.zone_id != parameters["source_zone_id"] for atom in atoms):
                raise ContractValidationError("atom movement source does not match machine state")
            for atom in atoms:
                atom.zone_id = None
                atom.trajectory_id = parameters["trajectory_id"]
            self._clear_alignment({atom.atom_id for atom in atoms}, state)
            self._refresh_block_locations(state)
        elif opcode in {PhysicalOpcode.ALIGN_ATOMS, PhysicalOpcode.APPLY_1Q_PULSE, PhysicalOpcode.APPLY_2Q_RYDBERG_GATE, PhysicalOpcode.MEASURE_ATOMS, PhysicalOpcode.RESET_ATOMS}:
            atoms = self._present_atoms(task.instruction.operands, state)
            if any(atom.zone_id not in task.zone_ids for atom in atoms):
                raise ContractValidationError("atom location does not match the task zone claim")
        elif opcode is PhysicalOpcode.IMAGE_ATOMS:
            atoms = self._atoms(task.instruction.operands, state)
            if any(atom.present and atom.zone_id not in task.zone_ids for atom in atoms):
                raise ContractValidationError("imaged atom location does not match the task zone claim")
        elif opcode is PhysicalOpcode.PLACE_ATOM:
            replacement = state.atoms.get(task.instruction.operands[0])
            site = state.sites.get(parameters["destination_site_id"])
            if replacement is None or not replacement.present or replacement.zone_id != self.target.bindings.reservoir_zone_id:
                raise ContractValidationError("replacement atom is not available in the reservoir")
            if site is None or site.atom_id is not None or not site.known_erasure:
                raise ContractValidationError("destination is not a recorded vacant erasure site")
            if task.instruction.operands[1] != parameters["destination_site_id"]:
                raise ContractValidationError("place operand and destination_site_id disagree")
            if parameters["source_zone_id"] != self.target.bindings.reservoir_zone_id or parameters["destination_zone_id"] != state.blocks[site.block_id].zone_id:
                raise ContractValidationError("place trajectory endpoints do not match reservoir and destination block")
            replacement.zone_id = None
            replacement.trajectory_id = parameters["trajectory_id"]
        elif opcode is PhysicalOpcode.LOAD_RESERVOIR_ATOM and task.instruction.operands[0] in state.atoms:
            raise ContractValidationError("cannot load an atom ID that already exists")

    def _complete_task(self, task: PhysicalTask, entry: ScheduledTask, state: MachineState, run_id: str, observation_offset: int) -> tuple[Observation, ...]:
        opcode = task.instruction.opcode
        parameters = task.instruction.parameters
        if opcode is PhysicalOpcode.MOVE_BLOCK:
            block = self._block(task.instruction.operands[0], state)
            block.zone_id = parameters["destination_zone_id"]
            block.trajectory_id = None
            for site_id in block.site_ids:
                atom_id = state.sites[site_id].atom_id
                if atom_id is not None:
                    state.atoms[atom_id].zone_id = block.zone_id
                    state.atoms[atom_id].trajectory_id = None
        elif opcode is PhysicalOpcode.MOVE_ATOMS:
            for atom in self._atoms(task.instruction.operands, state):
                atom.zone_id = parameters["destination_zone_id"]
                atom.trajectory_id = None
            self._refresh_block_locations(state)
        elif opcode is PhysicalOpcode.ALIGN_ATOMS:
            state.aligned_pairs.update(tuple(pair) for pair in parameters["pairs"])
        elif opcode is PhysicalOpcode.APPLY_1Q_PULSE:
            for atom in self._present_atoms(task.instruction.operands, state):
                if parameters["operation"] == "hadamard":
                    atom.pauli_x_error, atom.pauli_z_error = atom.pauli_z_error, atom.pauli_x_error
                self.backend.apply_1q(atom, parameters["operation"])
            self._apply_control_noise(task, entry, state)
        elif opcode is PhysicalOpcode.APPLY_2Q_RYDBERG_GATE:
            for left, right in parameters["pairs"]:
                if (left, right) not in state.aligned_pairs:
                    raise ContractValidationError("Rydberg pair is not aligned")
                left_x = state.atoms[left].pauli_x_error
                right_x = state.atoms[right].pauli_x_error
                self.backend.apply_2q(state.atoms[left], state.atoms[right], parameters["gate"])
                state.atoms[left].pauli_z_error ^= right_x
                state.atoms[right].pauli_z_error ^= left_x
            self._apply_control_noise(task, entry, state)
        elif opcode is PhysicalOpcode.RESET_ATOMS:
            for atom in self._present_atoms(task.instruction.operands, state):
                self.backend.reset(atom, parameters["state"])
                atom.pauli_x_error = atom.pauli_z_error = False
                if parameters["purpose"] == "ancilla-loss-replacement" and atom.site_id is not None:
                    site = state.sites[atom.site_id]
                    if site.role is not AtomRole.ANCILLA or not site.known_erasure:
                        raise ContractValidationError("ancilla replacement reset requires a known ancilla erasure")
                    state.resolve_erasure(site.site_id)
            self._apply_control_noise(task, entry, state)
        elif opcode is PhysicalOpcode.LOAD_RESERVOIR_ATOM:
            atom_id = task.instruction.operands[0]
            state.atoms[atom_id] = AtomState(atom_id, AtomRole.RESERVOIR, self.target.bindings.reservoir_zone_id)
        elif opcode is PhysicalOpcode.PLACE_ATOM:
            atom = state.atoms[task.instruction.operands[0]]
            site = state.sites[parameters["destination_site_id"]]
            block = state.blocks[site.block_id]
            if block.zone_id is None:
                raise ContractValidationError("cannot place an atom into a block without one current zone")
            site.atom_id = atom.atom_id
            atom.role = AtomRole.REPLACEMENT
            atom.block_id = site.block_id
            atom.site_id = site.site_id
            atom.zone_id = block.zone_id
            atom.trajectory_id = None
            atom.qubit_label = QubitLabel.ZERO
            atom.pauli_x_error = atom.pauli_z_error = False
        elif opcode is PhysicalOpcode.IMAGE_ATOMS:
            emitted: list[Observation] = []
            for atom_id in task.instruction.operands:
                emitted.append(self._presence_observation(
                    task, state, run_id, observation_offset + len(emitted), atom_id,
                ))
                atom = state.atoms.get(atom_id)
                if atom is not None and not atom.present and atom.site_id is not None:
                    site = state.sites[atom.site_id]
                    if not site.known_erasure:
                        state.register_detected_erasure(atom_id)
                        emitted.append(Observation(
                            f"obs-{run_id}-{observation_offset + len(emitted):04d}",
                            ObservationKind.ATOM_LOSS, state.now_ns, task.task_id,
                            {
                                "atom_id": atom.atom_id, "block_id": site.block_id,
                                "site_id": site.site_id, "atom_role": site.role.value,
                            },
                        ))
            return tuple(emitted)
        elif opcode is PhysicalOpcode.MEASURE_ATOMS:
            if parameters["profile"] == "syndrome-readout-v0.1":
                return (self._syndrome_observation(task, state, run_id, observation_offset),)
            return tuple(self._measurement_observation(task, state, run_id, observation_offset + index, atom, parameters["basis"]) for index, atom in enumerate(self._present_atoms(task.instruction.operands, state)))
        return ()

    def _presence_observation(self, task: PhysicalTask, state: MachineState, run_id: str, index: int, atom_id: str) -> Observation:
        atom = state.atoms.get(atom_id)
        payload = {"atom_id": atom_id, "present": bool(atom and atom.present), "zone_id": atom.zone_id if atom else None}
        return Observation(f"obs-{run_id}-{index:04d}", ObservationKind.ATOM_PRESENCE, state.now_ns, task.task_id, payload)

    def _measurement_observation(self, task: PhysicalTask, state: MachineState, run_id: str, index: int, atom: AtomState, basis: str) -> Observation:
        value = self.backend.measure(atom, basis)
        value ^= int(atom.pauli_x_error if basis == "z" else atom.pauli_z_error)
        flip = self.noise_model.measurement_flip(task.task_id, atom.atom_id, state.now_ns)
        if flip is not None:
            value ^= 1
            self._noise_events.append(flip)
        atom.pauli_x_error = atom.pauli_z_error = False
        return Observation(f"obs-{run_id}-{index:04d}", ObservationKind.MEASUREMENT, state.now_ns, task.task_id, {"atom_id": atom.atom_id, "basis": basis, "value": value})

    def _syndrome_observation(
        self, task: PhysicalTask, state: MachineState, run_id: str, index: int,
    ) -> Observation:
        parameters = task.instruction.parameters
        ancillas = self._present_atoms(task.instruction.operands, state)
        by_id = {atom.atom_id: atom for atom in ancillas}
        bits: dict[str, int] = {}
        for check_id, check in parameters["checks"].items():
            ancilla = by_id[check["ancilla_atom_id"]]
            self.backend.measure(ancilla, parameters["basis"])
            ancilla.pauli_x_error = ancilla.pauli_z_error = False
            bit = self.backend.syndrome_bit(
                check_id, check["basis"], tuple(check["data_atom_ids"]),
            )
            for atom_id in check["data_atom_ids"]:
                atom = state.atoms[atom_id]
                bit ^= int(
                    atom.pauli_x_error if check["basis"] == "Z"
                    else atom.pauli_z_error
                )
            flip = self.noise_model.syndrome_flip(task.task_id, check_id, state.now_ns)
            if flip is not None:
                bit ^= 1
                self._noise_events.append(flip)
            if bit not in (0, 1) or isinstance(bit, bool):
                raise ContractValidationError("state backend syndrome bit must be integer zero or one")
            bits[check_id] = bit
        return Observation(
            f"obs-{run_id}-{index:04d}", ObservationKind.SYNDROME,
            state.now_ns, task.task_id,
            {
                "block_id": parameters["block_id"],
                "logical_qubit_id": parameters["logical_qubit_id"],
                "layout_id": parameters["layout_id"],
                "round_index": parameters["round_index"],
                "bits": bits,
            },
        )

    def _apply_control_noise(
        self, task: PhysicalTask, entry: ScheduledTask, state: MachineState,
    ) -> None:
        atoms = tuple(dict.fromkeys(
            atom_id for atom_id in task.instruction.operands
            if atom_id in state.atoms and state.atoms[atom_id].present
        ))
        faults = self.noise_model.pauli_faults(
            task.task_id, task.instruction.opcode.value, atoms, state.now_ns,
            self._parallel_rydberg_neighbors.get(task.task_id, 0),
        )
        for fault in faults:
            atom = state.atoms[fault.atom_id]
            atom.pauli_x_error ^= fault.pauli in {PauliFaultKind.X, PauliFaultKind.Y}
            atom.pauli_z_error ^= fault.pauli in {PauliFaultKind.Z, PauliFaultKind.Y}
            self._noise_events.append(fault.event)

    def _snapshot(self, snapshot_id: str, state: MachineState) -> MachineSnapshot:
        occupancy = state.zone_occupancy(self.target)
        blocks = {key: value.zone_id or f"in_transit:{value.trajectory_id}" for key, value in sorted(state.blocks.items())}
        atom_locations = {
            key: (value.zone_id or (f"in_transit:{value.trajectory_id}" if value.present else "absent"))
            for key, value in sorted(state.atoms.items())
        }
        labels: dict[str, int] = {}
        for atom in state.atoms.values():
            labels[atom.qubit_label.value] = labels.get(atom.qubit_label.value, 0) + 1
        primitive = {
            "time": state.now_ns, "zones": occupancy, "blocks": blocks, "atoms": atom_locations, "labels": labels,
            "present": sum(atom.present for atom in state.atoms.values()),
            "erasures": sum(site.known_erasure for site in state.sites.values()),
            "pauli_errors": {
                key: (value.pauli_x_error, value.pauli_z_error)
                for key, value in sorted(state.atoms.items())
                if value.pauli_x_error or value.pauli_z_error
            },
            "aligned": sorted(state.aligned_pairs),
            "sites": {key: (value.atom_id, value.known_erasure) for key, value in sorted(state.sites.items())},
        }
        digest = sha256(canonical_json(primitive).encode()).hexdigest()
        return MachineSnapshot(
            snapshot_id, state.now_ns, occupancy, blocks, atom_locations, labels,
            primitive["present"], primitive["erasures"],
            sum(atom.present and atom.zone_id == self.target.bindings.reservoir_zone_id for atom in state.atoms.values()),
            len(state.aligned_pairs), digest,
        )

    def _event(
        self, event_id: str, kind: TraceEventKind, occurred_at: int,
        task: PhysicalTask, entry: ScheduledTask, digest: str,
        observation_id: str | None = None,
    ) -> ExecutionEvent:
        trajectory_id = task.instruction.parameters.get("trajectory_id")
        return ExecutionEvent(
            event_id, kind, occurred_at, task.task_id, task.instruction.opcode,
            entry.start_ns, entry.end_ns,
            tuple(item.resource_id for item in entry.resource_assignments),
            tuple(item.zone_id for item in entry.zone_assignments),
            trajectory_id, observation_id, task.provenance, digest,
        )

    @staticmethod
    def _block(block_id: str, state: MachineState):
        if block_id not in state.blocks:
            raise ContractValidationError(f"unknown block {block_id!r}")
        return state.blocks[block_id]

    @staticmethod
    def _atoms(atom_ids: tuple[str, ...], state: MachineState) -> tuple[AtomState, ...]:
        try:
            return tuple(state.atoms[atom_id] for atom_id in atom_ids)
        except KeyError as exc:
            raise ContractValidationError(f"unknown atom {exc.args[0]!r}") from exc

    def _present_atoms(self, atom_ids: tuple[str, ...], state: MachineState) -> tuple[AtomState, ...]:
        atoms = self._atoms(atom_ids, state)
        if any(not atom.present or atom.zone_id is None for atom in atoms):
            raise ContractValidationError("operation requires present atoms in a zone")
        return atoms

    @staticmethod
    def _clear_alignment(atom_ids: set[str], state: MachineState) -> None:
        state.aligned_pairs = {pair for pair in state.aligned_pairs if not atom_ids.intersection(pair)}

    @staticmethod
    def _refresh_block_locations(state: MachineState) -> None:
        for block in state.blocks.values():
            zones = {
                state.atoms[atom_id].zone_id for site_id in block.site_ids
                if (atom_id := state.sites[site_id].atom_id) is not None
            }
            block.zone_id = zones.pop() if len(zones) == 1 else None
            block.trajectory_id = None

