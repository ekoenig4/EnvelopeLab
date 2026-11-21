from __future__ import annotations

from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.io.shape_file import load_shape_file
from envelopelab.project.shapes import scaled_mesh_vertices
from envelopelab.validation.primitives import ellipsoid_mesh

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "smalley_90k" / "shape.yaml"
SHAPE_FILE = load_shape_file(FIXTURE)


@settings(max_examples=20, deadline=None)
@given(
    mouth=st.floats(min_value=1.0, max_value=12.0),
    station=st.floats(min_value=0.05, max_value=0.4),
)
def test_held_mouth_diameter_is_met_and_shape_kept(mouth: float, station: float) -> None:
    """Holding a mouth diameter with fixed cut stations solves the scale only."""
    hold = {"mouth_diameter": mouth, "mouth_station": station, "top_station": 0.9}
    solution = SHAPE_FILE.solve(hold)
    assert solution.converged, solution.message
    assert abs(solution.values["mouth_diameter"] - mouth) <= 1e-3
    assert solution.parameters.mouth_station == station
    assert solution.parameters.top_station == 0.9


@settings(max_examples=15, deadline=None)
@given(volume_ratio=st.floats(min_value=0.3, max_value=3.0), mouth=st.floats(4.0, 7.0))
def test_held_volume_and_mouth_are_both_met(volume_ratio: float, mouth: float) -> None:
    """Two targets (volume, mouth diameter): scale and mouth station are solved."""
    base = SHAPE_FILE.solve()
    volume = volume_ratio * base.values["nominal_volume"]
    hold = {
        "nominal_volume": volume,
        "mouth_diameter": mouth * volume_ratio ** (1 / 3),
        "top_station": 0.9,
    }
    solution = SHAPE_FILE.solve(hold)
    assert solution.converged, solution.message
    assert abs(solution.values["nominal_volume"] / volume - 1.0) <= 1e-3
    assert abs(solution.values["mouth_diameter"] - hold["mouth_diameter"]) <= 1e-3


_FACTOR = st.floats(min_value=0.05, max_value=20.0)


@settings(max_examples=50, deadline=None)
@given(along=_FACTOR, across=_FACTOR, height=_FACTOR)
def test_mesh_resize_is_undone_by_the_inverse_factors(
    along: float, across: float, height: float
) -> None:
    """Scaling a mesh and scaling back returns it, and the base point stays fixed."""
    v = ellipsoid_mesh(0.3, 0.2, 0.4, -0.1, rings=6, segments=8).vertices
    scaled = scaled_mesh_vertices(v, along, across, height)
    back = scaled_mesh_vertices(scaled, 1.0 / along, 1.0 / across, 1.0 / height)
    assert np.allclose(back, v, rtol=1e-12, atol=1e-15)
    origin = scaled_mesh_vertices(np.zeros((1, 3)), along, across, height)
    assert np.array_equal(origin, np.zeros((1, 3)))
