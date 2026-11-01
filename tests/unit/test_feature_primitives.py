"""Special-shape primitives: placement, footprint, attachment, cutting pattern, sub-model."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import build_appendage
from envelopelab.features.primitives import (
    DEFAULT_TOLERANCE,
    Dome,
    EnvelopeSurface,
    Placement,
    PrimitiveError,
    Tube,
    design_primitive,
    primitive_appendage,
)
from envelopelab.project.gore_design import standard_gore_design
from envelopelab.solvers.model import OperatingConditions
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE
from envelopelab.validation.primitives import SPHERE_RADIUS, attachment_gap, sphere_envelope

SPHERE = sphere_envelope()
EQUATOR = 0.5 * math.pi * SPHERE_RADIUS - SPHERE.profile.s[0] - 0.15 * math.pi * SPHERE_RADIUS
HOT = OperatingConditions.hot_air(
    celsius_to_kelvin(100.0), mouth_height=float(SPHERE.profile.z[0]), self_weight=False
)


def _length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def test_envelope_surface_locates_points_and_signs_the_distance() -> None:
    s = np.array([5.0, 12.0, 18.0])
    theta = np.array([0.3, 2.0, 4.0])
    pts = SPHERE.point(s, theta)
    e_hoop, e_up, normal = SPHERE.frame(12.0, 2.0)
    assert abs(e_hoop @ e_up) < 1e-9 and abs(normal @ e_up) < 1e-9
    assert normal @ pts[1] > 0.0  # outward on a sphere centred at the origin
    out = pts + 0.05 * np.array([SPHERE.frame(a, b)[2] for a, b in zip(s, theta, strict=True)])
    s_got, th_got, dist = SPHERE.locate(out)
    assert s_got == pytest.approx(s, abs=1e-4)  # polyline against vertex normals
    assert th_got == pytest.approx(theta, abs=1e-9)
    assert dist == pytest.approx(0.05, abs=1e-6)
    assert SPHERE.signed_distance(0.5 * pts) == pytest.approx(-0.5 * SPHERE_RADIUS, abs=1e-3)


def test_gore_numbering_and_rows() -> None:
    assert SPHERE.theta_at(1, 0.0) == pytest.approx(0.5 * SPHERE.gore_angle)
    assert SPHERE.gore_position(np.array([SPHERE.theta_at(3, 0.25)]))[0] == pytest.approx(2.75)
    rows = SPHERE.rows
    assert SPHERE.row_index(np.array([0.0, rows[1].s_bottom + 1e-6, 1e9])).tolist() == [
        0,
        1,
        len(rows) - 1,
    ]


def test_upright_cylinder_develops_to_rectangles_on_its_footprint() -> None:
    tube = Tube("c", Placement(1, EQUATOR), 0.5, 0.5, 1.0, panels=3, marks_per_piece=2)
    d = design_primitive(tube, SPHERE, seam_allowance=0.01)
    delta = SPHERE_RADIUS - math.sqrt(SPHERE_RADIUS**2 - 0.25)
    assert d.footprint_length == pytest.approx(math.pi, rel=1e-4)
    assert SPHERE.signed_distance(d.footprint_points) == pytest.approx(0.0, abs=1e-6)
    labels = [p.label for p in d.pieces]
    assert labels == ["c-P1", "c-P2", "c-P3", "c-TIP"]
    for piece in d.pieces[:3]:
        width, height = piece.size
        assert width == pytest.approx(math.pi / 3, abs=1e-6)
        assert height == pytest.approx(1.0 + delta, abs=1e-6)
        assert piece.flat_area == pytest.approx(piece.surface_area, rel=1e-3)
        assert piece.cut.min(axis=0) == pytest.approx(piece.finished.min(axis=0) - 0.01, abs=1e-6)
    assert d.pieces[3].size == pytest.approx((1.0, 1.0), abs=1e-3)
    assert d.ok, [c for c in d.checks if not c.passed]
    assert len(d.marks) == 6
    assert d.marks[0].phi_deg == pytest.approx(0.0)
    # Mark 1 is the top of the feature: higher on the tape than the base point.
    assert d.marks[0].host_xy[1] > d.marks[3].host_xy[1]
    assert d.marks[0].host_xy[0] == pytest.approx(0.0, abs=1e-9)


def test_leaned_frustum_is_exact_and_its_footprint_follows_the_lean() -> None:
    up = design_primitive(Tube("h", Placement(2, EQUATOR), 0.6, 0.2, 2.0), SPHERE)
    lean = design_primitive(
        Tube("h", Placement(2, EQUATOR, lean_deg=30.0, lean_toward_deg=0.0), 0.6, 0.2, 2.0),
        SPHERE,
    )
    for d in (up, lean):
        checks = {c.name: c for c in d.checks}
        assert checks["skin seam match"].value < 1e-6
        assert checks["seam flattening"].value < 1e-6
        assert checks["area distortion"].value < 1e-3
        top = sum(_length(p.edges["top"]) for p in d.pieces[:4])
        assert top == pytest.approx(2 * math.pi * 0.2, rel=1e-5)
    # Leaning up the tape moves the tip towards the crown (higher) and closer to the
    # envelope.
    assert (lean.base_point + lean.axis)[2] > (up.base_point + up.axis)[2]
    assert lean.designed_height < up.designed_height


def test_dome_gores_match_at_every_seam_and_converge_with_gore_count() -> None:
    d8 = design_primitive(Dome("d", Placement(4, 11.0), 1.0, 0.8, gores=8), SPHERE)
    d16 = design_primitive(Dome("d", Placement(4, 11.0), 1.0, 0.8, gores=16), SPHERE)
    c8 = {c.name: c for c in d8.checks}
    c16 = {c.name: c for c in d16.checks}
    assert c8["skin seam match"].value < 1e-6 and c16["skin seam match"].value < 1e-6
    assert c8["rim length"].passed and c16["rim length"].passed
    ratio = c8["area distortion"].value / c16["area distortion"].value
    assert 3.0 < ratio < 5.0  # about 1/M^2
    assert c8["area distortion"].severity == "warning"
    for piece in d16.pieces:
        # One apex point per gore and a straight rim on y = 0.
        assert piece.rim is not None
        assert np.abs(piece.rim[:, 1]).max() < 1e-9
        assert np.isclose(piece.finished[:, 1], piece.finished[:, 1].max()).sum() == 1
    assert d16.designed_height == pytest.approx(0.8, abs=2e-3)


def test_attachment_lines_split_at_load_tapes_and_rows() -> None:
    s_row = SPHERE.rows[1].s_top
    d = design_primitive(Dome("x", Placement(5, s_row, across=0.5), 0.9, 0.6), SPHERE)
    keys = {(a.gore, a.row) for a in d.attachment}
    assert keys == {(5, "B"), (6, "B"), (5, "C"), (6, "C")}
    for line in d.attachment:
        row = next(r for r in SPHERE.rows if r.label == line.row)
        half = SPHERE.half_width(row.s_bottom + line.points[:, 1])
        assert np.all(np.abs(line.points[:, 0]) <= half + 1e-9)
        assert line.points[:, 1].min() >= -1e-9
        assert line.points[:, 1].max() <= row.s_top - row.s_bottom + 1e-9
    assert attachment_gap(d) < 1e-5
    total = sum(a.length for a in d.attachment)
    assert total == pytest.approx(d.footprint_length, rel=0.01)


def test_feed_hole_and_json_summary() -> None:
    d = design_primitive(Dome("e", Placement(3, 12.0), 1.0, 1.0), SPHERE, feed_hole_radius=0.3)
    assert d.feed_hole is not None and d.feed_hole.gore == 3
    assert d.feed_hole.centre_xy[0] == pytest.approx(0.0, abs=1e-9)
    summary = json.loads(json.dumps(d.as_dict()))
    assert summary["kind"] == "dome" and len(summary["pieces"]) == 8
    assert {c["name"] for c in summary["checks"]} >= {"rim length", "feed hole inside footprint"}
    big = design_primitive(Dome("e", Placement(3, 12.0), 1.0, 1.0), SPHERE, feed_hole_radius=1.2)
    assert any(c.name == "feed hole inside footprint" and c.severity == "error" for c in big.checks)


@pytest.mark.parametrize(
    "primitive, message",
    [
        (Dome("a", Placement(30, 10.0), 1.0, 1.0), "gore must be"),
        (Dome("a", Placement(1, 99.0), 1.0, 1.0), "tape position"),
        (Dome("a", Placement(1, 10.0), -1.0, 1.0), "positive"),
        (Tube("a", Placement(1, 10.0), 0.3, 0.5, 1.0), "tip radius"),
        (Dome("a", Placement(1, 10.0, across=0.7), 1.0, 1.0), "across"),
        (Dome("a", Placement(1, 10.0), 9.0, 1.0), "reach the envelope"),
        (Tube("a", Placement(1, 10.0, lean_deg=75.0), 1.0, 0.2, 0.3), "envelope"),
    ],
)
def test_invalid_primitives_are_rejected(primitive: Dome | Tube, message: str) -> None:
    with pytest.raises(PrimitiveError, match=message):
        design_primitive(primitive, SPHERE)


def test_from_design_uses_the_gore_design_rows_and_widths() -> None:
    design = standard_gore_design("generic", 2000.0, 17.0, 16.0, 12, 6)
    surface = EnvelopeSurface.from_design(design)
    assert surface.gore_count == 12
    assert [r.label for r in surface.rows] == [p.letter for p in design.gores.panel_rows]  # type: ignore[union-attr]
    assert surface.rows[-1].s_top == pytest.approx(surface.profile.meridian_length, abs=1e-3)
    s = np.array([8.0])
    r, _ = surface.radius_height(s)
    assert surface.half_width(s)[0] == pytest.approx(math.pi * r[0] / 12, rel=1e-3)


def test_designed_skin_rests_in_its_cut_pieces_and_is_sewn_to_the_footprint() -> None:
    d = design_primitive(
        Dome("pod", Placement(2, EQUATOR), 0.8, 0.6, gores=6), SPHERE, feed_hole_radius=0.25
    )
    spec = primitive_appendage(d, 0.3, load_tape=GENERIC_TAPE, rim_tape=GENERIC_TAPE)
    am = build_appendage(spec, HOT, {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC})
    model = am.model
    skin = model.triangles[am.skin_triangles]
    rest = model.rest_uv[am.skin_triangles]
    area = 0.5 * (
        (rest[:, 1, 0] - rest[:, 0, 0]) * (rest[:, 2, 1] - rest[:, 0, 1])
        - (rest[:, 1, 1] - rest[:, 0, 1]) * (rest[:, 2, 0] - rest[:, 0, 0])
    )
    assert np.all(area > 0.0)
    # Rest against facet area is the cut cloth against the designed surface: the chord
    # correction removes the faceting and keeps the pattern's own distortion.
    x = model.positions
    facet = 0.5 * np.linalg.norm(
        np.cross(x[skin[:, 1]] - x[skin[:, 0]], x[skin[:, 2]] - x[skin[:, 0]]), axis=1
    )
    flat = sum(p.flat_area for p in d.pieces) / sum(p.surface_area for p in d.pieces)
    assert area.sum() / facet.sum() == pytest.approx(flat, rel=0.01)
    # Only the rim is a free edge of the skin: every skin seam is sewn.
    edges = np.sort(np.concatenate([skin[:, [0, 1]], skin[:, [1, 2]], skin[:, [2, 0]]]), axis=1)
    uniq, count = np.unique(edges, axis=0, return_counts=True)
    free = uniq[count == 1]
    assert np.isin(free, am.rim_nodes).all()
    assert len(free) == len(am.rim_nodes)
    assert sum(1 for s in model.seams if s.name.startswith("pod:seam")) == 6
    # Rim nodes sit on the true envelope.
    assert np.abs(spec.host.height_above(model.positions[am.rim_nodes])).max() < 1e-6  # type: ignore[union-attr]
    assert am.feed is not None
    assert spec.intended["projected_height_m"] == pytest.approx(d.designed_height)


def test_revolved_profiles_reproduce_dome_and_tube() -> None:
    from envelopelab.features.primitives import Revolved

    w = np.linspace(0.0, 0.5 * math.pi, 41)
    arc = tuple((float(math.cos(a)), float(math.sin(a))) for a in w[:-1]) + ((0.0, 1.0),)
    dome = design_primitive(Dome("d", Placement(2, EQUATOR), 1.0, 1.0, gores=12), SPHERE)
    rev = design_primitive(Revolved("d", Placement(2, EQUATOR), arc, gores=12), SPHERE)
    assert rev.footprint_length == pytest.approx(dome.footprint_length, rel=1e-4)
    assert rev.designed_height == pytest.approx(dome.designed_height, abs=1e-3)
    assert [p.label for p in rev.pieces] == [p.label for p in dome.pieces]
    for a, b in zip(rev.pieces, dome.pieces, strict=True):
        assert a.flat_area == pytest.approx(b.flat_area, rel=2e-3)
    straight = ((0.6, 0.0), (0.2, 1.5))
    tube = design_primitive(Tube("t", Placement(2, EQUATOR), 0.6, 0.2, 1.5), SPHERE)
    rt = design_primitive(Revolved("t", Placement(2, EQUATOR), straight, 4), SPHERE)
    assert rt.footprint_length == pytest.approx(tube.footprint_length, rel=1e-5)
    assert rt.pieces[-1].label == "t-TIP"
    assert rt.pieces[-1].flat_area == pytest.approx(math.pi * 0.04, rel=1e-3)
    assert sum(p.flat_area for p in rt.pieces[:4]) == pytest.approx(
        sum(p.flat_area for p in tube.pieces[:4]), rel=1e-6
    )


def test_a_profile_flaring_outward_drops_straight_to_the_envelope() -> None:
    from envelopelab.features.primitives import Revolved

    onion = ((0.4, 0.0), (0.9, 0.5), (0.8, 1.0), (0.3, 1.5), (0.0, 1.9))
    d = design_primitive(Revolved("o", Placement(2, EQUATOR), onion), SPHERE)
    delta = SPHERE_RADIUS - math.sqrt(SPHERE_RADIUS**2 - 0.16)
    assert d.footprint_length == pytest.approx(2 * math.pi * 0.4, rel=1e-4)
    assert -float(d._skin.u0.min()) == pytest.approx(delta, abs=1e-6)
    assert all(c.severity != "error" for c in d.checks)


@pytest.mark.parametrize(
    "profile, message",
    [
        (((0.5, 0.1), (0.0, 1.0)), "start at zeta = 0"),
        (((0.5, 0.0), (0.0, 0.5), (0.2, 1.0)), "only the last"),
        (((0.5, 0.0),), "at least two"),
    ],
)
def test_invalid_revolved_profiles_are_rejected(
    profile: tuple[tuple[float, float], ...], message: str
) -> None:
    from envelopelab.features.primitives import Revolved

    with pytest.raises(PrimitiveError, match=message):
        design_primitive(Revolved("r", Placement(1, EQUATOR), profile), SPHERE)


def test_coarse_footprint_grid_gives_the_same_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    """The footprint grid only brackets the crossing; bisection finds it to 0.1 µm."""
    from envelopelab.features import primitives

    dome = Dome("d", Placement(1, EQUATOR, 0.0, 30.0, 45.0), 0.4, 0.5, 12)
    coarse = design_primitive(dome, SPHERE)
    monkeypatch.setattr(primitives, "FOOTPRINT_GRID", 801)
    fine = design_primitive(dome, SPHERE)
    assert len(coarse.pieces) == len(fine.pieces)
    for a, b in zip(coarse.pieces, fine.pieces, strict=True):
        assert np.abs(a.cut - b.cut).max() < 1e-6
    assert np.abs(coarse.footprint_points - fine.footprint_points).max() < 1e-6


@pytest.mark.parametrize(
    "primitive",
    [
        Dome("d", Placement(1, EQUATOR), 1.0, 1.2, gores=16),
        Tube("t", Placement(5, EQUATOR, lean_deg=20.0), 0.8, 0.3, 2.0),
    ],
    ids=["dome", "tube"],
)
def test_attachment_ease_adds_up_to_rim_minus_marked_line(primitive: Dome | Tube) -> None:
    d = design_primitive(primitive, SPHERE)
    rim = sum(_length(c.rim) for c in d.pieces if c.rim is not None)
    marked = sum(a.length for a in d.attachment)
    assert len(d.mark_ease) == len(d.marks)
    # Integrated per mark interval from the same geometry as the drawn lines.
    assert float(d.mark_ease.sum()) == pytest.approx(rim - marked, abs=2e-4)
    check = next(c for c in d.checks if c.name == "attachment ease")
    assert check.value == pytest.approx(float(np.abs(d.mark_ease).max()))
    assert check.severity == ("info" if check.value <= DEFAULT_TOLERANCE else "error")
    assert d.as_dict()["mark_ease_m"] == pytest.approx(d.mark_ease.tolist())


def _distance_to_loop(points: np.ndarray, loop: np.ndarray) -> np.ndarray:
    """Distance of 3D points to a closed 3D polyline, m."""
    a, b = loop, np.roll(loop, -1, axis=0)
    ab = b - a
    t = np.einsum("pij,ij->pi", points[:, None, :] - a[None], ab) / np.einsum("ij,ij->i", ab, ab)
    proj = a[None] + np.clip(t, 0.0, 1.0)[..., None] * ab[None]
    out: np.ndarray = np.linalg.norm(points[:, None, :] - proj, axis=2).min(axis=1)
    return out


@pytest.mark.parametrize("kind", ["dome", "mesh"])
def test_sub_model_rim_lies_on_the_footprint_where_host_tapes_cross_it(kind: str) -> None:
    """Rim nodes the host mesh adds where load tapes and row seams cross the footprint lie
    on the designed footprint, not on the chord between two footprint nodes, and every
    rim edge has the same length in the flat cut pieces as on the envelope."""
    from envelopelab.features.primitives import FreeformShape, _to_host_frame
    from envelopelab.validation.primitives import ellipsoid_mesh

    s_row = SPHERE.rows[1].s_top
    place = Placement(5, s_row, across=0.5)
    prim: Dome | FreeformShape = (
        Dome("x", place, 0.9, 0.6, gores=6)
        if kind == "dome"
        else FreeformShape("x", place, ellipsoid_mesh(0.9, 0.7, 0.6, -0.3), 6)
    )
    d = design_primitive(prim, SPHERE, feed_hole_radius=0.2)
    spec = primitive_appendage(d, 0.3, load_tape=GENERIC_TAPE, row_tape=GENERIC_TAPE)
    assert {t.name.split()[0] for t in spec.host_tapes} == {"load", "row"}
    am = build_appendage(spec, HOT, {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC})
    model = am.model
    loop = _to_host_frame(d, d.footprint_points)
    off = _distance_to_loop(model.positions[am.rim_nodes], loop)
    assert off.max() < 5e-4
    # Rim edges of the skin: flat (rest) length against the envelope (3D) length.
    rim = set(am.rim_nodes.tolist())
    tri = model.triangles[am.skin_triangles]
    rest = model.rest_uv[am.skin_triangles]
    worst = 0.0
    for k in range(3):
        i, j = (k + 1) % 3, (k + 2) % 3
        on_rim = np.array(
            [a in rim and b in rim for a, b in zip(tri[:, i], tri[:, j], strict=True)]
        )
        l3 = np.linalg.norm(
            model.positions[tri[on_rim, i]] - model.positions[tri[on_rim, j]], axis=1
        )
        lf = np.linalg.norm(rest[on_rim, i] - rest[on_rim, j], axis=1)
        if len(l3):
            worst = max(worst, float(np.abs(lf / l3 - 1.0).max()))
    assert worst < 0.01


def test_feed_holes_must_clear_the_seams_and_can_be_moved_clear() -> None:
    """A feed hole reaching over a row seam fails *feed hole clear of seams*; the nearest
    clear position in its panel, inside the footprint, passes."""
    from envelopelab.features.primitives import clear_feed_hole, feed_hole_seam_clearance

    seam = SPHERE.rows[1].s_top  # between rows B and C
    theta = SPHERE.theta_at(5)
    dome = Dome("pod", Placement(5, seam), 1.0, 0.6, gores=8)
    required = 0.05
    # One hole reaching over the row seam below it, one well inside row C.
    on_seam = (seam + 0.03, theta, 0.1)
    inside = (seam + 0.5, theta, 0.1)
    d = design_primitive(dome, SPHERE, feed_holes=[on_seam, inside], seam_clearance=required)
    checks = [c for c in d.checks if c.name == "feed hole clear of seams"]
    assert [c.severity for c in checks] == ["error", "info"]
    assert checks[0].value < 0.0  # over the seam
    hole = d.extra_feed_holes[1]
    assert checks[1].value == pytest.approx(
        feed_hole_seam_clearance(SPHERE, hole.row, hole.centre_xy, hole.radius)
    )
    found = clear_feed_hole(d, *on_seam, required)
    assert found is not None
    s, th = found
    moved = design_primitive(
        dome, SPHERE, feed_holes=[(s, th, 0.1), inside], seam_clearance=required
    )
    after = [c for c in moved.checks if c.name.startswith("feed hole")]
    assert all(c.severity == "info" for c in after), [c.message for c in after]
    # The least move: up the tape to just clear of the seam (10 mm search grid).
    assert seam + 0.1 + required <= s <= seam + 0.1 + required + 0.02
    assert (
        abs(SPHERE.gore_position(np.array([th]))[0] - SPHERE.gore_position(np.array([theta]))[0])
        < 0.01
    )
    # A hole too large for its panel cannot be cleared.
    big = (seam + 0.5, theta, 1.2)
    d_big = design_primitive(dome, SPHERE, feed_holes=[big], seam_clearance=required)
    assert clear_feed_hole(d_big, *big, required) is None


def test_a_capped_dome_stops_where_it_is_as_wide_as_its_cap() -> None:
    """A cap of radius r_c closes the half-spheroid where rho = r_c, at height
    h sqrt(1 - (r_c / a)^2); the gores end on the cap's circle."""
    from envelopelab.features.primitives import Revolved

    a, h, rc = 0.8, 0.6, 0.2
    dome = Dome("ear", Placement(3, EQUATOR), a, h, gores=8, cap_radius=rc)
    assert dome.closed_tip and dome.tip_radius == rc
    assert dome.tip_height == pytest.approx(h * math.sqrt(1.0 - (rc / a) ** 2), rel=1e-12)
    rho, zeta = dome.meridian()
    assert rho[-1] == pytest.approx(rc, rel=1e-12) and zeta[-1] == pytest.approx(dome.tip_height)
    d = design_primitive(dome, SPHERE)
    assert [p.label for p in d.pieces][-2:] == ["ear-G8", "ear-TIP"]
    tops = sum(_length(p.edges["top"]) for p in d.pieces[:-1])
    assert tops == pytest.approx(2.0 * math.pi * rc, rel=1e-3)
    assert d.pieces[-1].flat_area == pytest.approx(math.pi * rc**2, rel=1e-3)
    with pytest.raises(PrimitiveError, match="cap radius"):
        design_primitive(Dome("ear", Placement(3, EQUATOR), a, h, cap_radius=a), SPHERE)
    # A revolved profile ending on the axis is cut the same way; one ending off it is not.
    w = np.linspace(0.0, 0.5 * math.pi, 9)
    profile = tuple((float(a * math.cos(t)), float(h * math.sin(t))) for t in w[:-1]) + ((0.0, h),)
    rev = Revolved("bulb", Placement(3, EQUATOR), profile, 8, cap_radius=rc)
    rho, _ = rev.meridian()
    assert rev.closed_tip and rho[-1] == pytest.approx(rc, rel=1e-9)
    assert rho.min() == pytest.approx(rc, rel=1e-9)
    assert design_primitive(rev, SPHERE).pieces[-1].label == "bulb-TIP"
    open_tip = (*profile[:-1], (0.1, h))
    with pytest.raises(PrimitiveError, match="cap closes only a profile that ends on the axis"):
        design_primitive(Revolved("x", Placement(3, EQUATOR), open_tip, 8, cap_radius=rc), SPHERE)


def test_a_cap_starts_on_the_designed_top_in_the_sub_model() -> None:
    """The cap is cut flat, but its sub-model nodes start on the dome's top (taut and
    curved), so the solve starts near the inflated shape."""
    a, h, rc = 0.8, 0.6, 0.25
    d = design_primitive(
        Dome("ear", Placement(3, EQUATOR), a, h, 8, cap_radius=rc), SPHERE, feed_hole_radius=0.2
    )
    am = build_appendage(
        primitive_appendage(d, 0.1, load_tape=GENERIC_TAPE),
        HOT,
        {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC},
    )
    model = am.model
    tip = next(s for s in model.seams if s.name == "ear:tip seam")
    skin = model.triangles[am.skin_triangles]
    ring = set(np.unique(tip.edges).tolist())
    # Cap triangles are the grain-across ones; their inner nodes lie on the spheroid.
    cap = skin[np.all(np.isclose(model.grain[am.skin_triangles], [1.0, 0.0]), axis=1)]
    inner = sorted(set(np.unique(cap).tolist()) - ring)
    assert inner
    from envelopelab.features.scene import to_envelope_frame

    x = to_envelope_frame(d, model.positions[inner]) - d.base_point
    edge = to_envelope_frame(d, model.positions[sorted(ring)]) - d.base_point
    assert np.allclose(edge @ d.axis, d.primitive.tip_height, atol=1e-9)
    # Each inner node on the spheroid: zeta = h sqrt(1 - (rho / a)^2) above the base.
    height = x @ d.axis
    rho = np.linalg.norm(x - np.outer(height, d.axis), axis=1)
    assert np.all(height > d.primitive.tip_height)
    assert height == pytest.approx(h * np.sqrt(1.0 - (rho / a) ** 2), abs=2e-4)
