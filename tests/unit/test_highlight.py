"""What a selection is on the balloon (envelopelab.project.highlight)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.project.gore_design import design_profile, display_points, panel_rows
from envelopelab.project.highlight import ring, selection_highlight, tape_at
from envelopelab.project.model import PatternSet
from envelopelab.project.session import ProjectSession

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"
SESSION = ProjectSession.open(FIXTURE)
DESIGN = SESSION.design
ROWS = panel_rows(DESIGN, PatternSet())
N = DESIGN.gores.count  # type: ignore[union-attr]


def test_a_ring_goes_round_the_envelope_at_its_tape_position() -> None:
    s = 3.0
    line = ring(DESIGN, s)
    assert line[0] == pytest.approx(line[-1], abs=1e-9)  # closed
    expected = display_points(DESIGN, np.full(len(line), s), np.linspace(0, 2 * math.pi, len(line)))
    assert line == pytest.approx(expected)
    # Every point is at the profile's height there.
    z = float(design_profile(DESIGN).height_at(s))
    assert line[:, 2] == pytest.approx(z, abs=1e-6)


def test_a_row_is_its_band_and_one_panel_faced_at_its_centre() -> None:
    row = ROWS[1]
    h = selection_highlight(DESIGN, f"row:{row.label}", rows=ROWS)
    assert h is not None and h.key == f"row:{row.label}"
    bottom, top, panel = h.lines
    profile = design_profile(DESIGN)
    assert bottom[:, 2] == pytest.approx(float(profile.height_at(row.s_bottom)), abs=1e-6)
    assert top[:, 2] == pytest.approx(float(profile.height_at(row.s_top)), abs=1e-6)
    # The panel outline closes on itself and stays within gore 1's azimuths.
    assert panel[0] == pytest.approx(panel[-1], abs=1e-6)
    az = np.arctan2(panel[:, 1], panel[:, 0])  # (-pi, pi]
    assert az.min() >= -1e-6 and az.max() <= 2 * math.pi / N + 1e-6
    assert h.focus is not None
    zf = float(profile.height_at(0.5 * (row.s_bottom + row.s_top)))
    assert h.focus[2] == pytest.approx(zf, abs=1e-6)
    assert selection_highlight(DESIGN, "row:Z", rows=ROWS) is None


def test_a_control_point_is_the_ring_through_it() -> None:
    points = DESIGN.gores.meridian_profile_control_points  # type: ignore[union-attr]
    r, z = points[2].x, points[2].y
    h = selection_highlight(DESIGN, "point:2")
    assert h is not None and len(h.lines) == 1
    s = tape_at(DESIGN, r, z)
    profile = design_profile(DESIGN)
    assert math.hypot(float(profile.radius_at(s)) - r, float(profile.height_at(s)) - z) < 0.02
    assert h.lines[0][:, 2] == pytest.approx(float(profile.height_at(s)), abs=1e-6)
    assert selection_highlight(DESIGN, "point:999") is None


def test_rigging_selections_are_their_lines() -> None:
    wire = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, -1.0]])
    chute = np.array([[0.0, 0.0, 9.0], [1.0, 0.0, 9.0]])
    rigging = {"flying_wires": [wire], "parachute": [chute], "shroud_lines": [chute + 1]}
    h = selection_highlight(DESIGN, "flying_wires", rigging=rigging)
    assert h is not None and len(h.lines) == 1 and h.lines[0] == pytest.approx(wire)
    para = selection_highlight(DESIGN, "parachute", rigging=rigging)
    assert para is not None and len(para.lines) == 2
    every = selection_highlight(DESIGN, "rigging", rigging=rigging)
    assert every is not None and len(every.lines) == 3
    assert selection_highlight(DESIGN, "turning_vents", rigging=rigging) is None
    assert selection_highlight(DESIGN, "operating", rigging=rigging) is None


def test_the_profile_is_a_seam_meridian() -> None:
    h = selection_highlight(DESIGN, "profile")
    assert h is not None
    (line,) = h.lines
    assert line[:, 1] == pytest.approx(0.0, abs=1e-9)  # the seam at azimuth 0
    assert line[0, 2] < line[-1, 2]
