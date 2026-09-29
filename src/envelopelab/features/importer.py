r"""Feature geometry from an imported build pack.

Turns a :class:`~envelopelab.features.spec.FeatureSpec` and the imported build pack
(:class:`~envelopelab.assembly.pipeline.BuildPackResult`) into an
:class:`~envelopelab.features.builder.AppendageSpec` or
:class:`~envelopelab.features.tube.TubeSpec`. Nothing here knows any particular design:
pieces, instances, openings, rows and gores are all named by the YAML file.

Placement chart
---------------
A feature placed on gores :math:`g_0..g_1` and rows :math:`r_0..r_1` of a ring of
:math:`G` gores uses the host chart of :mod:`envelopelab.features.builder` with its origin
at the middle of the span: :math:`v = 0` half way up rows :math:`r_0..r_1` (finished row
heights from the pieces) and :math:`\theta = 0` half way across the gores. A point of
panel instance ``ring/row@g`` with local coordinates :math:`(x, y)` maps to

.. math:: \tau = \frac{x - x_l(y)}{x_r(y) - x_l(y)}, \qquad
          \theta = \frac{2\pi}{G}\left(g - g_c + \tau - \tfrac12\right), \qquad
          u = \rho(v)\,\theta

(:math:`g_c` the centre of the span, :math:`x_l, x_r` the panel's finished side edges at
height :math:`y`, :math:`\rho(v)` the host hoop radius), the frame of
:mod:`envelopelab.assembly.initial_shape`. A footprint drawn as its own piece is placed
with its bounding-box centre at the chart origin (the piece's :math:`y` along the
meridian, :math:`x` across the gores; mirrored when ``host.mirror``) and its height is
checked against the row span.

Host surface
------------
The local host (:class:`~envelopelab.features.builder.HostSurface`) is fitted to the
node positions of the host instances: a least-squares circle through their
:math:`(\rho, z)` about the ring axis gives :math:`R_1`, the normal elevation and the
height of the chart origin; :math:`R_2 = \rho_0 / \cos\beta`. By default the positions are
the rest model's as-sewn initial shape (a geometric guess, labelled so); pass a solved
shape when one is available.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from envelopelab.features.builder import (
    AppendageSpec,
    ChartHole,
    FeatureBuildError,
    HostSurface,
    HostTape,
    PressureSpec,
    RimTapeSpec,
)
from envelopelab.features.ease import loop_length
from envelopelab.features.pressure import independent_chamber
from envelopelab.features.spec import FeatureSpec
from envelopelab.features.tube import SupportLine, TubeSpec
from envelopelab.geometry.polygon import distance_to_polyline, points_in_polygon, signed_area
from envelopelab.materials.membrane import TapeMaterial
from envelopelab.solvers.membrane import FloatArray
from envelopelab.solvers.model import OperatingConditions

if TYPE_CHECKING:
    from envelopelab.assembly.pipeline import BuildPackResult
    from envelopelab.assembly.seam_graph import Instance


@dataclass
class Placement:
    """Chart of a feature's host span (see module docstring).

    Attributes
    ----------
    host : HostSurface
        Fitted host surface.
    gore_count : int
        Gores in the ring.
    centre_gore : float
        :math:`g_c`.
    row_bottom : dict of str to float
        Chart :math:`v` of the bottom of every row of the ring, m.
    row_height : dict of str to float
        Finished height of every row, m.
    span_height : float
        Height of rows :math:`r_0..r_1`, m.
    ring : str
        Ring name.
    """

    host: HostSurface
    gore_count: int
    centre_gore: float
    row_bottom: dict[str, float]
    row_height: dict[str, float]
    span_height: float
    ring: str

    def panel_to_chart(self, inst: Instance, points: FloatArray) -> FloatArray:
        """Chart coordinates (m) of points in a ring panel's local frame (m)."""
        if inst.row is None or inst.gore is None:
            raise FeatureBuildError(f"{inst.instance_id} is not a ring panel")
        outline = inst.outline
        y0 = float(outline[:, 1].min())
        out = np.zeros((len(points), 2))
        for k, (x, y) in enumerate(points):
            xl, xr = _span_at(outline, y)
            tau = (x - xl) / max(xr - xl, 1e-12)
            v = self.row_bottom[inst.row] + (y - y0)
            theta = 2.0 * math.pi / self.gore_count * (inst.gore - self.centre_gore + tau - 0.5)
            out[k] = (self.host.hoop_radius_at(v) * theta, v)
        return out

    def gore_seams(self, v_range: tuple[float, float], count: int = 60) -> list[FloatArray]:
        """Vertical (gore) seam lines crossing the chart, m."""
        v = np.linspace(v_range[0], v_range[1], count)
        rho = np.array([self.host.hoop_radius_at(float(t)) for t in v])
        u_max = rho.max() * 0.5 * math.pi
        out = []
        step = 2.0 * math.pi / self.gore_count
        first = math.floor(-u_max / (rho.min() * step)) - 1
        for j in range(first, -first + 1):
            theta = (j + 0.5 - (self.centre_gore % 1.0)) * step
            out.append(np.column_stack([rho * theta, v]))
        return out


def _span_at(outline: FloatArray, y: float) -> tuple[float, float]:
    xs = []
    n = len(outline)
    for i in range(n):
        a, b = outline[i], outline[(i + 1) % n]
        if (a[1] - y) * (b[1] - y) <= 0.0 and a[1] != b[1]:
            t = (y - a[1]) / (b[1] - a[1])
            xs.append(a[0] + t * (b[0] - a[0]))
    if len(xs) < 2:
        y_c = float(np.clip(y, outline[:, 1].min() + 1e-9, outline[:, 1].max() - 1e-9))
        if y_c == y:
            raise FeatureBuildError("height outside the panel")
        return _span_at(outline, y_c)
    return min(xs), max(xs)


def _circle_fit(points: FloatArray) -> tuple[float, float, float]:
    a = np.column_stack([2.0 * points, np.ones(len(points))])
    b = (points**2).sum(axis=1)
    (cx, cy, c), *_ = np.linalg.lstsq(a, b, rcond=None)
    return float(cx), float(cy), math.sqrt(float(c) + cx**2 + cy**2)


def placement_for(
    feature: FeatureSpec, built: BuildPackResult, positions: FloatArray | None = None
) -> Placement:
    """Fit the host chart of a feature.

    Parameters
    ----------
    feature : FeatureSpec
        Feature (its ``host`` placement).
    built : BuildPackResult
        Imported build pack with a rest model.
    positions : ndarray, shape (n, 3), optional
        Node positions of the rest mesh to fit the host to, m (default: the as-sewn
        initial shape).

    Returns
    -------
    Placement
        Chart and host surface.
    """
    if built.rest_model is None:
        raise FeatureBuildError("the build pack has no rest model")
    ring = next((r for r in built.spec.rings if r.name == feature.host.ring), None)
    if ring is None:
        raise FeatureBuildError(f"{feature.name}: unknown ring {feature.host.ring!r}")
    rows = list(ring.rows)
    r0, r1 = (rows.index(r) for r in feature.host.rows)
    g0, g1 = feature.host.gores
    heights = {}
    for row in rows:
        outline = built.pieces[row].outline
        heights[row] = float(outline[:, 1].max() - outline[:, 1].min())
    span = sum(heights[r] for r in rows[r0 : r1 + 1])
    bottom: dict[str, float] = {}
    v = -0.5 * span - sum(heights[r] for r in rows[:r0])
    for row in rows:
        bottom[row] = v
        v += heights[row]
    mesh = built.rest_model.mesh
    x = built.rest_model.positions if positions is None else positions
    source = (
        "as-sewn initial shape (geometric guess, not solved)"
        if positions is None
        else "supplied shape"
    )
    ids = [
        k
        for k, iid in enumerate(mesh.instance_ids)
        if any(
            iid == f"{ring.name}/{row}@{g}"
            for row in rows[r0 : r1 + 1]
            for g in _gore_range(g0, g1, ring.gore_count)
        )
    ]
    if not ids:
        raise FeatureBuildError(f"{feature.name}: no meshed host panels")
    tri = mesh.triangles[np.isin(mesh.tri_instance, ids)]
    nodes = np.unique(tri)
    mouth = mesh.openings.get(ring.bottom.name)
    axis = x[np.unique(mouth)].mean(axis=0) if mouth is not None else x.mean(axis=0)
    rho = np.hypot(x[nodes, 0] - axis[0], x[nodes, 1] - axis[1])
    rc, zc, r1_fit = _circle_fit(np.column_stack([rho, x[nodes, 2]]))
    ang = np.arctan2(x[nodes, 2] - zc, rho - rc)
    psi = 0.5 * (float(ang.min()) + float(ang.max()))
    rho0 = rc + r1_fit * math.cos(psi)
    z0 = zc + r1_fit * math.sin(psi)
    host = HostSurface(
        meridian_radius=r1_fit,
        hoop_radius=rho0 / math.cos(psi),
        normal_elevation=psi,
        centre_height=z0,
        source=source,
    )
    centre = 0.5 * (g0 + (g1 if g1 >= g0 else g1 + ring.gore_count))
    return Placement(host, ring.gore_count, centre, bottom, heights, span, ring.name)


def _gore_range(g0: int, g1: int, count: int) -> list[int]:
    if g1 >= g0:
        return list(range(g0, g1 + 1))
    return list(range(g0, count + 1)) + list(range(1, g1 + 1))


@dataclass
class FeatureGeometry:
    """Measured geometry of an imported feature (lengths m, areas m^2).

    Attributes
    ----------
    values : dict
        Measured quantities with units in the key names.
    findings : list of (str, str)
        (severity, message) for geometry that disagrees with the specification.
    """

    values: dict[str, Any] = field(default_factory=dict)
    findings: list[tuple[str, str]] = field(default_factory=list)


def _piece_outline(built: BuildPackResult, ref: Any) -> FloatArray:
    if ref is None:
        raise FeatureBuildError("missing piece reference")
    if ref.piece is not None:
        return np.asarray(built.pieces[ref.piece].outline, dtype=np.float64)
    if ref.instance is not None:
        return np.asarray(built.assembly.instances[ref.instance].outline, dtype=np.float64)
    raise FeatureBuildError("piece reference needs 'piece' or 'instance'")


def pod_geometry(
    feature: FeatureSpec, built: BuildPackResult
) -> tuple[FloatArray, FloatArray, FeatureGeometry]:
    """Footprint (chart, m) and skin outline (pattern, m) of a pod or blister.

    Returns
    -------
    footprint : ndarray, shape (k, 2)
        Footprint line in the host chart, m.
    skin : ndarray, shape (q, 2)
        Skin finished rim, centred on the footprint centroid, m.
    geometry : FeatureGeometry
        Rim lengths, ease, skin offset, area ratio and the row-fit check.
    """
    fp = _piece_outline(built, feature.footprint)
    lo, hi = fp.min(axis=0), fp.max(axis=0)
    fp = fp - 0.5 * (lo + hi)
    if feature.host.mirror:
        fp = fp * np.array([-1.0, 1.0])
    geo = FeatureGeometry()
    skin = None
    if feature.skin is not None:
        skin = _piece_outline(built, feature.skin)
        if feature.host.mirror:
            skin = skin * np.array([-1.0, 1.0])
        skin = skin - _centroid(skin) + _centroid(fp)
        d = distance_to_polyline(skin, fp, True)
        l_fp, l_sk = loop_length(fp), loop_length(skin)
        geo.values.update(
            {
                "footprint_rim_m": l_fp,
                "skin_rim_m": l_sk,
                "rim_ease_m": l_sk - l_fp,
                "rim_ease_fraction": (l_sk - l_fp) / l_fp,
                "skin_offset_mean_m": float(d.mean()),
                "skin_offset_min_m": float(d.min()),
                "skin_offset_max_m": float(d.max()),
                "footprint_area_m2": abs(signed_area(fp)),
                "skin_area_m2": abs(signed_area(skin)),
                "skin_area_ratio": abs(signed_area(skin)) / abs(signed_area(fp)),
                "match_points": feature.rim.match_points,
                "ease_per_segment_m": (l_sk - l_fp) / feature.rim.match_points,
            }
        )
    geo.values["footprint_width_m"] = float(hi[0] - lo[0])
    geo.values["footprint_height_m"] = float(hi[1] - lo[1])
    return fp, (skin if skin is not None else fp.copy()), geo


def _centroid(points: FloatArray) -> FloatArray:
    x, y = points[:, 0], points[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    a = 0.5 * cross.sum()
    return np.array(
        [
            ((x + np.roll(x, -1)) * cross).sum() / (6 * a),
            ((y + np.roll(y, -1)) * cross).sum() / (6 * a),
        ]
    )


def _tape(tapes: Mapping[str, TapeMaterial], name: str | None, what: str) -> TapeMaterial | None:
    if name is None:
        return None
    if name not in tapes:
        raise FeatureBuildError(f"no tape material for {what} {name!r}")
    return tapes[name]


def _host_tapes(
    placement: Placement,
    built: BuildPackResult,
    rect_v: tuple[float, float],
    u_half: float,
    tapes: Mapping[str, TapeMaterial],
) -> list[HostTape]:
    ring = next(r for r in built.spec.rings if r.name == placement.ring)
    out: list[HostTape] = []
    vertical = ring.vertical_seam.load_tape
    if vertical is not None and vertical in tapes:
        for k, line in enumerate(placement.gore_seams(rect_v)):
            if np.abs(line[:, 0]).max() < u_half:
                out.append(HostTape(f"gore seam {k}", line, tapes[vertical]))
    horizontal = ring.horizontal_seam.load_tape
    if horizontal is not None and horizontal in tapes:
        for row, v in placement.row_bottom.items():
            if rect_v[0] < v < rect_v[1] and row != ring.rows[0]:
                out.append(
                    HostTape(
                        f"row seam below {row}",
                        np.array([[-u_half, v], [u_half, v]]),
                        tapes[horizontal],
                    )
                )
    return out


def _holes(
    feature: FeatureSpec,
    built: BuildPackResult,
    placement: Placement,
    tapes: Mapping[str, TapeMaterial],
) -> list[ChartHole]:
    holes = []
    for ref in feature.feed_holes:
        inst_id, _, loop_name = ref.opening.rpartition(":")
        inst = built.assembly.instances[inst_id]
        loop = inst.loops[loop_name]
        pts = placement.panel_to_chart(inst, loop.points)
        centre = pts.mean(axis=0)
        radius = float(np.sqrt(abs(signed_area(loop.points)) / math.pi))
        hem = ref.hem_tape or (loop.hem.load_tape if loop.hem is not None else None)
        holes.append(
            ChartHole(
                ref.opening, (float(centre[0]), float(centre[1])), radius, _tape(tapes, hem, "hem")
            )
        )
    return holes


def appendage_spec(
    feature: FeatureSpec,
    built: BuildPackResult,
    tapes: Mapping[str, TapeMaterial],
    positions: FloatArray | None = None,
    mesh_size: float | None = None,
    loss_factor: float | None = None,
    host_zone: str | None = None,
) -> tuple[AppendageSpec, Placement, FeatureGeometry]:
    """Builder input of a pod or blister feature.

    Parameters
    ----------
    feature : FeatureSpec
        Feature of kind ``ram_air_pod`` or ``blister``.
    built : BuildPackResult
        Imported build pack.
    tapes : mapping of str to TapeMaterial
        Tape material per tape name used by the ring seams, rim and hems.
    positions : ndarray, optional
        Shape to fit the host to (default: the as-sewn initial shape), m.
    mesh_size : float, optional
        Overrides the feature's mesh size, m.
    loss_factor : float, optional
        Overrides the pressure-loss factor (sensitivity studies), dimensionless.
    host_zone : str, optional
        Material zone of the host (default: the zone of the first host panel).

    Returns
    -------
    spec : AppendageSpec
        Builder input (m).
    placement : Placement
        Host chart.
    geometry : FeatureGeometry
        Measured geometry and findings.
    """
    placement = placement_for(feature, built, positions)
    fp, skin, geo = pod_geometry(feature, built)
    height = geo.values["footprint_height_m"]
    if abs(height - placement.span_height) > 0.01:
        geo.findings.append(
            (
                "warning",
                f"footprint height {height * 1000:.0f} mm differs from rows "
                f"{feature.host.rows[0]}-{feature.host.rows[1]} "
                f"({placement.span_height * 1000:.0f} mm)",
            )
        )
    size = mesh_size if mesh_size is not None else feature.mesh_size_mm / 1000.0
    lo, hi = fp.min(axis=0), fp.max(axis=0)
    margin = (
        feature.host.margin_mm / 1000.0
        if feature.host.margin_mm is not None
        else 0.5 * float((hi - lo).max())
    )
    rect_v = (float(lo[1]) - margin - 1.0, float(hi[1]) + margin + 1.0)
    u_half = float(max(abs(lo[0]), abs(hi[0]))) + margin
    holes = _holes(feature, built, placement, tapes)
    for hole in holes:
        if not points_in_polygon(np.array([hole.centre]), fp)[0]:
            geo.findings.append(("error", f"feed hole {hole.name} is outside the footprint"))
    ring_panel = f"{feature.host.ring}/{feature.host.rows[0]}@{feature.host.gores[0]}"
    zone = host_zone or built.assembly.instances[ring_panel].material_zone
    pressure = _pressure(feature, placement, loss_factor)
    rim_tape = _tape(tapes, feature.rim.tape, "rim tape")
    spec = AppendageSpec(
        name=feature.name,
        footprint=fp,
        skin_outline=skin,
        skin_mode="flat_pattern",
        match_points=feature.rim.match_points,
        ease_mode=feature.rim.ease_mode,
        match_start=feature.rim.match_start,
        host=placement.host,
        margin=margin,
        mesh_size=size,
        host_zone=zone,
        skin_zone=feature.skin_zone or zone,
        host_grain=(1.0, 0.0),
        skin_grain=feature.skin.grain if feature.skin and feature.skin.grain else (1.0, 0.0),
        rim_tape=None
        if rim_tape is None
        else RimTapeSpec(rim_tape, feature.rim.caught_into_host_tapes),
        host_tapes=_host_tapes(placement, built, rect_v, u_half + 1.0, tapes),
        holes=holes,
        pressure=pressure,
        intended=feature.intended_si(),
    )
    return spec, placement, geo


def _pressure(
    feature: FeatureSpec, placement: Placement, loss_factor: float | None
) -> PressureSpec:
    p = feature.pressure
    if p.mode == "fed":
        return PressureSpec("fed", p.loss_factor if loss_factor is None else loss_factor)
    if p.reference_pressure_pa is None:
        raise FeatureBuildError(f"{feature.name}: independent pressure needs reference_pressure_pa")
    chamber = independent_chamber(
        feature.name, p.reference_pressure_pa, placement.host.centre_height, p.gradient_pa_m or 0.0
    )
    return PressureSpec("independent", chamber=chamber)


def tube_spec(
    feature: FeatureSpec,
    built: BuildPackResult,
    tapes: Mapping[str, TapeMaterial],
    conditions: OperatingConditions,
    positions: FloatArray | None = None,
    mesh_size: float | None = None,
    loss_factor: float | None = None,
    host_zone: str | None = None,
) -> tuple[TubeSpec, Placement, FeatureGeometry]:
    """Builder input of a tubular or line-supported feature (see :func:`appendage_spec`).

    The pattern edges come from the skin instance's named edges; the base footprint is
    the host mark named by ``tube.base_mark`` (or an ellipse of the given axes, mm).
    """
    if feature.tube is None or feature.skin is None or feature.skin.instance is None:
        raise FeatureBuildError(f"{feature.name}: a tube needs 'tube' and 'skin.instance'")
    ends = feature.tube
    placement = placement_for(feature, built, positions)
    host_id = f"{feature.host.ring}/{feature.host.rows[0]}@{feature.host.gores[0]}"
    host_inst = built.assembly.instances[host_id]
    geo = FeatureGeometry()
    if ends.base_footprint_ellipse_mm is not None:
        a, b = (0.5e-3 * v for v in ends.base_footprint_ellipse_mm)
        t = np.linspace(0.0, 2.0 * math.pi, 180, endpoint=False)
        centre = placement.panel_to_chart(host_inst, host_inst.outline.mean(axis=0)[None, :])[0]
        fp = np.column_stack([centre[0] + b * np.cos(t), centre[1] + a * np.sin(t)])
    elif ends.base_mark is not None:
        fp = placement.panel_to_chart(host_inst, host_inst.loops[ends.base_mark].points)
    else:
        raise FeatureBuildError(f"{feature.name}: give tube.base_mark or base_footprint_ellipse_mm")
    inst = built.assembly.instances[feature.skin.instance]
    edges = {k: np.asarray(v.points, dtype=np.float64) for k, v in inst.edges.items()}
    base, neck = edges[ends.base_edge], edges[ends.neck_edge]
    if np.linalg.norm(neck[0] - base[0]) > np.linalg.norm(neck[-1] - base[0]):
        neck = neck[::-1]
    side_a = np.vstack([base[:1], neck[:1]])
    side_b = np.vstack([base[-1:], neck[-1:]])
    for name in (ends.side_a, ends.side_b):
        e = edges[name]
        if np.linalg.norm(e[0] - base[0]) < 1e-6 or np.linalg.norm(e[-1] - base[0]) < 1e-6:
            side_a = e if np.linalg.norm(e[0] - base[0]) < 1e-6 else e[::-1]
        else:
            side_b = e if np.linalg.norm(e[0] - base[-1]) < 1e-6 else e[::-1]
    geo.values.update(
        {
            "base_edge_m": float(np.linalg.norm(np.diff(base, axis=0), axis=1).sum()),
            "footprint_rim_m": loop_length(fp),
            "side_a_m": float(np.linalg.norm(np.diff(side_a, axis=0), axis=1).sum()),
            "side_b_m": float(np.linalg.norm(np.diff(side_b, axis=0), axis=1).sum()),
        }
    )
    diff = geo.values["side_b_m"] - geo.values["side_a_m"]
    geo.values["side_difference_m"] = diff
    intended = feature.intended_si()
    if "lean_deg" in intended and abs(intended["lean_deg"]) > 1.0 and abs(diff) < 0.01:
        geo.findings.append(
            (
                "warning",
                f"intended lean {intended['lean_deg']:g} deg but the pattern's two side seams "
                f"are equal ({geo.values['side_a_m'] * 1000:.0f} mm): a straight base cut does "
                "not lean the tube",
            )
        )
    size = mesh_size if mesh_size is not None else feature.mesh_size_mm / 1000.0
    lo, hi = fp.min(axis=0), fp.max(axis=0)
    margin = (
        feature.host.margin_mm / 1000.0
        if feature.host.margin_mm is not None
        else float((hi - lo).max())
    )
    rect_v = (float(lo[1]) - margin - 1.0, float(hi[1]) + margin + 1.0)
    u_half = float(max(abs(lo[0]), abs(hi[0]))) + margin
    zone = host_zone or host_inst.material_zone
    base_spec = AppendageSpec(
        name=feature.name,
        footprint=fp,
        host=placement.host,
        margin=margin,
        mesh_size=size,
        host_zone=zone,
        skin_zone=feature.skin_zone or inst.material_zone,
        rim_tape=None
        if feature.rim.tape is None
        else RimTapeSpec(tapes[feature.rim.tape], feature.rim.caught_into_host_tapes),
        host_tapes=_host_tapes(placement, built, rect_v, u_half + 1.0, tapes),
        holes=_holes(feature, built, placement, tapes),
        pressure=_pressure(feature, placement, loss_factor),
        intended=intended,
    )
    tip_load = ends.tip_mass_kg * conditions.gravity - ends.tip_lift_n
    supports = []
    for line in feature.supports:
        anchor = (
            placement.host.map(np.array([[0.0, 0.0]]))[0]
            + np.asarray(line.anchor_offset_mm) / 1000.0
        )
        supports.append(
            SupportLine(
                line.name,
                line.neck_fraction,
                (float(anchor[0]), float(anchor[1]), float(anchor[2])),
                tapes[line.tape],
                line.slack_mm / 1000.0,
            )
        )
    spec = TubeSpec(
        base=base_spec,
        base_edge=base,
        neck_edge=neck,
        side_a=side_a,
        side_b=side_b,
        tube_zone=feature.skin_zone or inst.material_zone,
        tip_load=tip_load,
        neck_closed=ends.neck_closed,
        internal_ties=[v / 1000.0 for v in ends.internal_ties_mm],
        tie_material=_tape(tapes, ends.tie_tape, "tie"),
        supports=supports,
        intended_lean_deg=intended.get("lean_deg"),
        intended_length=intended.get("length_m"),
    )
    return spec, placement, geo


def read_strips(path: str | Path, layer: str) -> list[FloatArray]:
    """Closed polylines of one DXF layer (strip sub-division of a skin), m.

    Units follow the file's ``$INSUNITS`` (mm, cm, m or in).
    """
    from ezdxf.entities.lwpolyline import LWPolyline
    from ezdxf.filemanagement import readfile

    doc = readfile(str(path))
    scale = {1: 0.0254, 4: 1e-3, 5: 1e-2, 6: 1.0}.get(int(doc.header.get("$INSUNITS", 4)), 1e-3)
    out = []
    for entity in doc.modelspace():
        if isinstance(entity, LWPolyline) and entity.dxf.layer == layer and entity.closed:
            out.append(np.array([p[:2] for p in entity.get_points()], dtype=np.float64) * scale)
    return out
