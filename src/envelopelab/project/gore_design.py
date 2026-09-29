r"""Standard-gore design helpers for the editor: geometry, live outputs and constraint locks.

The design schema stores a gore envelope as meridian control points (``x`` = radius
:math:`r`, ``y`` = height :math:`z`, m, mouth first), a gore count :math:`N` and finished
panel-row heights along the tape (m). This module turns that into the objects of
:mod:`envelopelab.geometry.gore` and computes what the editor shows after every edit.

Live outputs
------------
* Profile: meridian length, height :math:`H`, maximum diameter :math:`D`, volume
  :math:`V` and fabric area :math:`A` of the surface of revolution
  (:class:`~envelopelab.geometry.gore.MeridianProfile`).
* Gross lift :math:`L = V(\rho_{amb} - \rho_{int})g` with dry-air densities
  :math:`\rho = p/(R T)` at the design's ambient pressure and the ambient and internal
  temperatures (:func:`envelopelab.atmosphere.gas_density`).
* Estimated envelope mass from the cut panel areas, tapes and thread
  (:func:`envelopelab.mass_estimate.estimate_mass`) and the lift margin
  :math:`L/g - m_{env} - m_{payload}`.

Constraint locks
----------------
After a profile edit the control points are corrected so every locked quantity keeps its
value (lengths within 1 mm, volume within 0.1 %, the AGENTS.md defaults):

* **height** — heights are scaled about the mouth, :math:`z' = z_0 + k (z - z_0)`;
* **maximum diameter** — radii are scaled, :math:`r' = k r`;
* **volume** — the scale factor of the free dimension is found by Brent's method
  [Brent]_: radii when the diameter is free, else heights when the height is free, else
  the *fullness* :math:`r' = r_{max} (r / r_{max})^{1/k}`, which keeps the maximum
  radius and changes the other radii (including the mouth);
* **gore count** — an edit that changes :math:`N` is refused.

The spline through scaled control points is not exactly the scaled spline (the chord
parameterisation changes), so each correction is iterated until it holds.

Wizard profile
--------------
:func:`standard_gore_design` starts from a truncated superellipse of revolution

.. math:: \left|\frac{r}{R}\right|^n + \left|\frac{z - z_c}{b}\right|^n = 1

with :math:`R = D/2`, cut at the mouth radius below the equator and at the top-opening
radius above it; :math:`b` is chosen so that the cut height is :math:`H`, and the exponent
:math:`n` (fullness; 2 is an ellipse) is found by Brent's method so that the volume is the
target. Achievable volumes lie between the :math:`n = 1.2` and :math:`n = 12` shapes.

Assumptions and valid range: axisymmetric envelope, one tape per gore seam, fabric stretch
neglected (see ``docs/theory/gore-geometry.md``); tape and thread masses use the generic
``assumed`` values in :data:`ASSUMED_TAPE_LINEAR_MASS` and :data:`ASSUMED_THREAD` unless
measured values are supplied.

References
----------
.. [Brent] R. P. Brent, *Algorithms for Minimization without Derivatives*, Prentice-Hall
   (1973), ch. 4.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.optimize import brentq

from envelopelab.atmosphere import gas_density, gross_lift
from envelopelab.design.model import DesignDocument
from envelopelab.geometry.gore import (
    LENGTH_TOLERANCE,
    GoreWidthModel,
    MeridianProfile,
    PanelRow,
    SeamAllowance,
    split_rows,
)
from envelopelab.mass_estimate import (
    MassEstimate,
    TapeMasses,
    ThreadSpec,
    estimate_mass,
    lift_margin,
)
from envelopelab.materials.repository import (
    FabricCatalog,
    FabricLibraryRepository,
    MaterialProperty,
)
from envelopelab.project.model import ConstraintLocks, PatternSet

FloatArray = np.ndarray
Severity = Literal["info", "warning", "error"]

#: Volume tolerance of the constraint locks, relative (AGENTS.md volume/area default).
VOLUME_TOLERANCE = 1e-3
#: Profile sampling of the editor (chord-length error below 1e-6 relative).
PROFILE_SAMPLES = 2001
#: Generic tape linear mass, kg/m (25 mm polyester load tape; ``assumed``).
ASSUMED_TAPE_LINEAR_MASS = MaterialProperty(0.02, "assumed")
#: Generic lockstitch thread: 30 tex, 2.75 m per m of seam per row, 2 rows (``assumed``).
ASSUMED_THREAD = ThreadSpec(
    linear_mass=MaterialProperty(30e-6, "assumed"),
    consumption_ratio=MaterialProperty(2.75, "assumed"),
    vertical_rows=2,
    horizontal_rows=2,
)
#: Fabric areal mass when a zone's fabric is not in the library, kg/m^2 (``assumed``).
ASSUMED_AREAL_MASS = MaterialProperty(0.065, "assumed")
#: Kilograms per square metre per gram per square metre (fabric library unit).
KG_PER_G = 1e-3


class LockError(ValueError):
    """An edit cannot satisfy the constraint locks."""


@dataclass(frozen=True)
class DesignFinding:
    """A validation message about a design (code, severity, message, target)."""

    code: str
    severity: Severity
    message: str
    target: str = ""


# --------------------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------------------


def control_arrays(design: DesignDocument) -> tuple[FloatArray, FloatArray]:
    """Control-point radii and heights of a gore design, m (mouth first)."""
    if design.gores is None:
        raise ValueError("not a standard-gore design")
    pts = design.gores.meridian_profile_control_points
    return (
        np.array([p.x for p in pts], dtype=np.float64),
        np.array([p.y for p in pts], dtype=np.float64),
    )


def profile_from_arrays(r: FloatArray, z: FloatArray) -> MeridianProfile:
    """Densely sampled spline profile through control points (m)."""
    return MeridianProfile.from_control_points(r, z, samples=PROFILE_SAMPLES)


def design_profile(design: DesignDocument) -> MeridianProfile:
    """Meridian profile of a gore design, m.

    Raises
    ------
    ValueError
        For a special-shape design, fewer than two control points or coincident points.
    """
    r, z = control_arrays(design)
    if r.size < 2:
        raise ValueError("a profile needs at least two control points")
    return profile_from_arrays(r, z)


def default_allowance(design: DesignDocument) -> float:
    """Seam allowance of the first seam type, m (0 without seam types)."""
    return design.seam_types[0].allowance if design.seam_types else 0.0


def row_allowance(design: DesignDocument, patterns: PatternSet, letter: str) -> float:
    """Seam allowance of a row, m (row override or the design default)."""
    override = patterns.row(letter).seam_allowance
    return default_allowance(design) if override is None else override


def row_zone(design: DesignDocument, patterns: PatternSet, letter: str) -> str:
    """Material zone of a row (row setting or the design's first zone)."""
    zone = patterns.row(letter).zone
    if zone is not None:
        return zone
    return next(iter(design.zones), "default")


def rows_coverage(design: DesignDocument, profile: MeridianProfile) -> tuple[float, float]:
    """(sum of finished row heights, meridian length), m."""
    assert design.gores is not None
    return (
        float(sum(row.finished_height for row in design.gores.panel_rows)),
        profile.meridian_length,
    )


def fit_row_heights(heights: Sequence[float], length: float) -> list[float]:
    """Scale row heights so they cover ``length`` exactly.

    Parameters
    ----------
    heights : sequence of float
        Current finished row heights, m.
    length : float
        Meridian length to cover, m.

    Returns
    -------
    list of float
        Heights in the same proportions, rounded to 0.1 mm; the last row takes the
        remainder, m.
    """
    total = float(sum(heights))
    if total <= 0.0 or length <= 0.0:
        raise ValueError("heights and length must be positive")
    scaled = [math.floor(h * length / total * 1e4) / 1e4 for h in heights[:-1]]
    scaled.append(length - sum(scaled))
    if min(scaled) <= 0.0:
        raise ValueError("row heights would not stay positive")
    return scaled


def equal_row_heights(length: float, count: int) -> list[float]:
    """``count`` equal rows covering ``length`` (m), rounded to 0.1 mm."""
    return fit_row_heights([1.0] * count, length)


def panel_rows(
    design: DesignDocument, patterns: PatternSet, profile: MeridianProfile | None = None
) -> list[PanelRow]:
    """Finished and cut panel rows of a gore design, mouth first.

    Parameters
    ----------
    design : DesignDocument
        Gore design; row heights in m.
    patterns : PatternSet
        Row seam-allowance overrides (m).
    profile : MeridianProfile, optional
        Precomputed :func:`design_profile`.

    Returns
    -------
    list of PanelRow
        One per design row (manual outline overrides are not applied here).

    Raises
    ------
    ValueError
        When the rows do not cover the meridian within 1 mm.
    """
    assert design.gores is not None
    profile = profile or design_profile(design)
    total, length = rows_coverage(design, profile)
    if abs(total - length) > LENGTH_TOLERANCE:
        raise ValueError(f"panel rows cover {total:.4f} m but the meridian is {length:.4f} m long")
    width = GoreWidthModel(n_gores=design.gores.count, form="small_bulge")
    rows: list[PanelRow] = []
    start = 0.0
    specs = design.gores.panel_rows
    for i, spec in enumerate(specs):
        a = row_allowance(design, patterns, spec.letter)
        height = spec.finished_height
        if i == len(specs) - 1:
            height = length - start  # absorb the sub-millimetre rounding of the rows
        rows += split_rows(
            profile,
            width,
            [height],
            labels=[spec.letter],
            allowance=SeamAllowance(side=a, bottom=a, top=a),
            start=start,
            require_full_coverage=False,
        )
        start += height
    return rows


# --------------------------------------------------------------------------------------
# Live outputs
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GoreOutputs:
    """Live outputs of a gore design (see the module docstring).

    Attributes
    ----------
    meridian_length, height, max_diameter : float
        m.
    volume : float
        m^3.
    area : float
        Fabric surface area through the tapes, m^2.
    ambient_density, internal_density : float
        kg/m^3.
    gross_lift : float
        N.
    mass : MassEstimate, optional
        Envelope mass estimate (None when the panel rows are invalid).
    envelope_mass : float, optional
        kg.
    lift_margin : float, optional
        Spare liftable mass after envelope and payload, kg.
    sources : tuple of str
        Source tags of the material values in the mass estimate.
    findings : list of DesignFinding
        Why an output is missing, and design warnings.
    """

    meridian_length: float
    height: float
    max_diameter: float
    volume: float
    area: float
    ambient_density: float
    internal_density: float
    gross_lift: float
    mass: MassEstimate | None
    envelope_mass: float | None
    lift_margin: float | None
    sources: tuple[str, ...]
    findings: list[DesignFinding] = field(default_factory=list)


def zone_areal_masses(
    design: DesignDocument, fabrics: FabricLibraryRepository | FabricCatalog | None
) -> dict[str, MaterialProperty]:
    """Areal mass per design zone, kg/m^2, from the fabric library (g/m^2 stored)."""
    out: dict[str, MaterialProperty] = {}
    for zone, fabric_id in design.zones.items():
        fabric = fabrics.fabric(fabric_id) if fabrics is not None else None
        if fabric is None:
            out[zone] = ASSUMED_AREAL_MASS
        else:
            out[zone] = MaterialProperty(
                fabric.areal_mass.value * KG_PER_G, fabric.areal_mass.source
            )
    return out


def gore_outputs(
    design: DesignDocument,
    patterns: PatternSet,
    fabrics: FabricLibraryRepository | FabricCatalog | None = None,
) -> GoreOutputs:
    """Area, volume, lift and estimated mass of a gore design.

    Parameters
    ----------
    design : DesignDocument
        Gore design. Operating conditions in SI: temperatures K, pressure Pa, payload kg.
    patterns : PatternSet
        Row zones and seam allowances.
    fabrics : FabricLibraryRepository, optional
        Fabric library for areal masses; ``assumed`` generic fabric when missing.

    Returns
    -------
    GoreOutputs
        See the class; lengths m, volume m^3, lift N, masses kg.
    """
    assert design.gores is not None
    profile = design_profile(design)
    op = design.operating
    findings: list[DesignFinding] = []
    rho_a = gas_density(op.ambient_pressure, op.ambient_temperature)
    rho_i = gas_density(op.ambient_pressure, op.internal_temperature)
    lift = gross_lift(profile.volume, rho_a, rho_i)
    if op.internal_temperature <= op.ambient_temperature:
        findings.append(
            DesignFinding(
                "no_lift",
                "error",
                "internal temperature is not above ambient: the envelope has no lift",
                "operating",
            )
        )
    mass: MassEstimate | None = None
    margin: float | None = None
    try:
        rows = panel_rows(design, patterns, profile)
    except ValueError as exc:
        findings.append(DesignFinding("rows", "error", f"{exc}; mass not estimated", "rows"))
        rows = []
    if rows:
        zones = [row_zone(design, patterns, r.label) for r in rows]
        areal = zone_areal_masses(design, fabrics)
        for z in set(zones) - set(areal):
            findings.append(
                DesignFinding(
                    "zone", "warning", f"zone {z!r} has no fabric; assumed areal mass", "zones"
                )
            )
            areal[z] = ASSUMED_AREAL_MASS
        tape = ASSUMED_TAPE_LINEAR_MASS
        mass = estimate_mass(
            rows,
            design.gores.count,
            zones,
            areal,
            TapeMasses(tape, tape, tape, tape),
            ASSUMED_THREAD,
        )
        margin = lift_margin(profile.volume, rho_a, rho_i, mass.total_mass, op.payload_mass).margin
    return GoreOutputs(
        meridian_length=profile.meridian_length,
        height=profile.height,
        max_diameter=profile.max_width,
        volume=profile.volume,
        area=profile.area,
        ambient_density=rho_a,
        internal_density=rho_i,
        gross_lift=lift,
        mass=mass,
        envelope_mass=None if mass is None else mass.total_mass,
        lift_margin=margin,
        sources=() if mass is None else mass.sources,
        findings=findings,
    )


def design_findings(design: DesignDocument, patterns: PatternSet) -> list[DesignFinding]:
    """Validation findings of a gore design (profile, rows, openings, zones)."""
    out: list[DesignFinding] = []
    if design.gores is None:
        if design.special is not None and not design.special.panel_list:
            out.append(
                DesignFinding(
                    "special_panels",
                    "warning",
                    "special shape has no panels yet: patterns and simulation are unavailable",
                    "special",
                )
            )
        return out
    g = design.gores
    try:
        profile = design_profile(design)
    except ValueError as exc:
        return [DesignFinding("profile", "error", str(exc), "profile")]
    r, _ = control_arrays(design)
    total, length = rows_coverage(design, profile)
    if abs(total - length) > LENGTH_TOLERANCE:
        out.append(
            DesignFinding(
                "rows",
                "error",
                f"panel rows cover {total:.4f} m but the meridian is {length:.4f} m long "
                "(use 'Fit rows to meridian')",
                "rows",
            )
        )
    if abs(2.0 * r[0] - g.mouth_diameter) > LENGTH_TOLERANCE:
        out.append(
            DesignFinding(
                "mouth",
                "warning",
                f"mouth diameter {g.mouth_diameter:.3f} m differs from the profile's "
                f"{2.0 * r[0]:.3f} m",
                "gores",
            )
        )
    if abs(2.0 * r[-1] - g.crown_ring) > LENGTH_TOLERANCE:
        out.append(
            DesignFinding(
                "crown",
                "warning",
                f"crown ring diameter {g.crown_ring:.3f} m differs from the profile's top "
                f"opening {2.0 * r[-1]:.3f} m",
                "gores",
            )
        )
    for letter, row in patterns.rows.items():
        if row.zone is not None and row.zone not in design.zones:
            out.append(
                DesignFinding(
                    "zone", "error", f"row {letter}: zone {row.zone!r} is not defined", letter
                )
            )
    letters = {row.letter for row in g.panel_rows}
    for letter in sorted(set(patterns.rows) - letters):
        out.append(
            DesignFinding(
                "orphan_row",
                "warning",
                f"pattern annotations for row {letter}, which the design does not have",
                letter,
            )
        )
    return out


# --------------------------------------------------------------------------------------
# Constraint locks
# --------------------------------------------------------------------------------------


def _scaled_z(r: FloatArray, z: FloatArray, k: float) -> tuple[FloatArray, FloatArray]:
    return r, z[0] + k * (z - z[0])


def _scaled_r(r: FloatArray, z: FloatArray, k: float) -> tuple[FloatArray, FloatArray]:
    return k * r, z


def _fuller(r: FloatArray, z: FloatArray, k: float) -> tuple[FloatArray, FloatArray]:
    r_max = float(r.max())
    return r_max * np.power(np.clip(r / r_max, 0.0, 1.0), 1.0 / k), z


def _hold(
    r: FloatArray, z: FloatArray, target: float, which: Literal["height", "diameter"]
) -> tuple[FloatArray, FloatArray]:
    for _ in range(20):
        profile = profile_from_arrays(r, z)
        value = profile.height if which == "height" else profile.max_width
        if value <= 0.0:
            raise LockError(f"the profile has no {which}; it cannot hold the lock")
        if abs(value - target) <= 0.1 * LENGTH_TOLERANCE:
            return r, z
        k = target / value
        r, z = _scaled_z(r, z, k) if which == "height" else _scaled_r(r, z, k)
    raise LockError(f"could not hold the locked {which} of {target:.4f} m")


def _hold_lengths(
    r: FloatArray, z: FloatArray, locks: ConstraintLocks
) -> tuple[FloatArray, FloatArray]:
    for _ in range(10):
        if locks.height is not None:
            r, z = _hold(r, z, locks.height, "height")
        if locks.max_diameter is not None:
            r, z = _hold(r, z, locks.max_diameter, "diameter")
        profile = profile_from_arrays(r, z)
        ok_h = locks.height is None or abs(profile.height - locks.height) <= LENGTH_TOLERANCE
        ok_d = (
            locks.max_diameter is None
            or abs(profile.max_width - locks.max_diameter) <= LENGTH_TOLERANCE
        )
        if ok_h and ok_d:
            return r, z
    raise LockError("height and diameter locks could not both be held")


def apply_locks(
    r: FloatArray, z: FloatArray, locks: ConstraintLocks
) -> tuple[FloatArray, FloatArray]:
    """Correct edited control points so every locked quantity keeps its value.

    Parameters
    ----------
    r, z : ndarray
        Edited control-point radii and heights, m.
    locks : ConstraintLocks
        Locked height (m), volume (m^3) and maximum diameter (m).

    Returns
    -------
    (ndarray, ndarray)
        Corrected radii and heights, m.

    Raises
    ------
    LockError
        When the locks cannot all be met (e.g. the edit collapsed the profile).
    """
    r = np.asarray(r, dtype=np.float64).copy()
    z = np.asarray(z, dtype=np.float64).copy()
    if np.any(r < 0.0):
        raise LockError("control-point radii must be non-negative")
    r, z = _hold_lengths(r, z, locks)
    if locks.volume is None:
        return r, z
    target = locks.volume
    if locks.max_diameter is None:
        transform = _scaled_r
    elif locks.height is None:
        transform = _scaled_z
    else:
        transform = _fuller

    def residual(k: float) -> float:
        rr, zz = _hold_lengths(*transform(r, z, k), locks)
        return profile_from_arrays(rr, zz).volume / target - 1.0

    lo, hi = 0.8, 1.25
    f_lo, f_hi = residual(lo), residual(hi)
    for _ in range(8):
        if f_lo * f_hi <= 0.0:
            break
        lo, hi = lo * 0.8, hi * 1.25
        f_lo, f_hi = residual(lo), residual(hi)
    else:
        raise LockError(f"no profile with the locked volume {target:.2f} m^3 near this edit")
    k = float(brentq(residual, lo, hi, xtol=1e-10, rtol=1e-12))
    r, z = _hold_lengths(*transform(r, z, k), locks)
    profile = profile_from_arrays(r, z)
    if abs(profile.volume / target - 1.0) > VOLUME_TOLERANCE:
        raise LockError(f"volume lock missed: {profile.volume:.2f} vs {target:.2f} m^3")
    return r, z


def check_locks(design: DesignDocument, locks: ConstraintLocks) -> list[str]:
    """Locked quantities the design no longer meets (empty when all hold)."""
    assert design.gores is not None
    profile = design_profile(design)
    out: list[str] = []
    if locks.height is not None and abs(profile.height - locks.height) > LENGTH_TOLERANCE:
        out.append(f"height {profile.height:.4f} m, locked {locks.height:.4f} m")
    if (
        locks.max_diameter is not None
        and abs(profile.max_width - locks.max_diameter) > LENGTH_TOLERANCE
    ):
        out.append(f"max diameter {profile.max_width:.4f} m, locked {locks.max_diameter:.4f} m")
    if locks.volume is not None and abs(profile.volume / locks.volume - 1.0) > VOLUME_TOLERANCE:
        out.append(f"volume {profile.volume:.2f} m^3, locked {locks.volume:.2f} m^3")
    if locks.gore_count is not None and design.gores.count != locks.gore_count:
        out.append(f"gore count {design.gores.count}, locked {locks.gore_count}")
    return out


# --------------------------------------------------------------------------------------
# Manual outline overrides: seam matching
# --------------------------------------------------------------------------------------


def _length(points: FloatArray) -> float:
    return float(np.sum(np.hypot(*np.diff(points, axis=0).T)))


def outline_edges(points: Sequence[Sequence[float]]) -> dict[str, float]:
    """Finished edge lengths of an editable outline, m.

    The outline layout is ``2k`` points: the right side from the bottom-right corner up
    (``0 .. k-1``), then the left side from the top-left corner down (``k .. 2k-1``). The
    top edge joins points ``k-1`` and ``k``, the bottom edge ``2k-1`` and ``0``.

    Returns
    -------
    dict of str to float
        ``left``, ``right``, ``top`` and ``bottom`` lengths, m.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 4 or len(pts) % 2:
        raise ValueError("an editable outline has an even number (>= 4) of 2-D points")
    k = len(pts) // 2
    return {
        "right": _length(pts[:k]),
        "left": _length(pts[k:]),
        "top": _length(pts[k - 1 : k + 1]),
        "bottom": _length(np.vstack((pts[-1], pts[0]))),
    }


def editable_outline(row: PanelRow, per_side: int = 9) -> list[tuple[float, float]]:
    """Resample a row's finished outline to the editable layout (m).

    Parameters
    ----------
    row : PanelRow
        Generated row.
    per_side : int
        Points on each side (corners included).

    Returns
    -------
    list of (float, float)
        ``2 * per_side`` points, see :func:`outline_edges`.
    """
    edge = row.right_edge
    s = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(edge, axis=0).T))))
    t = np.linspace(0.0, s[-1], per_side)
    right = np.column_stack((np.interp(t, s, edge[:, 0]), np.interp(t, s, edge[:, 1])))
    left = right[::-1] * np.array([-1.0, 1.0])
    return [(float(x), float(y)) for x, y in np.vstack((right, left))]


def generated_edges(row: PanelRow) -> dict[str, float]:
    """Finished edge lengths of a generated row, m."""
    return {
        "right": row.side_length,
        "left": row.side_length,
        "top": row.top_width,
        "bottom": row.bottom_width,
    }


def seam_mismatches(
    rows: Sequence[PanelRow],
    patterns: PatternSet,
    tolerance: float = 3e-3,
) -> list[DesignFinding]:
    """Seams whose two sides differ in length by more than ``tolerance`` (m).

    Vertical seams join the right side of one gore to the left side of the next (the same
    row piece); horizontal seams join a row's top edge to the next row's bottom edge.
    Manual outline overrides are used where present.
    """
    edges: list[dict[str, float]] = []
    for row in rows:
        manual = patterns.row(row.label).manual_outline
        edges.append(generated_edges(row) if manual is None else outline_edges(manual.points))
    out: list[DesignFinding] = []
    for row, e in zip(rows, edges, strict=True):
        diff = abs(e["right"] - e["left"])
        if diff > tolerance:
            out.append(
                DesignFinding(
                    "seam_mismatch",
                    "error",
                    f"row {row.label}: vertical seam sides differ by {diff * 1000:.1f} mm "
                    f"(tolerance {tolerance * 1000:.0f} mm)",
                    row.label,
                )
            )
    for (lower, e0), (upper, e1) in zip(
        zip(rows, edges, strict=True), list(zip(rows, edges, strict=True))[1:], strict=False
    ):
        diff = abs(e0["top"] - e1["bottom"])
        if diff > tolerance:
            out.append(
                DesignFinding(
                    "seam_mismatch",
                    "error",
                    f"seam {lower.label}/{upper.label}: top of {lower.label} and bottom of "
                    f"{upper.label} differ by {diff * 1000:.1f} mm "
                    f"(tolerance {tolerance * 1000:.0f} mm)",
                    upper.label,
                )
            )
    return out


# --------------------------------------------------------------------------------------
# Wizard
# --------------------------------------------------------------------------------------


def superellipse_points(
    width: float,
    height: float,
    exponent: float,
    mouth_diameter: float,
    top_diameter: float,
    count: int = 11,
) -> tuple[FloatArray, FloatArray]:
    """Control points of a truncated superellipse of revolution (module docstring), m.

    Parameters
    ----------
    width : float
        Maximum diameter D, m.
    height : float
        Height between the mouth and the top opening, m.
    exponent : float
        Superellipse exponent n (> 1), dimensionless.
    mouth_diameter, top_diameter : float
        Diameters at the mouth and the top opening, m (each < D).
    count : int
        Number of control points (odd, so the equator is one of them).

    Returns
    -------
    (ndarray, ndarray)
        Radii and heights, m, mouth at z = 0.
    """
    radius = width / 2.0
    if not (0.0 < mouth_diameter < width and 0.0 < top_diameter < width):
        raise ValueError("mouth and top diameters must be positive and below the width")
    n = exponent
    rm, rt = mouth_diameter / 2.0, top_diameter / 2.0

    def reach(rc: float) -> float:
        return float((1.0 - (rc / radius) ** n) ** (1.0 / n))

    b = height / (reach(rm) + reach(rt))
    t_bottom = -math.acos((rm / radius) ** (n / 2.0))
    t_top = math.acos((rt / radius) ** (n / 2.0))
    t = np.concatenate(
        (
            np.linspace(t_bottom, 0.0, count // 2 + 1),
            np.linspace(0.0, t_top, count - count // 2)[1:],
        )
    )
    c = np.cos(t)
    s = np.sin(t)
    r = radius * np.abs(c) ** (2.0 / n)
    z = b * np.sign(s) * np.abs(s) ** (2.0 / n)
    r[0], r[-1] = rm, rt
    return r, z - z[0]


EXPONENT_RANGE = (1.2, 12.0)


def wizard_control_points(
    target_volume: float,
    target_height: float,
    target_width: float,
    mouth_diameter: float,
    top_diameter: float,
    count: int = 11,
) -> tuple[FloatArray, FloatArray]:
    """Control points whose profile has the target volume, height and width.

    Parameters
    ----------
    target_volume : float
        m^3.
    target_height, target_width : float
        Height (mouth to top opening) and maximum diameter, m.
    mouth_diameter, top_diameter : float
        m.
    count : int
        Control points.

    Returns
    -------
    (ndarray, ndarray)
        Radii and heights, m.

    Raises
    ------
    ValueError
        When the target volume lies outside the achievable range for this height and
        width (the message gives the range).
    """
    locks = ConstraintLocks(height=target_height, max_diameter=target_width)

    def shape(n: float) -> tuple[FloatArray, FloatArray]:
        r, z = superellipse_points(
            target_width, target_height, n, mouth_diameter, top_diameter, count
        )
        return _hold_lengths(r, z, locks)

    def residual(n: float) -> float:
        return profile_from_arrays(*shape(n)).volume - target_volume

    lo, hi = EXPONENT_RANGE
    f_lo, f_hi = residual(lo), residual(hi)
    if f_lo * f_hi > 0.0:
        raise ValueError(
            f"a {target_width:g} m wide, {target_height:g} m high envelope holds "
            f"{f_lo + target_volume:.0f}-{f_hi + target_volume:.0f} m^3; the target "
            f"{target_volume:.0f} m^3 is outside that range"
        )
    n = float(brentq(residual, lo, hi, xtol=1e-10))
    return shape(n)


def standard_gore_design(
    name: str,
    target_volume: float,
    target_height: float,
    target_width: float,
    gore_count: int,
    row_count: int,
    mouth_diameter: float | None = None,
    top_diameter: float | None = None,
    fabric_id: str = "ripstop_nylon",
    seam_allowance: float = 0.025,
    internal_temperature: float = 373.15,
    ambient_temperature: float = 288.15,
    ambient_pressure: float = 101325.0,
    payload_mass: float = 0.0,
) -> DesignDocument:
    """New standard-gore design from target volume, height and width.

    Parameters
    ----------
    name : str
        Design name.
    target_volume : float
        m^3.
    target_height, target_width : float
        m.
    gore_count, row_count : int
        Gores N (>= 3) and horizontal panel rows (>= 1).
    mouth_diameter, top_diameter : float, optional
        m; default 0.3 and 0.25 of the width.
    fabric_id : str
        Fabric of the single zone ``body``.
    seam_allowance : float
        m.
    internal_temperature, ambient_temperature : float
        K.
    ambient_pressure : float
        Pa.
    payload_mass : float
        kg.

    Returns
    -------
    DesignDocument
        Schema-valid design with its content hash.
    """
    from envelopelab.project.templates import new_design

    mouth = mouth_diameter if mouth_diameter is not None else 0.3 * target_width
    top = top_diameter if top_diameter is not None else 0.25 * target_width
    r, z = wizard_control_points(target_volume, target_height, target_width, mouth, top)
    length = profile_from_arrays(r, z).meridian_length
    heights = equal_row_heights(length, row_count)
    return new_design(
        name=name,
        points=list(zip(r.tolist(), z.tolist(), strict=True)),
        gore_count=gore_count,
        row_heights=heights,
        mouth_diameter=2.0 * float(r[0]),
        top_diameter=2.0 * float(r[-1]),
        fabric_id=fabric_id,
        seam_allowance=seam_allowance,
        internal_temperature=internal_temperature,
        ambient_temperature=ambient_temperature,
        ambient_pressure=ambient_pressure,
        payload_mass=payload_mass,
    )


def rows_zones_mapping(design: DesignDocument, patterns: PatternSet) -> Mapping[str, str]:
    """Zone of every design row."""
    assert design.gores is not None
    return {r.letter: row_zone(design, patterns, r.letter) for r in design.gores.panel_rows}
