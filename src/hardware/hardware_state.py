"""Mutable, cloneable neutral-atom digital-twin machine state."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from compiler.qec_ir import QECProtocolIR
from contracts.common import ContractValidationError, require_id
from contracts.events import AtomRole
from hardware.atom import AtomState, BlockState, QubitLabel, SiteState
from hardware.zones import NeutralAtomTarget


@dataclass(slots=True)
class MachineState:
    machine_id: str
    now_ns: int
    atoms: dict[str, AtomState] = field(default_factory=dict)
    sites: dict[str, SiteState] = field(default_factory=dict)
    blocks: dict[str, BlockState] = field(default_factory=dict)
    aligned_pairs: set[tuple[str, str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        require_id(self.machine_id, "machine-state machine ID")
        if not isinstance(self.now_ns, int) or isinstance(self.now_ns, bool) or self.now_ns < 0:
            raise ContractValidationError("machine-state time must be non-negative")

    @classmethod
    def from_protocol(cls, protocol: QECProtocolIR, target: NeutralAtomTarget) -> "MachineState":
        storage = target.bindings.storage_zone_id
        atoms: dict[str, AtomState] = {}
        sites: dict[str, SiteState] = {}
        blocks: dict[str, BlockState] = {}
        for block in protocol.blocks:
            qualified_sites: list[str] = []
            for local_site_id in block.data_site_ids + block.ancilla_site_ids:
                site_id = f"{block.block_id}/{local_site_id}"
                role = AtomRole.DATA if local_site_id in block.data_site_ids else AtomRole.ANCILLA
                atoms[site_id] = AtomState(site_id, role, storage, block.block_id, site_id)
                sites[site_id] = SiteState(site_id, block.block_id, role, site_id)
                qualified_sites.append(site_id)
            blocks[block.block_id] = BlockState(block.block_id, tuple(qualified_sites), storage)
        state = cls(target.machine.machine_id, 0, atoms, sites, blocks)
        state.validate(target)
        return state

    def clone(self) -> "MachineState":
        return MachineState(
            self.machine_id, self.now_ns,
            {key: replace(value) for key, value in self.atoms.items()},
            {key: replace(value) for key, value in self.sites.items()},
            {key: replace(value) for key, value in self.blocks.items()},
            set(self.aligned_pairs),
        )

    def validate(self, target: NeutralAtomTarget) -> None:
        if self.machine_id != target.machine.machine_id:
            raise ContractValidationError("machine state and target machine IDs differ")
        zones = {zone.zone_id: zone.capacity for zone in target.machine.zones}
        occupancy = {zone_id: 0 for zone_id in zones}
        for atom_id, atom in self.atoms.items():
            if atom.atom_id != atom_id:
                raise ContractValidationError("atom dictionary key does not match atom identity")
            if atom.present:
                if atom.zone_id is None:
                    if atom.trajectory_id is None:
                        raise ContractValidationError("present atom without a zone must occupy a trajectory")
                elif atom.zone_id not in zones:
                    raise ContractValidationError("present atom must occupy a configured zone or trajectory")
                else:
                    occupancy[atom.zone_id] += 1
            if atom.site_id is not None:
                site = self.sites.get(atom.site_id)
                if site is None:
                    raise ContractValidationError("atom references an unknown site")
                if atom.present and site.atom_id != atom_id:
                    raise ContractValidationError("present atom/site occupancy is inconsistent")
        if any(occupancy[zone_id] > capacity for zone_id, capacity in zones.items()):
            raise ContractValidationError("persistent machine-state zone capacity exceeded")
        for site_id, site in self.sites.items():
            if site.site_id != site_id or site.block_id not in self.blocks:
                raise ContractValidationError("site identity or block reference is invalid")
            if site.atom_id is not None and (site.atom_id not in self.atoms or not self.atoms[site.atom_id].present):
                raise ContractValidationError("occupied site references an absent atom")
        for block_id, block in self.blocks.items():
            if block.block_id != block_id or any(site_id not in self.sites for site_id in block.site_ids):
                raise ContractValidationError("block identity or site references are invalid")
            if block.zone_id is not None:
                for site_id in block.site_ids:
                    atom_id = self.sites[site_id].atom_id
                    if atom_id is not None and self.atoms[atom_id].zone_id != block.zone_id:
                        raise ContractValidationError("block atoms must share the block zone")
        for pair in self.aligned_pairs:
            if len(pair) != 2 or any(atom_id not in self.atoms or not self.atoms[atom_id].present for atom_id in pair):
                raise ContractValidationError("aligned pair must reference two present atoms")
            if any(self.atoms[atom_id].zone_id != target.bindings.entangling_zone_id for atom_id in pair):
                raise ContractValidationError("aligned atoms must remain in the entangling zone")

    def zone_occupancy(self, target: NeutralAtomTarget) -> dict[str, int]:
        result = {zone.zone_id: 0 for zone in target.machine.zones}
        for atom in self.atoms.values():
            if atom.present and atom.zone_id is not None:
                result[atom.zone_id] += 1
        return result

    def add_reservoir_atom(self, atom_id: str, target: NeutralAtomTarget) -> None:
        """Seed one finite spare without assigning it to an encoded site."""

        require_id(atom_id, "reservoir atom ID")
        if atom_id in self.atoms:
            raise ContractValidationError("reservoir atom ID already exists")
        self.atoms[atom_id] = AtomState(
            atom_id, AtomRole.RESERVOIR, target.bindings.reservoir_zone_id,
        )
        self.validate(target)

    def mark_atom_lost(self, atom_id: str, *, detected: bool = True) -> None:
        """Remove a physical atom; detection may occur at a later image task."""

        atom = self.atoms.get(atom_id)
        if atom is None or not atom.present or atom.site_id is None:
            raise ContractValidationError("only a present, placed atom can be marked lost")
        site = self.sites[atom.site_id]
        site.atom_id = None
        site.known_erasure = detected
        atom.present = False
        atom.known_erasure = detected
        atom.zone_id = None
        atom.trajectory_id = None
        atom.qubit_label = QubitLabel.LOST

    def register_detected_erasure(self, atom_id: str) -> SiteState:
        """Promote an absent atom to a decoder-visible known erasure."""

        atom = self.atoms.get(atom_id)
        if atom is None or atom.present or atom.site_id is None:
            raise ContractValidationError("only an absent placed atom can be registered as an erasure")
        site = self.sites[atom.site_id]
        site.known_erasure = True
        atom.known_erasure = True
        return site

    def resolve_erasure(self, site_id: str) -> None:
        """Clear erasure metadata only after an explicit recovery decision."""

        site = self.sites.get(site_id)
        if site is None or not site.known_erasure or site.atom_id is None:
            raise ContractValidationError("resolved erasure must be an occupied known-erasure site")
        atom = self.atoms[site.atom_id]
        if not atom.present:
            raise ContractValidationError("resolved erasure replacement must be present")
        site.known_erasure = False
        atom.known_erasure = False
        atom.role = site.role

