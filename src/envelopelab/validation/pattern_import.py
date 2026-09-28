"""Pattern-import fixture checks: the numbers behind docs/validation/pattern-import-fixtures.md.

Each build-pack fixture is imported, assembled, audited and meshed with
:func:`envelopelab.assembly.pipeline.import_build_pack`. The summary contains only values
that do not depend on the triangulator's interior node placement (which may vary between
Gmsh versions and platforms): boundary loops, topology checks, seam-audit results and the
rest area, which is fixed by the prescribed boundary discretisation.

The same functions back ``tests/regression/test_pattern_import_fixtures.py`` and
``scripts/generate_validation_docs.py``. Fixture paths are passed in by the caller;
reference designs live only in ``tests/fixtures/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from envelopelab.assembly.pipeline import BuildPackResult, import_build_pack
from envelopelab.geometry.polygon import distance_to_polyline, offset_polygon

#: Required agreement between rest-mesh area and finished panel area (task requirement).
AREA_TOLERANCE = 0.005

#: Fixtures shown on the validation page: (name, role, path relative to the repository).
FIXTURES: tuple[tuple[str, str, str], ...] = (
    ("standard gore", "generic, cut + sew lines", "tests/fixtures/standard_gore/build-pack.yaml"),
    (
        "standard gore, cut only",
        "generic, cut lines only",
        "tests/fixtures/standard_gore/build-pack-cut-only.yaml",
    ),
    (
        "special shape",
        "generic, appendage + designed ease",
        "tests/fixtures/special_shape/build-pack.yaml",
    ),
    ("Alien", "regression only", "tests/fixtures/alien/build-pack.yaml"),
)


def fixture_paths(repo_root: Path) -> list[tuple[str, str, Path]]:
    """``FIXTURES`` with absolute paths under ``repo_root``."""
    return [(name, role, repo_root / rel) for name, role, rel in FIXTURES]


@dataclass(frozen=True)
class FixtureSummary:
    """Discretisation-independent summary of one fixture run."""

    name: str
    role: str
    pieces: int
    instances: int
    meshed_instances: int
    seams: int
    seams_with_ease: int
    audit_errors: int
    max_mismatch_mm: float
    boundary_loops: tuple[str, ...]
    unintended_holes: int
    components: int
    nonmanifold_edges: int
    attachment_edges: bool
    orientation_conflicts: int
    inverted: int
    area_error_pct: float
    inset_vs_sew_mm: float | None
    mesh_passed: bool
    errors: int
    warnings: int

    @property
    def passed(self) -> bool:
        """Mesh checks pass, no audit or import errors, area within tolerance."""
        return (
            self.mesh_passed
            and self.audit_errors == 0
            and self.errors == 0
            and abs(self.area_error_pct) <= AREA_TOLERANCE * 100
        )


def inset_versus_sew(result: BuildPackResult) -> float | None:
    """Largest distance between a drawn sew line and the cut line inset by the allowance.

    Parameters
    ----------
    result : BuildPackResult
        Pipeline result.

    Returns
    -------
    float or None
        Symmetric maximum distance over all panel pieces with both lines, mm (None when
        no piece has a sew line).
    """
    worst: float | None = None
    for piece in result.pieces.values():
        if piece.kind != "panel" or piece.outline_source != "sew":
            continue
        inset = offset_polygon(piece.cut_outline, -piece.seam_allowance)
        d = max(
            float(np.max(distance_to_polyline(piece.outline, inset, True))),
            float(np.max(distance_to_polyline(inset, piece.outline, True))),
        )
        worst = d if worst is None else max(worst, d)
    return None if worst is None else worst * 1e3


def summarize(name: str, role: str, result: BuildPackResult) -> FixtureSummary:
    """Summarise a pipeline result for the validation page.

    Parameters
    ----------
    name : str
        Fixture name.
    role : str
        What the fixture is for (shown on the page).
    result : BuildPackResult
        Pipeline result with a mesh.

    Returns
    -------
    FixtureSummary
        Summary values.
    """
    report = result.mesh_report
    if report is None:
        raise ValueError("fixture summaries need a meshed result")
    rows = result.audit.rows
    plain = [r.abs_mismatch for r in rows if r.designed_ease == 0.0]
    return FixtureSummary(
        name=name,
        role=role,
        pieces=len(result.pieces),
        instances=len(result.assembly.instances),
        meshed_instances=sum(i.mesh for i in result.assembly.instances.values()),
        seams=len(rows),
        seams_with_ease=sum(r.designed_ease != 0.0 for r in rows),
        audit_errors=result.audit.error_count,
        max_mismatch_mm=round(max(plain, default=0.0) * 1e3, 1),
        boundary_loops=tuple(
            sorted(loop.opening or "UNINTENDED" for loop in report.boundary_loops)
        ),
        unintended_holes=report.unintended_holes,
        components=report.components,
        nonmanifold_edges=report.edges_nonmanifold,
        attachment_edges=report.edges_attachment > 0,
        orientation_conflicts=report.orientation_conflicts,
        inverted=report.inverted,
        area_error_pct=round(report.area_relative_error * 100, 3),
        inset_vs_sew_mm=None if (d := inset_versus_sew(result)) is None else round(d, 1),
        mesh_passed=report.passed,
        errors=sum(w.severity == "error" for w in result.warnings),
        warnings=sum(w.severity == "warning" for w in result.warnings),
    )


def run_fixtures(fixtures: list[tuple[str, str, Path]]) -> list[FixtureSummary]:
    """Import and summarise several fixtures.

    Parameters
    ----------
    fixtures : list of (name, role, path)
        Build-pack YAML files.

    Returns
    -------
    list of FixtureSummary
        One summary per fixture.
    """
    return [summarize(name, role, import_build_pack(path)) for name, role, path in fixtures]


def _loops(summary: FixtureSummary) -> str:
    counts: dict[str, int] = {}
    for name in summary.boundary_loops:
        key = name.split(":")[-1] if ":" in name else name
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(f"{k} x{v}" if v > 1 else k for k, v in sorted(counts.items()))


def render_markdown(summaries: list[FixtureSummary]) -> str:
    """Render the validation page.

    Parameters
    ----------
    summaries : list of FixtureSummary
        Fixture results.

    Returns
    -------
    str
        Markdown text.
    """
    lines = [
        "# Pattern-import fixtures",
        "",
        "_Generated by `scripts/generate_validation_docs.py` from "
        "`envelopelab.validation.pattern_import`; do not edit by hand. A test fails when "
        "this page is stale._",
        "",
        "Each fixture is imported from its DXF files with its build-pack YAML file, "
        "assembled, seam-audited, meshed with Gmsh, sewn and validated. Only values that do "
        "not depend on interior mesh node placement are listed.",
        "",
        '!!! note "The Alien build pack is a regression fixture only"',
        "    `tests/fixtures/alien/` holds a complete third-party special-shape build pack "
        "(20 gores x 17 rows, 25 mm allowance) used to check that a real pack imports, "
        "audits and assembles **without any source-code special cases**. All of its "
        "specifics live in `tests/fixtures/alien/build-pack.yaml`. It is not a reference "
        "design and passing these checks says nothing about its airworthiness. Its eye pods "
        "(a separate skin sewn onto envelope panels over feed holes) are one example of an "
        "appendage layout, not a general assumption.",
        "",
        "| Fixture | Role | Status |",
        "|---|---|---|",
    ]
    for s in summaries:
        lines.append(f"| {s.name} | {s.role} | {'pass' if s.passed else '**FAIL**'} |")
    headers = [s.name for s in summaries]
    rows: list[tuple[str, list[str]]] = [
        ("Pieces imported", [str(s.pieces) for s in summaries]),
        ("Instances (meshed)", [f"{s.instances} ({s.meshed_instances})" for s in summaries]),
        ("Sewn pairs audited", [str(s.seams) for s in summaries]),
        ("Seams with designed ease", [str(s.seams_with_ease) for s in summaries]),
        ("Largest mismatch without ease (mm)", [f"{s.max_mismatch_mm:.1f}" for s in summaries]),
        ("Seam-audit errors", [str(s.audit_errors) for s in summaries]),
        ("Import errors / warnings", [f"{s.errors} / {s.warnings}" for s in summaries]),
        ("Boundary loops (all declared openings)", [_loops(s) for s in summaries]),
        ("Unintended holes", [str(s.unintended_holes) for s in summaries]),
        ("Connected parts", [str(s.components) for s in summaries]),
        ("Non-manifold edges", [str(s.nonmanifold_edges) for s in summaries]),
        (
            "Declared attachment (T-junction) seams",
            ["yes" if s.attachment_edges else "no" for s in summaries],
        ),
        ("Orientation conflicts", [str(s.orientation_conflicts) for s in summaries]),
        ("Inverted elements", [str(s.inverted) for s in summaries]),
        (
            "Rest-mesh area vs finished area (%)",
            [f"{s.area_error_pct:+.3f}" for s in summaries],
        ),
        (
            "Cut line inset by allowance vs drawn sew line (mm, max)",
            ["n/a" if s.inset_vs_sew_mm is None else f"{s.inset_vs_sew_mm:.1f}" for s in summaries],
        ),
    ]
    lines += [
        "",
        "## Results",
        "",
        "| Quantity | " + " | ".join(headers) + " |",
        "|---|" + "---|" * len(headers),
    ]
    for label, values in rows:
        lines.append(f"| {label} | " + " | ".join(values) + " |")
    lines += [
        "",
        f"Acceptance: no unintended holes, one connected part, no non-manifold edges other "
        f"than declared attachment seams, consistent orientation, no inverted elements, no "
        f"seam-audit errors, and rest-mesh area within {AREA_TOLERANCE * 100:g} % of the sum "
        "of finished panel areas (outline minus declared openings). The rest-area difference "
        "is the chord error of the resampled curved edges.",
        "",
    ]
    return "\n".join(lines)
