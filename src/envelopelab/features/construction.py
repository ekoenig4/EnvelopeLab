"""Construction-sequence checks of special-shape features.

The order in which a feature is built changes what the builder can check and where the
errors end up. The checks here are driven by the ``construction`` list and the
``doubler`` entry of each feature in the build-pack YAML (no design is known to the code):

* **Sequence**: required precedences between steps, per feature kind. For a skin made
  of strips (pods, blisters) the strips are seamed first, the assembled skin is then
  checked against its ordinates, and only then eased onto the envelope; feed holes and
  the rim tape come before the skin is eased on (the holes cannot be cut once the pod is
  closed).
* **Ordinate check**: the assembled strips must reproduce the skin outline within the
  stated tolerance (:func:`check_strip_assembly`): every point of the skin outline lies
  within the tolerance of a strip outline, no strip vertex lies more than the tolerance
  outside the skin, and the strip areas add up to the skin area within tolerance times
  perimeter.
* **Doubler caught into the seams**: a doubled panel must be sewn into every seam round
  it at gore assembly, not added afterwards (:func:`check_doubler`): each of its edges
  must belong to a ring seam whose construction order is no later than gore assembly,
  and none of them may be a later appendage attachment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np

from envelopelab.features.spec import FeatureSpec
from envelopelab.geometry.polygon import distance_to_polyline, points_in_polygon, signed_area
from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.assembly.pipeline import BuildPackResult
    from envelopelab.assembly.seam_graph import Assembly

Severity = Literal["ok", "warning", "error"]

#: Required precedences (earlier, later) per feature kind.
PRECEDENCE: dict[str, list[tuple[str, str]]] = {
    "ram_air_pod": [
        ("strip_seams", "ordinate_check"),
        ("ordinate_check", "ease_onto_envelope"),
        ("feed_holes", "ease_onto_envelope"),
        ("rim_tape", "ease_onto_envelope"),
        ("gore_assembly", "ease_onto_envelope"),
    ],
    "blister": [
        ("strip_seams", "ordinate_check"),
        ("ordinate_check", "ease_onto_envelope"),
        ("rim_tape", "ease_onto_envelope"),
    ],
    "tubular": [
        ("doubler_caught_into_seams", "attach_appendage"),
        ("gore_assembly", "attach_appendage"),
        ("feed_holes", "attach_appendage"),
    ],
    "line_supported": [("gore_assembly", "attach_appendage")],
}
#: Default tolerance of the assembled-skin check against the ordinates, m.
ORDINATE_TOLERANCE = 0.010


@dataclass(frozen=True)
class ConstructionCheck:
    """Outcome of one construction check.

    Attributes
    ----------
    feature : str
        Feature name.
    check : str
        Check name.
    severity : {"ok", "warning", "error"}
        Result.
    message : str
        Explanation with units.
    value : float, optional
        Measured quantity (m for deviations).
    """

    feature: str
    check: str
    severity: Severity
    message: str
    value: float | None = None

    @property
    def passed(self) -> bool:
        """True unless the check failed."""
        return self.severity != "error"


def check_sequence(feature: FeatureSpec) -> list[ConstructionCheck]:
    """Check the declared construction steps against the precedences of the kind.

    Parameters
    ----------
    feature : FeatureSpec
        Feature with its ``construction`` list.

    Returns
    -------
    list of ConstructionCheck
        One row per precedence whose two steps are both declared (error when reversed),
        and a warning per required step that is missing.
    """
    order = {step.step: k for k, step in enumerate(feature.construction)}
    out = []
    for before, after in PRECEDENCE.get(feature.kind, []):
        if before in order and after in order:
            ok = order[before] < order[after]
            out.append(
                ConstructionCheck(
                    feature.name,
                    f"{before} before {after}",
                    "ok" if ok else "error",
                    f"{before.replace('_', ' ')} (step {order[before] + 1}) "
                    f"{'precedes' if ok else 'comes after'} {after.replace('_', ' ')} "
                    f"(step {order[after] + 1})",
                )
            )
        elif after in order and before not in order:
            out.append(
                ConstructionCheck(
                    feature.name,
                    f"{before} before {after}",
                    "warning",
                    f"step {before.replace('_', ' ')} is not declared before "
                    f"{after.replace('_', ' ')}",
                )
            )
    return out


def check_strip_assembly(
    strips: list[FloatArray], outline: FloatArray, tolerance: float = ORDINATE_TOLERANCE
) -> tuple[Severity, float, str]:
    """Compare the assembled strips with the one-piece skin outline (the ordinates).

    Parameters
    ----------
    strips : list of ndarray
        Strip outlines as seamed (same frame as ``outline``), m.
    outline : ndarray, shape (q, 2)
        Skin outline the ordinate tables describe, m.
    tolerance : float
        Allowed deviation, m.

    Returns
    -------
    severity : {"ok", "error"}
        ``error`` when any measure exceeds the tolerance.
    deviation : float
        Largest of the three measures (coverage, overhang, area / perimeter), m.
    message : str
        Explanation.
    """
    if not strips:
        return "error", float("inf"), "no strips to check"
    coverage = float(
        np.min(
            np.stack([distance_to_polyline(outline, s, True) for s in strips], axis=1), axis=1
        ).max()
    )
    overhang = 0.0
    for s in strips:
        outside = ~points_in_polygon(s, outline)
        if outside.any():
            overhang = max(overhang, float(distance_to_polyline(s[outside], outline, True).max()))
    perimeter = float(np.linalg.norm(np.roll(outline, -1, axis=0) - outline, axis=1).sum())
    area_gap = abs(sum(abs(signed_area(s)) for s in strips) - abs(signed_area(outline)))
    area_dev = area_gap / perimeter
    deviation = max(coverage, overhang, area_dev)
    severity: Severity = "ok" if deviation <= tolerance else "error"
    message = (
        f"{len(strips)} strips: rim coverage {coverage * 1000:.1f} mm, overhang "
        f"{overhang * 1000:.1f} mm, area difference {area_gap:.4f} m^2 "
        f"({area_dev * 1000:.1f} mm over the perimeter); tolerance {tolerance * 1000:g} mm"
    )
    return severity, deviation, message


def check_doubler(
    assembly: Assembly, instance_id: str, gore_assembly_order: int, feature: str
) -> ConstructionCheck:
    """Check that a doubled panel is caught into all its surrounding seams.

    Parameters
    ----------
    assembly : Assembly
        Seam graph of the build pack.
    instance_id : str
        The doubled panel instance.
    gore_assembly_order : int
        Construction order of gore assembly (the latest ring seam order).
    feature : str
        Feature name.

    Returns
    -------
    ConstructionCheck
        ``error`` when an edge is not in a ring seam sewn at gore assembly or is part of
        a later attachment.
    """
    inst = assembly.instances[instance_id]
    problems = []
    caught = 0
    for edge_name in inst.edges:
        node_id = f"{instance_id}:{edge_name}"
        seams = [
            s
            for s in assembly.graph.seams
            if any(u.node_id == node_id for u in (*s.side_a, *s.side_b))
        ]
        ring_seams = [
            s
            for s in seams
            if not s.attachment and s.props.construction_order <= gore_assembly_order
        ]
        late = [
            s for s in seams if s.attachment or s.props.construction_order > gore_assembly_order
        ]
        if ring_seams and not late:
            caught += 1
        elif not seams:
            problems.append(f"edge {edge_name} is not sewn")
        else:
            problems.append(
                f"edge {edge_name} is sewn in {', '.join(s.seam_id for s in late)} "
                "after gore assembly"
            )
    total = len(inst.edges)
    if problems:
        return ConstructionCheck(
            feature,
            "doubler caught into seams",
            "error",
            f"{instance_id}: " + "; ".join(problems),
            float(caught),
        )
    return ConstructionCheck(
        feature,
        "doubler caught into seams",
        "ok",
        f"{instance_id}: all {total} edges are caught into ring seams at gore assembly "
        f"(construction order <= {gore_assembly_order})",
        float(caught),
    )


def feature_checks(
    feature: FeatureSpec, built: BuildPackResult, base_dir: Path
) -> list[ConstructionCheck]:
    """Every construction check that applies to a feature.

    Parameters
    ----------
    feature : FeatureSpec
        Feature.
    built : BuildPackResult
        Imported build pack.
    base_dir : Path
        Directory of the build-pack YAML (strip files are relative to it).

    Returns
    -------
    list of ConstructionCheck
        Sequence checks, the ordinate check of a stripped skin (when an
        ``ordinate_check`` step is declared) and the doubler check.
    """
    from envelopelab.features.importer import read_strips

    out = check_sequence(feature)
    steps = {s.step: s for s in feature.construction}
    skin = feature.skin
    if "ordinate_check" in steps and skin is not None and skin.strips is not None and skin.piece:
        tol_mm = steps["ordinate_check"].tolerance_mm
        tol = ORDINATE_TOLERANCE if tol_mm is None else tol_mm / 1000.0
        strips = read_strips(base_dir / skin.strips.file, skin.strips.layer)
        piece = built.pieces[skin.piece]
        severity, deviation, message = check_strip_assembly(strips, piece.cut_outline, tol)
        out.append(ConstructionCheck(feature.name, "ordinate check", severity, message, deviation))
    if feature.doubler is not None:
        ring = next(r for r in built.spec.rings if r.name == feature.host.ring)
        order = max(ring.horizontal_seam.construction_order, ring.vertical_seam.construction_order)
        out.append(check_doubler(built.assembly, feature.doubler.instance, order, feature.name))
    return out
