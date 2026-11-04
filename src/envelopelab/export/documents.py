"""Build-pack documents: cut list, rigging sheet and sewing schedule (PDF for printing,
CSV for reading back), the document list (:data:`DOCUMENTS`) and the shared helpers of
the shop documents (:mod:`envelopelab.export.shop`: index, spec summary, build log).

Every document is generated from the same data as the cutting sheets
(:class:`~envelopelab.export.build_pack.Sheet`, :class:`SeamPair`), the design's live
outputs (:func:`envelopelab.project.gore_design.gore_outputs`) and its rigging outputs
(:func:`envelopelab.rigging.rigging_outputs`); nothing is typed by hand. Values are SI
internally and printed in the units the builder measures with (m, mm, m², kg, N).

Safety: a factor of safety below the requirement is printed as ``FAILS`` with its value
and the requirement; a value that is not assessed says so; every material value carries
its source tag, and the spec summary lists the safety notice and every value tagged
``assumed``.

The PDFs use :class:`envelopelab.report.pdf.PdfCanvas` (Helvetica, Latin-1), so the
text is kept to Latin-1 (:func:`pdf_text`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from envelopelab.geometry.polygon import signed_area

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.export.build_pack import SeamPair, Sheet
    from envelopelab.project.gore_design import GoreOutputs
    from envelopelab.rigging import LineResult, RiggingOutputs

A4_PORTRAIT = (595.0, 842.0)  # points
MARGIN = 42.0  # points
ROW = 12.0  # points per table row
FONT = 8.0  # points
CHAR = 0.5  # average Helvetica glyph width, as a fraction of the font size


@dataclass(frozen=True)
class DocumentSpec:
    """One part of a pack a user can include: its files (suffix after ``<slug>-`` and a
    one-line description each), its group in the index, its tag (``REF``: reading, any
    printer; ``1:1``: print at actual size) and its name in the export dialog."""

    files: tuple[tuple[str, str], ...]
    group: str
    tag: str
    title: str


DOCUMENTS: dict[str, DocumentSpec] = {
    "index": DocumentSpec(
        (("00-BUILD-PACK-INDEX.pdf", "this document - specs, index, build order"),),
        "START HERE",
        "REF",
        "Build-pack index: specs, features, shop limits, files, build order (PDF)",
    ),
    "spec": DocumentSpec(
        (("spec-summary.pdf", "all key dimensions, metric + English"),),
        "START HERE",
        "REF",
        "Spec summary, metric + English (PDF)",
    ),
    "viewer": DocumentSpec(
        (("3d.html", "interactive 3D model (open in a browser)"),),
        "START HERE",
        "REF",
        "3D model (HTML, opens offline in a browser)",
    ),
    "planning": DocumentSpec(
        (
            ("layout-diagram.html", "gore x row grid with every feature located"),
            ("panel-map.html", "which panel carries which feature"),
            ("panel-map.csv", "which panel carries which feature"),
            ("gore-layout.pdf", "all gores + one page per gore"),
            ("panel-dimensions.html", "finished and cut sizes, every panel"),
            ("panel-dimensions.csv", "finished and cut sizes, every panel"),
            ("panel-loft.html", "panel width at 0/25/50/75/100 % height"),
            ("panel-loft.csv", "panel width at 0/25/50/75/100 % height"),
        ),
        "LAYOUT & PLANNING",
        "REF",
        "Layout and planning: layout diagram, panel map, gore layout, dimensions, loft",
    ),
    "sewing": DocumentSpec(
        (("sewing-schedule.html", "seam specs, tape schedule, assembly sequence"),),
        "LAYOUT & PLANNING",
        "REF",
        "Sewing schedule: seam specs, tapes, assembly sequence (HTML)",
    ),
    "build_log": DocumentSpec(
        (("build-log.pdf", "sign-off sheets - print and use on the floor"),),
        "LAYOUT & PLANNING",
        "REF",
        "Build log: sign-off sheets (PDF)",
    ),
    "assembly": DocumentSpec(
        (),
        "LAYOUT & PLANNING",
        "REF",
        "Picture assembly instructions: base envelope and each special shape (PDF)",
    ),
    "appendages": DocumentSpec(
        (),
        "APPENDAGES",
        "REF",
        "Appendages: per special shape spec and build procedure; turning vents (PDF)",
    ),
    "cad": DocumentSpec(
        (),
        "TOP & BOTTOM / CAD",
        "CAD",
        "Combined DXFs: envelope development, panel grid, appendage pieces (+ PNG previews)",
    ),
    "top_bottom": DocumentSpec(
        (
            ("parachute.pdf", "parachute data and full rigging lengths"),
            ("scoop.pdf", "scoop, mouth rigging, flying-wire tables"),
        ),
        "TOP & BOTTOM / CAD",
        "REF",
        "Parachute and scoop / flying-wire sheets (PDF)",
    ),
}


def document_files(slug: str, key: str) -> list[str]:
    """The file names of document ``key`` in a pack whose prefix is ``slug``."""
    return [f"{slug}-{suffix}" for suffix, _what in DOCUMENTS[key].files]


def document_description(name: str, slug: str) -> tuple[str, str, str, str]:
    """(key, group, tag, description) of a document file of a pack."""
    for key, spec in DOCUMENTS.items():
        for suffix, what in spec.files:
            if name == f"{slug}-{suffix}":
                return key, spec.group, spec.tag, what
    raise KeyError(name)


SAFETY_NOTICE = (
    "EnvelopeLab is a design aid, not certified engineering software. The builder is "
    "responsible for airworthiness. Check every value tagged 'assumed' against datasheet "
    "or measured values before building."
)

_PDF_REPLACEMENTS = {
    "–": "-",
    "—": "-",
    "≥": ">=",
    "≤": "<=",
    "▲": "!",
    "✓": "ok",
    "✕": "x",
    "◷": "~",
    "…": "...",
    "’": "'",
}


def pdf_text(text: str) -> str:
    """``text`` with the symbols Helvetica (Latin-1) lacks spelt in ASCII."""
    for a, b in _PDF_REPLACEMENTS.items():
        text = text.replace(a, b)
    return text


@dataclass(frozen=True)
class Provenance:
    """Where a pack comes from (printed on the cover and in ``index.json``).

    Attributes
    ----------
    app_version, git_commit : str
        EnvelopeLab version and the git commit it runs from (``unknown`` outside git).
    design_hash : str
        Content hash of the design state exported.
    created : str
        UTC time of the export, ISO 8601.
    project : str
        Project file name (empty for an unsaved project).
    """

    app_version: str
    git_commit: str
    design_hash: str
    created: str
    project: str = ""

    def as_dict(self) -> dict[str, str]:
        """The fields as a JSON object."""
        return {
            "app_version": self.app_version,
            "git_commit": self.git_commit,
            "design_hash": self.design_hash,
            "created": self.created,
            "project": self.project,
        }


def provenance(design_hash: str, project: str = "") -> Provenance:
    """The provenance of an export made now from this installation."""
    from envelopelab import __version__
    from envelopelab.assembly.rest_model import git_commit

    created = datetime.now(UTC).replace(microsecond=0).isoformat()
    return Provenance(__version__, git_commit(), design_hash, created, project)


@dataclass
class Table:
    """A titled table for a document (also written as CSV)."""

    title: str
    columns: list[str]
    rows: list[list[str]] = field(default_factory=list)
    fails: set[int] = field(default_factory=set)  # row indices printed as failing


# --------------------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------------------


def _area(points: Any) -> float:
    return abs(signed_area(points))


def fabric_totals(sheets: Sequence[Sheet]) -> Table:
    """Cut fabric area per fabric over every piece cut (m²)."""
    totals: dict[str, tuple[int, float, float]] = {}
    for s in sheets:
        if s.cut_count <= 0:
            continue
        n, fin, cut = totals.get(s.fabric, (0, 0.0, 0.0))
        totals[s.fabric] = (
            n + s.cut_count,
            fin + _area(s.finished) * s.cut_count,
            cut + _area(s.cut) * s.cut_count,
        )
    table = Table("Fabric totals", ["Fabric", "Pieces", "Finished area (m2)", "Cut area (m2)"])
    for fabric, (n, fin, cut) in sorted(totals.items()):
        table.rows.append([fabric, str(n), f"{fin:.2f}", f"{cut:.2f}"])
    return table


def rigging_lines(out: RiggingOutputs) -> list[tuple[str, LineResult, bool]]:
    """Every line and ring of ``out`` with its element and whether it is a ring."""
    lines: list[tuple[str, LineResult, bool]] = []
    if out.parachute is not None:
        lines += [("parachute", out.parachute.shroud, False)]
        lines += [("parachute", out.parachute.centralizing, False)]
        lines += [("parachute", ring, True) for ring in out.parachute.rings.values()]
    if out.flying_wires is not None:
        lines += [("flying wires", out.flying_wires.wires, False)]
        lines += [("flying wires", out.flying_wires.legs, False)]
    if out.red_line is not None:
        lines.append(("red line", out.red_line.line, False))
    lines += [(v.name, v.control_line, False) for v in out.turning_vents]
    return lines


def rigging_table(out: RiggingOutputs | None) -> Table:
    """Every line and ring: lengths (rings: diameter), limit load, strength, FoS, mass."""
    table = Table(
        "Lines and rings",
        [
            "Element",
            "Line",
            "Count",
            "Length each (m)",
            "Total (m)",
            "Limit load (N)",
            "Strength (N)",
            "Source",
            "FoS",
            "Required",
            "Check",
            "Mass (kg)",
        ],
    )
    if out is None:
        return table
    for element, line, ring in rigging_lines(out):
        fos = line.safety_factor
        length = f"dia {line.length / math.pi:.3f}" if ring else f"{line.length:.3f}"
        if fos is None:
            check = "not assessed"
        else:
            check = "ok" if line.passes else "FAILS"
        if not line.passes:
            table.fails.add(len(table.rows))
        table.rows.append(
            [
                element,
                line.name,
                str(line.count),
                length,
                f"{line.total_length:.3f}",
                "not assessed" if line.tension is None else f"{line.tension:.0f}",
                f"{line.strength.value:.0f}",
                line.strength.source,
                "-" if fos is None else f"{fos:.2f}",
                f"{line.required_safety_factor:g}",
                check,
                f"{line.mass:.3f}",
            ]
        )
    return table


def _sheet_names(sheets: Sequence[Sheet]) -> dict[str, Sheet]:
    return {s.name: s for s in sheets}


def _side(side: Sequence[tuple[str, str]], by_name: dict[str, Sheet]) -> str:
    counts: dict[tuple[str, str], int] = {}
    for name, edge in side:
        counts[(name, edge)] = counts.get((name, edge), 0) + 1
    parts = []
    for (name, edge), n in counts.items():
        piece = by_name[name].piece if name in by_name else name
        text = f"{piece} {edge.upper()}"
        parts.append(f"{n} x {text}" if n > 1 else text)
    return " + ".join(parts)


def _stage(pair: SeamPair, by_name: dict[str, Sheet]) -> tuple[int, str]:
    first = by_name.get(pair.a[0][0])
    kind = first.kind if first is not None else ""
    edges = {e for _n, e in pair.a}
    if kind == "envelope panel" and edges == {"left"}:
        return 1, "Gore seams (load tapes)"
    if kind == "envelope panel":
        return 2, "Row seams (horizontal tapes)"
    if kind == "parachute panel":
        return 3, "Parachute"
    if any(e == "rim" for e in edges):
        return 5, "Shape rim to the envelope"
    return 4, "Shape skin seams"


def sewing_schedule(sheets: Sequence[Sheet], pairs: Sequence[SeamPair], gores: int) -> Table:
    """Every sewn seam, in assembly order, with its lengths and a check box.

    Order: the gore seams of each row (with the load tapes), the row seams (with the
    horizontal tapes), the parachute, the special shapes' skin seams, then each shape's
    rim to the line marked on the envelope. Lengths are the finished edge lengths of the
    sheets (m); ``ease`` is the planned difference worked in between match marks.
    """
    from envelopelab.export.build_pack import SEWN_EDGE_TOLERANCE

    by_name = _sheet_names(sheets)

    def length(side: Sequence[tuple[str, str]]) -> float:
        total = 0.0
        for name, edge in side:
            sheet = by_name.get(name)
            if sheet is None or edge not in sheet.edges:
                continue
            p = sheet.edges[edge]
            total += float(sum(math.dist(a, b) for a, b in zip(p[:-1], p[1:], strict=True)))
        return total

    ordered = sorted(enumerate(pairs), key=lambda ip: (_stage(ip[1], by_name)[0], ip[0]))
    table = Table(
        "Seams in assembly order",
        ["Step", "Stage", "Sew", "To", "Times", "Length A (mm)", "Length B (mm)", "Ease", "Done"],
    )
    for step, (_i, pair) in enumerate(ordered, start=1):
        stage = _stage(pair, by_name)[1]
        first = by_name.get(pair.a[0][0])
        times = gores if first is not None and first.kind == "envelope panel" else 1
        if first is not None and first.kind == "parachute panel" and len(pair.a) == 1:
            times = first.cut_count
        ease = f"{pair.ease * 1000:+.0f} mm" if abs(pair.ease) > 1e-6 else "-"
        table.rows.append(
            [
                str(step),
                stage,
                _side(pair.a, by_name),
                _side(pair.b, by_name),
                str(times),
                f"{length(pair.a) * 1000:.0f}",
                f"{length(pair.b) * 1000:.0f}",
                ease,
                "[  ]",
            ]
        )
    table.title += f" (edge lengths agree within {SEWN_EDGE_TOLERANCE * 1000:g} mm)"
    return table


def assumed_values(design: DesignDocument, outputs: GoreOutputs | None) -> list[str]:
    """Every value of the design and its outputs tagged ``assumed``, one line each."""
    out: list[str] = []
    rig = design.rigging
    for name, prop in (
        ("limit load factor", rig.load_factor),
        ("required factor of safety", rig.required_safety_factor),
    ):
        if prop.source == "assumed":
            out.append(f"{name} {prop.value:g}")
    if outputs is not None and outputs.mass is not None:
        for zone, z in outputs.mass.zones.items():
            if z.areal_mass.source == "assumed":
                out.append(f"areal mass of zone {zone} {z.areal_mass.value * 1000:.0f} g/m2")
    if outputs is not None and outputs.rigging is not None:
        for element, line, _ring in rigging_lines(outputs.rigging):
            if line.strength.source == "assumed":
                out.append(f"{element}: {line.name} strength {line.strength.value:.0f} N")
    if outputs is not None and outputs.mass is not None and "assumed" in outputs.mass.sources:
        out.append("tape and thread masses (generic)")
    return out


# --------------------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------------------
