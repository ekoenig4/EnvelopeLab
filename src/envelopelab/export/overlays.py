"""Build-pack sheets of the overlays: appliqué patches sewn on the envelope (ADR-0056).

Every overlay (:mod:`envelopelab.project.overlays`) gives

* one **overlay piece** (kind ``overlay``, cut once): its finished outline (layer ``SEW``,
  edge ``outline``) with the hem turned under round it (``CUT``), and a numbered match mark
  wherever the outline crosses a seam of the envelope;
* one **marking sheet** per envelope panel the outline crosses (kind ``marking``, named
  ``<overlay>-mark-G<gore>-<row>`` as a special shape's, so the panel's marking template
  draws every shape's and overlay's lines on it): the panel's finished outline with the
  part of the overlay's outline on it (``ATTACH``) and the same numbered marks;

and one seam pair: the piece's outline against the marked lines, with the planned ease
(:attr:`envelopelab.project.overlays.OverlayLayout.ease`) that the QA checks.

:func:`write_overlay_pattern` writes one overlay's own cutting pattern (its 1:1 template
and DXFs) without the rest of the pack; :func:`overlay_cut_piece` and
:func:`overlay_checks` give the application its piece and checks.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from envelopelab.export.build_pack import SeamPair, Sheet
from envelopelab.geometry.polygon import offset_polygon

if TYPE_CHECKING:
    from envelopelab.features.primitives import CutPiece, DesignCheck, EnvelopeSurface
    from envelopelab.project.overlays import OverlayLayout


def overlay_sheet_name(name: str) -> str:
    """File stem of an overlay's piece."""
    return f"{name}-overlay"


def overlay_sheets(
    layout: OverlayLayout, surface: EnvelopeSurface, fabric: str
) -> tuple[list[Sheet], list[SeamPair]]:
    """The piece and marking sheets of one overlay, and its seam pair (module docstring).

    Parameters
    ----------
    layout : OverlayLayout
        The overlay laid on the envelope
        (:func:`envelopelab.project.overlays.overlay_layout`).
    surface : EnvelopeSurface
        The envelope it lies on, m.
    fabric : str
        Fabric name of the patch.

    Returns
    -------
    sheets : list of Sheet
        The piece first, then the marking sheets (one per panel the outline crosses).
    pairs : list of SeamPair
    """
    from envelopelab.features.primitives import band_outline

    spec = layout.spec
    name = spec.name
    finished = layout.outline
    closed = np.vstack([finished, finished[:1]])
    cut = offset_polygon(finished, spec.hem) if spec.hem > 0 else finished.copy()
    marks = [(float(p[0]), float(p[1]), str(k + 1)) for k, (p, *_r) in enumerate(layout.crossings)]
    panels = ", ".join(f"gore {g} row {r}" for g, r in layout.covered)
    piece = Sheet(
        name=overlay_sheet_name(name),
        piece=f"{name} overlay",
        kind="overlay",
        cut_count=1,
        fabric=fabric,
        finished=finished,
        cut=cut,
        edges={"outline": closed},
        marks=marks,
        note=f"appliqué: sew on top of the envelope over {panels}",
        notes=[
            f"turn {spec.hem * 1000:.0f} mm under along the sew line and sew it on the "
            "marked line of each panel, each number on the same number",
            *layout.warnings(),
        ],
    )
    labels = [b.label for b in surface.rows]
    by_panel: dict[tuple[int, str], list[int]] = {}
    for k, run in enumerate(layout.runs):
        by_panel.setdefault((run.gore, run.row), []).append(k)
    sheets = [piece]
    side_b: list[tuple[str, str]] = []
    count = len(layout.crossings)
    for (gore, row), runs in sorted(
        by_panel.items(), key=lambda kv: (labels.index(kv[0][1]), kv[0][0])
    ):
        sheet_name = f"{name}-mark-G{gore}-{row}"
        lines = [layout.runs[k].panel for k in runs]
        marked = []
        for k in runs:
            if count:
                # Run k starts at crossing k and ends at crossing k + 1 (round the outline).
                run = layout.runs[k]
                marked.append((float(run.panel[0, 0]), float(run.panel[0, 1]), f"{k + 1} ({name})"))
                end = (k + 1) % count + 1
                marked.append((float(run.panel[-1, 0]), float(run.panel[-1, 1]), f"{end} ({name})"))
        sheets.append(
            Sheet(
                name=sheet_name,
                piece=f"gore {gore} row {row}",
                kind="marking",
                cut_count=0,
                fabric="envelope",
                finished=band_outline(surface, labels.index(row)),
                cut=band_outline(surface, labels.index(row)),
                marks=marked,
                lines=lines,
                note=f"mark overlay {name} on this panel before assembly",
                notes=[f"sew overlay {name} on the marked line (ATTACH), numbers on numbers"],
            )
        )
        side_b += [(sheet_name, f"attach{i + 1}") for i in range(len(lines))]
    pairs = [SeamPair(((piece.name, "outline"),), tuple(side_b), layout.ease)]
    return sheets, pairs


def overlay_pack(
    overlays: Sequence[object],
    surface: EnvelopeSurface,
    fabric_of: dict[str, str],
) -> tuple[list[Sheet], list[SeamPair], list[OverlayLayout]]:
    """Sheets, seam pairs and layouts of every overlay (``fabric_of``: fabric by overlay
    name)."""
    from envelopelab.project.overlays import OverlaySpec, overlay_layout

    sheets: list[Sheet] = []
    pairs: list[SeamPair] = []
    layouts: list[OverlayLayout] = []
    for spec in overlays:
        assert isinstance(spec, OverlaySpec)
        layout = overlay_layout(spec, surface)
        s, p = overlay_sheets(layout, surface, fabric_of.get(spec.name, "applique"))
        sheets += s
        pairs += p
        layouts.append(layout)
    return sheets, pairs, layouts


__all__ = [
    "overlay_checks",
    "overlay_cut_piece",
    "overlay_pack",
    "overlay_sheet_name",
    "overlay_sheets",
    "write_overlay_pattern",
]


def overlay_cut_piece(layout: OverlayLayout) -> CutPiece:
    """The overlay as a cut piece (as a special shape's skin pieces are drawn and listed):
    finished outline, cut outline (the hem added), its outline as its one edge; its
    surface area is its flat area (a patch lies flat on the cloth under it)."""
    from envelopelab.features.primitives import CutPiece
    from envelopelab.geometry.gore import polygon_area

    spec = layout.spec
    finished = layout.outline
    cut = offset_polygon(finished, spec.hem) if spec.hem > 0 else finished.copy()
    return CutPiece(
        label=overlay_sheet_name(spec.name),
        finished=finished,
        cut=cut,
        rim=None,
        edges={"outline": np.vstack([finished, finished[:1]])},
        surface_area=float(polygon_area(finished)),
    )


def overlay_checks(layout: OverlayLayout, roll_width: float) -> list[DesignCheck]:
    """Checks of an overlay's pattern: how its outline fits the curved envelope (the ease
    between the piece and the marked line against :data:`~envelopelab.project.overlays.
    EASE_WARNING` of it) and whether its 1:1 page fits the print roll
    (:func:`envelopelab.export.templates.roll_checks`)."""
    from envelopelab.export.templates import roll_checks
    from envelopelab.features.primitives import DesignCheck
    from envelopelab.project.overlays import EASE_WARNING

    limit = EASE_WARNING * layout.perimeter
    ok = abs(layout.ease) <= limit
    fit = DesignCheck(
        f"{layout.spec.name}: fit on the envelope",
        abs(layout.ease) * 1000.0,
        limit * 1000.0,
        "mm",
        "info" if ok else "warning",
        (
            f"the outline is {layout.ease * 1000:+.0f} mm longer on the piece than the line "
            "marked on the panels; work it in between the numbered marks"
            + ("" if ok else " (too much for a flat patch here: make it smaller)")
        ),
    )
    piece = overlay_cut_piece(layout)
    return [fit, *roll_checks([(piece.label, piece.cut)], roll_width)]


def write_overlay_pattern(
    layout: OverlayLayout,
    surface: EnvelopeSurface,
    fabric: str,
    out_dir: str | Path,
    roll_width: float,
    title: str = "",
    colour: str | None = None,
) -> list[Path]:
    """Write one overlay's own cutting pattern into ``out_dir`` (created): its 1:1
    template PDF (as in the build pack, ``<slug>-<name>-overlay.pdf``), its DXF in mm and
    one DXF per envelope panel it is marked on (``<name>-mark-G<g>-<row>.dxf``).

    Parameters
    ----------
    layout : OverlayLayout
        The overlay laid on the envelope.
    surface : EnvelopeSurface
        The envelope, m.
    fabric : str
        Fabric printed on the piece.
    out_dir : str or Path
        Folder to write.
    roll_width : float
        Print roll width, m (the template page is no wider, or says so in red).
    title : str
        Design name (the file-name prefix of the template).
    colour : str or None
        The overlay's colour (``#rrggbb``), printed on the piece.

    Returns
    -------
    list of Path
        The files written, the template first.
    """
    from envelopelab.export.build_pack import write_dxf
    from envelopelab.export.templates import (
        TemplateFile,
        TemplatePage,
        piece_name,
        slug,
        write_template_pdf,
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sheets, _pairs = overlay_sheets(layout, surface, fabric)
    piece = sheets[0]
    if colour is not None:
        piece.colours = [(colour, [1])]
    stem = slug(title) if title else "overlay"
    template = TemplateFile(
        f"{stem}-{piece_name(piece.name)}.pdf",
        f"{piece.piece} (appliqué), cut {piece.cut_count}",
        [TemplatePage(piece, piece.piece.upper())],
    )
    written = [out / template.name]
    write_template_pdf(template, written[0], roll_width)
    for sheet in sheets:
        written.append(write_dxf(sheet, out / f"{sheet.name}.dxf"))
    return written
