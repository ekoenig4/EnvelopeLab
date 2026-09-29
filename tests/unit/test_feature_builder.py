"""Generic appendage assembly: host patch, footprint, skin with ease, tapes and tubes."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from envelopelab.atmosphere import celsius_to_kelvin
from envelopelab.features.builder import (
    AppendageSpec,
    ChartHole,
    FeatureBuildError,
    HostSurface,
    HostTape,
    PressureSpec,
    RimTapeSpec,
    build_appendage,
    conform_tapes,
    shell_prestress,
)
from envelopelab.features.ease import loop_length
from envelopelab.features.pressure import independent_chamber
from envelopelab.features.tube import TubeSpec, build_tube, frustum_pattern
from envelopelab.solvers.model import OperatingConditions
from envelopelab.validation.preview_solver import GENERIC_FABRIC, GENERIC_TAPE, _isotropic

HOT = OperatingConditions.hot_air(celsius_to_kelvin(100.0), mouth_height=0.0, self_weight=False)


def _circle(r: float, n: int = 120) -> np.ndarray:
    t = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    return np.column_stack([r * np.cos(t), r * np.sin(t)])


def test_host_surface_chart_is_arc_length_along_the_meridian() -> None:
    host = HostSurface(8.0, 9.0, math.radians(10.0), 12.0)
    v = np.linspace(-2.0, 2.0, 201)
    pts = host.map(np.column_stack([np.zeros_like(v), v]))
    arc = np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()
    assert arc == pytest.approx(4.0, rel=1e-4)
    assert host.height_above(pts) == pytest.approx(np.zeros_like(v), abs=1e-9)
    n = host.normal(np.zeros((1, 2)))[0]
    assert n[2] == pytest.approx(math.sin(math.radians(10.0)))
    assert host.map(np.zeros((1, 2)))[0, 2] == pytest.approx(12.0)


def test_shell_prestress_reduces_to_the_sphere() -> None:
    n_u, n_v = shell_prestress(20.0, HostSurface(5.0, 5.0))
    assert n_u == pytest.approx(50.0) and n_v == pytest.approx(50.0)


def test_flat_pattern_skin_keeps_its_eased_rim_lengths() -> None:
    fp, skin = _circle(1.5), _circle(1.6)
    spec = AppendageSpec(
        "pod",
        fp,
        skin_outline=skin,
        host=HostSurface(8.0, 8.0, 0.0, 10.0),
        mesh_size=0.3,
        host_zone="host",
        skin_zone="skin",
        match_points=8,
        rim_tape=RimTapeSpec(GENERIC_TAPE),
        host_tapes=[HostTape("t", np.array([[0.4, -4.0], [0.4, 4.0]]), GENERIC_TAPE)],
        holes=[ChartHole("feed", (0.0, -0.6), 0.2, GENERIC_TAPE)],
        pressure=PressureSpec("fed", 0.2),
    )
    am = build_appendage(spec, HOT, {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC})
    model = am.model
    assert am.ease is not None
    assert am.ease.ease == pytest.approx(loop_length(skin) - am.ease.footprint_length)
    assert len(am.match_nodes) == 8
    # Rest length of the skin along the rim equals the skin's rim; the host's equals the
    # footprint shrunk by the prestrain: the designed ease is carried by the rest geometry.
    rim = set(zip(am.rim_nodes, np.roll(am.rim_nodes, -1), strict=True))
    skin_len = 0.0
    for t in am.skin_triangles:
        tri = model.triangles[t]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            if (tri[a], tri[b]) in rim or (tri[b], tri[a]) in rim:
                skin_len += float(np.linalg.norm(model.rest_uv[t, a] - model.rest_uv[t, b]))
    assert skin_len == pytest.approx(loop_length(skin), rel=2e-3)
    assert am.feed is not None and am.feed.loss_factor == pytest.approx(0.2)
    names = {c.name for c in model.cables}
    assert {"pod:rim tape", "pod:host:t", "pod:hem:feed"} <= names
    assert model.tri_chambers is not None
    # Footprint triangles separate the envelope gas from the pod.
    assert np.all(model.tri_chambers[am.footprint_triangles] == [-1, 0])
    assert np.all(model.tri_chambers[am.skin_triangles] == [0, -2])


def test_rim_tape_not_caught_stops_short_of_host_tapes() -> None:
    kw: dict[str, Any] = dict(
        skin_mode="spherical_cap",
        cap_height=0.5,
        host=HostSurface(8.0, 8.0, 0.0, 10.0),
        mesh_size=0.3,
        host_zone="host",
        skin_zone="skin",
        host_tapes=[HostTape("t", np.array([[0.0, -4.0], [0.0, 4.0]]), GENERIC_TAPE)],
        holes=[ChartHole("feed", (0.5, 0.0), 0.2)],
        pressure=PressureSpec("fed", 0.2),
    )
    mats = {"host": GENERIC_FABRIC, "skin": GENERIC_FABRIC}
    caught = build_appendage(
        AppendageSpec("p", _circle(1.5), rim_tape=RimTapeSpec(GENERIC_TAPE, True), **kw), HOT, mats
    )
    loose = build_appendage(
        AppendageSpec("p", _circle(1.5), rim_tape=RimTapeSpec(GENERIC_TAPE, False), **kw), HOT, mats
    )
    n_caught = len(next(c for c in caught.model.cables if c.name == "p:rim tape").edges)
    rim_loose = next(c for c in loose.model.cables if c.name == "p:rim tape")
    tape_nodes = np.unique(next(c for c in loose.model.cables if c.name == "p:host:t").edges)
    assert len(rim_loose.edges) < n_caught
    assert not np.isin(rim_loose.edges, tape_nodes).any()


def test_conform_tapes_moves_a_tangent_seam_and_notes_it() -> None:
    fp = _circle(1.0, 200)
    tapes = [np.array([[-3.0, 1.0], [3.0, 1.0]])]  # touches the top of the circle
    new_fp, new_tapes, notes = conform_tapes(fp, tapes, 0.3, ["row"])
    assert notes and "tangency" in notes[0]
    assert new_tapes[0][:, 1].min() >= 1.0 + 0.09 - 1e-9
    assert len(new_fp) == len(fp)


def test_fed_chamber_needs_holes_and_zones_need_materials() -> None:
    spec = AppendageSpec(
        "b", _circle(1.0), skin_mode="spherical_cap", cap_height=1.0, skin_zone="s"
    )
    with pytest.raises(FeatureBuildError):
        build_appendage(spec, HOT, {"s": _isotropic()})
    ok = AppendageSpec(
        "b",
        _circle(1.0),
        skin_mode="spherical_cap",
        cap_height=1.0,
        skin_zone="s",
        pressure=PressureSpec("independent", chamber=independent_chamber("b", 100.0, 0.0, 0.0)),
    )
    with pytest.raises(FeatureBuildError):
        build_appendage(ok, HOT, {})


def test_frustum_pattern_lean_comes_from_the_oblique_base() -> None:
    straight = frustum_pattern(0.44, 0.16, 2.25, 0.0)
    lean = frustum_pattern(0.44, 0.16, 2.25, 35.0)
    base_s = np.linalg.norm(straight["base"], axis=1)
    base_l = np.linalg.norm(lean["base"], axis=1)
    assert np.ptp(base_s) == pytest.approx(0.0, abs=1e-9)
    assert np.ptp(base_l) > 0.3  # outboard side longer than inboard
    # Developed slant length of the straight cone: sqrt(L^2 + (rb - rt)^2).
    slant = np.linalg.norm(straight["side_a"][0] - straight["side_a"][-1])
    assert slant == pytest.approx(math.hypot(2.25, 0.28), rel=1e-9)


def test_tube_assembly_has_a_closed_neck_and_shares_the_base_loop() -> None:
    pat = frustum_pattern(0.44, 0.16, 2.25, 0.0)
    base_len = float(np.linalg.norm(np.diff(pat["base"], axis=0), axis=1).sum())
    fp = _circle(base_len / (2.0 * math.pi))
    base = AppendageSpec(
        "ant",
        fp,
        host=HostSurface(8.0, 8.0, 0.3, 14.0),
        mesh_size=0.15,
        margin=0.6,
        host_zone="host",
        holes=[ChartHole("feed", (0.0, 0.0), 0.2)],
        pressure=PressureSpec("fed", 0.1),
    )
    tube = build_tube(
        TubeSpec(base, pat["base"], pat["neck"], pat["side_a"], pat["side_b"], tube_zone="tube"),
        HOT,
        {"host": GENERIC_FABRIC, "tube": GENERIC_FABRIC},
    )
    model = tube.model
    assert model.closures and model.closures[0].chamber == "ant"
    tube_nodes = np.unique(model.triangles[tube.appendage.skin_triangles])
    assert set(tube.base_nodes.tolist()) <= set(tube_nodes.tolist())
    # Every tube edge is shared by two tube triangles except the base and neck rings.
    e = np.sort(
        np.concatenate(
            [
                model.triangles[tube.appendage.skin_triangles][:, [a, b]]
                for a, b in ((0, 1), (1, 2), (2, 0))
            ]
        ),
        axis=1,
    )
    _, counts = np.unique(e, axis=0, return_counts=True)
    assert counts.max() == 2
    assert (counts == 1).sum() == len(tube.base_nodes) + len(tube.neck_nodes)
