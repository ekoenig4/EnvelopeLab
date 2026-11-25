"""Lift-chart settings: validation, project file (format 9), undo and the build pack."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from envelopelab.design.model import TaggedValue
from envelopelab.export.build_pack import PackExtras, export_build_pack
from envelopelab.export.lift_chart import chart_axes, chart_inputs
from envelopelab.project import edits
from envelopelab.project.gore_design import gore_outputs
from envelopelab.project.lift_chart_settings import LiftChartSettings
from envelopelab.project.model import dump_project, load_project_text
from envelopelab.project.session import ProjectSession

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "standard_gore" / "design.elproj"

CUSTOM = LiftChartSettings(
    altitudes=[1500.0, 500.0],
    ambient_temperatures=[300.15, 280.15],
    isa_offsets=[10.0],
    max_load=900.0,
    lowest_top_temperature=353.15,
    top_to_mean=TaggedValue(value=12.0, source="measured", note="crown vs. mid-height log"),
)


@pytest.fixture
def session() -> ProjectSession:
    return ProjectSession.open(FIXTURE)


def test_defaults_match_the_charts_before_the_settings() -> None:
    s = LiftChartSettings()
    assert s.altitudes == [0.0, 1000.0, 2000.0, 3000.0]
    assert [round(t - 273.15) for t in s.ambient_temperatures] == [-10, 0, 10, 20, 30]
    assert s.isa_offsets == [-15.0, 0.0, 15.0, 30.0]
    assert s.max_load is None
    assert s.top_to_mean.value == 20.0 and s.top_to_mean.source == "assumed"
    assert s.is_default() and s.to_data() == {}


def test_values_are_sorted() -> None:
    assert CUSTOM.altitudes == [500.0, 1500.0]
    assert CUSTOM.ambient_temperatures == [280.15, 300.15]
    assert not CUSTOM.is_default()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("altitudes", [], "at least one"),
        ("altitudes", [0.0, 0.0], "must differ"),
        ("altitudes", [0.0, 1.0, 2.0, 3.0, 4.0], "at most 4"),
        ("altitudes", [12000.0], "between"),
        ("ambient_temperatures", [400.0], "between"),
        ("isa_offsets", [60.0], "between"),
        ("max_load", 0.0, "above 0 kg"),
        ("lowest_top_temperature", 500.0, "between"),
        ("top_to_mean", {"value": -1.0, "source": "assumed"}, "between"),
        ("mouth_excess", {"value": 1.5, "source": "assumed"}, "between 0 % and 100 %"),
        ("mean_model", "guess", "envelope_shape"),
    ],
)
def test_bad_settings_are_refused_with_a_reason(field: str, value: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        LiftChartSettings.model_validate({field: value})


def test_default_settings_leave_file_and_fingerprints_unchanged(session: ProjectSession) -> None:
    before = session.fingerprints()
    data = json.loads(dump_project(session.project))
    assert "lift_chart" not in data["state"]
    assert data["format_version"] == 10
    edits.set_lift_chart(session, CUSTOM)
    assert session.fingerprints()["export"] != before["export"]
    assert session.fingerprints()["simulation"] == before["simulation"]
    edits.set_lift_chart(session, None)
    assert session.fingerprints() == before


def test_settings_survive_save_load_and_snapshots(session: ProjectSession, tmp_path: Path) -> None:
    edits.set_lift_chart(session, CUSTOM)
    session.create_snapshot("custom")
    path = session.save(tmp_path / "lift.elproj")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["state"]["lift_chart"]["altitudes"] == [500.0, 1500.0]
    again = ProjectSession.open(path)
    assert again.project.state.lift_chart == CUSTOM
    assert again.project.snapshots[0].state.lift_chart == CUSTOM


def test_version_8_files_read_with_default_settings(session: ProjectSession) -> None:
    data = json.loads(dump_project(session.project))
    data["format_version"] = 8
    project = load_project_text(json.dumps(data))
    assert project.format_version == 10
    assert project.state.lift_chart.is_default()


def test_setting_is_one_undo_step_and_survives_design_edits(session: ProjectSession) -> None:
    assert edits.set_lift_chart(session, CUSTOM)
    assert not edits.set_lift_chart(session, CUSTOM)  # no change, no history entry
    session.set_design_value(("operating", "payload_mass"), 321.0)
    assert session.project.state.lift_chart == CUSTOM
    session.undo()
    assert session.project.state.lift_chart == CUSTOM
    session.undo()
    assert session.project.state.lift_chart.is_default()


def test_chart_axes_follow_the_settings(session: ProjectSession) -> None:
    inputs = chart_inputs(session.design, gore_outputs(session.design, session.patterns))
    assert inputs is not None
    axes = chart_axes(inputs, CUSTOM)
    assert axes.altitudes == (500.0, 1500.0)
    assert axes.ambient_temperatures == (280.15, 300.15)
    assert axes.isa_offsets == (10.0,)
    assert axes.loads[0] == 0.0 and axes.loads[-1] == pytest.approx(900.0)
    assert axes.top_temperatures[0] == pytest.approx(353.15)
    assert axes.top_temperatures[-1] == pytest.approx(inputs.top_limit.value)


def test_build_pack_uses_the_project_settings(session: ProjectSession, tmp_path: Path) -> None:
    out = tmp_path / "pack"
    export_build_pack(
        session.design,
        [],
        out,
        session.patterns,
        extras=PackExtras(frozenset({"lift_chart"}), lift_chart=CUSTOM),
    )
    (path,) = out.glob("*-lift-chart.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    loads = [r for r in rows if r["solved_for"] == "load"]
    assert {r["altitude_m"] for r in loads} == {"500.0", "1500.0"}
    assert {r["ambient_C"] for r in loads} == {"7.00", "27.00"}
    # Envelope-shape model: the measured 12 K is the floor, the profile may need more.
    offsets = [float(r["top_C"]) - float(r["mean_C"]) for r in loads]
    assert min(offsets) >= 12.0 - 1e-6
    ceilings = [r for r in rows if r["solved_for"] == "altitude"]
    assert {r["isa_offset_K"] for r in ceilings} == {"10.0"}
    # With a fixed offset the measured 12 K is used exactly.
    fixed = CUSTOM.model_copy(update={"mean_model": "fixed_offset"})
    out2 = tmp_path / "fixed"
    export_build_pack(
        session.design,
        [],
        out2,
        session.patterns,
        extras=PackExtras(frozenset({"lift_chart"}), lift_chart=fixed),
    )
    (path2,) = out2.glob("*-lift-chart.csv")
    rows2 = [r for r in csv.DictReader(path2.open(encoding="utf-8")) if r["solved_for"] == "load"]
    assert {round(float(r["top_C"]) - float(r["mean_C"]), 6) for r in rows2} == {12.0}


def test_mean_model_defaults_to_the_envelope_shape() -> None:
    s = LiftChartSettings()
    assert s.mean_model == "envelope_shape"
    assert s.mouth_excess.value == 0.5 and s.mouth_excess.source == "assumed"
    assert s.top_to_mean.value == 20.0  # the floor


def test_version_9_custom_settings_read_with_the_shape_model(session: ProjectSession) -> None:
    edits.set_lift_chart(session, CUSTOM)
    data = json.loads(dump_project(session.project))
    data["format_version"] = 9
    for key in ("mean_model", "mouth_excess"):
        del data["state"]["lift_chart"][key]
    project = load_project_text(json.dumps(data))
    assert project.state.lift_chart.mean_model == "envelope_shape"
    assert project.state.lift_chart.altitudes == CUSTOM.altitudes


def test_mouth_excess_is_entered_in_percent() -> None:
    from envelopelab.project.lift_chart_settings import displayed, from_displayed

    settings = LiftChartSettings(
        mean_model="fixed_offset",
        mouth_excess=TaggedValue(value=0.35, source="measured", note="flight 3"),
    )
    shown = displayed(settings, "english")
    assert shown.mouth_excess == pytest.approx(35.0)
    assert shown.mean_model == "fixed_offset" and shown.mouth_source == "measured"
    assert from_displayed(shown) == settings
