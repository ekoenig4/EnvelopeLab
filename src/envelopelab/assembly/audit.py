r"""Seam-length audit of the seam graph.

For every sewn pair the finished lengths of the two sides are compared. With side
lengths :math:`L_a`, :math:`L_b` and designed ease :math:`e` (the intended excess of side
B, declared explicitly in the assembly spec) the *mismatch* is

.. math:: \delta = (L_b - L_a) - e, \qquad
          \delta_\mathrm{rel} = \frac{|\delta|}{\max(L_a, L_b)}

and a seam passes when :math:`|\delta|` is within its tolerance (3 mm by default,
configurable per seam). Designed ease is therefore never reported as an error, but it is
kept in the seam metadata that feeds the structural simulation.

The audit also flags finished edges that are neither sewn nor part of a declared opening
(*unmatched*), edges used by more than one seam or opening (*duplicate assignment*),
seams whose declared orientation contradicts the pattern geometry (*reversed
orientation*), and sides whose measured seam allowance differs from the declared one or
from the other side (*incompatible allowance*).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from envelopelab.assembly.seam_graph import Assembly, GraphSeam, SeamGraph

Severity = Literal["ok", "info", "warning", "error"]
SEVERITY_ORDER: dict[str, int] = {"ok": 0, "info": 1, "warning": 2, "error": 3}
#: Allowed difference between a measured and a declared seam allowance, m.
ALLOWANCE_TOLERANCE = 2e-3
#: Relative mismatch above which a pairing is reported as possibly ambiguous.
AMBIGUOUS_RELATIVE_MISMATCH = 0.05


@dataclass
class SeamAuditRow:
    """Audit result for one seam.

    Attributes
    ----------
    seam_id, seam_type : str
        Seam identity.
    panels_a, panels_b : list of str
        Instances on each side.
    length_a, length_b : float
        Finished side lengths, m.
    designed_ease : float
        Declared ease (side B minus side A), m.
    mismatch : float
        Signed residual :math:`(L_b - L_a) - e`, m.
    abs_mismatch : float
        :math:`|\\delta|`, m.
    rel_mismatch : float
        :math:`|\\delta| / \\max(L_a, L_b)` (dimensionless).
    tolerance : float
        Allowed :math:`|\\delta|`, m.
    allowance_a, allowance_b : float or None
        Measured median allowance on each side, m.
    severity : {"ok", "info", "warning", "error"}
        Worst finding.
    findings : list of str
        Explanations.
    meshed : bool
        The seam is joined in the rest mesh.
    """

    seam_id: str
    seam_type: str
    panels_a: list[str]
    panels_b: list[str]
    length_a: float
    length_b: float
    designed_ease: float
    mismatch: float
    abs_mismatch: float
    rel_mismatch: float
    tolerance: float
    allowance_a: float | None
    allowance_b: float | None
    severity: Severity
    findings: list[str] = field(default_factory=list)
    meshed: bool = True

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary (lengths in m)."""
        return {
            "seam_id": self.seam_id,
            "seam_type": self.seam_type,
            "panels_a": self.panels_a,
            "panels_b": self.panels_b,
            "length_a_m": round(self.length_a, 6),
            "length_b_m": round(self.length_b, 6),
            "designed_ease_m": round(self.designed_ease, 6),
            "mismatch_m": round(self.mismatch, 6),
            "abs_mismatch_m": round(self.abs_mismatch, 6),
            "rel_mismatch": round(self.rel_mismatch, 8),
            "tolerance_m": self.tolerance,
            "allowance_a_m": None if self.allowance_a is None else round(self.allowance_a, 6),
            "allowance_b_m": None if self.allowance_b is None else round(self.allowance_b, 6),
            "severity": self.severity,
            "findings": self.findings,
            "meshed": self.meshed,
        }


@dataclass
class EdgeFinding:
    """A finding about a single edge (unmatched or duplicate)."""

    node_id: str
    kind: Literal["unmatched_edge", "duplicate_assignment"]
    severity: Severity
    message: str
    used_by: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary."""
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "used_by": self.used_by,
        }


@dataclass
class SeamAudit:
    """Complete seam audit."""

    rows: list[SeamAuditRow]
    edge_findings: list[EdgeFinding]

    @property
    def error_count(self) -> int:
        """Seams and edges with severity ``error``."""
        return sum(r.severity == "error" for r in self.rows) + sum(
            f.severity == "error" for f in self.edge_findings
        )

    @property
    def worst(self) -> Severity:
        """Worst severity found."""
        levels: list[Severity] = [r.severity for r in self.rows]
        levels += [f.severity for f in self.edge_findings]
        return max(levels, key=lambda s: SEVERITY_ORDER[s], default="ok")

    def summary(self) -> dict[str, int]:
        """Counts per severity (seams and edge findings together)."""
        out = {k: 0 for k in SEVERITY_ORDER}
        for row in self.rows:
            out[row.severity] += 1
        for finding in self.edge_findings:
            out[finding.severity] += 1
        return out

    def to_json(self) -> str:
        """JSON text."""
        return json.dumps(
            {
                "summary": self.summary(),
                "seams": [r.as_dict() for r in self.rows],
                "edges": [f.as_dict() for f in self.edge_findings],
            },
            indent=2,
        )

    def to_csv(self) -> str:
        """CSV text, one row per seam followed by one row per edge finding (mm)."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "seam_id",
                "seam_type",
                "panels_a",
                "panels_b",
                "length_a_mm",
                "length_b_mm",
                "designed_ease_mm",
                "mismatch_mm",
                "abs_mismatch_mm",
                "rel_mismatch_pct",
                "tolerance_mm",
                "allowance_a_mm",
                "allowance_b_mm",
                "severity",
                "findings",
            ]
        )
        for r in self.rows:
            writer.writerow(
                [
                    r.seam_id,
                    r.seam_type,
                    " ".join(r.panels_a),
                    " ".join(r.panels_b),
                    f"{r.length_a * 1e3:.1f}",
                    f"{r.length_b * 1e3:.1f}",
                    f"{r.designed_ease * 1e3:.1f}",
                    f"{r.mismatch * 1e3:.1f}",
                    f"{r.abs_mismatch * 1e3:.1f}",
                    f"{r.rel_mismatch * 100:.3f}",
                    f"{r.tolerance * 1e3:.1f}",
                    "" if r.allowance_a is None else f"{r.allowance_a * 1e3:.1f}",
                    "" if r.allowance_b is None else f"{r.allowance_b * 1e3:.1f}",
                    r.severity,
                    "; ".join(r.findings),
                ]
            )
        for f in self.edge_findings:
            writer.writerow(
                [
                    f.node_id,
                    f.kind,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    f.severity,
                    f.message,
                ]
            )
        return buffer.getvalue()


def _side_allowance(graph: SeamGraph, seam: GraphSeam, side: Literal["a", "b"]) -> float | None:
    chain = seam.side_a if side == "a" else seam.side_b
    values = [graph.nodes[u.node_id].measured_allowance for u in chain]
    known = [v for v in values if v is not None]
    if not known:
        return None
    return sum(known) / len(known)


def _bump(row: SeamAuditRow, severity: Severity, message: str) -> None:
    row.findings.append(message)
    if SEVERITY_ORDER[severity] > SEVERITY_ORDER[row.severity]:
        row.severity = severity


def audit_seam(graph: SeamGraph, seam: GraphSeam) -> SeamAuditRow:
    """Audit one two-sided seam.

    Parameters
    ----------
    graph : SeamGraph
        The seam graph.
    seam : GraphSeam
        Seam with two non-empty sides.

    Returns
    -------
    SeamAuditRow
        Lengths, mismatch and findings.
    """
    la = graph.chain_length(seam.side_a)
    lb = graph.chain_length(seam.side_b)
    ease = seam.props.designed_ease_m
    delta = (lb - la) - ease
    longest = max(la, lb, 1e-12)
    row = SeamAuditRow(
        seam_id=seam.seam_id,
        seam_type=seam.seam_type,
        panels_a=graph.chain_pieces(seam.side_a),
        panels_b=graph.chain_pieces(seam.side_b),
        length_a=la,
        length_b=lb,
        designed_ease=ease,
        mismatch=delta,
        abs_mismatch=abs(delta),
        rel_mismatch=abs(delta) / longest,
        tolerance=seam.props.tolerance_m,
        allowance_a=_side_allowance(graph, seam, "a"),
        allowance_b=_side_allowance(graph, seam, "b"),
        severity="ok",
        meshed=seam.mesh,
    )
    if abs(delta) > seam.props.tolerance_m:
        _bump(
            row,
            "error",
            f"length mismatch {delta * 1e3:+.1f} mm exceeds {seam.props.tolerance_mm:.1f} mm",
        )
        if abs(delta) / longest > AMBIGUOUS_RELATIVE_MISMATCH:
            _bump(row, "error", "mismatch over 5 %: check the seam pairing")
    if ease != 0.0:
        _bump(
            row,
            "info",
            f"designed ease {ease * 1e3:+.1f} mm (side B longer); passed to the simulation",
        )
    if seam.orientation_check == "error":
        _bump(
            row,
            "error",
            f"reversed orientation: declared '{seam.props.orientation}' but the edge "
            "directions in the pattern frame disagree",
        )
    for side, measured in (("a", row.allowance_a), ("b", row.allowance_b)):
        declared = seam.props.side_allowance_m(side)  # type: ignore[arg-type]
        if declared is not None and measured is not None:
            if abs(measured - declared) > ALLOWANCE_TOLERANCE:
                _bump(
                    row,
                    "warning",
                    f"incompatible seam allowance: side {side.upper()} measures "
                    f"{measured * 1e3:.1f} mm, seam declares {declared * 1e3:.1f} mm",
                )
    same_declared = seam.props.allowance_a_mm is None and seam.props.allowance_b_mm is None
    if (
        same_declared
        and row.allowance_a is not None
        and row.allowance_b is not None
        and abs(row.allowance_a - row.allowance_b) > ALLOWANCE_TOLERANCE
    ):
        _bump(
            row,
            "warning",
            f"incompatible seam allowances: {row.allowance_a * 1e3:.1f} mm vs "
            f"{row.allowance_b * 1e3:.1f} mm and no per-side allowance declared",
        )
    if not seam.mesh:
        _bump(row, "info", "not joined in the rest mesh (audit only)")
    return row


def audit_assembly(assembly: Assembly) -> SeamAudit:
    """Audit every seam and edge assignment of an assembly.

    Parameters
    ----------
    assembly : Assembly
        Instances and seam graph.

    Returns
    -------
    SeamAudit
        Seam rows and edge findings.
    """
    graph = assembly.graph
    rows = [audit_seam(graph, s) for s in graph.seams if s.seam_type != "rim" and s.side_b]
    usage: dict[str, list[str]] = {}
    for seam in graph.seams:
        if seam.seam_type == "rim":
            continue
        for use in seam.side_a + seam.side_b:
            usage.setdefault(use.node_id, []).append(f"seam {seam.seam_id}")
    for opening in graph.openings:
        for use in opening.uses:
            usage.setdefault(use.node_id, []).append(f"opening {opening.name}")
    findings: list[EdgeFinding] = []
    for node_id, node in graph.nodes.items():
        if not node.instance_id:
            continue
        inst = assembly.instances[node.instance_id]
        used = usage.get(node_id, [])
        is_outline_edge = node.name in inst.edges
        # A line marked on a panel may carry several attachments only if the spec says so;
        # everything else may appear in one relationship.
        if len(used) > 1:
            findings.append(
                EdgeFinding(
                    node_id,
                    "duplicate_assignment",
                    "error",
                    f"edge is assigned {len(used)} times: {', '.join(used)}",
                    used,
                )
            )
        elif not used and is_outline_edge and (inst.mesh or inst.piece.kind != "mark"):
            findings.append(
                EdgeFinding(
                    node_id,
                    "unmatched_edge",
                    "error" if inst.mesh else "warning",
                    "finished edge is neither sewn nor part of a declared opening",
                )
            )
    return SeamAudit(rows, findings)
