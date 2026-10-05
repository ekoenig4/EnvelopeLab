"""Build-pack output QA (AGENTS.md §6.6), measured from the exported files.

:func:`check_pack` reads a pack written by :mod:`envelopelab.export.build_pack` and checks:

* every file in ``index.json`` exists and every file in the directory is listed;
* every DXF declares millimetres (``$INSUNITS`` = 4);
* every calibration line (DXF layer ``CAL`` and every PDF page) measures what its label
  says, measured from the drawn geometry, and the label was generated from the same
  value (its numbers match);
* every PDF page is as wide as the roll;
* every sheet header (piece, cut count, fabric, finished size) matches the index, and the
  finished size matches the ``SEW`` outline drawn in the DXF;
* every sewn edge pair differs by its planned ease (``ease_mm``, 0 for edges cut to the
  same length) within its tolerance (default 3 mm), measured from the ``EDGE_*``
  polylines and, for a shape's footprint lines, the ``ATTACH`` polylines.

The index entries are the design data of the export; a pack is consistent when the
drawn geometry agrees with them.
"""

from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from envelopelab.export.build_pack import INDEX, PT_PER_M

HEADER = re.compile(
    r"^(?P<piece>.+?) \| (?P<kind>.+?) \| cut (?P<cut>\d+) \| fabric (?P<fabric>.+?) \| "
    r"finished (?P<w>\d+) x (?P<h>\d+) mm$"
)
CAL_LABEL = re.compile(r"must measure (?P<len>\d+) mm at 1:1, ticks every (?P<tick>\d+) mm")
SIZE_TOLERANCE_MM = 1.0  # header sizes are rounded to whole mm
CAL_TOLERANCE_MM = 0.1


@dataclass(frozen=True)
class QAFinding:
    """A failed check: the file it concerns and what is wrong."""

    file: str
    check: str
    message: str


def _polyline_length(points: list[tuple[float, float]]) -> float:
    p = np.asarray(points, dtype=np.float64)
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum()) if len(p) > 1 else 0.0


def _read_dxf(path: Path) -> dict[str, Any]:
    from ezdxf.entities.lwpolyline import LWPolyline
    from ezdxf.filemanagement import readfile

    doc = readfile(path)
    msp = doc.modelspace()
    out: dict[str, Any] = {
        "units": doc.header.get("$INSUNITS", 0),
        "edges": {},
        "sew": None,
        "cal_lines": [],
        "cal_text": [],
        "label": [],
    }
    attach = 0
    for e in msp:
        layer = e.dxf.layer
        kind = e.dxftype()
        if isinstance(e, LWPolyline):
            pts = [(float(x), float(y)) for x, y, *_ in e.get_points()]
            if e.closed:
                pts.append(pts[0])
            if layer == "SEW":
                out["sew"] = np.asarray(pts)
            elif layer.startswith("EDGE_"):
                out["edges"][layer[5:].lower()] = pts
            elif layer == "ATTACH":
                # Footprint lines are sewn edges too, named in drawing order.
                attach += 1
                out["edges"][f"attach{attach}"] = pts
        elif kind == "LINE" and layer == "CAL":
            s, t = e.dxf.start, e.dxf.end
            out["cal_lines"].append(((s.x, s.y), (t.x, t.y)))
        elif kind == "TEXT" and layer == "CAL":
            out["cal_text"].append(e.dxf.text)
        elif kind == "TEXT" and layer == "LABEL":
            out["label"].append(e.dxf.text)
    return out


def _pdf_pages(path: Path) -> list[tuple[float, str]]:
    """(page width in pt, decompressed content stream) of every page, in order."""
    data = path.read_bytes()
    objects = {
        int(m.group(1)): m.group(2)
        for m in re.finditer(rb"(\d+) 0 obj\n(.*?)\nendobj\n", data, re.S)
    }
    pages = []
    for body in objects.values():
        if b"/Type /Page " not in body:
            continue
        width = float(re.search(rb"/MediaBox \[0 0 ([\d.]+) [\d.]+\]", body).group(1))  # type: ignore[union-attr]
        content = int(re.search(rb"/Contents (\d+) 0 R", body).group(1))  # type: ignore[union-attr]
        raw = re.search(rb"stream\n(.*)\nendstream", objects[content], re.S).group(1)  # type: ignore[union-attr]
        pages.append((width, zlib.decompress(raw).decode("latin-1")))
    return pages


def _check_cal_dxf(name: str, dxf: dict[str, Any]) -> list[QAFinding]:
    if not dxf["cal_lines"] or not dxf["cal_text"]:
        return [QAFinding(name, "calibration", "no calibration line or label")]
    m = CAL_LABEL.search(dxf["cal_text"][0])
    if m is None:
        return [QAFinding(name, "calibration", f"unreadable label {dxf['cal_text'][0]!r}")]
    lines = dxf["cal_lines"]
    main = max(lines, key=lambda ln: abs(ln[1][0] - ln[0][0]))
    measured = abs(main[1][0] - main[0][0])
    ticks = sorted(ln[0][0] for ln in lines if ln is not main)
    out = []
    if abs(measured - float(m["len"])) > CAL_TOLERANCE_MM:
        out.append(
            QAFinding(name, "calibration", f"line measures {measured:.2f} mm, label {m['len']} mm")
        )
    if len(ticks) > 1 and abs(float(np.diff(ticks).max()) - float(m["tick"])) > CAL_TOLERANCE_MM:
        out.append(QAFinding(name, "calibration", "tick spacing differs from its label"))
    return out


def _check_cal_pdf(name: str, page: int, content: str) -> list[QAFinding]:
    m = re.search(r"%CAL (\d+) (\d+)\n[^\n]*?([\d.]+) ([\d.]+) m ([\d.]+) ([\d.]+) l S", content)
    if m is None:
        return [QAFinding(name, "calibration", f"page {page}: no calibration line")]
    drawn = (float(m.group(5)) - float(m.group(3))) / PT_PER_M * 1000.0
    label = CAL_LABEL.search(content)
    out = []
    if abs(drawn - float(m.group(1))) > 0.05 * 1000.0 / PT_PER_M * 2 + CAL_TOLERANCE_MM:
        out.append(
            QAFinding(name, "calibration", f"page {page}: line {drawn:.2f} mm, label {m.group(1)}")
        )
    if label is None or label["len"] != m.group(1) or label["tick"] != m.group(2):
        out.append(QAFinding(name, "calibration", f"page {page}: label differs from the line"))
    return out


def check_pack(out_dir: str | Path) -> list[QAFinding]:
    """Check an exported build pack (module docstring).

    Parameters
    ----------
    out_dir : str or Path
        Pack directory.

    Returns
    -------
    list of QAFinding
        Empty when the pack passes.
    """
    root = Path(out_dir)
    findings: list[QAFinding] = []
    index_path = root / INDEX
    if not index_path.is_file():
        return [QAFinding(INDEX, "index", "index.json is missing")]
    index = json.loads(index_path.read_text(encoding="utf-8"))
    listed = {s["file"] for s in index["sheets"]} | {index["pdf"]}
    present = {p.name for p in root.iterdir() if p.is_file() and p.name != INDEX}
    findings += [QAFinding(f, "index", "listed but missing") for f in sorted(listed - present)]
    findings += [QAFinding(f, "index", "present but not listed") for f in sorted(present - listed)]

    dxfs: dict[str, dict[str, Any]] = {}
    for entry in index["sheets"]:
        name = entry["file"]
        if name not in present:
            continue
        dxf = _read_dxf(root / name)
        dxfs[name] = dxf
        if dxf["units"] != 4:
            findings.append(QAFinding(name, "units", f"$INSUNITS is {dxf['units']}, not 4 (mm)"))
        findings += _check_cal_dxf(name, dxf)
        header = HEADER.match(dxf["label"][0]) if dxf["label"] else None
        if header is None:
            findings.append(QAFinding(name, "header", "no readable sheet header"))
            continue
        expected = {
            "piece": entry["piece"],
            "kind": entry["kind"],
            "cut": str(entry["cut_count"]),
            "fabric": entry["fabric"],
        }
        for key, value in expected.items():
            if header[key] != value:
                findings.append(
                    QAFinding(name, "header", f"{key} {header[key]!r} != index {value!r}")
                )
        sew = dxf["sew"]
        drawn = (sew.max(axis=0) - sew.min(axis=0)) if sew is not None else np.zeros(2)
        for k, key in enumerate(("w", "h")):
            idx = entry["finished_width_mm" if key == "w" else "finished_height_mm"]
            if abs(float(header[key]) - idx) > SIZE_TOLERANCE_MM:
                findings.append(QAFinding(name, "header", f"{key} {header[key]} != index {idx}"))
            if abs(float(drawn[k]) - idx) > SIZE_TOLERANCE_MM:
                findings.append(
                    QAFinding(name, "header", f"drawn {key} {drawn[k]:.1f} != index {idx}")
                )

    for pair in index.get("seam_pairs", []):
        sides = []
        for side in (pair["a"], pair["b"]):
            total = 0.0
            for ref in side:
                edge = dxfs.get(ref["file"], {}).get("edges", {}).get(ref["edge"])
                if edge is None:
                    findings.append(QAFinding(ref["file"], "seam", f"no edge {ref['edge']!r}"))
                    total = float("nan")
                    break
                total += _polyline_length(edge)
            sides.append(total)
        a, b = sides
        ease = float(pair.get("ease_mm", 0.0))
        if np.isfinite(a) and np.isfinite(b) and abs(a - b - ease) > pair["tolerance_mm"]:
            names = " + ".join(f"{r['file']}:{r['edge']}" for r in pair["a"])
            other = " + ".join(f"{r['file']}:{r['edge']}" for r in pair["b"])
            planned = f" (planned ease {ease:+.1f} mm)" if ease else ""
            findings.append(
                QAFinding(names, "seam", f"{a:.1f} mm against {other} {b:.1f} mm{planned}")
            )

    pdf = root / index["pdf"]
    if pdf.is_file():
        roll_pt = index["roll_width_mm"] / 1000.0 * PT_PER_M
        pages = _pdf_pages(pdf)
        expected_pages = sum(int(s["pdf_pages"]) for s in index["sheets"])
        if len(pages) != expected_pages:
            findings.append(
                QAFinding(index["pdf"], "pdf", f"{len(pages)} pages, index lists {expected_pages}")
            )
        for k, (width, content) in enumerate(pages, start=1):
            if abs(width - roll_pt) > 1.0:
                findings.append(
                    QAFinding(
                        index["pdf"],
                        "page size",
                        f"page {k}: {width:.0f} pt, roll {roll_pt:.0f} pt",
                    )
                )
            findings += _check_cal_pdf(index["pdf"], k, content)
    return findings
