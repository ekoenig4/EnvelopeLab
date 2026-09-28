"""Shared helpers: synthetic DXF build packs for pattern-import tests, and the ``ccx``
fixture of the CalculiX verification tests.

Tests that run CalculiX use the ``ccx`` fixture; without a ``ccx`` executable they are
skipped with the installation message, so a missing solver is never reported as a
verification that passed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from ezdxf.filemanagement import new as new_dxf

from calculix_adapter import SETUP_MESSAGE, CalculixInstallation, find_calculix

Point = tuple[float, float]
Entity = tuple[str, str, Any]  # (layer, kind, data)


def rect(x0: float, y0: float, width: float, height: float) -> list[Point]:
    """Counter-clockwise rectangle, mm."""
    return [(x0, y0), (x0 + width, y0), (x0 + width, y0 + height), (x0, y0 + height)]


def panel_entities(
    x0: float,
    width: float,
    height: float,
    label: str | None,
    allowance: float = 25.0,
    sew: bool = True,
) -> list[Entity]:
    """Cut outline (sew rectangle grown by the allowance), sew outline and label, mm."""
    out: list[Entity] = [
        (
            "CUT",
            "poly",
            rect(x0 - allowance, -allowance, width + 2 * allowance, height + 2 * allowance),
        )
    ]
    if sew:
        out.append(("SEW", "poly", rect(x0, 0.0, width, height)))
    if label is not None:
        out.append(("TEXT", "text", (label, (x0 + width / 2, height / 2))))
    return out


def write_dxf(path: Path, entities: Sequence[Entity], insunits: int = 4) -> Path:
    """Write entities to a DXF file.

    Kinds: ``poly`` (closed LWPOLYLINE), ``open`` (open LWPOLYLINE), ``line`` (LINE from
    two points), ``circle`` ((centre, radius)), ``text`` ((text, insert)), ``point``.
    """
    doc = new_dxf("R2010", setup=False)
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    for layer, kind, data in entities:
        if layer not in doc.layers:
            doc.layers.add(layer)
        attribs = {"layer": layer}
        if kind == "poly":
            msp.add_lwpolyline(data, close=True, dxfattribs=attribs)
        elif kind == "open":
            msp.add_lwpolyline(data, close=False, dxfattribs=attribs)
        elif kind == "line":
            msp.add_line(data[0], data[1], dxfattribs=attribs)
        elif kind == "circle":
            msp.add_circle(data[0], data[1], dxfattribs=attribs)
        elif kind == "text":
            msp.add_text(data[0], height=20.0, dxfattribs={**attribs, "insert": data[1]})
        elif kind == "point":
            msp.add_point(data, dxfattribs=attribs)
        else:
            raise ValueError(kind)
    doc.saveas(path)
    return path


def default_import(**overrides: Any) -> dict[str, Any]:
    """A typical import section for the synthetic packs."""
    cfg: dict[str, Any] = {
        "mapping_version": "test/1",
        "units": "auto",
        "seam_allowance_mm": 25,
        "default_grain": [1.0, 0.0],
        "layers": {"cut": ["CUT"], "sew": ["SEW"], "feature": ["FEAT"], "label": ["TEXT"]},
        "labels": [{"pattern": r"^PANEL\s+(?P<panel>\w+)\s+x(?P<quantity>\d+)"}],
        "sources": [{"file": "pack.dxf"}],
    }
    cfg.update(overrides)
    return cfg


PackFactory = Callable[..., Path]


@pytest.fixture
def make_pack(tmp_path: Path) -> PackFactory:
    """Factory: ``make_pack(entities, import_cfg=None, assembly=None, name='pack')``."""

    def factory(
        entities: Sequence[Entity],
        import_cfg: dict[str, Any] | None = None,
        assembly: dict[str, Any] | None = None,
        name: str = "pack",
        insunits: int = 4,
    ) -> Path:
        write_dxf(tmp_path / "pack.dxf", entities, insunits)
        doc: dict[str, Any] = {"import": import_cfg or default_import()}
        if assembly is not None:
            doc["assembly"] = assembly
        target = tmp_path / f"{name}.yaml"
        target.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        return target

    return factory


def ring_pack_entities(
    rows: Sequence[tuple[str, float, float]], gores: int, allowance: float = 25.0
) -> list[Entity]:
    """Rectangular row pieces (label, width, height in mm) laid side by side."""
    out: list[Entity] = []
    x = 0.0
    for label, width, height in rows:
        out.extend(panel_entities(x, width, height, f"PANEL {label} x{gores}", allowance))
        x += width + 4 * allowance
    return out


def ring_assembly(rows: Sequence[str], gores: int, **extra: Any) -> dict[str, Any]:
    """Assembly section with one ring over the given rows."""
    cfg: dict[str, Any] = {
        "kind": "standard_gore",
        "rings": [
            {
                "name": "body",
                "gore_count": gores,
                "rows": list(rows),
                "bottom": {"name": "mouth", "kind": "mouth"},
                "top": {"name": "crown", "kind": "parachute_opening"},
            }
        ],
        "mesh": {"target_edge_length_mm": 200},
    }
    cfg.update(extra)
    return cfg


@pytest.fixture(scope="session")
def ccx() -> CalculixInstallation:
    """The installed CalculiX; skips the test (with the setup message) when it is missing."""
    found = find_calculix()
    if found is None:
        pytest.skip("CalculiX verification tests skipped, ccx not installed.\n" + SETUP_MESSAGE)
    return found
