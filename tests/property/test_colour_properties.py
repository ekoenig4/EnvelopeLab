"""Panel colours (ADR-0055): JSON round trips are lossless and painting is reversible;
overlay symmetry (ADR-0056): a symmetric polygon is its own mirror image in every axis."""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from envelopelab.project.colours import CAP, PanelColours, PanelRef, painted, repeated

COLOUR = st.integers(0, 0xFFFFFF).map(lambda v: f"#{v:06x}")
REF = st.one_of(
    st.builds(PanelRef, st.none(), st.sampled_from("ABCDEFGH"), st.integers(1, 64)),
    st.builds(
        PanelRef,
        st.sampled_from(["Nose", "Ear 1", "tail"]),
        st.sampled_from(["A", "B", "C", CAP]),
        st.integers(1, 64),
    ),
)
STROKES = st.lists(st.tuples(st.lists(REF, min_size=1, max_size=8), COLOUR), max_size=8)


def _paint(strokes: list[tuple[list[PanelRef], str]]) -> PanelColours:
    c = PanelColours()
    for refs, colour in strokes:
        c = painted(c, refs, colour)
    return c


@settings(max_examples=60, deadline=None)
@given(strokes=STROKES)
def test_colours_round_trip_through_json(strokes: list[tuple[list[PanelRef], str]]) -> None:
    c = _paint(strokes)
    text = json.dumps(c.to_data(), sort_keys=True)
    assert PanelColours.model_validate(json.loads(text)) == c


@settings(max_examples=60, deadline=None)
@given(strokes=STROKES)
def test_the_last_stroke_wins_and_clearing_every_panel_empties(
    strokes: list[tuple[list[PanelRef], str]],
) -> None:
    c = _paint(strokes)
    last: dict[PanelRef, str] = {}
    for refs, colour in strokes:
        for ref in refs:
            last[ref] = colour
    assert all(c.colour_of(ref) == colour for ref, colour in last.items())
    assert painted(c, list(last), None).is_empty()


@settings(max_examples=100, deadline=None)
@given(count=st.integers(3, 64), data=st.data())
def test_a_repeat_visits_each_gore_once(count: int, data: st.DataObject) -> None:
    index = data.draw(st.integers(1, count))
    every = data.draw(st.integers(0, 70))
    out = repeated(index, count, every)
    assert out[0] == index and len(set(out)) == len(out)
    assert all(1 <= g <= count for g in out)
    if 0 < every < count:
        assert all((b - a) % count == every % count for a, b in zip(out, out[1:], strict=False))


# -- overlay symmetry (ADR-0056) ------------------------------------------------------------

POINT = st.tuples(st.floats(-2.0, 2.0), st.floats(-2.0, 2.0))


@settings(max_examples=80, deadline=None)
@given(axes=st.integers(1, 8), chain=st.lists(POINT, min_size=2, max_size=6))
def test_a_symmetric_polygon_is_its_own_mirror_image_in_every_axis(
    axes: int, chain: list[tuple[float, float]]
) -> None:
    import math

    import numpy as np

    from envelopelab.project.overlays import axis_angles, symmetric_polygon

    outline, owners = symmetric_polygon(chain, axes)
    for angle in axis_angles(axes):
        c, s = math.cos(math.radians(2 * angle)), math.sin(math.radians(2 * angle))
        image = outline @ np.array([[c, s], [s, -c]])
        for q in image:
            assert float(np.min(np.linalg.norm(outline - q, axis=1))) < 1e-7
    # Every corner is the image of its owner by its matrix (the owner moved onto an axis
    # when it lies within AXIS_SNAP of one).
    from envelopelab.project.overlays import AXIS_SNAP

    for corner, (g, t) in zip(outline, owners, strict=True):
        assert np.allclose(np.asarray(chain[g], float) @ t, corner, atol=AXIS_SNAP)
