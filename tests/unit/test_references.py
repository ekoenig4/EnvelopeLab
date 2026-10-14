"""Reference profiles: from files and snapshots, compared with the design, saved."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from envelopelab.project import edits
from envelopelab.project import references as rf
from envelopelab.project.gore_design import design_profile, standard_gore_design
from envelopelab.project.session import ProjectSession

ROOT = Path(__file__).resolve().parents[2]
SHAPE = ROOT / "tests" / "fixtures" / "flat_chord_pattern" / "shape.yaml"
PROJECT = ROOT / "tests" / "fixtures" / "standard_gore" / "design.elproj"


def session() -> ProjectSession:
    return ProjectSession.new(standard_gore_design("ref", 2600.0, 17.0, 18.0, 16, 8))


def test_references_come_from_shape_files_and_projects() -> None:
    shape = rf.reference_from_file(SHAPE)
    assert shape.name == "shape" and shape.source == str(SHAPE)
    assert len(shape.r) == rf.REFERENCE_SAMPLES
    from envelopelab.io.shape_file import load_shape_file

    profile = design_profile(load_shape_file(SHAPE).design())
    assert shape.r[0] == pytest.approx(profile.r[0]) and shape.z[-1] == pytest.approx(profile.z[-1])
    project = rf.reference_from_file(PROJECT, name="old")
    assert project.name == "old"
    with pytest.raises((OSError, ValueError)):
        rf.reference_from_file(ROOT / "README.md")


def test_a_snapshot_keeps_the_profile_as_it_was() -> None:
    s = session()
    snap = rf.add_reference(s, rf.snapshot_reference(s.design))
    # The stored outline is a 401-point sampling of the profile: within a millimetre.
    assert rf.reference_deviation(snap, s.design) < 1e-3
    edits.scale_points(s, [4, 5, 6, 7], 1.1, 1.0)
    assert rf.reference_deviation(s.project.references[0], s.design) > 0.05
    # An offset shifts the reference (and the comparison) up.
    shifted = rf.update_reference(s, 0, z_offset=0.5)
    assert rf.reference_profile(shifted).z[0] == pytest.approx(snap.z[0] + 0.5)


def test_names_are_unique_and_edits_are_checked() -> None:
    s = session()
    ref = rf.reference_from_file(SHAPE)
    rf.add_reference(s, ref)
    rf.add_reference(s, ref)
    assert [r.name for r in s.project.references] == ["shape", "shape (2)"]
    with pytest.raises(ValueError, match="already used"):
        rf.update_reference(s, 1, name="shape")
    with pytest.raises(ValueError, match="finite"):
        rf.update_reference(s, 1, z_offset=np.inf)
    assert not rf.update_reference(s, 1, visible=False).visible
    rf.remove_reference(s, 0)
    assert [r.name for r in s.project.references] == ["shape (2)"]
    with pytest.raises(IndexError):
        rf.remove_reference(s, 5)


def test_references_are_saved_with_the_project(tmp_path: Path) -> None:
    s = session()
    rf.add_reference(s, rf.reference_from_file(SHAPE))
    rf.update_reference(s, 0, z_offset=0.25, visible=False)
    assert s.is_dirty
    path = s.save(tmp_path / "with-refs.elproj")
    again = ProjectSession.open(path)
    (ref,) = again.project.references
    assert ref.name == "shape" and ref.z_offset == 0.25 and not ref.visible
    assert ref.r == s.project.references[0].r
