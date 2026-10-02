from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.io.shape_file import load_shape_file

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
