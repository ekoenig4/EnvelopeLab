"""Import reports: panel inventory, seam audit, seam graph, mesh report and warnings.

All reports are written from the same result objects the tests check. HTML pages are
self-contained (inline CSS, no scripts) and always start with the overall status so that
failed checks and errors cannot be missed. Tables use mm for lengths and m^2 for areas;
JSON files use SI units (m, m^2).
"""

from __future__ import annotations

import csv
import html
import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from envelopelab.assembly.pipeline import BuildPackResult
from envelopelab.assembly.rest_model import save_rest_model

_CSS = """
body{font-family:system-ui,sans-serif;margin:24px;color:#1b1b1b;background:#fff}
table{border-collapse:collapse;margin:12px 0;font-size:13px}
th,td{border:1px solid #bbb;padding:3px 6px;text-align:left;vertical-align:top}
th{background:#eee}
.status{padding:10px 14px;font-weight:600;border-radius:4px;display:inline-block}
.PASS{background:#d8f0d8}.PASS_WITH_WARNINGS{background:#fff1c2}
.FAIL{background:#f8d0d0}.INCOMPLETE{background:#fff1c2}
.error{background:#f8d0d0}.warning{background:#fff1c2}.info{background:#e6eefc}
.ok{}
.note{color:#555;font-size:13px}
"""


def overall_status(result: BuildPackResult) -> str:
    """``PASS``, ``PASS_WITH_WARNINGS``, ``FAIL`` or ``INCOMPLETE`` (mesh not built)."""
    status = result.status
    if status == "PASS" and (
        any(w.severity == "warning" for w in result.warnings)
        or any(f.severity == "warning" for f in result.audit.edge_findings)
        or any(r.severity == "warning" for r in result.audit.rows)
    ):
        return "PASS_WITH_WARNINGS"
    return status


def _page(title: str, status: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p><span class='status {status}'>Status: {status.replace('_', ' ')}</span></p>"
        "<p class='note'>EnvelopeLab is a design aid, not certified engineering software. "
        "The builder is responsible for airworthiness.</p>"
        f"{body}</body></html>"
    )


def _table(
    headers: list[str], rows: Sequence[Sequence[Any]], row_classes: list[str] | None = None
) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    out = [f"<table><thead><tr>{head}</tr></thead><tbody>"]
    for k, row in enumerate(rows):
        cls = f" class='{row_classes[k]}'" if row_classes else ""
        cells = "".join(f"<td>{html.escape(str(c))}</td>" for c in row)
        out.append(f"<tr{cls}>{cells}</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _csv(headers: list[str], rows: Sequence[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def panel_inventory(result: BuildPackResult) -> list[dict[str, Any]]:
    """One record per imported piece (SI units).

    Parameters
    ----------
    result : BuildPackResult
        Pipeline result.

    Returns
    -------
    list of dict
        Piece id, kind, quantity, assembled count, finished and cut area (m^2, per piece),
        material zones, grain, allowances (m), outline source, validity and provenance.
    """
    instances = result.assembly.instances.values()
    records = []
    for pid, piece in result.pieces.items():
        used = [i for i in instances if i.piece.piece_id == pid]
        zones = sorted({i.material_zone for i in used}) or [piece.material_zone]
        records.append(
            {
                "piece_id": pid,
                "kind": piece.kind,
                "quantity": piece.quantity,
                "assembled": len(used),
                "meshed": sum(i.mesh for i in used),
                "mirrored_copies": sum(i.mirrored for i in used),
                "finished_area_m2": piece.finished_area,
                "cut_area_m2": piece.cut_area,
                "material_zones": zones,
                "grain": list(piece.grain) if piece.grain is not None else None,
                "grain_source": piece.grain_source,
                "outline_source": piece.outline_source,
                "seam_allowance_m": piece.seam_allowance,
                "measured_allowance_m": piece.measured_allowance,
                "holes": len(piece.holes),
                "valid": piece.valid,
                "label": piece.label_text,
                "provenance": piece.provenance.as_dict(),
                "sew_provenance": piece.sew_provenance.as_dict() if piece.sew_provenance else None,
                "notes": piece.notes,
            }
        )
    return records


def _inventory_outputs(result: BuildPackResult, status: str) -> tuple[str, str, str]:
    records = panel_inventory(result)
    headers = [
        "piece",
        "kind",
        "qty",
        "assembled",
        "meshed",
        "finished area m2",
        "cut area m2",
        "zones",
        "grain",
        "grain source",
        "finished from",
        "allowance mm",
        "measured mm",
        "valid",
        "source",
    ]
    rows = []
    for r in records:
        grain = "" if r["grain"] is None else f"({r['grain'][0]:.3f}, {r['grain'][1]:.3f})"
        measured = r["measured_allowance_m"]
        rows.append(
            [
                r["piece_id"],
                r["kind"],
                r["quantity"],
                r["assembled"],
                r["meshed"],
                f"{r['finished_area_m2']:.4f}",
                f"{r['cut_area_m2']:.4f}",
                " ".join(r["material_zones"]),
                grain,
                r["grain_source"],
                r["outline_source"],
                f"{r['seam_allowance_m'] * 1e3:.1f}",
                "" if measured is None else f"{measured * 1e3:.1f}",
                "yes" if r["valid"] else "NO",
                f"{r['provenance']['source_file']}:{r['provenance']['layer']}:"
                f"{r['provenance']['entity_id']}",
            ]
        )
    total_finished = sum(
        r["finished_area_m2"] * r["quantity"] for r in records if r["kind"] != "mark"
    )
    total_cut = sum(r["cut_area_m2"] * r["quantity"] for r in records if r["kind"] != "mark")
    body = (
        f"<p>{len(records)} pieces. Total finished area x quantity {total_finished:.2f} m2, "
        f"cut area x quantity {total_cut:.2f} m2 (marks excluded).</p>"
        + _table(headers, rows, ["ok" if r["valid"] else "error" for r in records])
    )
    return (
        json.dumps(records, indent=2),
        _csv(headers, rows),
        _page("Panel inventory", status, body),
    )


def _audit_html(result: BuildPackResult, status: str) -> str:
    audit = result.audit
    summary = audit.summary()
    rows = sorted(
        audit.rows,
        key=lambda r: (-{"error": 3, "warning": 2, "info": 1, "ok": 0}[r.severity], r.seam_id),
    )
    headers = [
        "seam",
        "type",
        "side A",
        "side B",
        "A mm",
        "B mm",
        "ease mm",
        "mismatch mm",
        "rel %",
        "tol mm",
        "severity",
        "findings",
    ]
    table_rows = [
        [
            r.seam_id,
            r.seam_type,
            " ".join(r.panels_a),
            " ".join(r.panels_b),
            f"{r.length_a * 1e3:.1f}",
            f"{r.length_b * 1e3:.1f}",
            f"{r.designed_ease * 1e3:.1f}",
            f"{r.mismatch * 1e3:+.1f}",
            f"{r.rel_mismatch * 100:.3f}",
            f"{r.tolerance * 1e3:.1f}",
            r.severity,
            "; ".join(r.findings),
        ]
        for r in rows
    ]
    edge_rows = [[f.node_id, f.kind, f.severity, f.message] for f in audit.edge_findings]
    worst = max((r.abs_mismatch for r in audit.rows if r.designed_ease == 0), default=0.0)
    body = (
        f"<p>{len(audit.rows)} sewn pairs. Severity counts: "
        + ", ".join(f"{k}: {v}" for k, v in summary.items())
        + f". Largest mismatch without designed ease: {worst * 1e3:.2f} mm.</p>"
        + "<p class='note'>mismatch = (B - A) - designed ease. Designed ease is intended and "
        "is passed to the structural simulation; it is not an error.</p>"
        + "<h2>Edge findings</h2>"
        + (
            _table(
                ["edge", "finding", "severity", "message"],
                edge_rows,
                [f.severity for f in audit.edge_findings],
            )
            if edge_rows
            else "<p>None.</p>"
        )
        + "<h2>Seams</h2>"
        + _table(headers, table_rows, [r.severity for r in rows])
    )
    return _page("Seam-length audit", status, body)


def _mesh_html(result: BuildPackResult, status: str) -> str:
    report = result.mesh_report
    if report is None:
        return _page("Mesh report", status, "<p>Meshing was skipped; nothing is verified.</p>")
    checks = [[name, "pass" if ok else "FAIL"] for name, ok in report.checks.items()]
    loops = [
        [k, loop.opening or "UNINTENDED HOLE", len(loop.nodes), f"{loop.rest_length * 1e3:.1f}"]
        for k, loop in enumerate(report.boundary_loops)
    ]
    facts: list[list[Any]] = [
        ["nodes", report.nodes],
        ["triangles", report.triangles],
        ["boundary edges", report.edges_boundary],
        ["manifold edges", report.edges_manifold],
        ["attachment (T-junction) edges", report.edges_attachment],
        ["non-manifold edges", report.edges_nonmanifold],
        ["non-manifold vertices", report.nonmanifold_vertices],
        ["orientation conflicts", report.orientation_conflicts],
        ["connected parts", report.components],
        ["min / mean triangle quality", f"{report.min_quality:.3f} / {report.mean_quality:.3f}"],
        ["triangles below quality threshold", report.low_quality],
        ["inverted elements", report.inverted],
        ["total rest area m2", f"{report.total_rest_area:.4f}"],
        ["finished panel area m2", f"{report.expected_area:.4f}"],
        ["area difference", f"{report.area_relative_error * 100:+.4f} %"],
        ["Euler characteristic", report.euler_characteristic],
        ["distinct Gmsh panel meshes", report.gmsh_runs],
    ]
    body = (
        "<h2>Checks</h2>"
        + _table(
            ["check", "result"], checks, ["ok" if ok else "error" for ok in report.checks.values()]
        )
        + "<h2>Summary</h2>"
        + _table(["quantity", "value"], facts)
        + "<h2>Boundary loops</h2>"
        + _table(
            ["#", "opening", "edges", "rest length mm"],
            loops,
            ["ok" if lp.opening else "error" for lp in report.boundary_loops],
        )
        + (
            "<p>Missing openings: " + html.escape(", ".join(report.missing_openings)) + "</p>"
            if report.missing_openings
            else ""
        )
        + "<p class='note'>Attachment edges carry an appendage sewn onto a line marked on a "
        "panel (three incident triangles by design); they are declared in the assembly spec "
        "and are not counted as non-manifold.</p>"
    )
    return _page("Mesh report", status, body)


def _warnings_outputs(result: BuildPackResult, status: str) -> tuple[str, str, str]:
    order = {"error": 0, "warning": 1, "info": 2}
    items = sorted(result.warnings, key=lambda w: order[w.severity])
    rows = [
        [
            w.severity,
            w.code,
            w.piece_id or "",
            w.provenance.pattern_id if w.provenance else "",
            w.message,
        ]
        for w in items
    ]
    headers = ["severity", "code", "piece", "source entity", "message"]
    body = _table(headers, rows, [w.severity for w in items]) if rows else "<p>No warnings.</p>"
    return (
        json.dumps([w.as_dict() for w in items], indent=2),
        _csv(headers, rows),
        _page("Import warnings and assumptions", status, body),
    )


def write_reports(result: BuildPackResult, out_dir: str | Path) -> dict[str, Path]:
    """Write every import report into a directory.

    Parameters
    ----------
    result : BuildPackResult
        Pipeline result.
    out_dir : str or Path
        Output directory (created if needed).

    Returns
    -------
    dict of str to Path
        Written files keyed by report name (``index``, ``inventory_html``, ...).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    status = overall_status(result)
    files: dict[str, Path] = {}

    def put(key: str, name: str, text: str) -> None:
        path = out / name
        path.write_text(text, encoding="utf-8")
        files[key] = path

    inv_json, inv_csv, inv_html = _inventory_outputs(result, status)
    put("inventory_json", "panel-inventory.json", inv_json)
    put("inventory_csv", "panel-inventory.csv", inv_csv)
    put("inventory_html", "panel-inventory.html", inv_html)
    put("audit_json", "seam-audit.json", result.audit.to_json())
    put("audit_csv", "seam-audit.csv", result.audit.to_csv())
    put("audit_html", "seam-audit.html", _audit_html(result, status))
    put("graph_json", "seam-graph.json", result.assembly.graph.to_json())
    put("graph_csv", "seam-graph.csv", result.assembly.graph.to_csv())
    mesh_json = json.dumps(
        result.mesh_report.as_dict() if result.mesh_report else {"skipped": True}, indent=2
    )
    put("mesh_json", "mesh-report.json", mesh_json)
    put("mesh_html", "mesh-report.html", _mesh_html(result, status))
    w_json, w_csv, w_html = _warnings_outputs(result, status)
    put("warnings_json", "import-warnings.json", w_json)
    put("warnings_csv", "import-warnings.csv", w_csv)
    put("warnings_html", "import-warnings.html", w_html)
    if result.rest_model is not None:
        files["rest_model"] = save_rest_model(result.rest_model, out / "rest-model.json")
    counts = {
        s: sum(w.severity == s for w in result.warnings) for s in ("error", "warning", "info")
    }
    links = "".join(
        f"<li><a href='{html.escape(p.name)}'>{html.escape(p.name)}</a></li>"
        for key, p in sorted(files.items(), key=lambda kv: kv[1].name)
    )
    instances = list(result.assembly.instances.values())
    facts: list[list[Any]] = [
        ["build pack", result.config_path.name],
        ["mapping version", result.imported.mapping_version],
        ["design content hash", result.imported.content_hash],
        ["pieces", len(result.pieces)],
        ["instances (meshed)", f"{len(instances)} ({sum(i.mesh for i in instances)})"],
        ["seams audited", len(result.audit.rows)],
        ["audit errors", result.audit.error_count],
        [
            "warnings (error / warning / info)",
            f"{counts['error']} / {counts['warning']} / {counts['info']}",
        ],
        [
            "mesh checks",
            "not run"
            if result.mesh_report is None
            else ("all pass" if result.mesh_report.passed else "FAILED"),
        ],
    ]
    body = _table(["item", "value"], facts) + f"<h2>Reports</h2><ul>{links}</ul>"
    put("index", "index.html", _page("Pattern import report", status, body))
    return files
