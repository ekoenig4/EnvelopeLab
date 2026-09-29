"""Parachute in a gore design: pieces, mass, findings, edits and staleness."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from envelopelab.geometry.parachute import gore_outline
from envelopelab.mass_estimate import estimate_parachute_mass
from envelopelab.materials.repository import MaterialProperty
from envelopelab.project import edits
from envelopelab.project.dependencies import ARTIFACTS, invalidated_by
from envelopelab.project.gore_design import (
    ASSUMED_THREAD,
    design_findings,
    design_parachute,
    gore_outputs,
)
from envelopelab.project.session import ProjectSession

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"


@pytest.fixture
def session() -> ProjectSession:
    s = ProjectSession.open(FIXTURE)
    for spec in ARTIFACTS:
        s.mark_built(spec.name)
    return s


def codes(session: ProjectSession) -> set[str]:
    return {f.code for f in design_findings(session.design, session.patterns)}


def test_parachute_edits_touch_patterns_only() -> None:
    assert invalidated_by({"parachute"}) == {"patterns", "nesting", "export"}


def test_added_parachute_covers_the_hole_with_the_seal_overlap(session: ProjectSession) -> None:
    g = session.design.gores
    assert g is not None and g.parachute is None
    assert edits.add_parachute(session)
    assert not edits.add_parachute(session)  # already there
    g = session.design.gores
    assert g is not None and g.parachute is not None
    assert g.parachute.gore_count == g.count
    assert g.parachute.diameter == pytest.approx(g.parachute_hole_diameter + 2 * g.seal_overlap)
    pieces = design_parachute(session.design, session.patterns)
    assert pieces is not None
    assert pieces.finished_area == pytest.approx(
        math.pi * (g.parachute.diameter / 2) ** 2, rel=1e-4
    )
    assert not {"parachute_seam", "parachute_overlap", "parachute"} & codes(session)
    status = session.tracker.statuses()
    assert status["patterns"] == status["nesting"] == status["export"] == "stale"
    for name in ("profile", "assembly", "rest_mesh", "simulation", "flattening"):
        assert status[name] == "current", name
    session.undo()
    assert session.design.gores is not None and session.design.gores.parachute is None
    assert session.artifact_status("patterns") == "current"


def test_parachute_mass_is_part_of_the_envelope_mass(session: ProjectSession) -> None:
    before = gore_outputs(session.design, session.patterns)
    assert before.parachute is None and before.envelope_mass is not None
    edits.add_parachute(session)
    after = gore_outputs(session.design, session.patterns)
    assert after.parachute is not None and after.envelope_mass is not None
    assert after.envelope_mass == pytest.approx(before.envelope_mass + after.parachute.total_mass)
    assert before.lift_margin is not None and after.lift_margin is not None
    assert after.lift_margin == pytest.approx(before.lift_margin - after.parachute.total_mass)
    assert after.volume == before.volume  # the parachute does not change the lift


def test_parachute_mass_hand_calculation() -> None:
    from envelopelab.geometry.parachute import parachute_pieces

    pieces = parachute_pieces(4.0, 0.8, 16, 0.0)
    mu = MaterialProperty(0.05, "assumed")
    tape = MaterialProperty(0.02, "assumed")
    est = estimate_parachute_mass(pieces, "a", "b", {"a": mu, "b": mu}, tape, tape, ASSUMED_THREAD)
    fabric = math.pi * 2.0**2 * 0.05  # no allowance: finished = cut
    assert est.fabric_mass == pytest.approx(fabric, rel=1e-4)
    assert est.tape_lengths["radial"] == pytest.approx(16 * 1.6)
    assert est.tape_lengths["rim"] == pytest.approx(math.pi * 4.0, rel=1e-5)
    seams = 16 * 1.6 + math.pi * 0.8
    thread = 2.75 * 2 * seams * 30e-6
    assert est.thread_mass == pytest.approx(thread, rel=1e-5)
    assert est.total_mass == pytest.approx(
        fabric + 0.02 * (25.6 + math.pi * 4.0) + thread, rel=1e-4
    )
    assert est.sources == ("assumed",)


def test_mismatched_override_and_stale_override_are_errors(session: ProjectSession) -> None:
    edits.add_parachute(session)
    spec = session.design.gores.parachute  # type: ignore[union-attr]
    assert spec is not None
    gore = gore_outline(spec.diameter / 2, spec.centre_diameter / 2, spec.gore_count)
    # A smooth shear: the right side gets longer and the left shorter, no new corners.
    skewed = gore.copy()
    skewed[:, 1] *= 1.0 + 0.02 * skewed[:, 0] / np.abs(skewed[:, 0]).max()
    edits.set_parachute_outline(session, "gore", [tuple(p) for p in skewed], "test")
    found = codes(session)
    assert {"manual_override", "parachute_seam"} <= found
    assert "manual_override_outdated" not in found
    assert session.project.provenance[-1].target == "parachute gore"
    edits.set_parachute_value(session, "diameter", spec.diameter + 0.1)
    assert "manual_override_outdated" in codes(session)


def test_centre_seam_must_match_the_gore_ends(session: ProjectSession) -> None:
    edits.add_parachute(session)
    spec = session.design.gores.parachute  # type: ignore[union-attr]
    assert spec is not None
    t = np.linspace(0, 2 * np.pi, 200, endpoint=False)
    r = spec.centre_diameter / 2 + 0.01  # 10 mm too big all round
    disc = [(float(r * np.cos(a)), float(r * np.sin(a))) for a in t]
    edits.set_parachute_outline(session, "centre", disc, "test")
    messages = [f.message for f in design_findings(session.design, session.patterns)]
    assert any("parachute centre seam" in m for m in messages)
