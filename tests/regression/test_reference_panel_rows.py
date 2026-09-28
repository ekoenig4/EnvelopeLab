"""Row test against the reference fixture's finished panel sizes.

PENDING until the reference fixture profile is added (Prompt 3). The test activates by
itself once ``tests/fixtures/reference_gore_profile.json`` exists, with this layout (SI):

.. code-block:: json

    {
      "source": "citation for the reference design [1]",
      "n_gores": 24,
      "width_model": {"form": "small_bulge"},
      "profile": {"r": [0.0], "z": [0.0]},
      "row_heights": [1.0],
      "row_labels": ["A"],
      "expected_panels": {
        "C": {"bottom_width": 1.480, "top_width": 1.782, "height": 1.328}
      }
    }

``profile`` holds meridian control points (m) from mouth to top; ``width_model`` takes the
keyword arguments of :class:`~envelopelab.geometry.gore.GoreWidthModel` except ``n_gores``.
Expected finished sizes must be reproduced within 2 mm.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from envelopelab.geometry.gore import GoreWidthModel, MeridianProfile, split_rows

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "reference_gore_profile.json"
TOLERANCE = 2e-3  # m


def load_fixture() -> dict[str, Any]:
    if not FIXTURE.exists():
        pytest.skip(
            "pending: reference fixture profile (tests/fixtures/reference_gore_profile.json) "
            "arrives with Prompt 3"
        )
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def test_reference_panel_finished_sizes() -> None:
    data = load_fixture()
    profile = MeridianProfile.from_control_points(data["profile"]["r"], data["profile"]["z"])
    model = GoreWidthModel(data["n_gores"], **data.get("width_model", {}))
    rows = split_rows(profile, model, data["row_heights"], labels=data["row_labels"])
    by_label = {row.label: row for row in rows}
    for label, expected in data["expected_panels"].items():
        row = by_label[label]
        assert row.bottom_width == pytest.approx(expected["bottom_width"], abs=TOLERANCE)
        assert row.top_width == pytest.approx(expected["top_width"], abs=TOLERANCE)
        assert row.finished_height == pytest.approx(expected["height"], abs=TOLERANCE)
