"""Helpers that draw a solved envelope like the design: panel ids and seam segments."""

from __future__ import annotations

import numpy as np

from envelopelab.assembly.spec import parse_instance_id
from envelopelab.solvers.model import SeamLine, seam_segments


def test_ring_panel_instance_ids_are_parsed() -> None:
    assert parse_instance_id("envelope/C@12") == ("envelope", "C", 12)
    assert parse_instance_id("body/NOMEX@3") == ("body", "NOMEX", 3)
    assert parse_instance_id("eye_skin_left") is None
    assert parse_instance_id("envelope/C") is None


def test_seams_become_segments_on_the_given_positions() -> None:
    positions = np.array([[0.0, 0, 0], [1.0, 0, 0], [1.0, 1, 0], [0.0, 1, 0]])
    seams = [
        SeamLine("envelope:v:1/2:C", np.array([[0, 1], [1, 2]])),
        SeamLine("envelope:h:B/C@1", np.array([[2, 3]])),
        SeamLine("envelope:rim:mouth", np.array([[3, 0]])),
    ]
    out = seam_segments(seams, positions)
    assert [s.tolist() for s in out["vertical_seams"]] == [
        [[0, 0, 0], [1, 0, 0]],
        [[1, 0, 0], [1, 1, 0]],
    ]
    assert len(out["horizontal_seams"]) == 2
    moved = seam_segments(seams, positions + 5.0)
    assert np.allclose(moved["vertical_seams"][0], [[5, 5, 5], [6, 5, 5]])
