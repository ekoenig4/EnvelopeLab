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
