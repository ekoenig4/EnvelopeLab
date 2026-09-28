from __future__ import annotations

import math

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.geometry.gore import GoreWidthModel, MeridianProfile, SeamAllowance, split_rows

radii = st.floats(min_value=0.5, max_value=20.0)
gores = st.integers(min_value=3, max_value=48)


@given(radius=radii, n=gores, ratio=st.floats(min_value=1.0, max_value=5.0))
def test_chord_width_bounded_by_chord_and_small_bulge(radius: float, n: int, ratio: float) -> None:
    flat = GoreWidthModel(n, "chord").half_width(radius)
    lobe = GoreWidthModel(n, "chord", bulge_ratio=ratio).half_width(radius)
    circle = GoreWidthModel(n).half_width(radius)
    assert flat <= lobe * (1 + 1e-12) and lobe <= circle * (1 + 1e-12)


@settings(max_examples=25, deadline=None)
@given(scale=st.floats(min_value=0.1, max_value=10.0))
def test_volume_and_area_scale(scale: float) -> None:
    theta = np.linspace(-1.2, 1.3, 401)
    base = MeridianProfile.from_points(np.cos(theta), np.sin(theta))
    scaled = MeridianProfile.from_points(scale * np.cos(theta), scale * np.sin(theta))
    assert math.isclose(scaled.volume, base.volume * scale**3, rel_tol=1e-9)
    assert math.isclose(scaled.area, base.area * scale**2, rel_tol=1e-9)


@settings(max_examples=25, deadline=None)
@given(
    n=gores,
    rows=st.integers(min_value=1, max_value=8),
    side=st.floats(min_value=0.0, max_value=0.03),
    edge=st.floats(min_value=0.0, max_value=0.03),
)
def test_cut_panel_contains_finished_panel(n: int, rows: int, side: float, edge: float) -> None:
    theta = np.linspace(-1.0, 1.4, 801)
    profile = MeridianProfile.from_points(6 * np.cos(theta), 6 * np.sin(theta))
    panels = split_rows(
        profile,
        GoreWidthModel(n),
        [profile.meridian_length / rows] * rows,
        allowance=SeamAllowance(side, edge, edge),
    )
    total = sum(p.finished_area for p in panels) * n
    assert math.isclose(total, profile.area, rel_tol=1e-6)
    for panel in panels:
        assert panel.cut_area >= panel.finished_area * (1 - 1e-12)
