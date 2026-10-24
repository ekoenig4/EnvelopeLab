"""Segment profiles as undoable edits: convert, change spans, insert, delete, locks."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from envelopelab.design.model import (
    CURRENT_SCHEMA_VERSION,
    _raw_hash,
    dump_design_document,
    load_design_document,
)
from envelopelab.geometry.profile_editing import profile_deviation
from envelopelab.project import edits
from envelopelab.project.gore_design import (
    check_locks,
    control_arrays,
    design_findings,
    design_profile,
    design_volume,
    standard_gore_design,
)
from envelopelab.project.model import PatternSet
from envelopelab.project.session import ProjectSession

#: Distance between two dense samplings of the same curve, m (20 um).
SAMPLING = 2e-5
POINTS = [(2.7, 0.0), (6.5, 3.0), (9.0, 6.5), (9.0, 10.0), (6.0, 15.0), (1.2, 17.0)]


def session() -> ProjectSession:
    s = ProjectSession.new(standard_gore_design("seg", 2600.0, 17.0, 18.0, 16, 8))
    edits.set_control_points(s, POINTS, "Shape")
    return s


@pytest.mark.parametrize("start", ["spline", "linear"])
def test_switching_to_segments_draws_the_same_profile(start: str) -> None:
    s = session()
    edits.set_profile_interpolation(s, start)  # type: ignore[arg-type]
    before = design_profile(s.design)
    assert edits.set_profile_interpolation(s, "segments")
    gores = s.design.gores
    assert gores is not None and gores.profile_segments is not None
    kind = "line" if start == "linear" else "curve"
    assert {seg.kind for seg in gores.profile_segments} == {kind}
    after = design_profile(s.design)
    assert np.array_equal(before.r, after.r) and np.array_equal(before.z, after.z)
    assert not edits.set_profile_interpolation(s, "segments")
    assert edits.set_profile_interpolation(s, start)  # type: ignore[arg-type]
    assert s.design.gores is not None and s.design.gores.profile_segments is None


def test_a_cone_a_cylinder_and_an_arc_shoulder() -> None:
    s = session()
    edits.set_profile_interpolation(s, "segments")
    edits.set_profile_segment(s, 0, kind="line")
    edits.set_profile_segment(s, 1, kind="line", smooth=False)  # a corner
    edits.set_profile_segment(s, 2, kind="line", smooth=False)
    edits.set_profile_segment(s, 3, kind="arc", smooth=False)
    edits.set_profile_segment(s, 3, bulge=0.25)
    gores = s.design.gores
    assert gores is not None and gores.profile_segments is not None
    assert [seg.kind for seg in gores.profile_segments] == ["line"] * 3 + ["arc", "curve"]
    assert gores.profile_segments[3].bulge == 0.25
    # The cylinder is straight: every sample between z 6.5 and 10 is at r 9.
    profile = design_profile(s.design)
    band = (profile.z > 6.5 + 1e-6) & (profile.z < 10.0 - 1e-6)
    assert np.allclose(profile.r[band], 9.0)
    assert not [f for f in design_findings(s.design, PatternSet()) if f.code == "profile_kink"]
    # Each change is one undo.
    for _ in range(6):
        s.undo()
    assert s.design.gores is not None and s.design.gores.profile_interpolation != "segments"


def test_inserting_into_an_arc_and_deleting_keep_the_shape() -> None:
    s = session()
    edits.set_profile_interpolation(s, "segments")
    for k in range(5):
        edits.set_profile_segment(s, k, kind="arc", smooth=False)
        edits.set_profile_segment(s, k, bulge=0.15)
    before = design_profile(s.design)
    assert edits.insert_control_point(s, 3)
    # Same arcs; only the dense sampling differs (chord sag of a ~12 mm step: ~6 um).
    assert profile_deviation(before, design_profile(s.design)) < SAMPLING
    gores = s.design.gores
    assert gores is not None and gores.profile_segments is not None
    assert len(gores.profile_segments) == 6
    assert edits.delete_control_point(s, 4)
    assert profile_deviation(before, design_profile(s.design)) < SAMPLING
    assert edits.delete_control_point(s, 0)  # the mouth span goes with the mouth point
    assert s.design.gores is not None and s.design.gores.profile_segments is not None
    assert len(s.design.gores.profile_segments) == 4


def test_straighten_makes_lines_and_simplify_is_refused() -> None:
    s = session()
    edits.set_profile_interpolation(s, "segments")
    assert edits.straighten_points(s, 1, 4)
    gores = s.design.gores
    assert gores is not None and gores.profile_segments is not None
    assert [seg.kind for seg in gores.profile_segments[1:4]] == ["line"] * 3
    with pytest.raises(ValueError, match="segment profile"):
        edits.simplify_profile(s, 0.01)


def test_locks_hold_on_a_segment_profile() -> None:
    s = session()
    edits.set_profile_interpolation(s, "segments")
    edits.set_profile_segment(s, 2, kind="line")
    for name in ("volume", "height", "mouth_diameter", "top_diameter"):
        edits.set_lock(s, name, True)
    volume = design_volume(s.design)
    edits.set_profile_segment(s, 3, kind="arc", smooth=False)
    edits.set_profile_segment(s, 3, bulge=0.4)
    edits.move_points(s, [2, 3], 0.4, 0.0)
    assert check_locks(s.design, s.project.locks) == []
    assert design_volume(s.design) == pytest.approx(volume, rel=1e-3)


def test_span_edits_check_their_values() -> None:
    s = session()
    with pytest.raises(ValueError, match="segments"):
        edits.set_profile_segment(s, 0, kind="line")
    edits.set_profile_interpolation(s, "segments")
    with pytest.raises(IndexError):
        edits.set_profile_segment(s, 9, kind="line")
    with pytest.raises(ValueError, match="bulge"):
        edits.set_profile_segment(s, 0, bulge=math.inf)
    with pytest.raises(ValueError, match="kind"):
        edits.set_profile_segment(s, 0, kind="spiral")  # type: ignore[arg-type]


def test_version_6_documents_migrate_without_segments() -> None:
    design = session().design
    raw = json.loads(dump_design_document(design))
    raw["schema_version"] = 6
    del raw["gores"]["profile_segments"]
    raw["meta"]["content_hash"] = None
    raw["meta"]["content_hash"] = _raw_hash(raw)
    loaded = load_design_document(json.dumps(raw))
    assert loaded.schema_version == CURRENT_SCHEMA_VERSION == 8
    assert loaded.gores is not None and loaded.gores.profile_segments is None
    r, _ = control_arrays(loaded)
    assert r.size == len(POINTS)


def test_the_schema_checks_one_segment_per_span() -> None:
    from pydantic import ValidationError

    data = json.loads(dump_design_document(session().design))
    data["gores"]["profile_interpolation"] = "segments"
    data["gores"]["profile_segments"] = [{"kind": "line"}]
    with pytest.raises(ValidationError, match="one profile segment per span"):
        load_design_document(json.dumps(data))
    data["gores"]["profile_interpolation"] = "spline"
    with pytest.raises(ValidationError, match="need profile_interpolation"):
        load_design_document(json.dumps(data))
