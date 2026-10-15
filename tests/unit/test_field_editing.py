"""Kinds of design fields and new values for the generic editors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from envelopelab.design.model import DesignDocument
from envelopelab.io.shape_file import load_shape_file
from envelopelab.project.field_editing import field_info, new_value

ROOT = Path(__file__).resolve().parents[2]
DESIGN = load_shape_file(
    ROOT / "tests" / "fixtures" / "flat_chord_pattern" / "special.yaml"
).design()


@pytest.mark.parametrize(
    ("path", "kind", "optional"),
    [
        (("operating", "ambient_pressure"), "number", False),
        (("parachute", "centre_ring_diameter"), "number", True),
        (("parachute", "panel_count"), "integer", False),
        (("parachute", "zone"), "text", True),
        (("parachute", "crown_ring"), "object", True),
        (("turning_vents", 0, "simulate_open"), "bool", False),
        (("turning_vents", 0, "direction"), "choice", False),
        (("turning_vents", 0, "rows"), "scalars", False),
        (("tapes", "vertical", "class"), "text", False),
        (("scale_variants", 0, "fixed_size_overrides"), "mapping", False),
        (("features",), "objects", False),
        (("gores", "crest_loft"), "object", True),
    ],
)
def test_field_kinds(path: tuple[Any, ...], kind: str, optional: bool) -> None:
    info = field_info(path)
    assert (info.kind, info.optional) == (kind, optional)


def test_choices_and_item_kinds() -> None:
    assert field_info(("rigging", "load_factor", "source")).choices == (
        "datasheet",
        "measured",
        "assumed",
    )
    assert field_info(("gores", "panel_zones", 0, "gores")).item_kind == "integer"
    with pytest.raises(KeyError):
        field_info(("operating", "no_such_field"))
    with pytest.raises(KeyError):
        field_info(("operating", 0))


@pytest.mark.parametrize(
    "path",
    [
        ("parachute",),
        ("parachute", "centre_ring"),
        ("rigging", "red_line"),
        ("rigging", "flying_wires"),
        ("scoop",),
        ("features", 0),
        ("scale_variants", 0),
        ("seam_types", 1),
        ("turning_vents", 2),
        ("gores", "panel_zones", 2),
    ],
)
def test_new_values_make_a_valid_design(path: tuple[Any, ...]) -> None:
    data = DESIGN.model_dump(by_alias=True, mode="json")
    value = new_value(DESIGN, path)
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    if isinstance(path[-1], int):
        target.append(value)
    else:
        target[path[-1]] = value
    DesignDocument.model_validate(data)


def test_a_new_list_entry_gets_a_free_name() -> None:
    names = {v.name for v in DESIGN.turning_vents}
    entry = new_value(DESIGN, ("turning_vents", len(names)))
    assert entry["name"] not in names


def test_no_default_for_required_fields() -> None:
    with pytest.raises(KeyError):
        new_value(DESIGN, ("operating",))
