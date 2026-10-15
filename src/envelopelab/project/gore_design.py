r"""Standard-gore design helpers for the editor: geometry, live outputs and constraint locks.

The design schema stores a gore envelope as meridian control points (``x`` = radius
:math:`r`, ``y`` = height :math:`z`, m, mouth first), a gore count :math:`N` and finished
panel-row heights along the tape (m). This module turns that into the objects of
:mod:`envelopelab.geometry.gore` and computes what the editor shows after every edit.

Live outputs
------------
* Profile: meridian length, height :math:`H`, maximum diameter :math:`D`
  (:class:`~envelopelab.geometry.gore.MeridianProfile`), and the volume :math:`V` and
  fabric area :math:`A` of the lofted envelope: tapes plus the fabric lobe between
  adjacent tapes set by the design's loft
  (:func:`~envelopelab.geometry.gore.lofted_volume`,
  :func:`~envelopelab.geometry.gore.lofted_area`; without a loft, the small-bulge gore,
  these equal the surface of revolution through the tapes).
* Gross lift :math:`L = V(\rho_{amb} - \rho_{int})g` with dry-air densities
  :math:`\rho = p/(R T)` at the design's ambient pressure and the ambient and internal
  temperatures (:func:`envelopelab.atmosphere.gas_density`).
* Estimated envelope mass from the cut panel areas, tapes and thread
  (:func:`envelopelab.mass_estimate.estimate_mass`), the parachute and rigging mass
  (:func:`envelopelab.rigging.rigging_outputs`: parachute fabric, shroud and centralising
  lines, red line, flying wires and turning-vent lines) and the lift margin
  :math:`L/g - m_{env} - m_{rig} - m_{payload}`.

Constraint locks
----------------
After a profile edit the control points are corrected so every locked quantity keeps its
value (lengths within 1 mm, volume within 0.1 %, the AGENTS.md defaults):

* **height** — heights are scaled about the mouth, :math:`z' = z_0 + k (z - z_0)`;
* **maximum diameter** — radii are scaled, :math:`r' = k r`;
* **volume** (lofted, as shown) — the scale factor of the free dimension is found by Brent's method
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
target (the lofted volume when the design has a loft). Achievable volumes lie between the
:math:`n = 1.2` and :math:`n = 12` shapes.

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
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np
import numpy.typing as npt
from scipy.optimize import brentq

from envelopelab.atmosphere import gas_density, gross_lift
from envelopelab.design.model import (
    CrestLoftSpec,
    DesignDocument,
    GoreSpec,
    TaperPoint,
    row_bottom_fraction,
)
from envelopelab.geometry.gore import (
    LENGTH_TOLERANCE,
    CrestLoft,
    GoreLoft,
    GoreWidthModel,
    MeridianProfile,
    PanelRow,
    SeamAllowance,
    crest_offsets_from_bows,
    flat_chord_rows,
    lofted_area,
    lofted_volume,
    split_rows,
)
from envelopelab.geometry.profile_segments import Segment, segment_kinks, segment_points
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

if TYPE_CHECKING:
    from envelopelab.rigging import RiggingOutputs

FloatArray = np.ndarray
Severity = Literal["info", "warning", "error"]

#: Volume tolerance of the constraint locks, relative (AGENTS.md volume/area default).
VOLUME_TOLERANCE = 1e-3
#: Crest loft a design gets when it is switched to flat-chord gores (source: assumed). A
#: 2 % crest offset, tapered from 0 at the mouth to full at mid-tape and 0 at the top
#: opening; a starting point to edit, not a recommendation.
DEFAULT_CREST_LOFT = CrestLoftSpec(
    fraction=0.02,
    taper=[
        TaperPoint(station=0.0, taper=0.0),
        TaperPoint(station=0.5, taper=1.0),
        TaperPoint(station=1.0, taper=0.0),
    ],
)
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


_PROFILE_CACHE: OrderedDict[bytes, MeridianProfile] = OrderedDict()
_PROFILE_CACHE_SIZE = 64


@dataclass(frozen=True)
class SegmentLayout:
    """The segments of a ``profile_interpolation: segments`` design, one per span
    (:mod:`envelopelab.geometry.profile_segments`). Frozen and hashable: it is part of
    the profile cache key, like the interpolation name."""

    segments: tuple[Segment, ...]


#: How a profile runs between its control points: a spline, straight segments, or the
#: design's own segments.
Interpolation = Literal["spline", "linear"] | SegmentLayout


def profile_layout(gores: GoreSpec) -> Interpolation:
    """How a gore design's profile runs between its control points."""
    if gores.profile_interpolation != "segments":
        return gores.profile_interpolation
    assert gores.profile_segments is not None
    return SegmentLayout(tuple(Segment(s.kind, s.bulge, s.smooth) for s in gores.profile_segments))


def profile_from_arrays(
    r: FloatArray, z: FloatArray, interpolation: Interpolation = "spline"
) -> MeridianProfile:
    """Densely sampled profile through control points (m): a spline, straight segments,
    or lines, arcs and curves (:class:`SegmentLayout`).

    The profile is a pure function of the control points, and every live output of the
    editor asks for it, so the most recent profiles are memoized by their control-point
    values. Cached arrays are read-only: a caller that tried to change one in place would
    fail loudly instead of corrupting the cache. A segment layout of only curves is the
    spline, and one of only lines the straight segments, sample for sample.
    """
    r_arr = np.ascontiguousarray(r, dtype=np.float64)
    z_arr = np.ascontiguousarray(z, dtype=np.float64)
    if isinstance(interpolation, SegmentLayout):
        kinds = {s.kind for s in interpolation.segments}
        if kinds == {"curve"}:
            interpolation = "spline"
        elif kinds == {"line"}:
            interpolation = "linear"
    key = repr(interpolation).encode() + b"|" + r_arr.tobytes() + b"|" + z_arr.tobytes()
    hit = _PROFILE_CACHE.get(key)
    if hit is not None:
        _PROFILE_CACHE.move_to_end(key)
        return hit
    if isinstance(interpolation, SegmentLayout):
        profile = MeridianProfile.from_points(
            *segment_points(r_arr, z_arr, interpolation.segments, PROFILE_SAMPLES)
        )
    else:
        profile = MeridianProfile.from_control_points(
            r_arr, z_arr, samples=PROFILE_SAMPLES, interpolation=interpolation
        )
    for arr in (profile.s, profile.r, profile.z):
        arr.setflags(write=False)
    _PROFILE_CACHE[key] = profile
    if len(_PROFILE_CACHE) > _PROFILE_CACHE_SIZE:
        _PROFILE_CACHE.popitem(last=False)
    return profile


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
    assert design.gores is not None
    return profile_from_arrays(r, z, profile_layout(design.gores))


def design_loft(design: DesignDocument) -> GoreLoft | None:
    """Loft of a gore design (lobe-radius ratio along the tape); None for small bulge."""
    if design.gores is None or design.gores.loft is None:
        return None
    return GoreLoft(
        stations=tuple(p.station for p in design.gores.loft),
        ratios=tuple(p.ratio for p in design.gores.loft),
    )


def design_crest_loft(design: DesignDocument) -> CrestLoft | None:
    """Crest loft of a flat-chord gore design; None without one."""
    if design.gores is None or design.gores.crest_loft is None:
        return None
    spec = design.gores.crest_loft
    letters = [r.letter for r in design.gores.panel_rows]
    heights = [r.finished_height for r in design.gores.panel_rows]
    # A row-anchored station is its row's bottom seam (the stored station mirrors it).
    stations = tuple(
        p.station if p.at_row is None else row_bottom_fraction(heights, letters.index(p.at_row))
        for p in spec.taper
    )
    return CrestLoft(
        fraction=spec.fraction, stations=stations, taper=tuple(p.taper for p in spec.taper)
    )


def design_width_model(design: DesignDocument) -> GoreWidthModel:
    """Flat gore width model of a gore design: gore count and loft.

    A flat-chord gore has the flat tape-to-tape chord width at every station (its loft is
    lengthwise, in the seam bows), so its volume is that of the flat-gore polygon.
    """
    if design.gores is None:
        raise ValueError("not a standard-gore design")
    if design.gores.construction == "flat_chord":
        return GoreWidthModel(n_gores=design.gores.count, form="chord")
    return GoreWidthModel.lofted(design.gores.count, design_loft(design))


def design_volume(design: DesignDocument, profile: MeridianProfile | None = None) -> float:
    """Enclosed volume of a gore design with its loft, m^3 (see the module docstring)."""
    profile = profile or design_profile(design)
    return lofted_volume(profile, design_width_model(design))


def default_allowance(design: DesignDocument) -> float:
    """Seam allowance of the first seam type, m (0 without seam types)."""
    return design.seam_types[0].allowance if design.seam_types else 0.0


def row_allowance(design: DesignDocument, patterns: PatternSet, letter: str) -> float:
    """Seam allowance of a row, m (row override or the design default)."""
    override = patterns.row(letter).seam_allowance
    return default_allowance(design) if override is None else override


def row_zone(design: DesignDocument, patterns: PatternSet, letter: str) -> str:
    """Material zone of a row: its pattern annotation, else the design row's zone, else the
    design's first zone."""
    zone = patterns.row(letter).zone
    if zone is not None:
        return zone
    if design.gores is not None:
        for row in design.gores.panel_rows:
            if row.letter == letter and row.zone is not None:
                return row.zone
    return next(iter(design.zones), "default")


def panel_zone_counts(design: DesignDocument, letter: str) -> dict[str, int]:
    """Number of a row's panels cut in another zone (``GoreSpec.panel_zones``), by zone."""
    out: dict[str, int] = {}
    if design.gores is None:
        return out
    for zone in design.gores.panel_zones:
        if zone.row == letter:
            out[zone.zone] = out.get(zone.zone, 0) + len(zone.gores)
    return out


def panel_zone(design: DesignDocument, patterns: PatternSet, letter: str, gore: int) -> str:
    """Material zone of one panel: a panel zone covering it, else :func:`row_zone`."""
    if design.gores is not None:
        for zone in design.gores.panel_zones:
            if zone.row == letter and gore in zone.gores:
                return zone.zone
    return row_zone(design, patterns, letter)


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


@dataclass(frozen=True)
class Equator:
    """The equator of a profile: its widest point, the farthest from the axis.

    Attributes
    ----------
    s : float
        Tape length from the mouth, m.
    r, z : float
        Radius and height, m.
    height_above_mouth : float
        :math:`z - z_{mouth}`, m.
    fraction : float
        ``s`` over the tape length, dimensionless (0 at the mouth, 1 at the top opening).
    """

    s: float
    r: float
    z: float
    height_above_mouth: float
    fraction: float


def profile_equator(profile: MeridianProfile) -> Equator:
    r"""The widest point of a densely sampled profile, :math:`\arg\max_s r(s)`.

    A parabola through the largest sample and its two neighbours refines the position
    between samples (exact for a smooth maximum to the sampling's third order). Where
    the profile has a straight vertical stretch at the widest radius (a cylinder), the
    middle of that stretch is returned.
    """
    r = np.asarray(profile.r)
    k = int(np.argmax(r))
    top = float(r[k])
    lo, hi = k, k  # the contiguous stretch at the widest radius (a cylinder)
    while lo > 0 and r[lo - 1] >= top - 1e-9:
        lo -= 1
    while hi < r.size - 1 and r[hi + 1] >= top - 1e-9:
        hi += 1
    s = 0.5 * float(profile.s[lo] + profile.s[hi])
    if lo == hi and 0 < k < r.size - 1:
        s0, s1, s2 = profile.s[k - 1 : k + 2]
        r0, r1, r2 = r[k - 1 : k + 2]
        # Vertex of the parabola through three (s, r) points.
        den = (s0 - s1) * (s0 - s2) * (s1 - s2)
        a = (s2 * (r1 - r0) + s1 * (r0 - r2) + s0 * (r2 - r1)) / den
        b = (s2**2 * (r0 - r1) + s1**2 * (r2 - r0) + s0**2 * (r1 - r2)) / den
        if a < 0.0:
            s = float(np.clip(-b / (2.0 * a), s0, s2))
    radius = float(profile.radius_at(s))
    height = float(profile.height_at(s))
    return Equator(
        s=s,
        r=max(radius, top),
        z=height,
        height_above_mouth=height - float(profile.z[0]),
        fraction=s / profile.meridian_length,
    )


def seam_fractions(design: DesignDocument) -> list[float]:
    """Where the row seams lie along the tape, as fractions of the rows' total height
    (0 = the mouth, 1 = the top opening), mouth first: one more than there are rows."""
    assert design.gores is not None
    heights = np.array([row.finished_height for row in design.gores.panel_rows])
    cumulative = np.concatenate(([0.0], np.cumsum(heights)))
    return [float(v) for v in cumulative / cumulative[-1]]


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
    if design.gores.construction == "flat_chord":
        return _flat_chord_panel_rows(design, patterns, profile)
    width = design_width_model(design)
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


def _row_heights(design: DesignDocument, profile: MeridianProfile) -> list[float]:
    assert design.gores is not None
    heights = [spec.finished_height for spec in design.gores.panel_rows]
    heights[-1] = profile.meridian_length - sum(heights[:-1])  # absorb the rounding
    return heights


def design_seam_bows(
    design: DesignDocument, profile: MeridianProfile | None = None
) -> list[tuple[float, float]]:
    """Seam bows a flat-chord design cuts, per row (bottom, top), m, positive outward.

    The measured bows of the rows, else the bows of the crest loft, else straight seams
    (0). A lobe design has straight seams.
    """
    assert design.gores is not None
    specs = design.gores.panel_rows
    if design.gores.construction != "flat_chord":
        return [(0.0, 0.0)] * len(specs)
    crest = design_crest_loft(design)
    if crest is not None:
        profile = profile or design_profile(design)
        all_rows = flat_chord_rows(
            profile,
            design.gores.count,
            _row_heights(design, profile),
            [s.letter for s in specs],
            crest=crest,
        )
        return [(r.bottom_bow, r.top_bow) for r in all_rows]
    if all(s.bow_bottom is not None and s.bow_top is not None for s in specs):
        return [(float(s.bow_bottom or 0.0), float(s.bow_top or 0.0)) for s in specs]
    return [(0.0, 0.0)] * len(specs)


def design_crest_offset(
    design: DesignDocument, s: npt.ArrayLike, profile: MeridianProfile | None = None
) -> FloatArray:
    r"""Crest offset of a flat-chord design along the tape, m (0 for lobe gores).

    The crest is the middle of the fabric between two tapes. With a crest loft it stands
    :math:`\delta(s) = \lambda\tau(f)r(s)` outside the flat chord. With measured seam
    bows the offset at each row boundary follows from the bows
    (:func:`~envelopelab.geometry.gore.crest_offsets_from_bows`) and is interpolated
    linearly between boundaries, 0 at the mouth and the top opening. With straight seams
    it is 0.

    Parameters
    ----------
    design : DesignDocument
        Gore design.
    s : array_like
        Tape lengths from the mouth, m.
    profile : MeridianProfile, optional
        The design's profile (computed when not given).

    Returns
    -------
    ndarray
        Offset normal to the tape, m, positive outward.
    """
    s_arr = np.asarray(s, dtype=np.float64)
    gores = design.gores
    if gores is None or gores.construction != "flat_chord":
        return np.zeros_like(s_arr)
    profile = profile or design_profile(design)
    crest = design_crest_loft(design)
    if crest is not None:
        offset = crest.offset(s_arr / profile.meridian_length, profile.radius_at(s_arr))
        return np.asarray(offset, dtype=np.float64)
    bows = design_seam_bows(design, profile)
    if not any(b or t for b, t in bows):
        return np.zeros_like(s_arr)
    heights = _row_heights(design, profile)
    boundaries = np.concatenate(([0.0], np.cumsum(heights)))
    delta = crest_offsets_from_bows(profile, boundaries, bows)
    return np.asarray(np.interp(s_arr, boundaries, delta), dtype=np.float64)


def _flat_chord_panel_rows(
    design: DesignDocument, patterns: PatternSet, profile: MeridianProfile
) -> list[PanelRow]:
    """Panel rows of a flat-chord gore design (seam bows measured or from the crest loft)."""
    assert design.gores is not None
    specs = design.gores.panel_rows
    heights = _row_heights(design, profile)
    bows = design_seam_bows(design, profile)
    rows: list[PanelRow] = []
    start = 0.0
    for spec, height, bow in zip(specs, heights, bows, strict=True):
        a = row_allowance(design, patterns, spec.letter)
        rows += flat_chord_rows(
            profile,
            design.gores.count,
            [height],
            labels=[spec.letter],
            bows=[bow],
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
        Enclosed volume of the lofted envelope, m^3.
    area : float
        Fabric area of the lofted envelope (N flat finished gores), m^2.
    ambient_density, internal_density : float
        kg/m^3.
    gross_lift : float
        N.
    mass : MassEstimate, optional
        Envelope mass estimate (None when the panel rows are invalid).
    envelope_mass : float, optional
        kg.
    lift_margin : float, optional
        Spare liftable mass after envelope, parachute and rigging, and payload, kg.
    sources : tuple of str
        Source tags of the material values in the mass estimate.
    findings : list of DesignFinding
        Why an output is missing, and design warnings.
    rigging : RiggingOutputs, optional
        Parachute, red line, flying wires and turning vents (None when the profile has
        no valid rigging evaluation).
    rigging_mass : float, optional
        Parachute and rigging mass, kg.
    equator : Equator, optional
        Widest point of the profile (:func:`profile_equator`).
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
    rigging: RiggingOutputs | None = None
    rigging_mass: float | None = None
    equator: Equator | None = None


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
    width_model = design_width_model(design)
    volume = lofted_volume(profile, width_model)
    op = design.operating
    findings: list[DesignFinding] = []
    rho_a = gas_density(op.ambient_pressure, op.ambient_temperature)
    rho_i = gas_density(op.ambient_pressure, op.internal_temperature)
    lift = gross_lift(volume, rho_a, rho_i)
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
        extra = [panel_zone_counts(design, r.label) for r in rows]
        for z in {z for e in extra for z in e} - set(areal):
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
            panel_zones=extra,
        )
    from envelopelab.rigging import rigging_outputs

    rigging = rigging_outputs(design, patterns, fabrics, profile)
    if mass is not None:
        margin = lift_margin(
            volume, rho_a, rho_i, mass.total_mass + rigging.total_mass, op.payload_mass
        ).margin
    return GoreOutputs(
        meridian_length=profile.meridian_length,
        height=profile.height,
        max_diameter=profile.max_width,
        volume=volume,
        area=lofted_area(profile, width_model),
        ambient_density=rho_a,
        internal_density=rho_i,
        gross_lift=lift,
        mass=mass,
        envelope_mass=None if mass is None else mass.total_mass,
        lift_margin=margin,
        sources=() if mass is None else tuple(sorted({*mass.sources, *rigging.sources})),
        findings=findings,
        rigging=rigging,
        rigging_mass=rigging.total_mass,
        equator=profile_equator(profile),
    )


def rigging_findings(
    design: DesignDocument,
    patterns: PatternSet,
    fabrics: FabricLibraryRepository | FabricCatalog | None = None,
) -> list[DesignFinding]:
    """Parachute, red-line, flying-wire and turning-vent findings (FoS failures are errors)."""
    from envelopelab.rigging import rigging_outputs

    try:
        found = rigging_outputs(design, patterns, fabrics).findings
    except ValueError as exc:
        return [DesignFinding("rigging", "error", f"rigging not evaluated: {exc}", "rigging")]
    return [DesignFinding(f.code, f.severity, f.message, f.target) for f in found]


def design_findings(design: DesignDocument, patterns: PatternSet) -> list[DesignFinding]:
    """Validation findings of a gore design (profile, rows, openings, zones, rigging)."""
    out: list[DesignFinding] = []
    if design.gores is None:
        out += rigging_findings(design, patterns)
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
    layout = profile_layout(g)
    if isinstance(layout, SegmentLayout):
        z_points = control_arrays(design)[1]
        for k, turn in segment_kinks(r, z_points, layout.segments):
            out.append(
                DesignFinding(
                    "profile_kink",
                    "warning",
                    f"control point {k + 1}: the joint is set smooth but the profile turns "
                    f"{math.degrees(turn):.1f} degrees there (two lines, or an arc tangent "
                    "on its other side)",
                    "profile",
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
    for spec in g.panel_rows:
        if spec.zone is not None and spec.zone not in design.zones:
            out.append(
                DesignFinding(
                    "zone",
                    "error",
                    f"row {spec.letter}: zone {spec.zone!r} is not defined",
                    spec.letter,
                )
            )
    for letter, row in patterns.rows.items():
        if row.zone is not None and row.zone not in design.zones:
            out.append(
                DesignFinding(
                    "zone", "error", f"row {letter}: zone {row.zone!r} is not defined", letter
                )
            )
    for panels in g.panel_zones:
        if panels.zone not in design.zones:
            out.append(
                DesignFinding(
                    "zone",
                    "error",
                    f"panel zone {panels.name}: zone {panels.zone!r} is not defined",
                    panels.row,
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
    out += rigging_findings(design, patterns)
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


def _volume(
    r: FloatArray, z: FloatArray, width_model: GoreWidthModel | None, interpolation: Interpolation
) -> float:
    profile = profile_from_arrays(r, z, interpolation)
    return profile.volume if width_model is None else lofted_volume(profile, width_model)


def _hold(
    r: FloatArray,
    z: FloatArray,
    target: float,
    which: Literal["height", "diameter"],
    interpolation: Interpolation,
) -> tuple[FloatArray, FloatArray]:
    for _ in range(20):
        profile = profile_from_arrays(r, z, interpolation)
        value = profile.height if which == "height" else profile.max_width
        if value <= 0.0:
            raise LockError(f"the profile has no {which}; it cannot hold the lock")
        if abs(value - target) <= 0.1 * LENGTH_TOLERANCE:
            return r, z
        k = target / value
        r, z = _scaled_z(r, z, k) if which == "height" else _scaled_r(r, z, k)
    raise LockError(f"could not hold the locked {which} of {target:.4f} m")


def _pin_openings(r: FloatArray, locks: ConstraintLocks) -> FloatArray:
    """Set the end radii to the locked mouth and top-hole diameters, m."""
    if locks.mouth_diameter is None and locks.top_diameter is None:
        return r
    r = r.copy()
    if locks.mouth_diameter is not None:
        r[0] = 0.5 * locks.mouth_diameter
    if locks.top_diameter is not None:
        r[-1] = 0.5 * locks.top_diameter
    return r


def _hold_lengths(
    r: FloatArray, z: FloatArray, locks: ConstraintLocks, interpolation: Interpolation
) -> tuple[FloatArray, FloatArray]:
    # The maximum-diameter hold scales every radius, the end radii too; alternate it with
    # pinning the ends (the maximum lies inside the profile, so this converges).
    for _ in range(20):
        if locks.height is not None:
            r, z = _hold(r, z, locks.height, "height", interpolation)
        if locks.max_diameter is not None:
            r, z = _hold(r, z, locks.max_diameter, "diameter", interpolation)
        r = _pin_openings(r, locks)
        profile = profile_from_arrays(r, z, interpolation)
        ok_h = locks.height is None or abs(profile.height - locks.height) <= LENGTH_TOLERANCE
        ok_d = (
            locks.max_diameter is None
            or abs(profile.max_width - locks.max_diameter) <= LENGTH_TOLERANCE
        )
        if ok_h and ok_d:
            return r, z
    raise LockError("the height, diameter and opening locks could not all be held")


def apply_locks(
    r: FloatArray,
    z: FloatArray,
    locks: ConstraintLocks,
    width_model: GoreWidthModel | None = None,
    interpolation: Interpolation = "spline",
) -> tuple[FloatArray, FloatArray]:
    """Correct edited control points so every locked quantity keeps its value.

    Parameters
    ----------
    r, z : ndarray
        Edited control-point radii and heights, m.
    locks : ConstraintLocks
        Locked height (m), volume (m^3), maximum diameter (m), and mouth and top-hole
        diameters (m; the end control points' radii are set to half of them).
    width_model : GoreWidthModel, optional
        Gore count and loft of the design: the locked volume is the lofted volume
        (:func:`~envelopelab.geometry.gore.lofted_volume`); default the surface of
        revolution through the tapes.
    interpolation : {"spline", "linear"} or SegmentLayout
        How the profile runs between control points (:func:`profile_layout`);
        the locked lengths and volume are those of this profile.

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
    r, z = _hold_lengths(r, z, locks, interpolation)
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
        rr, zz = _hold_lengths(*transform(r, z, k), locks, interpolation)
        return _volume(rr, zz, width_model, interpolation) / target - 1.0

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
    r, z = _hold_lengths(*transform(r, z, k), locks, interpolation)
    volume = _volume(r, z, width_model, interpolation)
    if abs(volume / target - 1.0) > VOLUME_TOLERANCE:
        raise LockError(f"volume lock missed: {volume:.2f} vs {target:.2f} m^3")
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
    volume = lofted_volume(profile, design_width_model(design))
    if locks.volume is not None and abs(volume / locks.volume - 1.0) > VOLUME_TOLERANCE:
        out.append(f"volume {volume:.2f} m^3, locked {locks.volume:.2f} m^3")
    if locks.gore_count is not None and design.gores.count != locks.gore_count:
        out.append(f"gore count {design.gores.count}, locked {locks.gore_count}")
    r, _ = control_arrays(design)
    for name, label, radius in (
        ("mouth_diameter", "mouth diameter", r[0]),
        ("top_diameter", "top hole diameter", r[-1]),
    ):
        locked = getattr(locks, name)
        if locked is not None and abs(2.0 * radius - locked) > LENGTH_TOLERANCE:
            out.append(f"{label} {2.0 * radius:.4f} m, locked {locked:.4f} m")
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
        "top": row.top_seam_length,
        "bottom": row.bottom_seam_length,
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
    width_model: GoreWidthModel | None = None,
    interpolation: Interpolation = "spline",
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
    width_model : GoreWidthModel, optional
        Gore count and loft: the target is then the lofted volume; default the surface of
        revolution through the tapes.
    interpolation : {"spline", "linear"}
        How the design's profile runs between the control points.

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
        return _hold_lengths(r, z, locks, interpolation)

    def residual(n: float) -> float:
        return _volume(*shape(n), width_model, interpolation) - target_volume

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
    mouth_fabric_id: str | None = None,
    mouth_row_height: float | None = None,
    loft: GoreLoft | None = None,
    construction: Literal["lobe", "flat_chord"] = "lobe",
    interpolation: Interpolation = "spline",
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
        Gores N (>= 3) and horizontal body panel rows (>= 1); with a mouth fabric the
        design has ``row_count + 1`` rows.
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
    mouth_fabric_id : str, optional
        Fabric of a separate mouth row (zone ``mouth``), e.g. ``nomex`` next to the burner;
        the body rows and the parachute use ``fabric_id``.
    mouth_row_height : float, optional
        Finished height of the mouth row along the tape, m; default the same as each
        body row.
    loft : GoreLoft, optional
        Lobe-radius ratio along the gore (dimensionless); default none (small bulge). The
        target volume is the lofted volume.
    construction : {"lobe", "flat_chord"}
        Gore construction. Flat-chord gores get :data:`DEFAULT_CREST_LOFT` and no lobe loft;
        the target volume is then the flat-chord polygon's.
    interpolation : {"spline", "linear"}
        Profile between control points: spline or straight tape segments.

    Returns
    -------
    DesignDocument
        Schema-valid design with its content hash.
    """
    from envelopelab.project.templates import new_design

    if construction == "flat_chord" and loft is not None:
        raise ValueError("a flat-chord gore is lofted by a crest loft, not a lobe loft")
    width_model = (
        GoreWidthModel(n_gores=gore_count, form="chord")
        if construction == "flat_chord"
        else GoreWidthModel.lofted(gore_count, loft)
    )

    mouth = mouth_diameter if mouth_diameter is not None else 0.3 * target_width
    top = top_diameter if top_diameter is not None else 0.25 * target_width
    r, z = wizard_control_points(
        target_volume,
        target_height,
        target_width,
        mouth,
        top,
        width_model=width_model,
        interpolation=interpolation,
    )
    length = profile_from_arrays(r, z, interpolation).meridian_length
    row_zones: list[str | None] | None = None
    if mouth_fabric_id is None:
        heights = equal_row_heights(length, row_count)
    elif mouth_row_height is None:
        heights = equal_row_heights(length, row_count + 1)
        row_zones = ["mouth"] + [None] * row_count
    else:
        if not 0.0 < mouth_row_height < length:
            raise ValueError(
                f"mouth row height {mouth_row_height:g} m must be between 0 and the "
                f"meridian length {length:.3f} m"
            )
        heights = [mouth_row_height, *equal_row_heights(length - mouth_row_height, row_count)]
        heights[-1] = length - sum(heights[:-1])
        row_zones = ["mouth"] + [None] * row_count
    document = new_design(
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
        row_zones=row_zones,
        extra_zones=None if mouth_fabric_id is None else {"mouth": mouth_fabric_id},
        loft=loft,
    )
    if construction == "lobe" and interpolation == "spline":
        return document
    data = document.model_dump(by_alias=True, mode="json")
    data["gores"]["construction"] = construction
    data["gores"]["profile_interpolation"] = interpolation
    if construction == "flat_chord":
        data["gores"]["crest_loft"] = DEFAULT_CREST_LOFT.model_dump(mode="json")
    return DesignDocument.model_validate(data).with_updated_hash()


def rows_zones_mapping(design: DesignDocument, patterns: PatternSet) -> Mapping[str, str]:
    """Zone of every design row."""
    assert design.gores is not None
    return {r.letter: row_zone(design, patterns, r.letter) for r in design.gores.panel_rows}


# --------------------------------------------------------------------------------------
# Display surface
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DisplaySurface:
    r"""Envelope surface for display, with its gores, panel rows and seams (m).

    The lofted envelope is tessellated so that every vertical seam (gore boundary) and
    every horizontal seam (row boundary) is a mesh line. Between adjacent tapes each
    horizontal section is the design's fabric lobe, a circular arc of radius
    :math:`\rho = k r` (:func:`lobe_ring`); without a loft (:math:`k = 1`) that is the
    surface of revolution through the tapes. A flat-chord gore is the flat chord between
    the tapes with its crest raised by the crest offset :math:`\delta(s)`
    (:func:`design_crest_offset`), normal to the tape, as a parabola across the gore,
    :math:`\delta(1 - u^2)` (:func:`crest_section`); this is the shape as cut, the
    inflated shape is a solver result.

    Attributes
    ----------
    points : ndarray, shape (n, 3)
        m.
    faces : ndarray of int, shape (m, 3)
        Triangles.
    face_gore : ndarray of int, shape (m,)
        Gore number (1..N) of each triangle; gore k lies between seams k-1 and k.
    face_row : ndarray of int, shape (m,)
        Index of the panel row (mouth first) of each triangle.
    vertical_seams : list of ndarray
        One meridian polyline per vertical seam (load tape), shape (k, 3).
    horizontal_seams : list of ndarray
        One closed ring per row boundary (mouth and top opening included), shape (k, 3).
    row_letters : list of str
        Row letters, mouth first.
    """

    points: FloatArray
    faces: np.ndarray
    face_gore: np.ndarray
    face_row: np.ndarray
    vertical_seams: list[FloatArray]
    horizontal_seams: list[FloatArray]
    row_letters: list[str]


def lobe_ring(radius: float, ratio: float, n_gores: int, per_gore: int) -> FloatArray:
    r"""Horizontal section of a lofted envelope: N circular lobes between the tapes (m).

    Gore :math:`g` lies between the tapes at angles :math:`2\pi g/N` and
    :math:`2\pi (g+1)/N`. Its lobe is the arc of radius :math:`\rho = k r` through both
    tapes, bulging outward; at arc angle :math:`t \in [-\theta, \theta]`,
    :math:`\theta = \arcsin(\sin(\pi/N)/k)`, the point lies at

    .. math:: a = r\cos\frac{\pi}{N} - \rho\cos\theta + \rho\cos t, \qquad
              b = \rho \sin t

    along and across the gore's bisector. For :math:`k = 1` this is the circle of radius r.

    Parameters
    ----------
    radius : float
        Tape radius r, m.
    ratio : float
        Lobe-radius ratio k, dimensionless (>= sin(π/N)); ``inf`` for a flat chord.
    n_gores : int
        Gores N.
    per_gore : int
        Points per gore (the first is on the gore's left tape).

    Returns
    -------
    ndarray, shape (N * per_gore, 2)
        x, y, m, counter-clockwise from the tape at angle 0.
    """
    sin_n, cos_n = math.sin(math.pi / n_gores), math.cos(math.pi / n_gores)
    u = -1.0 + 2.0 * np.arange(per_gore) / per_gore
    if math.isinf(ratio):
        # Flat chord (flat-chord gores): straight from tape to tape.
        a = np.full(per_gore, radius * cos_n)
        b = radius * sin_n * u
    else:
        theta = math.asin(min(sin_n / ratio, 1.0))
        rho = ratio * radius
        t = theta * u
        a = radius * cos_n - rho * math.cos(theta) + rho * np.cos(t)
        b = rho * np.sin(t)
    out = []
    for g in range(n_gores):
        phi = 2.0 * math.pi * (g + 0.5) / n_gores
        c, s = math.cos(phi), math.sin(phi)
        out.append(np.column_stack((a * c - b * s, a * s + b * c)))
    return np.vstack(out)


def _outward_normals(profile: MeridianProfile, s: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Outward unit normal of the meridian (radial, axial components) at tape lengths s."""
    h = 1e-4 * profile.meridian_length
    lo = np.clip(s - h, 0.0, profile.meridian_length)
    hi = np.clip(s + h, 0.0, profile.meridian_length)
    dr = profile.radius_at(hi) - profile.radius_at(lo)
    dz = profile.height_at(hi) - profile.height_at(lo)
    norm = np.hypot(dr, dz)
    norm[norm == 0.0] = 1.0
    return dz / norm, -dr / norm


def crest_section(
    radius: float,
    offset: float,
    normal: tuple[float, float],
    n_gores: int,
    per_gore: int,
) -> tuple[FloatArray, FloatArray]:
    r"""Horizontal section of flat-chord gores with a raised crest, m.

    Each gore is the flat chord between its tapes (:func:`lobe_ring` with
    :math:`k = \infty`), moved by :math:`\delta(1 - u^2)` along the outward normal of the
    meridian, :math:`u \in [-1, 1]` across the gore (0 at its middle). The tapes stay on
    the profile and the crest stands :math:`\delta` out, the parabola the seam bows are
    cut as.

    Parameters
    ----------
    radius : float
        Tape radius r, m.
    offset : float
        Crest offset :math:`\delta`, m.
    normal : (float, float)
        Outward meridian normal (radial, axial), unit length.
    n_gores : int
        Gores N.
    per_gore : int
        Points per gore (the first is on the gore's left tape).

    Returns
    -------
    (ndarray, ndarray)
        x, y, shape (N * per_gore, 2), and the height change of each point, m.
    """
    xy = lobe_ring(radius, math.inf, n_gores, per_gore)
    u = -1.0 + 2.0 * np.arange(per_gore) / per_gore
    bump = np.tile(offset * (1.0 - u**2), n_gores)
    phi = 2.0 * math.pi * (np.repeat(np.arange(n_gores), per_gore) + 0.5) / n_gores
    xy = xy + np.column_stack((np.cos(phi), np.sin(phi))) * (bump * normal[0])[:, None]
    return xy, bump * normal[1]


def display_points(
    design: DesignDocument,
    s: npt.ArrayLike,
    theta: npt.ArrayLike,
    profile: MeridianProfile | None = None,
) -> FloatArray:
    r"""Points of the display surface (:func:`display_surface`) at tape lengths and
    azimuths, m.

    Gore :math:`g` (1..N) spans the azimuths :math:`2\pi(g-1)/N` to :math:`2\pi g/N`; a
    point's position across it, :math:`u \in [-1, 1]`, gives its place on the lobe arc or,
    for flat-chord gores, on the flat chord with the raised crest
    (:func:`lobe_ring`, :func:`crest_section`).

    Parameters
    ----------
    design : DesignDocument
        Gore design.
    s : array_like
        Tape lengths from the mouth, m.
    theta : array_like
        Azimuths, rad (gore 1 starts at 0).
    profile : MeridianProfile, optional
        The design's profile (computed when not given).

    Returns
    -------
    ndarray, shape (n, 3)
        x, y, z, m.
    """
    assert design.gores is not None
    profile = profile or design_profile(design)
    s_arr, th = np.broadcast_arrays(
        np.asarray(s, dtype=np.float64).ravel(), np.asarray(theta, dtype=np.float64).ravel()
    )
    n = design.gores.count
    gore_angle = 2.0 * math.pi / n
    index = np.floor(np.mod(th, 2.0 * math.pi) / gore_angle)
    u = 2.0 * (np.mod(th, 2.0 * math.pi) / gore_angle - index) - 1.0
    r, z = profile.radius_at(s_arr), profile.height_at(s_arr)
    sin_n, cos_n = math.sin(math.pi / n), math.cos(math.pi / n)
    if design.gores.construction == "flat_chord":
        a = r * cos_n
        b = r * sin_n * u
        bump = design_crest_offset(design, s_arr, profile) * (1.0 - u**2)
        nr, nz = _outward_normals(profile, s_arr)
        a = a + bump * nr
        z = z + bump * nz
    else:
        k = np.asarray(
            design_width_model(design).lobe_ratio(r, s_arr / profile.meridian_length),
            dtype=np.float64,
        )
        a, b = np.empty_like(r), np.empty_like(r)
        for i, (ri, ki, ui) in enumerate(zip(r, k, u, strict=True)):
            theta_i = math.asin(min(sin_n / ki, 1.0)) if math.isfinite(ki) else 0.0
            if theta_i == 0.0:
                a[i], b[i] = ri * cos_n, ri * sin_n * ui
            else:
                rho = ki * ri
                t_i = theta_i * ui
                a[i] = ri * cos_n - rho * math.cos(theta_i) + rho * math.cos(t_i)
                b[i] = rho * math.sin(t_i)
    phi = (index + 0.5) * gore_angle
    c, s_ = np.cos(phi), np.sin(phi)
    return np.column_stack((a * c - b * s_, a * s_ + b * c, z))


def panel_to_display(
    design: DesignDocument,
    row: PanelRow,
    gore: int,
    xy: npt.ArrayLike,
    profile: MeridianProfile | None = None,
) -> FloatArray:
    """Points given in a panel's pattern coordinates, on the display surface, m.

    A point's height between the panel's finished bottom and top seam lines (bows
    included) gives its tape length between the row's seams; its distance from the
    centreline over the panel's half width at that height gives its place across the gore.

    Parameters
    ----------
    design : DesignDocument
        Gore design.
    row : PanelRow
        The panel's row (:func:`panel_rows`).
    gore : int
        Gore number, 1..N.
    xy : array_like, shape (n, 2)
        Points in panel coordinates (x across from the centreline, y up from the bottom
        corners), m.
    profile : MeridianProfile, optional
        The design's profile (computed when not given).

    Returns
    -------
    ndarray, shape (n, 3)
        m.
    """
    assert design.gores is not None
    pts = np.atleast_2d(np.asarray(xy, dtype=np.float64))
    edge = row.right_edge
    y0, y1 = float(edge[0, 1]), float(edge[-1, 1])
    w0, w1 = max(float(edge[0, 0]), 1e-9), max(float(edge[-1, 0]), 1e-9)
    x, y = pts[:, 0], pts[:, 1]
    bottom = y0 - row.bottom_bow * (1.0 - np.clip(x / w0, -1.0, 1.0) ** 2)
    top = y1 + row.top_bow * (1.0 - np.clip(x / w1, -1.0, 1.0) ** 2)
    f = np.clip((y - bottom) / np.maximum(top - bottom, 1e-9), 0.0, 1.0)
    s = row.s_bottom + f * (row.s_top - row.s_bottom)
    half = np.interp(np.clip(y, y0, y1), edge[:, 1], edge[:, 0])
    u = np.clip(x / np.maximum(half, 1e-9), -1.0, 1.0)
    gore_angle = 2.0 * math.pi / design.gores.count
    # Just inside the gore at its edges, so that a point on a tape stays in this gore.
    theta = (gore - 0.5 + 0.5 * u * (1.0 - 1e-9)) * gore_angle
    return display_points(design, s, theta, profile)


def envelope_marks(
    design: DesignDocument,
    patterns: PatternSet,
    rows: Sequence[PanelRow] | None = None,
    per_seam: int = 24,
) -> dict[str, list[FloatArray]]:
    """Polylines of the design's panel-level details on the display surface, m.

    Keys (present only when the design has some): ``panel_zones`` (outline of every panel
    in a panel zone), ``tape_paths`` and ``feature_locations`` (the pattern annotations of
    each row, on every panel of the row, since a row is cut once per gore).
    """
    assert design.gores is not None
    profile = design_profile(design)
    rows = list(rows) if rows is not None else panel_rows(design, patterns)
    by_letter = {r.label: r for r in rows}
    n = design.gores.count
    gore_angle = 2.0 * math.pi / n
    out: dict[str, list[FloatArray]] = {}
    outlines: list[FloatArray] = []
    for zone in design.gores.panel_zones:
        row = by_letter.get(zone.row)
        if row is None:
            continue
        for gore in zone.gores:
            t0 = (gore - 1) * gore_angle * (1.0 + 1e-12)
            t1 = gore * gore_angle * (1.0 - 1e-12)
            across = np.linspace(t0, t1, per_seam)
            along = np.linspace(row.s_bottom, row.s_top, per_seam)
            s = np.concatenate(
                (np.full(per_seam, row.s_bottom), along, np.full(per_seam, row.s_top), along[::-1])
            )
            th = np.concatenate(
                (across, np.full(per_seam, t1), across[::-1], np.full(per_seam, t0))
            )
            outlines.append(display_points(design, s, th, profile))
    if outlines:
        out["panel_zones"] = outlines
    tapes: list[FloatArray] = []
    circles: list[FloatArray] = []
    ring = np.linspace(0.0, 2.0 * math.pi, 33)
    for letter, ann in patterns.rows.items():
        row = by_letter.get(letter)
        if row is None:
            continue
        for gore in range(1, n + 1):
            for tape in ann.tape_paths:
                pts = np.asarray(tape.points, dtype=np.float64)
                dense = np.vstack(
                    [
                        np.linspace(a, b, 8, endpoint=False)
                        for a, b in zip(pts[:-1], pts[1:], strict=True)
                    ]
                    + [pts[-1:]]
                )
                tapes.append(panel_to_display(design, row, gore, dense, profile))
            for feat in ann.feature_locations:
                xy = np.column_stack(
                    (feat.x + feat.radius * np.cos(ring), feat.y + feat.radius * np.sin(ring))
                )
                circles.append(panel_to_display(design, row, gore, xy, profile))
    if tapes:
        out["tape_paths"] = tapes
    if circles:
        out["feature_locations"] = circles
    return out


def display_surface(design: DesignDocument, per_gore: int = 6, per_row: int = 8) -> DisplaySurface:
    """Display tessellation of a gore design (see :class:`DisplaySurface`).

    Parameters
    ----------
    design : DesignDocument
        Gore design; row heights along the tape in m.
    per_gore : int
        Segments across each gore.
    per_row : int
        Segments along the tape in each row.

    Returns
    -------
    DisplaySurface
        Points in m. Rows that do not reach the top (rows not fitted) end where they end.
    """
    assert design.gores is not None
    profile = design_profile(design)
    n = design.gores.count
    length = profile.meridian_length
    bounds = [0.0]
    for row in design.gores.panel_rows:
        bounds.append(min(bounds[-1] + row.finished_height, length))
    stations = [0.0]
    s_row: list[int] = []
    for i, (s0, s1) in enumerate(zip(bounds[:-1], bounds[1:], strict=True)):
        if s1 > s0:
            stations += list(np.linspace(s0, s1, per_row + 1)[1:])
            s_row += [i] * per_row
    s = np.array(stations)
    r, z = profile.radius_at(s), profile.height_at(s)
    width_model = design_width_model(design)
    m = n * per_gore
    flat = design.gores.construction == "flat_chord"

    def section(s_at: FloatArray, r_at: FloatArray, count: int) -> tuple[FloatArray, FloatArray]:
        """x, y and height change of the sections at tape lengths s_at."""
        if not flat:
            k = width_model.lobe_ratio(r_at, s_at / length)
            xy = [lobe_ring(float(a), float(b), n, count) for a, b in zip(r_at, k, strict=True)]
            return np.vstack(xy), np.zeros(len(s_at) * n * count)
        delta = design_crest_offset(design, s_at, profile)
        nr, nz = _outward_normals(profile, s_at)
        parts = [
            crest_section(float(a), float(d), (float(c), float(e)), n, count)
            for a, d, c, e in zip(r_at, delta, nr, nz, strict=True)
        ]
        return np.vstack([p[0] for p in parts]), np.concatenate([p[1] for p in parts])

    xy, dz = section(s, r, per_gore)
    pts = np.column_stack((xy, np.repeat(z, m) + dz))
    faces, gores, rows = [], [], []
    for i in range(len(s) - 1):
        for j in range(m):
            a = i * m + j
            b = i * m + (j + 1) % m
            faces += [[a, b, b + m], [a, b + m, a + m]]
            gores += [j // per_gore + 1] * 2
            rows += [s_row[i]] * 2
    seams_h = []
    for bound in dict.fromkeys(bounds):
        sb = np.array([bound])
        ring, ring_dz = section(sb, profile.radius_at(sb), 4 * per_gore)
        z_ring = float(profile.height_at(bound)) + ring_dz
        seam = np.column_stack((ring, z_ring))
        seams_h.append(np.vstack((seam, seam[:1])))
    dense = np.linspace(0.0, bounds[-1], 200)
    rd, zd = profile.radius_at(dense), profile.height_at(dense)
    seams_v = [
        np.column_stack((rd * math.cos(a), rd * math.sin(a), zd))
        for a in 2.0 * np.pi * np.arange(n) / n
    ]
    return DisplaySurface(
        points=pts,
        faces=np.array(faces, dtype=np.int64),
        face_gore=np.array(gores, dtype=np.int64),
        face_row=np.array(rows, dtype=np.int64),
        vertical_seams=seams_v,
        horizontal_seams=seams_h,
        row_letters=[row.letter for row in design.gores.panel_rows],
    )
