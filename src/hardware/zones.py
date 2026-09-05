"""Validated neutral-atom target bindings used by physical lowering."""

from __future__ import annotations

from dataclasses import dataclass

from compiler.physical_ir import PhysicalOpcode
from compiler.qec_ir import QECOpKind, QECProtocolIR
from contracts.common import ContractValidationError, require_id
from contracts.machine import CalibrationSnapshot, MachineConfig, ResourceSpec, ZoneKind, ZoneSpec
from hardware.geometry import MachineGeometry, Point2D, TrajectorySpec, ZoneGeometry


@dataclass(frozen=True, slots=True)
class HardwareResourceBindings:
    storage_zone_id: str
    entangling_zone_id: str
    readout_zone_id: str
    reservoir_zone_id: str
    transport_resource_id: str
    one_qubit_resource_id: str
    rydberg_resource_id: str
    imaging_resource_id: str
    readout_resource_id: str
    reset_resource_id: str
    reservoir_loading_resource_id: str
    clock_resource_id: str

    def __post_init__(self) -> None:
        for name in self.__slots__:
            require_id(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class NeutralAtomTarget:
    machine: MachineConfig
    geometry: MachineGeometry
    bindings: HardwareResourceBindings

    def __post_init__(self) -> None:
        machine_zones = {zone.zone_id: zone for zone in self.machine.zones}
        geometry_zones = {zone.zone_id for zone in self.geometry.zones}
        if geometry_zones != set(machine_zones):
            raise ContractValidationError("geometry must describe every machine zone exactly once")
        expected = {
            self.bindings.storage_zone_id: ZoneKind.STORAGE,
            self.bindings.entangling_zone_id: ZoneKind.ENTANGLING,
            self.bindings.readout_zone_id: ZoneKind.READOUT,
            self.bindings.reservoir_zone_id: ZoneKind.RESERVOIR,
        }
        for zone_id, kind in expected.items():
            if zone_id not in machine_zones or machine_zones[zone_id].kind is not kind:
                raise ContractValidationError(f"binding {zone_id!r} does not reference a {kind.value} zone")
        resources = {resource.resource_id: resource.resource_class for resource in self.machine.resources}
        required = {
            self.bindings.transport_resource_id: "transport",
            self.bindings.one_qubit_resource_id: "one_qubit_control",
            self.bindings.rydberg_resource_id: "rydberg_control",
            self.bindings.imaging_resource_id: "imaging",
            self.bindings.readout_resource_id: "readout",
            self.bindings.reset_resource_id: "reset",
            self.bindings.reservoir_loading_resource_id: "reservoir_loading",
            self.bindings.clock_resource_id: "clock",
        }
        for resource_id, resource_class in required.items():
            if resources.get(resource_id) != resource_class:
                raise ContractValidationError(f"resource {resource_id!r} is not class {resource_class!r}")
        for trajectory in self.geometry.trajectories:
            for group_id in trajectory.conflict_group_ids:
                if resources.get(group_id) != "transport_corridor":
                    raise ContractValidationError(f"trajectory conflict group {group_id!r} is not a transport_corridor resource")

    def validate_protocol_capacity(self, protocol: QECProtocolIR) -> None:
        capacities = {zone.kind: zone.capacity for zone in self.machine.zones}
        block_sizes = [len(block.data_site_ids) + len(block.ancilla_site_ids) for block in protocol.blocks]
        if sum(block_sizes) > capacities[ZoneKind.STORAGE]:
            raise ContractValidationError("protocol exceeds finite storage-zone atom capacity")
        blocks = {block.block_id: block for block in protocol.blocks}
        entangling_loads = [
            sum(len(blocks[block_id].data_site_ids) + len(blocks[block_id].ancilla_site_ids) for block_id in op.block_ids)
            for op in protocol.operations if op.kind is QECOpKind.TRANSVERSAL_CNOT
        ]
        readout_loads = [
            len(blocks[op.block_ids[0]].data_site_ids) + len(blocks[op.block_ids[0]].ancilla_site_ids)
            for op in protocol.operations if op.kind is QECOpKind.MEASURE_LOGICAL
        ]
        if entangling_loads and max(entangling_loads) > capacities[ZoneKind.ENTANGLING]:
            raise ContractValidationError("transversal operation exceeds finite entangling-zone atom capacity")
        if readout_loads and max(readout_loads) > capacities[ZoneKind.READOUT]:
            raise ContractValidationError("logical measurement exceeds finite readout-zone atom capacity")


def build_reference_target() -> NeutralAtomTarget:
    """Return the explicit, finite-capacity target used by the M2 GHZ demo."""

    zones = (
        ZoneSpec("storage", ZoneKind.STORAGE, 256),
        ZoneSpec("entangling", ZoneKind.ENTANGLING, 256),
        ZoneSpec("readout", ZoneKind.READOUT, 256),
        ZoneSpec("reservoir", ZoneKind.RESERVOIR, 128),
    )
    resource_classes = (
        ("aod-0", "transport"), ("oneq-0", "one_qubit_control"),
        ("rydberg-0", "rydberg_control"), ("camera-0", "imaging"),
        ("readout-0", "readout"), ("reset-0", "reset"),
        ("loader-0", "reservoir_loading"), ("clock-0", "clock"),
        ("corridor-storage-entangling", "transport_corridor"),
        ("corridor-storage-readout", "transport_corridor"),
        ("corridor-reservoir-storage", "transport_corridor"),
    )
    durations = {opcode.value: 1_000 for opcode in PhysicalOpcode}
    durations.update({
        PhysicalOpcode.APPLY_1Q_PULSE.value: 500,
        PhysicalOpcode.APPLY_2Q_RYDBERG_GATE.value: 1_200,
        PhysicalOpcode.MEASURE_ATOMS.value: 20_000,
        PhysicalOpcode.RESET_ATOMS.value: 10_000,
        PhysicalOpcode.EMIT_SYNC.value: 100,
    })
    machine = MachineConfig(
        "reference-neutral-atom-v0.1", zones,
        tuple(ResourceSpec(resource_id, resource_class, 1) for resource_id, resource_class in resource_classes),
        CalibrationSnapshot("reference-calibration-v0.1", durations),
    )
    geometry = MachineGeometry(
        zones=(
            ZoneGeometry("storage", Point2D(0, 0), 100, 100),
            ZoneGeometry("entangling", Point2D(150, 0), 100, 100),
            ZoneGeometry("readout", Point2D(300, 0), 100, 100),
            ZoneGeometry("reservoir", Point2D(0, 150), 100, 100),
        ),
        trajectories=(
            TrajectorySpec("storage-to-entangling", "storage", "entangling", (Point2D(100, 50), Point2D(150, 50)), 50_000, ("corridor-storage-entangling",)),
            TrajectorySpec("entangling-to-storage", "entangling", "storage", (Point2D(150, 50), Point2D(100, 50)), 50_000, ("corridor-storage-entangling",)),
            TrajectorySpec("storage-to-readout", "storage", "readout", (Point2D(100, 50), Point2D(300, 50)), 80_000, ("corridor-storage-readout",)),
            TrajectorySpec("readout-to-storage", "readout", "storage", (Point2D(300, 50), Point2D(100, 50)), 80_000, ("corridor-storage-readout",)),
            TrajectorySpec("reservoir-to-storage", "reservoir", "storage", (Point2D(50, 150), Point2D(50, 100)), 40_000, ("corridor-reservoir-storage",)),
        ),
    )
    bindings = HardwareResourceBindings(
        "storage", "entangling", "readout", "reservoir", "aod-0", "oneq-0",
        "rydberg-0", "camera-0", "readout-0", "reset-0", "loader-0", "clock-0",
    )
    return NeutralAtomTarget(machine, geometry, bindings)
