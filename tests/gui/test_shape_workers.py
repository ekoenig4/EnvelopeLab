"""How many threads solve a run's special shapes."""

from __future__ import annotations

import os

import pytest

from envelopelab_app.simulation import PREVIEW, shape_workers


@pytest.mark.parametrize(
    ("cpus", "count", "solver", "expected"),
    [
        (8, 4, PREVIEW, 4),  # one per shape
        (4, 4, PREVIEW, 3),  # one processor left for the GUI
        (1, 4, PREVIEW, 1),
        (8, 4, "calculix", 2),  # CalculiX runs threads of its own
        (8, 1, PREVIEW, 1),
    ],
)
def test_shape_workers(
    monkeypatch: pytest.MonkeyPatch, cpus: int, count: int, solver: str, expected: int
) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: cpus)
    assert shape_workers(count, solver) == expected
