"""Vertical load tapes cut to the design's tape line (``tapes.vertical_length``)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from envelopelab.design.model import _raw_hash, load_design_document
from envelopelab.project.dependencies import fingerprints, group_hashes, input_groups
from envelopelab.project.session import ProjectSession
from envelopelab.project.simulation import (
    BuildError,
    build_solver_model,
    cut_tapes_to_tape_line,
    solve_preview,
)
from envelopelab.solvers.model import ModelError, edge_rest_lengths, tape_line_rest_lengths

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SMALL = FIXTURES / "standard_gore" / "design.elproj"
FULL = FIXTURES / "full_size_gore" / "design.elproj"


def test_a_slanted_gore_edge_is_longer_than_its_tape() -> None:
    # One triangle whose edge 0-1 runs 0.3 m across and 0.4 m along the gore (0.5 m long).
    tri = np.array([[0, 1, 2]])
    uv = np.array([[[0.0, 0.0], [0.3, 0.4], [-0.5, 0.2]]])
    edges = np.array([[0, 1]])
    assert edge_rest_lengths(edges, tri, uv) == pytest.approx([0.5])
    assert tape_line_rest_lengths(edges, tri, uv) == pytest.approx([0.4])
    # A pattern cut 2 % longer than the tape along the gore still has the same tape.
    assert tape_line_rest_lengths(edges, tri, uv * [1.0, 1.02], scale=1.02) == pytest.approx([0.4])
    with pytest.raises(ModelError, match="not a mesh edge"):
        tape_line_rest_lengths(np.array([[0, 5]]), tri, uv)
    with pytest.raises(ModelError, match="across the gore"):
        tape_line_rest_lengths(np.array([[0, 2]]), tri, uv * [1.0, 0.0])


def _design(path: Path, vertical_length: str) -> tuple[ProjectSession, object]:
    session = ProjectSession.open(path)
    design = session.design.model_copy(deep=True)
    design.tapes.vertical_length = vertical_length  # type: ignore[assignment]
    return session, design


def test_tapes_cut_to_the_tape_line_total_each_rows_tape_length() -> None:
    session, design = _design(SMALL, "tape_line")
    with tempfile.TemporaryDirectory() as tmp:
        cut = build_solver_model(design, session.patterns, Path(tmp) / "a", 1600.0)  # type: ignore[arg-type]
        edge = build_solver_model(session.design, session.patterns, Path(tmp) / "b", 1600.0)
    heights = {r.letter: r.finished_height for r in session.design.gores.panel_rows}  # type: ignore[union-attr]
    by_name = {c.name: c for c in edge.model.cables}
    vertical = [c for c in cut.model.cables if c.name.startswith("body:v:")]
    assert len(vertical) == 8 * 4
    for cable in vertical:
        assert float(cable.rest_lengths.sum()) == pytest.approx(  # type: ignore[union-attr]
            heights[cable.name.rsplit(":", 1)[-1]], abs=1e-3
        )
        # The fabric-edge tape is the longer gore edge (up to 4.5 % near the mouth).
        assert float(by_name[cable.name].rest_lengths.sum()) > float(cable.rest_lengths.sum())  # type: ignore[union-attr]
    # Horizontal tapes and rims are cut as before.
    for cable in cut.model.cables:
        if not cable.name.startswith("body:v:"):
            assert np.array_equal(cable.rest_lengths, by_name[cable.name].rest_lengths)  # type: ignore[arg-type]


def test_a_pattern_without_the_tape_length_along_its_axis_is_refused() -> None:
    session, design = _design(SMALL, "tape_line")
    with tempfile.TemporaryDirectory() as tmp:
        built = build_solver_model(design, session.patterns, Path(tmp) / "a", 1600.0)  # type: ignore[arg-type]
    wrong = design.model_copy(deep=True)  # type: ignore[attr-defined]
    wrong.gores.panel_rows[0].finished_height += 0.01
    with pytest.raises(BuildError, match="tape line"):
        cut_tapes_to_tape_line(built.model, built.build, wrong)


def test_the_default_keeps_fingerprints_and_the_cut_moves_only_the_simulation() -> None:
    session, design = _design(SMALL, "tape_line")
    patterns = session.patterns.model_dump(mode="json")
    old = session.design.model_dump(by_alias=True, mode="json")
    legacy = json.loads(json.dumps(old))
    del legacy["tapes"]["vertical_length"]
    assert input_groups(old, patterns)["tapes"] == input_groups(legacy, patterns)["tapes"]
    before = fingerprints(group_hashes(input_groups(old, patterns)))
    after = fingerprints(
        group_hashes(input_groups(design.model_dump(by_alias=True, mode="json"), patterns))  # type: ignore[attr-defined]
    )
    assert after["simulation"] != before["simulation"]
    assert after["patterns"] == before["patterns"]


def test_version_7_designs_keep_fabric_edge_tapes() -> None:
    raw = ProjectSession.open(SMALL).design.model_dump(by_alias=True, mode="json")
    raw["schema_version"] = 7
    del raw["tapes"]["vertical_length"]
    raw["meta"]["content_hash"] = None
    raw["meta"]["content_hash"] = _raw_hash(raw)  # written by a version-7 EnvelopeLab
    loaded = load_design_document(json.dumps(raw))
    assert loaded.schema_version == 8
    assert loaded.tapes.vertical_length == "fabric_edge"


@pytest.mark.slow
def test_full_size_tapes_cut_to_the_tape_line_carry_more_of_the_load() -> None:
    session, design = _design(FULL, "tape_line")
    with tempfile.TemporaryDirectory() as tmp:
        cut = solve_preview(build_solver_model(design, session.patterns, Path(tmp) / "a", 1600.0))  # type: ignore[arg-type]
        edge = solve_preview(
            build_solver_model(session.design, session.patterns, Path(tmp) / "b", 1600.0)
        )
    assert cut.converged and edge.converged

    def row_max(result: object, row: str) -> float:
        return max(
            float(np.max(t))
            for name, t in result.tape_tensions.items()  # type: ignore[attr-defined]
            if name.startswith("body:v:") and name.endswith(":" + row)
        )

    # The bottom and top rows, where the gore edge is longest against the tape.
    for row in ("A", "L"):
        assert row_max(cut, row) > 1.5 * row_max(edge, row)
