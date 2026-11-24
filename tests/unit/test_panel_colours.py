"""Panel colours (ADR-0055): the model, painting helpers, grids, project format 8,
session edits and undo, renames, and that colours make only the export stale."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from envelopelab.project import edits
from envelopelab.project.colours import (
    CAP,
    PanelColours,
    PanelRef,
    envelope_cells,
    envelope_targets,
    normalise_colour,
    painted,
    pruned,
    renamed,
    repeated,
    replaced,
    shape_grid,
)
from envelopelab.project.model import dump_project, load_project_text
from envelopelab.project.placement_map import gore_map
from envelopelab.project.session import ProjectSession
from envelopelab.project.shapes import DomeShape, default_shape, envelope_surface

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


@pytest.fixture
def session() -> ProjectSession:
    return ProjectSession.open(FIXTURE)


def _rows(s: ProjectSession) -> list[str]:
    assert s.design.gores is not None
    return [r.letter for r in s.design.gores.panel_rows]


def _dome(s: ProjectSession, name: str = "Nose", **values: object) -> DomeShape:
    spec = default_shape("dome", s.design, name)
    assert isinstance(spec, DomeShape)
    return spec.model_copy(update=values)


# -- colours and the model ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("#FF8800", "#ff8800"), ("ff8800", "#ff8800"), ("#f80", "#ff8800"), (" abc ", "#aabbcc")],
)
def test_colours_are_normalised(text: str, expected: str) -> None:
    assert normalise_colour(text) == expected


@pytest.mark.parametrize("text", ["", "#12345", "red", "#gggggg", "#1234567"])
def test_malformed_colours_are_refused(text: str) -> None:
    with pytest.raises(ValueError, match="not a colour"):
        normalise_colour(text)


def test_model_reads_json_keys_and_drops_empty_entries() -> None:
    c = PanelColours.model_validate(
        {"envelope": {"A": {"3": "#F00"}, "B": {}}, "shapes": {"Nose": {"A": {}}}}
    )
    assert c.envelope == {"A": {3: "#ff0000"}} and c.shapes == {}
    with pytest.raises(ValueError, match="start at 1"):
        PanelColours.model_validate({"envelope": {"A": {"0": "#ff0000"}}})


def test_painting_sets_and_clears_without_changing_the_input() -> None:
    a, cap = PanelRef(None, "A", 2), PanelRef("Nose", CAP, 1)
    start = PanelColours()
    c = painted(start, [a, cap], "#00FF00")
    assert start.is_empty()
    assert c.colour_of(a) == c.colour_of(cap) == "#00ff00"
    assert c.colour_of(PanelRef(None, "A", 3)) is None
    c = painted(c, [a], None)
    assert c.colour_of(a) is None and c.envelope == {}
    assert c.colour_of(cap) == "#00ff00"


def test_used_colours_most_used_first_and_replace() -> None:
    c = painted(PanelColours(), [PanelRef(None, "A", g) for g in (1, 2, 3)], "#0000ff")
    c = painted(c, [PanelRef(None, "B", 1)], "#ff0000")
    assert c.used() == ["#0000ff", "#ff0000"]
    r = replaced(c, "#0000FF", "#00ff00")
    assert r.used() == ["#00ff00", "#ff0000"]
    assert replaced(c, "#ff0000", None).used() == ["#0000ff"]


@pytest.mark.parametrize(
    ("index", "count", "every", "expected"),
    [
        (2, 12, 0, [2]),
        (2, 12, 4, [2, 6, 10]),
        (11, 12, 4, [11, 3, 7]),
        (1, 12, 12, [1]),  # a period of the whole round: just the one
        (1, 7, 3, [1, 4, 7, 3, 6, 2, 5]),  # 3 and 7 coprime: every gore
    ],
)
def test_repeat_round_the_envelope(index: int, count: int, every: int, expected: list[int]) -> None:
    assert repeated(index, count, every) == expected


def test_envelope_targets_by_scope() -> None:
    rows = ["A", "B", "C"]
    panel = envelope_targets(rows, 6, "B", 2, "panel")
    assert panel == [PanelRef(None, "B", 2)]
    assert {r.index for r in envelope_targets(rows, 6, "B", 2, "row")} == set(range(1, 7))
    assert {r.group for r in envelope_targets(rows, 6, "B", 2, "gore")} == set(rows)
    assert len(envelope_targets(rows, 6, "B", 2, "all")) == 18
    assert envelope_targets(rows, 6, "B", 2, "gore", every=3) == [
        PanelRef(None, r, g) for r in rows for g in (2, 5)
    ]


# -- grids -------------------------------------------------------------------------------


def test_shape_grid_follows_widths_splits_and_cap(session: ProjectSession) -> None:
    spec = _dome(session, gores=4, panel_widths=[2.0, 1.0, 1.0, 4.0], splits=[0.25, 0.6])
    grid = shape_grid(spec)
    assert grid.pieces == 4 and grid.tier_letters == ("A", "B", "C")
    assert grid.widths == pytest.approx((0.25, 0.125, 0.125, 0.5))
    assert grid.cap  # a dome closes with a cap
    cells = dict(grid.cells())
    assert len(cells) == 4 * 3 + 1
    first = cells[PanelRef("Nose", "A", 1)]
    assert first[:, 0].max() == pytest.approx(0.25) and first[:, 1].max() == pytest.approx(0.25)
    top = cells[PanelRef("Nose", "C", 4)]
    assert top[:, 0].min() == pytest.approx(0.5) and top[:, 1].min() == pytest.approx(0.6)
    assert PanelRef("Nose", CAP, 1) in cells
    # Every piece of the grid is a target of Fill all; Fill row stays on its tier.
    assert len(grid.targets("B", 2, "all")) == 13
    assert {r.group for r in grid.targets("B", 2, "row")} == {"B"}
    assert grid.targets(CAP, 1, "row") == [PanelRef("Nose", CAP, 1)]


def test_envelope_cells_tile_every_gore_and_row(session: ProjectSession) -> None:
    m = gore_map(envelope_surface(session.design, session.patterns))
    cells = envelope_cells(m)
    rows = _rows(session)
    assert len(cells) == m.gores * len(rows)
    assert {r.group for r, _p in cells} == set(rows)
    # Cells of one gore stack without gaps from the mouth to the crown (m).
    gore1 = [p for r, p in cells if r.index == 1]
    lows = sorted(float(p[:, 1].min()) for p in gore1)
    highs = sorted(float(p[:, 1].max()) for p in gore1)
    assert lows[0] == pytest.approx(0.0, abs=1e-9)
    assert highs[-1] == pytest.approx(m.length)
    assert np.allclose(lows[1:], highs[:-1])
    # Each cell lies in its gore's column.
    for ref, poly in cells:
        assert (
            (ref.index - 1) * m.column
            <= poly[:, 0].min()
            < poly[:, 0].max()
            <= (ref.index * m.column)
        )


def test_pruned_drops_panels_not_in_the_design(session: ProjectSession) -> None:
    grid = shape_grid(_dome(session, gores=4))
    c = painted(
        PanelColours(),
        [
            PanelRef(None, "A", 1),
            PanelRef(None, "A", 99),
            PanelRef(None, "Q", 1),
            PanelRef("Nose", "A", 4),
            PanelRef("Nose", "A", 5),
            PanelRef("Gone", "A", 1),
        ],
        "#123456",
    )
    kept = pruned(c, ["A", "B"], 8, [grid])
    assert sorted((r.shape or "", r.group, r.index) for r, _c in _panels(kept)) == [
        ("", "A", 1),
        ("Nose", "A", 4),
    ]


def _panels(c: PanelColours) -> list[tuple[PanelRef, str]]:
    from envelopelab.project.colours import coloured_panels

    return coloured_panels(c)


def test_renamed_follows_a_rename_but_not_a_swap() -> None:
    c = painted(PanelColours(), [PanelRef(None, "A", 1)], "#111111")
    assert renamed(c, ["A", "B"], ["Z", "B"], shapes=False).envelope == {"Z": {1: "#111111"}}
    assert renamed(c, ["A", "B"], ["B", "A"], shapes=False) == c
    assert renamed(c, ["A", "B"], ["A"], shapes=False) == c


# -- sessions, files and fingerprints ----------------------------------------------------


def test_paint_is_one_undo_step_and_stales_only_the_export(session: ProjectSession) -> None:
    fingerprints = session.fingerprints()
    refs = [PanelRef(None, r, 1) for r in _rows(session)]
    assert edits.paint_panels(session, refs, "#C00000")
    assert session.state.colours.colour_of(refs[0]) == "#c00000"
    # A visual layer: only the build pack (which prints the colours) is stale.
    changed = {k for k, v in session.fingerprints().items() if fingerprints[k] != v}
    assert changed == {"export"}
    assert "colours" in session.unsaved_groups()
    assert not edits.paint_panels(session, refs, "#c00000")  # no change, no history
    session.undo()
    assert session.state.colours.is_empty()
    session.redo()
    assert session.state.colours.colour_of(refs[-1]) == "#c00000"
    with pytest.raises(ValueError, match="not a colour"):
        edits.paint_panels(session, refs, "blue")


def test_unpainted_designs_keep_their_fingerprints(session: ProjectSession) -> None:
    """An empty colour group is left out, so projects saved before colours existed open
    with the fingerprints their runs were recorded with."""
    from envelopelab.project.dependencies import group_hashes, input_groups

    design = session.design.model_dump(by_alias=True, mode="json")
    patterns = session.patterns.model_dump(mode="json")
    assert "colours" not in group_hashes(input_groups(design, patterns))


def test_colours_survive_save_load_and_older_files_read_uncoloured(
    session: ProjectSession, tmp_path: Path
) -> None:
    raw = json.loads(dump_project(session.project))
    assert "colours" not in raw["state"]  # uncoloured designs write nothing
    session.edit_shapes("add", lambda shapes: shapes.append(_dome(session).model_dump()))
    edits.paint_panels(session, [PanelRef(None, "A", 3), PanelRef("Nose", CAP, 1)], "#7030a0")
    session.create_snapshot("painted")
    path = session.save(tmp_path / "c.elproj")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format_version"] == 9
    assert data["state"]["colours"]["envelope"] == {"A": {"3": "#7030a0"}}
    again = ProjectSession.open(path)
    assert again.state.colours == session.state.colours
    assert again.project.snapshots[0].state.colours == session.state.colours
    data["format_version"] = 7
    del data["state"]["colours"]
    for snap in data["snapshots"]:
        snap["state"].pop("colours", None)
    old = load_project_text(json.dumps(data))
    assert old.format_version == 9 and old.state.colours.is_empty()


def test_renames_keep_colours_and_removed_panels_drop_at_the_next_paint(
    session: ProjectSession,
) -> None:
    edits.add_shape(session, _dome(session))
    first = _rows(session)[0]
    edits.paint_panels(session, [PanelRef(None, first, 2), PanelRef("Nose", "A", 1)], "#00b050")
    edits.rename_row(session, first, "Z")
    assert session.state.colours.colour_of(PanelRef(None, "Z", 2)) == "#00b050"

    def rename(shapes: list[dict[str, object]]) -> None:
        shapes[0]["name"] = "Snout"

    session.edit_shapes("rename", rename)
    assert session.state.colours.colour_of(PanelRef("Snout", "A", 1)) == "#00b050"
    # Removing the shape keeps its colours until the next colour edit prunes them.
    edits.remove_shape(session, "Snout")
    assert "Snout" in session.state.colours.shapes
    edits.paint_panels(session, [PanelRef(None, "Z", 1)], "#ffffff")
    assert "Snout" not in session.state.colours.shapes


def test_replace_and_clear_all(session: ProjectSession) -> None:
    rows = _rows(session)
    edits.paint_panels(session, [PanelRef(None, r, 1) for r in rows], "#ff0000")
    edits.paint_panels(session, [PanelRef(None, rows[0], 2)], "#0000ff")
    assert edits.replace_colour(session, "#ff0000", "#00ff00")
    assert session.state.colours.used() == ["#00ff00", "#0000ff"]
    assert edits.clear_colours(session)
    assert session.state.colours.is_empty()
    session.undo()
    assert session.state.colours.used() == ["#00ff00", "#0000ff"]


# -- colours on the 3D displays ----------------------------------------------------------


def test_envelope_sketch_knows_every_triangles_gore_and_row(session: ProjectSession) -> None:
    from envelopelab.project.placement_map import azimuth_position, envelope_sketch

    sketch = envelope_sketch(session.design)
    assert sketch.row_letters == tuple(_rows(session))
    centres = sketch.points[sketch.triangles].mean(axis=1)
    gores = [int(azimuth_position(c, int(sketch.face_gore.max()))) + 1 for c in centres]
    assert np.array_equal(sketch.face_gore, gores)
    # Row seams are grid rings: every triangle lies within its row's tape positions.
    assert set(sketch.face_row.tolist()) == set(range(len(_rows(session))))


def test_envelope_face_colours_follow_the_panels(session: ProjectSession) -> None:
    from envelopelab.project.colours import envelope_face_colours
    from envelopelab.project.placement_map import envelope_sketch

    sketch = envelope_sketch(session.design)
    rows = _rows(session)
    c = painted(PanelColours(), [PanelRef(None, rows[1], 3)], "#ff0000")
    rgb, mask = envelope_face_colours(c, sketch.row_letters, sketch.face_row, sketch.face_gore)
    expected = (sketch.face_row == 1) & (sketch.face_gore == 3)
    assert np.array_equal(mask, expected) and expected.any()
    assert np.allclose(rgb[mask], [1.0, 0.0, 0.0]) and np.all(rgb[~mask] == 0.0)


def test_shape_display_tiers_and_face_colours(session: ProjectSession) -> None:
    from envelopelab.features.scene import designed_display
    from envelopelab.project.colours import shape_face_colours
    from envelopelab.project.shapes import shape_design

    spec = _dome(session, gores=6, splits=[0.4])
    placed = shape_design(spec, envelope_surface(session.design, session.patterns))
    shown = designed_display(placed, rows=20, per_piece=3)
    assert shown.tier is not None and set(shown.tier.tolist()) == {0, 1}
    c = painted(
        PanelColours(),
        [PanelRef("Nose", "B", 2), PanelRef("Nose", CAP, 1)],
        "#0000ff",
    )
    _rgb, mask = shape_face_colours(c, "Nose", shown.piece, shown.pieces, shown.tier)
    on_skin = (shown.piece == 1) & (shown.tier == 1)
    cap = shown.piece >= shown.pieces
    assert np.array_equal(mask, on_skin | cap) and on_skin.any() and cap.any()
    # Another shape's colours do not leak.
    assert not shape_face_colours(c, "Other", shown.piece, shown.pieces, shown.tier)[1].any()


# -- half gores (each half its own colour) -------------------------------------------------


def test_a_half_overrides_its_panel_and_a_whole_paint_resets_both_halves() -> None:
    left = PanelRef(None, "C", 3, "left")
    c = painted(PanelColours(), [PanelRef(None, "C", 3)], "#ff0000")
    c = painted(c, [left], "#0000ff")
    assert c.half_colours("C", 3) == ("#0000ff", "#ff0000")
    assert c.colour_of(PanelRef(None, "C", 3)) == "#ff0000"
    assert set(c.used()) == {"#ff0000", "#0000ff"}
    assert painted(c, [left], None).half_colours("C", 3) == ("#ff0000", "#ff0000")
    whole = painted(c, [PanelRef(None, "C", 3)], "#00ff00")
    assert whole.halves == {} and whole.half_colours("C", 3) == ("#00ff00", "#00ff00")
    # Replacing a colour keeps the other half's own colour.
    swapped = replaced(c, "#ff0000", "#00ff00")
    assert swapped.half_colours("C", 3) == ("#0000ff", "#00ff00")
    with pytest.raises(ValueError, match="left or right"):
        PanelColours.model_validate({"halves": {"C": {"3": {"middle": "#ffffff"}}}})


def test_halves_round_trip_prune_and_rename() -> None:
    c = painted(PanelColours(), [PanelRef(None, "C", 3, "right")], "#123456")
    assert PanelColours.model_validate(json.loads(json.dumps(c.to_data()))) == c
    assert pruned(c, ["C"], 8, halved=["C"]) == c
    assert pruned(c, ["C"], 8).is_empty()  # C no longer cut as half gores
    assert renamed(c, ["C"], ["Z"], shapes=False).half_colours("Z", 3)[1] == "#123456"


def test_envelope_targets_paint_the_half_clicked() -> None:
    assert envelope_targets(["A", "C"], 8, "C", 2, "panel", every=4, half="left") == [
        PanelRef(None, "C", 2, "left"),
        PanelRef(None, "C", 6, "left"),
    ]
    assert all(r.half is None for r in envelope_targets(["A", "C"], 8, "C", 2, "row", half="left"))


def test_half_gore_cells_and_3d_faces_agree(session: ProjectSession) -> None:
    from envelopelab.project.colours import envelope_face_colours, face_halves
    from envelopelab.project.placement_map import envelope_sketch

    edits.set_half_gores(session, [_rows(session)[1]], True)
    row = _rows(session)[1]
    m = gore_map(envelope_surface(session.design, session.patterns))
    cells = dict(envelope_cells(m, [row]))
    left, right = cells[PanelRef(None, row, 2, "left")], cells[PanelRef(None, row, 2, "right")]
    centre = 1.5 * m.column
    assert left[:, 0].max() == pytest.approx(centre) and right[:, 0].min() == pytest.approx(centre)
    sketch = envelope_sketch(session.design)
    assert sketch.halved == (row,)
    # The sketch's halves by column are the halves by azimuth.
    assert np.array_equal(sketch.face_half, face_halves(sketch.points, sketch.triangles, m.gores))
    c = painted(PanelColours(), [PanelRef(None, row, 2, "left")], "#ff0000")
    _rgb, mask = envelope_face_colours(
        c, sketch.row_letters, sketch.face_row, sketch.face_gore, sketch.face_half, sketch.halved
    )
    expected = (sketch.face_row == 1) & (sketch.face_gore == 2) & (sketch.face_half == 0)
    assert np.array_equal(mask, expected) and expected.any()
    # Without the row cut as half gores the half colour is not drawn.
    _rgb, mask = envelope_face_colours(
        c, sketch.row_letters, sketch.face_row, sketch.face_gore, sketch.face_half, ()
    )
    assert not mask.any()
