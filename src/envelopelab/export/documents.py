"""Build-pack documents: cover and index, spec summary, cut list, rigging sheet and sewing
schedule (PDF for printing, CSV or JSON for reading back).

Every document is generated from the same data as the cutting sheets
(:class:`~envelopelab.export.build_pack.Sheet`, :class:`SeamPair`), the design's live
outputs (:func:`envelopelab.project.gore_design.gore_outputs`) and its rigging outputs
(:func:`envelopelab.rigging.rigging_outputs`); nothing is typed by hand. Values are SI
internally and printed in the units the builder measures with (m, mm, m², kg, N).

Safety: a factor of safety below the requirement is printed as ``FAILS`` with its value
and the requirement; a value that is not assessed says so; every material value carries
its source tag, and the cover lists the safety notice and every value tagged
``assumed``.

The PDFs use :class:`envelopelab.report.pdf.PdfCanvas` (Helvetica, Latin-1), so the
text is kept to Latin-1 (:func:`pdf_text`).
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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

COVER = "00-cover.pdf"
VIEWER = "3d-view.html"
SPEC_PDF, SPEC_JSON = "spec-summary.pdf", "spec-summary.json"
CUT_PDF, CUT_CSV = "cut-list.pdf", "cut-list.csv"
RIG_PDF, RIG_CSV = "rigging.pdf", "rigging.csv"
SEW_PDF, SEW_CSV = "sewing-schedule.pdf", "sewing-schedule.csv"

#: Document parts a pack can include, with their files and a one-line description.
DOCUMENTS = {
    "viewer": ((VIEWER,), "3D view of the design, its rigging and the shown run (offline)"),
    "cover": ((COVER,), "Cover and index: provenance, safety notice, assumed values, files"),
    "spec": ((SPEC_PDF, SPEC_JSON), "Spec summary: size, volume, lift, masses, materials, FoS"),
    "cut_list": ((CUT_PDF, CUT_CSV), "Cut list: pieces, cut counts, fabric areas, tapes"),
    "rigging": ((RIG_PDF, RIG_CSV), "Rigging sheet: lines and rings, lengths, loads, FoS"),
    "sewing": ((SEW_PDF, SEW_CSV), "Sewing schedule: every seam in order, with a check box"),
}

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


def cut_list(sheets: Sequence[Sheet]) -> Table:
    """Every sheet: piece, file, kind, cut count, fabric, finished size, areas.

    Areas are those of the finished and cut outlines of one piece and of all pieces cut
    (m²); marking sheets are cut 0 times (they are drawn on panels cut elsewhere).
    """
    table = Table(
        "Pieces",
        [
            "File",
            "Piece",
            "Kind",
            "Cut",
            "Fabric",
            "Finished W x H (mm)",
            "Finished area (m2)",
            "Cut area (m2)",
            "Cut area, all (m2)",
        ],
    )
    for s in sheets:
        w, h = s.finished_size
        cut = _area(s.cut)
        table.rows.append(
            [
                f"cad/{s.name}.dxf",
                s.piece,
                s.kind,
                str(s.cut_count),
                s.fabric,
                f"{w * 1000:.0f} x {h * 1000:.0f}",
                f"{_area(s.finished):.3f}",
                f"{cut:.3f}",
                f"{cut * s.cut_count:.3f}",
            ]
        )
    return table


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


TAPE_NAMES = {
    "vertical": "load tapes (vertical seams)",
    "horizontal": "horizontal tapes (row seams)",
    "rim": "mouth rim tape",
    "hole": "crown hole tape",
}


def tape_list(outputs: GoreOutputs | None) -> Table:
    """Tape lengths per class (m) and thread, from the envelope mass estimate."""
    table = Table("Tapes and thread", ["Item", "Length (m)", "Mass (kg)"])
    mass = None if outputs is None else outputs.mass
    if mass is None:
        table.rows.append(["not estimated (the panel rows are invalid)", "-", "-"])
        return table
    for key, length in mass.tape_lengths.items():
        table.rows.append(
            [TAPE_NAMES.get(key, key), f"{length:.2f}", f"{mass.tape_masses.get(key, 0.0):.3f}"]
        )
    table.rows.append(["thread", f"{mass.thread_length:.0f}", f"{mass.thread_mass:.3f}"])
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


def spec_tables(design: DesignDocument, outputs: GoreOutputs | None) -> list[Table]:
    """The spec summary: size and lift, mass budget, materials, factors of safety."""
    op = design.operating
    size = Table("Size and lift", ["Quantity", "Value", "Note"])
    if outputs is None:
        size.rows.append(["outputs", "not available", "the design outputs could not be computed"])
        return [size]
    g = design.gores
    size.rows += [
        ["gores", str(g.count if g is not None else "-"), ""],
        ["panel rows", str(len(g.panel_rows) if g is not None else "-"), ""],
        ["height", f"{outputs.height:.3f} m", "design shape (as cut), not inflated"],
        ["maximum diameter", f"{outputs.max_diameter:.3f} m", ""],
        ["load-tape length", f"{outputs.meridian_length:.3f} m", "mouth to crown"],
        ["volume", f"{outputs.volume:.2f} m3", "lofted design surface"],
        ["fabric area", f"{outputs.area:.2f} m2", "finished"],
        ["ambient", f"{op.ambient_temperature:.2f} K, {op.ambient_pressure:.0f} Pa", ""],
        ["internal temperature", f"{op.internal_temperature:.2f} K", ""],
        ["gross lift", f"{outputs.gross_lift:.0f} N", "V (rho_amb - rho_int) g"],
        ["payload", f"{op.payload_mass:.1f} kg", ""],
    ]
    margin = outputs.lift_margin
    size.rows.append(
        [
            "lift margin",
            "not estimated" if margin is None else f"{margin:.1f} kg",
            "NEGATIVE: cannot lift its mass" if margin is not None and margin < 0 else "",
        ]
    )
    if margin is not None and margin < 0:
        size.fails.add(len(size.rows) - 1)
    masses = Table("Mass budget", ["Item", "Mass (kg)"])
    if outputs.mass is not None:
        m = outputs.mass
        masses.rows += [
            ["envelope fabric", f"{m.fabric_mass:.2f}"],
            ["envelope tapes", f"{sum(m.tape_masses.values()):.2f}"],
            ["thread", f"{m.thread_mass:.3f}"],
        ]
    for item, kg in (outputs.rigging.masses if outputs.rigging is not None else {}).items():
        masses.rows.append([item, f"{kg:.3f}"])
    total = (outputs.envelope_mass or 0.0) + (outputs.rigging_mass or 0.0)
    masses.rows.append(["total (without payload)", f"{total:.2f}"])
    materials = Table("Materials", ["Zone", "Fabric", "Finished area (m2)", "Areal mass", "Source"])
    if outputs.mass is not None:
        for zone, z in outputs.mass.zones.items():
            materials.rows.append(
                [
                    zone,
                    design.zones.get(zone, "-"),
                    f"{z.finished_area:.2f}",
                    f"{z.areal_mass.value * 1000:.0f} g/m2",
                    z.areal_mass.source,
                ]
            )
    tables = [size, masses, materials]
    rig = rigging_table(outputs.rigging)
    rig.title = "Factors of safety (rigging)"
    tables.append(rig)
    return tables


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


def write_csv(tables: Sequence[Table], path: str | Path) -> Path:
    """Write ``tables`` to one CSV file (a title row and a header row per table)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for k, table in enumerate(tables):
        if k:
            writer.writerow([])
        if len(tables) > 1:
            writer.writerow([f"# {table.title}"])
        writer.writerow(table.columns)
        writer.writerows(table.rows)
    out = Path(path)
    out.write_text(buf.getvalue(), encoding="utf-8")
    return out


class _Document:
    """A4 portrait pages of text and tables, paginated."""

    FAIL = (0.49, 0.18, 0.07)
    MUTED = (0.29, 0.33, 0.39)

    def __init__(self, title: str, subtitle: str) -> None:
        from envelopelab.report.pdf import PdfCanvas

        self.canvas = PdfCanvas(A4_PORTRAIT)
        self.title, self.subtitle = pdf_text(title), pdf_text(subtitle)
        self.page = 1
        self._header()

    def _header(self) -> None:
        w, h = A4_PORTRAIT
        self.canvas.text(MARGIN, h - MARGIN, self.title, 14, bold=True)
        self.canvas.text(MARGIN, h - MARGIN - 14, self.subtitle, 8, color=self.MUTED)
        self.canvas.text(w - MARGIN - 40, MARGIN / 2, f"page {self.page}", 7, color=self.MUTED)
        self.y = h - MARGIN - 36

    def _need(self, height: float) -> None:
        if self.y - height < MARGIN:
            self.canvas.new_page()
            self.page += 1
            self._header()

    def heading(self, text: str) -> None:
        self._need(3 * ROW)
        self.y -= 6
        self.canvas.text(MARGIN, self.y, pdf_text(text), 11, bold=True)
        self.y -= ROW + 2

    def paragraph(self, text: str, bold: bool = False, fail: bool = False) -> None:
        width = A4_PORTRAIT[0] - 2 * MARGIN
        per_line = max(int(width / (9 * CHAR)), 20)
        words, line = pdf_text(text).split(), ""
        lines = []
        for word in words:
            if len(line) + len(word) + 1 > per_line:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        for ln in lines:
            self._need(ROW)
            colour = self.FAIL if fail else (0.0, 0.0, 0.0)
            self.canvas.text(MARGIN, self.y, ln, 9, bold=bold, color=colour)
            self.y -= ROW
        self.y -= 4

    def table(self, table: Table) -> None:
        self.heading(table.title)
        width = A4_PORTRAIT[0] - 2 * MARGIN
        cells = [table.columns, *table.rows]
        n = len(table.columns)
        need = [max(len(pdf_text(str(r[c]))) for r in cells if c < len(r)) for c in range(n)]
        need = [min(max(k, 3), 40) for k in need]
        scale = min(1.0, width / (sum(need) * FONT * CHAR + 6 * n))
        size = max(FONT * scale, 5.5)
        cols = [k * size * CHAR + 6 for k in need]
        stretch = width / sum(cols)
        cols = [c * stretch for c in cols]
        limit = [max(int((c - 4) / (size * CHAR)), 3) for c in cols]

        def row(values: Sequence[str], bold: bool, fail: bool) -> None:
            self._need(ROW)
            x = MARGIN
            colour = self.FAIL if fail else (0.0, 0.0, 0.0)
            for c, value in enumerate(values):
                text = pdf_text(str(value))
                if len(text) > limit[c]:
                    text = text[: limit[c] - 1] + "~"
                self.canvas.text(x + 2, self.y, text, size, bold=bold or fail, color=colour)
                x += cols[c]
            self.canvas.line(MARGIN, self.y - 3, MARGIN + width, self.y - 3, (0.8, 0.83, 0.86))
            self.y -= ROW

        row(table.columns, True, False)
        for k, values in enumerate(table.rows):
            if self.y - ROW < MARGIN:
                row(table.columns, True, False)  # header again on the new page
            row(values, False, k in table.fails)
        if not table.rows:
            self.paragraph("(none)")
        self.y -= 6

    def save(self, path: str | Path) -> Path:
        return self.canvas.save(path)


def _subtitle(design: DesignDocument, prov: Provenance | None) -> str:
    parts = [design.meta.name or "design"]
    if prov is not None:
        parts += [f"exported {prov.created}", f"design {prov.design_hash[:12]}"]
    return " | ".join(parts)


def write_spec(
    design: DesignDocument,
    outputs: GoreOutputs | None,
    out_dir: Path,
    prov: Provenance | None = None,
) -> list[Path]:
    """``spec-summary.pdf`` and ``spec-summary.json``."""
    tables = spec_tables(design, outputs)
    doc = _Document("Spec summary", _subtitle(design, prov))
    fails = [t for t in tables if t.fails]
    if fails:
        doc.paragraph(
            "FAILS: "
            + "; ".join(t.rows[i][0] + " " + t.rows[i][1] for t in fails for i in t.fails),
            bold=True,
            fail=True,
        )
    for t in tables:
        doc.table(t)
    doc.paragraph(SAFETY_NOTICE)
    pdf = doc.save(out_dir / SPEC_PDF)
    data = {
        "design": design.meta.name,
        "provenance": None if prov is None else prov.as_dict(),
        "tables": [
            {"title": t.title, "columns": t.columns, "rows": t.rows, "fails": sorted(t.fails)}
            for t in tables
        ],
    }
    js = out_dir / SPEC_JSON
    js.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [pdf, js]


def write_cut_list(
    design: DesignDocument,
    sheets: Sequence[Sheet],
    outputs: GoreOutputs | None,
    out_dir: Path,
    prov: Provenance | None = None,
) -> list[Path]:
    """``cut-list.pdf`` and ``cut-list.csv`` (the pieces table first)."""
    tables = [cut_list(sheets), fabric_totals(sheets), tape_list(outputs)]
    doc = _Document("Cut list", _subtitle(design, prov))
    doc.paragraph(
        "Cut counts and fabrics are those printed on each sheet's header. Areas include the "
        "seam allowance ('cut') or not ('finished'); marking sheets are drawn on panels cut "
        "from their row sheet and are not cut themselves."
    )
    for t in tables:
        doc.table(t)
    return [doc.save(out_dir / CUT_PDF), write_csv(tables, out_dir / CUT_CSV)]


def write_rigging(
    design: DesignDocument,
    outputs: GoreOutputs | None,
    out_dir: Path,
    prov: Provenance | None = None,
) -> list[Path]:
    """``rigging.pdf`` and ``rigging.csv``."""
    rig = None if outputs is None else outputs.rigging
    table = rigging_table(rig)
    doc = _Document("Rigging sheet", _subtitle(design, prov))
    r = design.rigging
    doc.paragraph(
        f"Load case: limit load factor {r.load_factor.value:g} ({r.load_factor.source}), "
        f"required factor of safety {r.required_safety_factor.value:g} "
        f"({r.required_safety_factor.source}). Lengths are finished lengths between "
        "attachment points; add the splices and loops of your hardware."
    )
    failing = [table.rows[i] for i in sorted(table.fails)]
    if failing:
        doc.paragraph(
            "FAILS: " + "; ".join(f"{row[1]} FoS {row[8]} < {row[9]}" for row in failing),
            bold=True,
            fail=True,
        )
    if rig is None:
        doc.paragraph("Rigging not evaluated (no valid rigging outputs).", bold=True)
    doc.table(table)
    if rig is not None and rig.parachute is not None:
        op = rig.parachute.opening
        seal = "NOT REACHABLE" if op.seal_open_travel is None else f"{op.seal_open_travel:.3f} m"
        full = "NOT REACHABLE" if op.full_open_travel is None else f"{op.full_open_travel:.3f} m"
        doc.paragraph(f"Red-line pull: seal open {seal}, fully open {full}.")
    doc.paragraph("Not assessed: red-line pull force, scoop wind load.")
    return [doc.save(out_dir / RIG_PDF), write_csv([table], out_dir / RIG_CSV)]


def write_sewing(
    design: DesignDocument,
    sheets: Sequence[Sheet],
    pairs: Sequence[SeamPair],
    out_dir: Path,
    prov: Provenance | None = None,
) -> list[Path]:
    """``sewing-schedule.pdf`` and ``sewing-schedule.csv``."""
    gores = design.gores.count if design.gores is not None else 1
    table = sewing_schedule(sheets, pairs, gores)
    doc = _Document("Sewing schedule", _subtitle(design, prov))
    doc.paragraph(
        "Sew in this order. 'Times' is how often the seam is sewn (gore seams once per "
        "gore). Match the marks on both edges; where an ease is given, work it in evenly "
        "between the marks. Tick 'Done' as you go."
    )
    doc.table(table)
    return [doc.save(out_dir / SEW_PDF), write_csv([table], out_dir / SEW_CSV)]


def write_cover(
    design: DesignDocument,
    outputs: GoreOutputs | None,
    files: Sequence[tuple[str, str]],
    out_dir: Path,
    prov: Provenance | None = None,
    status: str = "",
) -> Path:
    """``00-cover.pdf``: provenance, safety notice, assumed values, the result status and
    every file of the pack with what it is."""
    doc = _Document(f"Build pack: {design.meta.name or 'design'}", _subtitle(design, prov))
    doc.paragraph(SAFETY_NOTICE, bold=True)
    if prov is not None:
        doc.heading("Provenance")
        for key, value in prov.as_dict().items():
            doc.paragraph(f"{key.replace('_', ' ')}: {value or '-'}")
    if status:
        doc.heading("Structural result")
        doc.paragraph(status)
    doc.heading("Values tagged 'assumed'")
    assumed = assumed_values(design, outputs)
    for line in assumed or ["none"]:
        doc.paragraph(f"- {line}")
    doc.heading("Before cutting")
    doc.paragraph(
        "Print every 1:1 template at 100 % (no fit-to-page) and measure both calibration "
        "lines on every page: each must measure what its label says."
    )
    table = Table("Files", ["File", "What it is"])
    table.rows = [[name, what] for name, what in files]
    doc.table(table)
    return doc.save(out_dir / COVER)
