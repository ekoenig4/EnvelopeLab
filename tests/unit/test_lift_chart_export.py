"""Build-pack lift chart: PDF and CSV from the design (envelopelab.export.lift_chart)."""

from __future__ import annotations

import csv
import dataclasses
import math
from collections.abc import Callable
from pathlib import Path

import pytest

from envelopelab.export.build_pack import PackExtras, export_build_pack
from envelopelab.export.documents import DOCUMENTS
from envelopelab.export.lift_chart import (
    CSV_COLUMNS,
    build_chart,
    chart_axes,
    chart_inputs,
    fahrenheit,
    ft,
    lb,
    top_temperature_limit,
)
from envelopelab.export.qa import _page_boxes, check_pack
from envelopelab.lift_chart import equilibrium_load
from envelopelab.materials.repository import EXAMPLE_FABRICS, FabricCatalog, MaterialProperty
from envelopelab.project.gore_design import gore_outputs, standard_gore_design
from envelopelab.project.model import PatternSet

BASE = standard_gore_design("Lift Sample", 2000.0, 17.0, 16.0, 12, 6)
DESIGN = BASE.model_copy(
    update={"operating": BASE.operating.model_copy(update={"payload_mass": 300.0})}
)
OUTPUTS = gore_outputs(DESIGN, PatternSet())


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("lift-pack")
    export_build_pack(DESIGN, [], out, extras=PackExtras(frozenset({"lift_chart", "index"})))
    return out


def _text(pdf: Path) -> str:
    return "\n".join(text for _w, _h, text in _page_boxes(pdf))


def test_lift_chart_is_a_pack_document(pack: Path) -> None:
    assert "lift_chart" in DOCUMENTS
    assert (pack / "lift-sample-lift-chart.pdf").exists()
    assert (pack / "lift-sample-lift-chart.csv").exists()
    assert check_pack(pack) == []


def test_pdf_shows_limit_inputs_and_assumptions(pack: Path) -> None:
    text = _text(pack / "lift-sample-lift-chart.pdf")
    assert text.count("LIFT CHART") == 3  # one header per page
    assert "LIMIT 120 degC" in text
    assert "ABOVE TOP-TEMPERATURE LIMIT - NOT PERMITTED" in text
    assert "[assumed]" in text and "top - 20 K" in text
    assert "design load 300 kg / 661 lb" in text
    assert "LIMIT 120 degC / 248 degF" in text
    for unit in ("lb", "degF", "ft"):  # English scales; PDF escapes the parentheses
        assert f"\\({unit}\\)" in text
    assert "not certified engineering software" in text


def test_csv_lists_every_equilibrium_point_with_status(pack: Path) -> None:
    rows = list(csv.reader((pack / "lift-sample-lift-chart.csv").open(encoding="utf-8")))
    assert tuple(rows[0]) == CSV_COLUMNS
    inputs = chart_inputs(DESIGN, OUTPUTS)
    assert inputs is not None
    chart = build_chart(inputs, chart_axes(inputs))
    assert len(rows) - 1 == len(chart.points())
    statuses = {r[-1] for r in rows[1:]}
    assert {"ok", "above_limit"} <= statuses
    first = rows[1]
    point = equilibrium_load(inputs, float(first[1]), float(first[3]) + 273.15, 343.15)
    assert float(first[6]) == pytest.approx(point.load, abs=0.01)


@pytest.mark.parametrize(
    ("metric", "english", "convert"),
    [
        (1.0, 2.2046226218, lb),
        (100.0, 212.0, fahrenheit),
        (-40.0, -40.0, fahrenheit),
        (0.3048, 1.0, ft),
    ],
)
def test_english_units_are_exact_conversions(
    metric: float, english: float, convert: Callable[[float], float]
) -> None:
    assert convert(metric) == pytest.approx(english, rel=1e-10)


def test_inputs_come_from_the_design_outputs() -> None:
    inputs = chart_inputs(DESIGN, OUTPUTS)
    assert inputs is not None
    assert inputs.volume == OUTPUTS.volume
    assert OUTPUTS.envelope_mass is not None and OUTPUTS.rigging_mass is not None
    assert inputs.fixed_mass == pytest.approx(OUTPUTS.envelope_mass + OUTPUTS.rigging_mass)
    assert inputs.top_limit.source == "assumed"  # no library: generic 120 degC
    assert inputs.top_limit.value == pytest.approx(393.15)


def test_axes_reach_the_most_the_balloon_lifts() -> None:
    inputs = chart_inputs(DESIGN, OUTPUTS)
    assert inputs is not None
    axes = chart_axes(inputs)
    most = equilibrium_load(inputs, 0.0, 263.15, inputs.top_limit.value).load
    assert axes.loads[0] == 0.0 and axes.loads[-1] >= most
    assert axes.top_temperatures[-1] == pytest.approx(inputs.top_limit.value)


def test_limit_is_the_lowest_fabric_service_temperature() -> None:
    nylon = dataclasses.replace(
        EXAMPLE_FABRICS[0], max_service_temperature=MaterialProperty(100.0, "datasheet - test")
    )
    catalog = FabricCatalog((nylon, *EXAMPLE_FABRICS[1:]))
    limit = top_temperature_limit(DESIGN, catalog)
    assert limit.value == pytest.approx(373.15)
    assert limit.source == "datasheet"
    assert "ripstop_nylon" in limit.reference


def test_without_mass_the_documents_say_so(tmp_path: Path) -> None:
    broken = dataclasses.replace(OUTPUTS, envelope_mass=None, mass=None)
    assert chart_inputs(DESIGN, broken) is None
    out = tmp_path / "pack"
    export_build_pack(
        DESIGN,
        [],
        out,
        extras=PackExtras(frozenset({"lift_chart"}), outputs=broken),
    )
    assert "NOT PRODUCED" in _text(out / "lift-sample-lift-chart.pdf")
    rows = list(csv.reader((out / "lift-sample-lift-chart.csv").open(encoding="utf-8")))
    assert rows == [list(CSV_COLUMNS)]


def test_no_nan_in_ok_rows(pack: Path) -> None:
    rows = list(csv.reader((pack / "lift-sample-lift-chart.csv").open(encoding="utf-8")))
    for row in rows[1:]:
        if row[-1] == "ok":
            assert all(row[k] for k in (1, 3, 4, 5, 6, 7)), row
            assert all(math.isfinite(float(row[k])) for k in (1, 3, 4, 5, 6, 7))
