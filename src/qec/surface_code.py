"""Distance-parameterized rotated planar surface-code geometry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from contracts.common import (
    SCHEMA_VERSION, ContractValidationError, canonical_json, parse_json,
    require_id, require_schema, to_primitive,
)


class SurfaceCodeLayoutKind(StrEnum):
    ROTATED_PLANAR = "rotated_planar"


class SiteRole(StrEnum):
    DATA = "data"
    X_ANCILLA = "x_ancilla"
    Z_ANCILLA = "z_ancilla"


class PauliBasis(StrEnum):
    X = "X"
    Z = "Z"


@dataclass(frozen=True, slots=True, order=True)
class LatticeCoordinate:
    """Coordinate in half-trap-spacing lattice units, avoiding floats."""

    x: int
    y: int

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (self.x, self.y)):
            raise ContractValidationError("lattice coordinates must be integers")


@dataclass(frozen=True, slots=True)
class SurfaceCodeSpec:
    distance: int
    layout_kind: SurfaceCodeLayoutKind = SurfaceCodeLayoutKind.ROTATED_PLANAR

    def __post_init__(self) -> None:
        if not isinstance(self.distance, int) or isinstance(self.distance, bool):
            raise ContractValidationError("distance must be an integer")
        if self.distance < 3 or self.distance % 2 == 0:
            raise ContractValidationError("surface-code distance must be an odd integer >= 3")
        if self.layout_kind is not SurfaceCodeLayoutKind.ROTATED_PLANAR:
            raise ContractValidationError("only rotated_planar is supported in M1")


@dataclass(frozen=True, slots=True)
class PhysicalSite:
    site_id: str
    role: SiteRole
    coordinate: LatticeCoordinate

    def __post_init__(self) -> None:
        require_id(self.site_id, "site_id")
        if not isinstance(self.role, SiteRole):
            raise ContractValidationError("role must be a SiteRole")


@dataclass(frozen=True, slots=True)
class StabilizerCheck:
    check_id: str
    basis: PauliBasis
    ancilla_site_id: str
    data_site_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_id(self.check_id, "check_id")
        require_id(self.ancilla_site_id, "ancilla_site_id")
        if not isinstance(self.basis, PauliBasis):
            raise ContractValidationError("basis must be a PauliBasis")
        if len(self.data_site_ids) not in (2, 4):
            raise ContractValidationError("rotated-planar checks must have weight two or four")
        if len(self.data_site_ids) != len(set(self.data_site_ids)):
            raise ContractValidationError("stabilizer support must not contain duplicate sites")


@dataclass(frozen=True, slots=True)
class SurfaceCodeLayout:
    layout_id: str
    spec: SurfaceCodeSpec
    sites: tuple[PhysicalSite, ...]
    stabilizers: tuple[StabilizerCheck, ...]
    logical_x_support: tuple[str, ...]
    logical_z_support: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_schema(self.schema_version)
        require_id(self.layout_id, "layout_id")
        site_ids = [site.site_id for site in self.sites]
        check_ids = [check.check_id for check in self.stabilizers]
        coordinates = [site.coordinate for site in self.sites]
        if len(site_ids) != len(set(site_ids)):
            raise ContractValidationError("surface-code site IDs must be unique")
        if len(check_ids) != len(set(check_ids)):
            raise ContractValidationError("stabilizer IDs must be unique")
        if len(coordinates) != len(set(coordinates)):
            raise ContractValidationError("surface-code coordinates must be unique")

        site_by_id = {site.site_id: site for site in self.sites}
        data_ids = {site.site_id for site in self.sites if site.role is SiteRole.DATA}
        ancilla_ids = set(site_ids) - data_ids
        distance = self.spec.distance
        if len(data_ids) != distance**2:
            raise ContractValidationError("rotated planar layout must contain d^2 data sites")
        if len(ancilla_ids) != distance**2 - 1:
            raise ContractValidationError("rotated planar layout must contain d^2-1 ancilla sites")
        for check in self.stabilizers:
            if check.ancilla_site_id not in ancilla_ids:
                raise ContractValidationError("stabilizer references an unknown ancilla site")
            if not set(check.data_site_ids) <= data_ids:
                raise ContractValidationError("stabilizer references an unknown data site")
            expected_role = SiteRole.X_ANCILLA if check.basis is PauliBasis.X else SiteRole.Z_ANCILLA
            if site_by_id[check.ancilla_site_id].role is not expected_role:
                raise ContractValidationError("stabilizer basis and ancilla role disagree")
        check_ancillas = [check.ancilla_site_id for check in self.stabilizers]
        if len(check_ancillas) != len(set(check_ancillas)) or set(check_ancillas) != ancilla_ids:
            raise ContractValidationError("every ancilla site must own exactly one stabilizer")
        if set(self.logical_x_support) - data_ids or set(self.logical_z_support) - data_ids:
            raise ContractValidationError("logical support references an unknown data site")
        if len(self.logical_x_support) != distance or len(self.logical_z_support) != distance:
            raise ContractValidationError("logical operators must have weight d")
        if len(set(self.logical_x_support) & set(self.logical_z_support)) % 2 != 1:
            raise ContractValidationError("logical X and Z must anticommute")
        _validate_commutation(self.stabilizers)
        for check in self.z_stabilizers:
            if len(set(self.logical_x_support) & set(check.data_site_ids)) % 2:
                raise ContractValidationError("logical X must commute with every Z stabilizer")
        for check in self.x_stabilizers:
            if len(set(self.logical_z_support) & set(check.data_site_ids)) % 2:
                raise ContractValidationError("logical Z must commute with every X stabilizer")

    @property
    def data_sites(self) -> tuple[PhysicalSite, ...]:
        return tuple(site for site in self.sites if site.role is SiteRole.DATA)

    @property
    def ancilla_sites(self) -> tuple[PhysicalSite, ...]:
        return tuple(site for site in self.sites if site.role is not SiteRole.DATA)

    @property
    def x_stabilizers(self) -> tuple[StabilizerCheck, ...]:
        return tuple(check for check in self.stabilizers if check.basis is PauliBasis.X)

    @property
    def z_stabilizers(self) -> tuple[StabilizerCheck, ...]:
        return tuple(check for check in self.stabilizers if check.basis is PauliBasis.Z)

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SurfaceCodeLayout":
        spec_data = data["spec"]
        return cls(
            layout_id=data["layout_id"],
            spec=SurfaceCodeSpec(
                distance=spec_data["distance"],
                layout_kind=SurfaceCodeLayoutKind(spec_data.get("layout_kind", "rotated_planar")),
            ),
            sites=tuple(
                PhysicalSite(
                    site_id=item["site_id"], role=SiteRole(item["role"]),
                    coordinate=LatticeCoordinate(item["coordinate"]["x"], item["coordinate"]["y"]),
                ) for item in data["sites"]
            ),
            stabilizers=tuple(
                StabilizerCheck(
                    check_id=item["check_id"], basis=PauliBasis(item["basis"]),
                    ancilla_site_id=item["ancilla_site_id"],
                    data_site_ids=tuple(item["data_site_ids"]),
                ) for item in data["stabilizers"]
            ),
            logical_x_support=tuple(data["logical_x_support"]),
            logical_z_support=tuple(data["logical_z_support"]),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, payload: str) -> "SurfaceCodeLayout":
        return cls.from_dict(parse_json(payload))


def generate_surface_code_layout(
    spec: SurfaceCodeSpec, layout_id: str | None = None
) -> SurfaceCodeLayout:
    """Generate the canonical M1 rotated planar layout for any supported distance."""

    if not isinstance(spec, SurfaceCodeSpec):
        raise ContractValidationError("spec must be a SurfaceCodeSpec")
    distance = spec.distance
    resolved_id = layout_id or f"rotated-planar-d{distance}"
    data: dict[tuple[int, int], str] = {}
    sites: list[PhysicalSite] = []
    checks: list[StabilizerCheck] = []

    for row in range(distance):
        for column in range(distance):
            site_id = f"data-r{row}-c{column}"
            data[(row, column)] = site_id
            sites.append(PhysicalSite(site_id, SiteRole.DATA, LatticeCoordinate(2 * column + 1, 2 * row + 1)))

    def add_check(name: str, basis: PauliBasis, x: int, y: int, support: tuple[tuple[int, int], ...]) -> None:
        role = SiteRole.X_ANCILLA if basis is PauliBasis.X else SiteRole.Z_ANCILLA
        ancilla_id = f"ancilla-{name}"
        sites.append(PhysicalSite(ancilla_id, role, LatticeCoordinate(x, y)))
        checks.append(StabilizerCheck(f"check-{name}", basis, ancilla_id, tuple(data[item] for item in support)))

    for row in range(distance - 1):
        for column in range(distance - 1):
            basis = PauliBasis.X if (row + column) % 2 == 0 else PauliBasis.Z
            add_check(
                f"interior-r{row}-c{column}", basis, 2 * column + 2, 2 * row + 2,
                ((row, column), (row, column + 1), (row + 1, column), (row + 1, column + 1)),
            )

    for column in range(1, distance - 1, 2):
        add_check(f"top-c{column}", PauliBasis.X, 2 * column + 2, 0, ((0, column), (0, column + 1)))
    for column in range(0, distance - 1, 2):
        add_check(
            f"bottom-c{column}", PauliBasis.X, 2 * column + 2, 2 * distance,
            ((distance - 1, column), (distance - 1, column + 1)),
        )
    for row in range(0, distance - 1, 2):
        add_check(f"left-r{row}", PauliBasis.Z, 0, 2 * row + 2, ((row, 0), (row + 1, 0)))
    for row in range(1, distance - 1, 2):
        add_check(
            f"right-r{row}", PauliBasis.Z, 2 * distance, 2 * row + 2,
            ((row, distance - 1), (row + 1, distance - 1)),
        )

    return SurfaceCodeLayout(
        layout_id=resolved_id,
        spec=spec,
        sites=tuple(sites),
        stabilizers=tuple(checks),
        logical_x_support=tuple(data[(row, 0)] for row in range(distance)),
        logical_z_support=tuple(data[(0, column)] for column in range(distance)),
    )


def _validate_commutation(stabilizers: tuple[StabilizerCheck, ...]) -> None:
    x_checks = [check for check in stabilizers if check.basis is PauliBasis.X]
    z_checks = [check for check in stabilizers if check.basis is PauliBasis.Z]
    for x_check in x_checks:
        for z_check in z_checks:
            overlap = set(x_check.data_site_ids) & set(z_check.data_site_ids)
            if len(overlap) % 2:
                raise ContractValidationError(
                    f"stabilizers {x_check.check_id!r} and {z_check.check_id!r} anticommute"
                )

