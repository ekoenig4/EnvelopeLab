"""Build-pack output QA (AGENTS.md §6.6): export a generic sample pack and check it.

Exports the envelope rows of a generic standard-gore design with a dome, a leaned tube,
a revolved bulb and a free-form mesh shape on it, with every document (cover, spec,
cut list, rigging, sewing schedule, 3D view), to a temporary directory and runs
:func:`envelopelab.export.qa.check_pack`; then the same with three rows (one carrying the
dome) cut as half gores and panel colours (ADR-0055) on envelope rows, halves, split
and unsplit skin pieces and a tip disc, so the colour lines on the DXFs and templates, the
colour plan and the cloth table are checked too, and three overlays (appliqués: across a
gore seam, across a row seam, across the last-to-first gore seam) with their pieces,
marking sheets and seam pairs; then that pack as a scale model, every piece on one sheet
of US Letter at the largest whole scale that fits (ADR-0062). Exits non-zero when any
check fails. Run by ``scripts/verify.py``.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace

from envelopelab.export.build_pack import PackExtras, export_build_pack, pack_sheets
from envelopelab.export.documents import DOCUMENTS
from envelopelab.export.qa import check_pack
from envelopelab.export.scale_model import PAPER_SIZES, ScaleModel, fit_scale
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    FreeformShape,
    Placement,
    Revolved,
    Tube,
    design_primitive,
)
from envelopelab.project.colours import CAP, PanelColours, PanelRef, painted
from envelopelab.project.gore_design import standard_gore_design
from envelopelab.project.overlays import OverlaySpec
from envelopelab.project.shapes import ShapePlacement
from envelopelab.validation.primitives import ellipsoid_mesh


def main() -> int:
    design = standard_gore_design("generic sample", 2000.0, 17.0, 16.0, 12, 6)
    surface = EnvelopeSurface.from_design(design)
    shapes = [
        design_primitive(Dome("dome", Placement(3, 12.0, across=0.5), 1.0, 1.2, 16), surface),
        design_primitive(Tube("tube", Placement(7, 10.0, lean_deg=20), 0.8, 0.3, 2.0), surface),
        design_primitive(
            Revolved("bulb", Placement(10, 11.0), ((0.4, 0.0), (0.7, 0.5), (0.0, 1.2))),
            surface,
        ),
        design_primitive(
            FreeformShape("blob", Placement(1, 9.0), ellipsoid_mesh(0.8, 0.6, 1.1, -0.3), 12),
            surface,
        ),
    ]
    with tempfile.TemporaryDirectory() as out:
        export_build_pack(design, shapes, out, extras=PackExtras(frozenset(DOCUMENTS)))
        findings = check_pack(out)
    assert design.gores is not None
    halved = design.model_copy(
        update={
            "gores": design.gores.model_copy(
                update={
                    "panel_rows": [
                        r.model_copy(update={"half_gore": i in (2, 3, 4)})
                        for i, r in enumerate(design.gores.panel_rows)
                    ]
                }
            )
        }
    )
    with tempfile.TemporaryDirectory() as out:
        rows = [r.letter for r in design.gores.panel_rows]
        colours = painted(
            PanelColours(), [PanelRef(None, rows[2], g) for g in (1, 4, 7)], "#c00000"
        )
        colours = painted(colours, [PanelRef(None, rows[0], g) for g in range(1, 13)], "#ffc000")
        colours = painted(colours, [PanelRef(None, rows[3], 3)], "#0070c0")  # under the dome
        # Half gores (rows 2-4): the halves of one panel in two colours, another's left only.
        colours = painted(colours, [PanelRef(None, rows[3], 5, "left")], "#ffffff")
        colours = painted(colours, [PanelRef(None, rows[3], 5, "right")], "#002060")
        colours = painted(colours, [PanelRef(None, rows[4], 8, "left")], "#92d050")
        colours = painted(colours, [PanelRef("dome", "A", p) for p in (1, 3)], "#7030a0")
        colours = painted(colours, [PanelRef("tube", CAP, 1), PanelRef("blob", "A", 2)], "#00b050")
        # Overlays (ADR-0056): across a gore seam, across a row seam, and on the seam
        # between the last gore and the first.
        overlays = [
            OverlaySpec(
                name="sun",
                placement=ShapePlacement(gore=5, tape_position=8.0, across=0.5),
                width=1.5,
            ),
            OverlaySpec(
                name="band",
                placement=ShapePlacement(gore=9, tape_position=6.0),
                outline="rectangle",
                width=0.8,
                height=2.5,
                turn_deg=10.0,
            ),
            OverlaySpec(
                name="star",
                placement=ShapePlacement(gore=12, tape_position=13.0, across=0.5),
                outline="polygon",
                points=[
                    (0, 0.6),
                    (0.2, 0.2),
                    (0.6, 0),
                    (0.2, -0.2),
                    (0, -0.6),
                    (-0.2, -0.2),
                    (-0.6, 0),
                    (-0.2, 0.2),
                ],
            ),
        ]
        colours = painted(colours, [PanelRef("sun", "A", 1)], "#ffc000")
        export_build_pack(
            halved,
            shapes,
            out,
            extras=PackExtras(frozenset(DOCUMENTS)),
            colours=colours,
            overlays=overlays,
        )
        findings += check_pack(out)
        # The same pack as a scale model (ADR-0062): every piece on one Letter sheet at
        # the largest whole scale that fits, with a fixed 5 mm allowance.
        model = ScaleModel(1.0, PAPER_SIZES["letter"], seam_allowance=0.005)
        sheets = pack_sheets(halved, shapes, colours=colours, overlays=overlays)[0]
        model = replace(model, denominator=fit_scale(sheets, model))
        with tempfile.TemporaryDirectory() as small:
            export_build_pack(
                halved, shapes, small, colours=colours, overlays=overlays, scale_model=model
            )
            findings += check_pack(small)
    for f in findings:
        print(f"FAIL {f.file}: {f.check}: {f.message}")
    print(f"build-pack QA: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
