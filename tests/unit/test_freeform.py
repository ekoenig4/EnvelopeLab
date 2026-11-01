"""Free-form shapes from a mesh: clipping, panels, flattening, sub-model."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import build_appendage
from envelopelab.features.primitives import (
    Dome,
    FreeformShape,
    Placement,
    PrimitiveError,
    design_primitive,
    primitive_appendage,
)
from envelopelab.io.blender import MeshObject, read_shape_mesh, write_obj_scene
from envelopelab.io.reference_mesh import ReferenceMesh
from envelopelab.solvers.model import OperatingConditions
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.primitives import SPHERE_RADIUS, ellipsoid_mesh, sphere_envelope

SPHERE = sphere_envelope()
EQUATOR = 0.35 * math.pi * SPHERE_RADIUS
BLOB = ellipsoid_mesh(1.0, 0.7, 1.4, -0.3)
HOT = OperatingConditions.hot_air(
    celsius_to_kelvin(100.0), mouth_height=float(SPHERE.profile.z[0]), self_weight=False
)


def _checks(d: object) -> dict[str, float]:
    return {c.name: c.value for c in d.checks}  # type: ignore[attr-defined]


def test_mesh_is_clipped_at_the_envelope_and_cut_into_true_length_panels() -> None:
    d = design_primitive(FreeformShape("blob", Placement(2, EQUATOR), BLOB, 8), SPHERE, 0.01, 0.2)
    c = _checks(d)
    assert c["rim length"] < 1e-6 and c["skin seam match"] < 1e-6
    assert c["seam flattening"] < 1e-6
    # Seam crossings of the rim are interpolated along a rim chord (sagitta < 0.1 mm).
    assert np.abs(SPHERE.signed_distance(d.footprint_points)).max() < 1e-4
    assert [p.label for p in d.pieces] == [f"blob-P{k}" for k in range(1, 9)]
    assert d.designed_height == pytest.approx(1.1, abs=2e-3)
    assert len(d.marks) == 16 and d.marks[0].phi_deg == 0.0
    for piece in d.pieces:
        assert piece.rim is not None and piece.flat_area > 0.0
        assert piece.cut.min(axis=0)[1] < piece.finished.min(axis=0)[1]
    d16 = design_primitive(FreeformShape("blob", Placement(2, EQUATOR), BLOB, 16), SPHERE)
    assert _checks(d16)["area distortion"] < 0.5 * c["area distortion"]
    assert _checks(d16)["edge strain"] < c["edge strain"]


def test_sphere_mesh_matches_the_parametric_dome() -> None:
    ball = ellipsoid_mesh(1.0, 1.0, 1.0, 0.0, rings=48, segments=96)
    mesh = design_primitive(FreeformShape("m", Placement(2, EQUATOR), ball, 12), SPHERE)
    dome = design_primitive(Dome("d", Placement(2, EQUATOR), 1.0, 1.0, 12), SPHERE)
    # Two spheres (r = 1 m round the base point, the envelope R round its centre) meet
    # in a circle of radius r sqrt(1 - (r / 2R)^2); the inscribed mesh is within its
    # chord error of it.
    exact = 2.0 * math.pi * math.sqrt(1.0 - (1.0 / (2.0 * SPHERE_RADIUS)) ** 2)
    assert mesh.footprint_length == pytest.approx(exact, rel=1e-3)
    assert mesh.designed_height == pytest.approx(dome.designed_height, abs=2e-3)
    flat = sum(p.flat_area for p in mesh.pieces)
    assert flat == pytest.approx(sum(p.flat_area for p in dome.pieces), rel=0.01)


def test_blender_obj_round_trip_places_the_same_shape(tmp_path: Path) -> None:
    path = write_obj_scene(
        tmp_path / "blob.obj", [MeshObject("blob", BLOB.vertices, BLOB.triangles)]
    )
    back = read_shape_mesh(path)
    a = design_primitive(FreeformShape("b", Placement(2, EQUATOR), back, 6), SPHERE)
    b = design_primitive(FreeformShape("b", Placement(2, EQUATOR), BLOB, 6), SPHERE)
    assert a.footprint_length == pytest.approx(b.footprint_length, rel=1e-6)  # 6-digit OBJ


def test_meshes_that_do_not_fit_are_rejected() -> None:
    above = ReferenceMesh(BLOB.vertices + np.array([0.0, 0.0, 2.0]), BLOB.triangles)
    with pytest.raises(PrimitiveError, match="does not reach into the envelope"):
        design_primitive(FreeformShape("a", Placement(2, EQUATOR), above, 6), SPHERE)
    top = BLOB.vertices[BLOB.triangles].mean(axis=1)[:, 2] > 0.9
    holed = ReferenceMesh(BLOB.vertices, BLOB.triangles[~top])
    with pytest.raises(PrimitiveError, match="open edges|axis"):
        design_primitive(FreeformShape("a", Placement(2, EQUATOR), holed, 6), SPHERE)
    with pytest.raises(PrimitiveError, match="at least 2 panels"):
        design_primitive(FreeformShape("a", Placement(2, EQUATOR), BLOB, 1), SPHERE)


def test_freeform_sub_model_rests_in_its_flat_panels() -> None:
    d = design_primitive(FreeformShape("blob", Placement(2, EQUATOR), BLOB, 8), SPHERE, 0.01, 0.2)
    spec = primitive_appendage(d, 0.3, load_tape=GENERIC_TAPE)
    am = build_appendage(spec, HOT, {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC})
    model = am.model
    skin = model.triangles[am.skin_triangles]
    rest = model.rest_uv[am.skin_triangles]
    area = 0.5 * (
        (rest[:, 1, 0] - rest[:, 0, 0]) * (rest[:, 2, 1] - rest[:, 0, 1])
        - (rest[:, 1, 1] - rest[:, 0, 1]) * (rest[:, 2, 0] - rest[:, 0, 0])
    )
    assert np.all(area > 0.0)
    assert area.sum() == pytest.approx(sum(p.flat_area for p in d.pieces), rel=0.02)
    edges = np.sort(np.concatenate([skin[:, [0, 1]], skin[:, [1, 2]], skin[:, [2, 0]]]), axis=1)
    uniq, count = np.unique(edges, axis=0, return_counts=True)
    assert np.isin(uniq[count == 1], am.rim_nodes).all()
    assert len(uniq[count == 1]) == len(am.rim_nodes)
    assert sum(1 for s in model.seams if s.name.startswith("blob:seam")) == 8


@pytest.mark.slow
def test_freeform_shape_inflates_to_its_designed_height() -> None:
    from envelopelab.features.metrics import appendage_metrics
    from envelopelab.solvers.dynamic_relaxation import solve
    from envelopelab.solvers.simulation import from_preview

    d = design_primitive(FreeformShape("blob", Placement(2, EQUATOR), BLOB, 16), SPHERE, 0.01, 0.2)
    am = build_appendage(
        primitive_appendage(d, 0.2, load_tape=GENERIC_TAPE),
        HOT,
        {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC},
    )
    result = from_preview(am.model, solve(am.model))
    assert result.converged
    m = appendage_metrics(am, result)
    assert m.projected_height == pytest.approx(d.designed_height, rel=0.01)


def test_freeform_attachment_ease_adds_up_to_rim_minus_marked_line() -> None:
    d = design_primitive(FreeformShape("blob", Placement(2, EQUATOR), BLOB, 8), SPHERE)
    rims = [c.rim for c in d.pieces if c.rim is not None]
    rim = sum(float(np.linalg.norm(np.diff(r, axis=0), axis=1).sum()) for r in rims)
    marked = sum(a.length for a in d.attachment)
    assert len(d.mark_ease) == 16
    assert float(d.mark_ease.sum()) == pytest.approx(rim - marked, abs=5e-4)
    assert _checks(d)["attachment ease"] == pytest.approx(float(np.abs(d.mark_ease).max()))


def test_a_cap_closes_the_top_and_the_panels_end_on_its_edge() -> None:
    """With a cap, the panels end on a circle round the pole instead of a point."""
    rc = 0.15
    d = design_primitive(
        FreeformShape("blob", Placement(2, EQUATOR), BLOB, 8, cap_radius=rc), SPHERE, 0.01, 0.2
    )
    assert [p.label for p in d.pieces] == [*(f"blob-P{k}" for k in range(1, 9)), "blob-TIP"]
    c = _checks(d)
    assert c["cap seam match"] < 1e-9 and c["skin seam match"] < 1e-6
    cap = d.pieces[-1]
    assert cap.rim is None and len(cap.seam_points) == 8
    # The panel tops are sewn round the cap's edge, on the cylinder rho = rc about the
    # axis: at least the circle's length (more where the top is not level, < 1 % here).
    edge = float(np.linalg.norm(np.diff(cap.edges["top"], axis=0), axis=1).sum())
    assert 2.0 * math.pi * rc * (1.0 - 1e-3) < edge < 2.0 * math.pi * rc * 1.01
    skin = d._skin
    ring = skin.cap.x[skin.cap.top] - d.base_point
    rho = np.linalg.norm(ring - np.outer(ring @ d.axis, d.axis), axis=1)
    assert rho.max() == pytest.approx(rc, abs=1e-9)
    for piece in d.pieces[:-1]:
        top = piece.edges["top"]
        assert len(top) > 1 and float(np.linalg.norm(np.diff(top, axis=0), axis=1).sum()) > 0.1
    # The seams meet the cap where the panels' tops end, at the cap's edge, in order.
    finished = cap.finished
    for x, y in cap.seam_points:
        assert np.min(np.linalg.norm(finished - [x, y], axis=1)) < 1e-12
    # The cap lifts nothing off the designed shape: same footprint and height.
    plain = design_primitive(FreeformShape("blob", Placement(2, EQUATOR), BLOB, 8), SPHERE)
    assert d.footprint_length == pytest.approx(plain.footprint_length, rel=1e-9)
    assert d.designed_height == pytest.approx(plain.designed_height, abs=1e-9)
    assert sum(p.surface_area for p in d.pieces) == pytest.approx(
        sum(p.surface_area for p in plain.pieces), rel=1e-9
    )


def test_a_cap_that_does_not_fit_on_the_top_is_rejected() -> None:
    with pytest.raises(PrimitiveError, match="cap of diameter 2.000 m reaches the footprint"):
        design_primitive(FreeformShape("a", Placement(2, EQUATOR), BLOB, 6, cap_radius=1.0), SPHERE)
    with pytest.raises(PrimitiveError, match="cap radius must not be negative"):
        design_primitive(
            FreeformShape("a", Placement(2, EQUATOR), BLOB, 6, cap_radius=-0.1), SPHERE
        )


def test_capped_sub_model_shares_the_cap_circle_nodes() -> None:
    d = design_primitive(
        FreeformShape("blob", Placement(2, EQUATOR), BLOB, 8, cap_radius=0.15), SPHERE, 0.01, 0.2
    )
    am = build_appendage(
        primitive_appendage(d, 0.1, load_tape=GENERIC_TAPE),
        HOT,
        {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC},
    )
    model = am.model
    skin = model.triangles[am.skin_triangles]
    rest = model.rest_uv[am.skin_triangles]
    area = 0.5 * (
        (rest[:, 1, 0] - rest[:, 0, 0]) * (rest[:, 2, 1] - rest[:, 0, 1])
        - (rest[:, 1, 1] - rest[:, 0, 1]) * (rest[:, 2, 0] - rest[:, 0, 0])
    )
    assert np.all(area > 0.0)
    assert area.sum() == pytest.approx(sum(p.flat_area for p in d.pieces), rel=0.02)
    # Closed except for the rim: the cap is sewn to every panel along one shared circle.
    edges = np.sort(np.concatenate([skin[:, [0, 1]], skin[:, [1, 2]], skin[:, [2, 0]]]), axis=1)
    uniq, count = np.unique(edges, axis=0, return_counts=True)
    assert len(uniq[count == 1]) == len(am.rim_nodes)
    tip = next(s for s in model.seams if s.name == "blob:tip seam")
    ring = np.unique(tip.edges)
    assert len(ring) == len(tip.edges)  # one closed loop
    for j in range(1, 9):
        seam = next(s for s in model.seams if s.name == f"blob:seam {j}")
        assert np.isin(seam.edges, ring).sum() == 1  # each seam ends on the cap circle


@pytest.mark.slow
def test_capped_freeform_shape_inflates_to_its_designed_height() -> None:
    from envelopelab.features.metrics import appendage_metrics
    from envelopelab.solvers.dynamic_relaxation import solve
    from envelopelab.solvers.simulation import from_preview

    # A 0.10 m cap converges in about 17,000 iterations. A 0.15 m cap is a slow case
    # (111,000 to 283,000 iterations, depending on rounding-level differences in the node
    # numbering), too close to the solver's limit for a test.
    d = design_primitive(
        FreeformShape("blob", Placement(2, EQUATOR), BLOB, 16, cap_radius=0.10),
        SPHERE,
        0.01,
        0.2,
    )
    am = build_appendage(
        primitive_appendage(d, 0.2, load_tape=GENERIC_TAPE),
        HOT,
        {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC},
    )
    result = from_preview(am.model, solve(am.model))
    assert result.converged
    m = appendage_metrics(am, result)
    # The cap is cut flat, so it flattens the top: the height drops by at most the cap's
    # sagitta (its rise above its edge on the designed mesh), less what the cloth stretches.
    cap = d._skin.cap
    sagitta = float(((cap.x - d.base_point) @ d.axis).max()) - d._skin.cap_floor
    assert d.designed_height - sagitta < m.projected_height < d.designed_height


def test_closed_form_rotation_is_the_svd_rotation() -> None:
    """The ARAP local step's 2D rotation (closed form) equals the polar factor of an SVD
    with the reflection removed, as used before."""
    from envelopelab.features.freeform import _best_rotations

    rng = np.random.default_rng(7)
    cov = rng.normal(size=(500, 2, 2))
    c, s = _best_rotations(cov)
    uu, _, vt = np.linalg.svd(cov)
    rot = uu @ vt
    bad = np.linalg.det(rot) < 0
    uu[bad, :, 1] *= -1.0
    rot[bad] = uu[bad] @ vt[bad]
    assert np.allclose(rot[:, 0, 0], c, atol=1e-12) and np.allclose(rot[:, 1, 0], s, atol=1e-12)
    assert np.allclose(rot[:, 0, 1], -s, atol=1e-12) and np.allclose(rot[:, 1, 1], c, atol=1e-12)


def test_conformal_map_direct_solve_matches_the_iterative_one() -> None:
    from scipy.sparse import bmat, coo_matrix
    from scipy.sparse.linalg import lsqr

    from envelopelab.features.freeform import _local_frames, _lscm

    d = design_primitive(FreeformShape("blob", Placement(2, EQUATOR), BLOB, 8), SPHERE)
    panel = d._skin.panels[0]
    x, tri = panel.x, panel.tri
    pins = (panel.rim[0], panel.rim[-1])
    flat = _lscm(x, tri, pins)
    # The same least-squares problem solved iteratively (the former implementation).
    n = len(x)
    loc = _local_frames(x, tri)
    area = 0.5 * np.abs(loc[:, 1, 0] * loc[:, 2, 1])
    vals, cols = [], []
    for k in range(3):
        w = (loc[:, (k + 2) % 3] - loc[:, (k + 1) % 3]) / np.sqrt(2.0 * area)[:, None]
        vals.append(w[:, 0] + 1j * w[:, 1])
        cols.append(tri[:, k])
    rows = np.tile(np.arange(len(tri)), 3)
    m = coo_matrix((np.concatenate(vals), (rows, np.concatenate(cols))), shape=(len(tri), n))
    big = bmat([[m.real, -m.imag], [m.imag, m.real]]).tocsc()
    pin_idx = [pins[0], pins[1], pins[0] + n, pins[1] + n]
    free = np.setdiff1d(np.arange(2 * n), pin_idx)
    rhs = -big[:, pin_idx] @ np.array([0.0, 1.0, 0.0, 0.0])
    sol = lsqr(big[:, free], rhs, atol=1e-14, btol=1e-14, iter_lim=50000)[0]
    full = np.zeros(2 * n)
    full[free] = sol
    full[pin_idx] = [0.0, 1.0, 0.0, 0.0]
    assert np.abs(flat - np.column_stack([full[:n], full[n:]])).max() < 1e-8
