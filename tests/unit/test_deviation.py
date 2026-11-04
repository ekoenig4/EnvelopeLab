"""Unit tests: signed deviation of a solved shape from its design."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from envelopelab.project.deviation import (
    closest_points,
    deviation_at_nodes,
    interpolate_on_mesh,
    vertex_normals,
)
from envelopelab.validation.meshes import sphere

RADIUS = 2.0  # m (test value)


def test_closest_point_on_a_triangle_in_every_region() -> None:
    v = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    t = np.array([[0, 1, 2]])
    queries = np.array(
        [
            [0.2, 0.2, 0.5],  # above the face: straight down
            [-1.0, -1.0, 0.0],  # vertex a
            [2.0, -0.5, 0.0],  # vertex b
            [0.5, -1.0, 0.0],  # edge ab
            [1.0, 1.0, 0.0],  # edge bc
            [-1.0, 0.5, 0.0],  # edge ca
        ]
    )
    q, tri, w = closest_points(queries, v, t)
    expected = np.array(
        [
            [0.2, 0.2, 0.0],
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.5, 0.0, 0.0],
            [0.5, 0.5, 0.0],
            [0.0, 0.5, 0.0],
        ]
    )
    assert np.allclose(q, expected)
    assert (tri == 0).all()
    assert np.allclose(w.sum(axis=1), 1.0)


def test_normals_point_outward() -> None:
    mesh = sphere(RADIUS, 6)
    n = vertex_normals(mesh.positions, mesh.triangles)
    radial = mesh.positions / np.linalg.norm(mesh.positions, axis=1)[:, None]
    assert np.einsum("ij,ij->i", n, radial).min() > 0.95
    flipped = vertex_normals(mesh.positions, mesh.triangles[:, ::-1])
    assert np.einsum("ij,ij->i", flipped, radial).min() > 0.95  # winding does not matter


@pytest.mark.parametrize("delta", [0.05, -0.05])
def test_sphere_offset_matches_hand_calculation(delta: float) -> None:
    # Points on a sphere of radius R + delta against a dense design sphere of radius R:
    # d = delta everywhere, within the design's faceting error. A flat triangle inscribed
    # in the sphere sags rho^2 / (2 R) below it, rho its circumradius = h / sqrt(3) for an
    # equilateral triangle of edge h: h^2 / (6 R).
    design = sphere(RADIUS, 24)
    rng = np.random.default_rng(1)
    u = rng.normal(size=(200, 3))
    solved = (RADIUS + delta) * u / np.linalg.norm(u, axis=1)[:, None]
    d = deviation_at_nodes(solved, design.positions, design.triangles)
    p, t = design.positions, design.triangles
    edge = float(np.linalg.norm(p[t[:, 0]] - p[t[:, 1]], axis=1).max())
    facet = edge**2 / (6 * RADIUS)
    assert np.all(np.abs(d - delta) <= facet + 1e-9)
    assert np.sign(d).tolist() == [np.sign(delta)] * len(d)


def test_far_nodes_are_nan() -> None:
    design = sphere(RADIUS, 8)
    solved = np.array([[0.0, 0.0, RADIUS + 0.01], [0.0, 0.0, RADIUS + 5.0]])
    d = deviation_at_nodes(solved, design.positions, design.triangles, max_distance=1.0)
    assert np.isfinite(d[0]) and np.isnan(d[1])


def test_interpolation_reproduces_a_linear_field() -> None:
    mesh = sphere(RADIUS, 6)
    f = 3.0 * mesh.positions[:, 0] - 2.0 * mesh.positions[:, 2] + 1.0
    # Query points on the mesh itself (its triangle centroids): linear in each triangle.
    centroids = mesh.positions[mesh.triangles].mean(axis=1)
    got = interpolate_on_mesh(centroids, mesh.positions, mesh.triangles, f)
    want = 3.0 * centroids[:, 0] - 2.0 * centroids[:, 2] + 1.0
    assert np.allclose(got, want, atol=1e-9)


def test_panel_mapping_places_grid_points_on_the_flat_rows() -> None:
    from envelopelab.project.deviation import panel_deviation
    from envelopelab.project.gore_design import display_stations, display_surface, panel_rows
    from envelopelab.project.session import ProjectSession

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
    session = ProjectSession.open(fixture)
    design = session.design
    assert design.gores is not None
    per_gore, per_row = 6, 8
    surface = display_surface(design, per_gore, per_row)
    s, _, _ = display_stations(design, per_row)
    m = design.gores.count * per_gore
    assert len(surface.points) == len(s) * m  # point i * m + j is station i
    # Value = tape length of the point; gore 3 (columns 12..17, its right seam excluded)
    # one metre more, so it is always the worst.
    values = np.repeat(s, m).astype(float).reshape(len(s), m)
    values[:, 2 * per_gore + 1 : 3 * per_gore] += 1.0
    rows = panel_rows(design, session.patterns)
    heat = panel_deviation(design, rows, values.ravel(), per_gore, per_row)
    assert [h.row for h in heat] == [r.label for r in rows]
    for h, row in zip(heat, rows, strict=True):
        interior = (h.gore == 3) & (np.abs(h.values - (h.points[:, 1] + row.s_bottom + 1.0)) < 1e-9)
        # Away from the gore's own seams every grid point takes gore 3's (larger) value.
        assert interior.sum() >= (per_gore - 1) * 2
        seam = ~(h.gore == 3)
        assert np.allclose(h.values[seam], h.points[seam, 1] + row.s_bottom)
        half = 0.5 * row.bottom_width
        bottom = h.points[:, 1] < 1e-9
        assert np.isclose(h.points[bottom, 0].max(), half, atol=1e-6)
        assert np.isclose(h.points[bottom, 0].min(), -half, atol=1e-6)
        assert np.isclose(h.points[:, 1].max(), row.s_top - row.s_bottom, atol=1e-9)
