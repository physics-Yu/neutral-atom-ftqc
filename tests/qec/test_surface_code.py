from __future__ import annotations

import pytest

from contracts import ContractValidationError
from qec.surface_code import (
    PauliBasis, SiteRole, SurfaceCodeLayout, SurfaceCodeSpec, generate_surface_code_layout,
)


@pytest.mark.parametrize("distance", [3, 5])
def test_rotated_planar_layout_counts_and_round_trip(distance: int) -> None:
    layout = generate_surface_code_layout(SurfaceCodeSpec(distance))
    assert len(layout.data_sites) == distance**2
    assert len(layout.ancilla_sites) == distance**2 - 1
    assert len(layout.stabilizers) == distance**2 - 1
    assert len(layout.x_stabilizers) == len(layout.z_stabilizers) == (distance**2 - 1) // 2
    assert {len(check.data_site_ids) for check in layout.stabilizers} == {2, 4}
    assert SurfaceCodeLayout.from_json(layout.to_json()) == layout


@pytest.mark.parametrize("distance", [3, 5])
def test_stabilizers_commute_and_logical_operators_anticommute(distance: int) -> None:
    layout = generate_surface_code_layout(SurfaceCodeSpec(distance))
    for x_check in layout.x_stabilizers:
        for z_check in layout.z_stabilizers:
            assert len(set(x_check.data_site_ids) & set(z_check.data_site_ids)) % 2 == 0
    for check in layout.z_stabilizers:
        assert len(set(check.data_site_ids) & set(layout.logical_x_support)) % 2 == 0
    for check in layout.x_stabilizers:
        assert len(set(check.data_site_ids) & set(layout.logical_z_support)) % 2 == 0
    assert len(set(layout.logical_x_support) & set(layout.logical_z_support)) == 1
    assert len(layout.logical_x_support) == len(layout.logical_z_support) == distance
    data_index = {site.site_id: index for index, site in enumerate(layout.data_sites)}
    rows = []
    for check in layout.stabilizers:
        offset = 0 if check.basis is PauliBasis.X else len(data_index)
        rows.append(sum(1 << (offset + data_index[site_id]) for site_id in check.data_site_ids))
    assert _gf2_rank(rows) == distance**2 - 1


def test_site_ids_coordinates_and_ancilla_roles_are_unique() -> None:
    layout = generate_surface_code_layout(SurfaceCodeSpec(3))
    assert len({site.site_id for site in layout.sites}) == len(layout.sites)
    assert len({site.coordinate for site in layout.sites}) == len(layout.sites)
    roles = {check.ancilla_site_id: check.basis for check in layout.stabilizers}
    for site in layout.ancilla_sites:
        expected = PauliBasis.X if site.role is SiteRole.X_ANCILLA else PauliBasis.Z
        assert roles[site.site_id] is expected


@pytest.mark.parametrize("distance", [1, 2, 4, 6])
def test_invalid_distance_is_rejected(distance: int) -> None:
    with pytest.raises(ContractValidationError, match="odd integer"):
        SurfaceCodeSpec(distance)


def _gf2_rank(rows: list[int]) -> int:
    rank = 0
    values = list(rows)
    while values:
        pivot = max(values)
        if pivot == 0:
            break
        rank += 1
        pivot_bit = 1 << (pivot.bit_length() - 1)
        values = [value ^ pivot if value & pivot_bit else value for value in values if value != pivot]
    return rank

