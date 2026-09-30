"""Parachute, red line, flying wires and turning vents of a standard-gore design.

:func:`rigging_outputs` evaluates every rigging element of a design with the models of
:mod:`~envelopelab.rigging.parachute`, :mod:`~envelopelab.rigging.flying_wires` and
:mod:`~envelopelab.rigging.turning_vents` at the design's operating conditions, and
returns their lengths, limit loads, factors of safety, masses and validation findings.
Every factor-of-safety failure, unreachable opening and inconsistent placement is an
``error`` finding; missing parachute, red line or flying wires are ``warning`` findings.

Loads use the rigging load case of the design (limit load factor and required factor
of safety, both with their source tags). Masses are added to the design's lift margin by
:func:`envelopelab.project.gore_design.gore_outputs`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from envelopelab.atmosphere import G0, gas_density, pressure_gradient
from envelopelab.design.model import DesignDocument, LineSpec
from envelopelab.geometry.gore import LENGTH_TOLERANCE, MeridianProfile, PanelRow
from envelopelab.mass_estimate import MassEstimate, TapeMasses, estimate_mass
from envelopelab.materials.repository import (
    FabricCatalog,
    FabricLibraryRepository,
    MaterialProperty,
)
from envelopelab.project.model import PatternSet
from envelopelab.rigging.common import (
    FloatArray,
    LineResult,
    RiggingFinding,
    fos_finding,
    point,
    seam_azimuth,
)
from envelopelab.rigging.flying_wires import WireGeometry, wire_geometry, wire_tensions
from envelopelab.rigging.parachute import (
    OpeningResult,
    ParachuteGeometry,
    crown_force,
    opening,
    parachute_panel,
    seated_geometry,
    shroud_tension,
)
from envelopelab.rigging.turning_vents import VentJet, side_force, vent_jet


@dataclass(frozen=True)
class ParachuteResult:
    """Parachute geometry, panel, loads and opening.

    Attributes
    ----------
    geometry : ParachuteGeometry
        Seated shape and line lengths.
    panel : PanelRow, optional
        Flat pattern of one parachute panel.
    panel_count : int
        Radial panels (one shroud and one centralising line each).
    crown_pressure : float
        Differential pressure at the cap apex, Pa.
    force : float
        Vertical force carried by the shroud lines (static), N.
    shroud, centralizing : LineResult
        Shroud lines (with limit tension) and centralising lines (length only).
    opening : OpeningResult
        Red-line travels.
    mass : MassEstimate, optional
        Parachute fabric, radial and edge tapes and thread.
    """

    geometry: ParachuteGeometry
    panel: PanelRow | None
    panel_count: int
    crown_pressure: float
    force: float
    shroud: LineResult
    centralizing: LineResult
    opening: OpeningResult
    mass: MassEstimate | None


@dataclass(frozen=True)
class RedLineResult:
    """Red-line routing and length.

    Attributes
    ----------
    line : LineResult
        Length includes the spare length; tension is not assessed.
    confluence, guide, anchor : ndarray, shape (3,)
        Confluence, mouth guide ring and basket anchor (None without flying wires), m.
    route_length : float
        Confluence to guide ring to anchor, without spare, m.
    """

    line: LineResult
    confluence: FloatArray
    guide: FloatArray
    anchor: FloatArray | None
    route_length: float


@dataclass(frozen=True)
class FlyingWireResult:
    """Flying wires, crow's-foot legs and their loads.

    Attributes
    ----------
    geometry : WireGeometry
        Layout.
    suspended_weight : float
        Static weight on the wires, N.
    limit_weight : float
        Weight times the limit load factor, N.
    wire_tensions, leg_tensions : ndarray
        Limit tensions, N.
    wires, legs : LineResult
        Most loaded wire and leg (legs are the load tapes' ends).
    """

    geometry: WireGeometry
    suspended_weight: float
    limit_weight: float
    wire_tensions: FloatArray
    leg_tensions: FloatArray
    wires: LineResult
    legs: LineResult


@dataclass(frozen=True)
class TurningVentResult:
    """One turning vent.

    Attributes
    ----------
    name : str
    seam : int
    azimuth : float
        rad.
    s0, s1 : float
        Slot along the tape, m.
    counterclockwise : bool
    jet : VentJet
        Fully open outflow.
    control_line : LineResult
        From the slot midpoint to the basket (or mouth), length only.
    """

    name: str
    seam: int
    azimuth: float
    s0: float
    s1: float
    counterclockwise: bool
    jet: VentJet
    control_line: LineResult


@dataclass(frozen=True)
class RiggingOutputs:
    """Everything :func:`rigging_outputs` computes (see the result classes).

    Attributes
    ----------
    parachute, red_line, flying_wires : optional
    turning_vents : list of TurningVentResult
    net_torque, net_side_force, total_heat_loss : float
        All vents fully open: N m, N, W.
    masses : dict of str to float
        Mass per item, kg.
    sources : tuple of str
        Source tags of the material values used.
    findings : list of RiggingFinding
    """

    parachute: ParachuteResult | None = None
    red_line: RedLineResult | None = None
    flying_wires: FlyingWireResult | None = None
    turning_vents: list[TurningVentResult] = field(default_factory=list)
    net_torque: float = 0.0
    net_side_force: float = 0.0
    total_heat_loss: float = 0.0
    masses: dict[str, float] = field(default_factory=dict)
    sources: tuple[str, ...] = ()
    findings: list[RiggingFinding] = field(default_factory=list)

    @property
    def total_mass(self) -> float:
        """Parachute and all lines and wires, kg."""
        return float(sum(self.masses.values()))


def _prop(value: object) -> MaterialProperty:
    return MaterialProperty(value.value, value.source)  # type: ignore[attr-defined]


def _line_result(
    name: str, spec: LineSpec, count: int, length: float, tension: float | None, required: float
) -> LineResult:
    return LineResult(
        name=name,
        count=count,
        length=length,
        tension=tension,
        strength=_prop(spec.strength),
        linear_mass=_prop(spec.linear_mass),
        required_safety_factor=required,
    )


def _row_span(design: DesignDocument, letters: list[str]) -> tuple[float, float] | None:
    assert design.gores is not None
    starts: dict[str, tuple[int, float, float]] = {}
    s = 0.0
    for i, row in enumerate(design.gores.panel_rows):
        starts[row.letter] = (i, s, s + row.finished_height)
        s += row.finished_height
    if any(letter not in starts for letter in letters):
        return None
    idx = sorted(starts[letter][0] for letter in letters)
    if idx != list(range(idx[0], idx[0] + len(idx))):
        return None
    return min(starts[x][1] for x in letters), max(starts[x][2] for x in letters)


def rigging_outputs(
    design: DesignDocument,
    patterns: PatternSet | None = None,
    fabrics: FabricLibraryRepository | FabricCatalog | None = None,
    profile: MeridianProfile | None = None,
) -> RiggingOutputs:
    """Parachute, red line, flying wires and turning vents of a design (module docstring).

    Parameters
    ----------
    design : DesignDocument
        Design; SI operating conditions (K, Pa, kg).
    patterns : PatternSet, optional
        Unused today (reserved for parachute pattern annotations).
    fabrics : FabricLibraryRepository, optional
        Fabric library for the parachute zone's areal mass (``assumed`` when missing).
    profile : MeridianProfile, optional
        Precomputed envelope profile.

    Returns
    -------
    RiggingOutputs
        Lengths m, forces N, torques N m, masses kg, heat W.
    """
    from envelopelab.project.gore_design import (
        ASSUMED_TAPE_LINEAR_MASS,
        ASSUMED_THREAD,
        default_allowance,
        design_profile,
        zone_areal_masses,
    )

    findings: list[RiggingFinding] = []
    if design.gores is None:
        return RiggingOutputs(
            findings=[
                RiggingFinding(
                    "rigging_special",
                    "info",
                    "parachute and rigging analysis is available for standard-gore designs "
                    "only; design them by hand for this special shape",
                    "rigging",
                )
            ]
        )
    g = design.gores
    n = g.count
    op = design.operating
    rig = design.rigging
    lf = rig.load_factor.value
    required = rig.required_safety_factor.value
    profile = profile or design_profile(design)
    rho_a = gas_density(op.ambient_pressure, op.ambient_temperature)
    rho_i = gas_density(op.ambient_pressure, op.internal_temperature)
    grad = pressure_gradient(rho_a, rho_i)
    z_m = float(profile.height_at(0.0))
    r_m = float(profile.radius_at(0.0))
    masses: dict[str, float] = {}
    sources: set[str] = {rig.load_factor.source, rig.required_safety_factor.source}

    def add_line(key: str, line: LineResult) -> None:
        masses[key] = masses.get(key, 0.0) + line.mass
        sources.update({line.strength.source, line.linear_mass.source})
        f = fos_finding(line, key.split(":")[0])
        if f is not None:
            findings.append(f)

    # -- parachute -----------------------------------------------------------------
    parachute: ParachuteResult | None = None
    pc = design.parachute
    if pc is None:
        findings.append(
            RiggingFinding(
                "parachute_missing",
                "warning",
                "no parachute is defined: the crown opening is not closed (use 'Add parachute')",
                "parachute",
            )
        )
    else:
        r_top = float(profile.radius_at(profile.meridian_length))
        if abs(2.0 * r_top - g.parachute_hole_diameter) > LENGTH_TOLERANCE:
            findings.append(
                RiggingFinding(
                    "parachute_hole",
                    "warning",
                    f"parachute hole diameter {g.parachute_hole_diameter:.3f} m differs from "
                    f"the profile's top opening {2.0 * r_top:.3f} m; the parachute is sized "
                    "on the profile",
                    "gores",
                )
            )
        if n % pc.panel_count:
            findings.append(
                RiggingFinding(
                    "parachute_panels",
                    "warning",
                    f"{pc.panel_count} parachute panels do not divide {n} gores: shroud lines "
                    "do not all meet a load tape",
                    "parachute",
                )
            )
        if pc.zone is not None and pc.zone not in design.zones:
            findings.append(
                RiggingFinding(
                    "parachute_zone",
                    "error",
                    f"parachute zone {pc.zone!r} is not defined",
                    "parachute",
                )
            )
        try:
            geom = seated_geometry(
                profile, g.seal_overlap, pc.billow, pc.shroud_attachment, pc.centralizing_depth
            )
        except ValueError as exc:
            findings.append(RiggingFinding("parachute_geometry", "error", str(exc), "parachute"))
            geom = None
        if geom is not None:
            force = crown_force(geom, grad, z_m)
            try:
                tension: float | None = shroud_tension(geom, lf * force, pc.panel_count)
            except ValueError as exc:
                findings.append(
                    RiggingFinding("parachute_geometry", "error", str(exc), "parachute")
                )
                tension = None
            if geom.confluence_height >= geom.edge_height:
                findings.append(
                    RiggingFinding(
                        "parachute_confluence",
                        "error",
                        "the centralising-line confluence is not below the parachute edge; "
                        "increase the centralising depth",
                        "parachute",
                    )
                )
            shroud = _line_result(
                "shroud line", pc.shroud_line, pc.panel_count, geom.shroud_length, tension, required
            )
            central = _line_result(
                "centralising line",
                pc.centralizing_line,
                pc.panel_count,
                geom.centralizing_length,
                None,
                required,
            )
            add_line("parachute:shroud lines", shroud)
            add_line("parachute:centralising lines", central)
            open_ = opening(geom, profile, g.seal_overlap)
            if open_.full_open_travel is None:
                findings.append(
                    RiggingFinding(
                        "parachute_opening",
                        "error",
                        "the red line cannot open the parachute fully with these line lengths "
                        f"(kinematic limit at {open_.max_travel:.2f} m of pull); change the "
                        "shroud attachment or centralising depth",
                        "parachute",
                    )
                )
            elif (open_.confluence_height_full or 0.0) <= z_m:
                findings.append(
                    RiggingFinding(
                        "parachute_opening",
                        "error",
                        "at full opening the confluence is pulled below the mouth",
                        "parachute",
                    )
                )
            zone = pc.zone if pc.zone is not None else next(iter(design.zones), "default")
            areal = zone_areal_masses(design, fabrics)
            mass: MassEstimate | None = None
            panel: PanelRow | None = None
            try:
                panel = parachute_panel(geom, pc.panel_count, default_allowance(design))
                tape = ASSUMED_TAPE_LINEAR_MASS
                mass = estimate_mass(
                    [panel],
                    pc.panel_count,
                    [zone],
                    {zone: areal.get(zone, MaterialProperty(0.065, "assumed"))},
                    TapeMasses(tape, tape, tape, tape),
                    ASSUMED_THREAD,
                )
                masses["parachute:fabric, tapes and thread"] = mass.total_mass
                sources.update(mass.sources)
            except ValueError as exc:
                findings.append(RiggingFinding("parachute_panel", "error", str(exc), "parachute"))
            parachute = ParachuteResult(
                geometry=geom,
                panel=panel,
                panel_count=pc.panel_count,
                crown_pressure=max(grad * (geom.rim_height + geom.cap_rise - z_m), 0.0),
                force=force,
                shroud=shroud,
                centralizing=central,
                opening=open_,
                mass=mass,
            )

    # -- flying wires --------------------------------------------------------------
    wires: FlyingWireResult | None = None
    fw = rig.flying_wires
    if fw is None:
        findings.append(
            RiggingFinding(
                "flying_wires_missing",
                "warning",
                "no flying wires are defined: the basket is not attached (use 'Add flying wires')",
                "rigging",
            )
        )
    else:
        try:
            wg = wire_geometry(
                n,
                r_m,
                z_m,
                fw.count,
                fw.frame_points,
                fw.frame_radius,
                fw.frame_drop,
                fw.frame_azimuth_deg,
                fw.crows_foot_drop,
            )
        except ValueError as exc:
            findings.append(RiggingFinding("flying_wires", "error", str(exc), "rigging"))
            wg = None
        if wg is not None:
            if fw.count % fw.frame_points:
                findings.append(
                    RiggingFinding(
                        "flying_wires_frame",
                        "warning",
                        f"{fw.count} flying wires do not share {fw.frame_points} frame points "
                        "equally",
                        "rigging",
                    )
                )
            weight = op.payload_mass * G0.value
            if weight <= 0.0:
                findings.append(
                    RiggingFinding(
                        "flying_wires_load",
                        "warning",
                        "payload mass is 0: flying wires and load tapes are not load-checked",
                        "operating",
                    )
                )
            t_w, t_l = wire_tensions(wg, lf * weight)
            jw, jl = int(np.argmax(t_w)), int(np.argmax(t_l))
            wire_line = _line_result(
                "flying wire",
                fw.wire,
                fw.count,
                float(wg.wire_lengths[jw]),
                float(t_w[jw]),
                required,
            )
            # Every wire is cut to its own length; the mass uses the actual lengths.
            wire_line = LineResult(
                wire_line.name,
                wire_line.count,
                float(np.mean(wg.wire_lengths)),
                wire_line.tension,
                wire_line.strength,
                wire_line.linear_mass,
                required,
            )
            tape_strength = MaterialProperty(design.tapes.vertical.strength, "assumed")
            legs = LineResult(
                "load tape at the crow's foot",
                n,
                float(np.mean(wg.leg_lengths)),
                float(t_l[jl]),
                tape_strength,
                ASSUMED_TAPE_LINEAR_MASS,
                required,
            )
            add_line("rigging:flying wires", wire_line)
            masses["rigging:crow's-foot legs"] = legs.mass
            sources.update({tape_strength.source, legs.linear_mass.source})
            f = fos_finding(
                legs, "tapes", f"vertical load tape ({design.tapes.vertical.tape_class})"
            )
            if f is not None:
                findings.append(f)
            wires = FlyingWireResult(wg, weight, lf * weight, t_w, t_l, wire_line, legs)

    def basket_point(azimuth: float) -> FloatArray | None:
        if wires is None:
            return None
        frames = wires.geometry.frame_points
        az = np.arctan2(frames[:, 1], frames[:, 0])
        k = int(np.argmin([abs(math.remainder(azimuth - a, 2.0 * math.pi)) for a in az]))
        return np.asarray(frames[k])

    # -- red line ------------------------------------------------------------------
    red: RedLineResult | None = None
    rl = rig.red_line
    if rl is None:
        findings.append(
            RiggingFinding(
                "red_line_missing",
                "warning",
                "no red line is defined: the parachute cannot be opened (use 'Add red line')",
                "rigging",
            )
        )
    elif not 1 <= rl.guide_seam <= n:
        findings.append(
            RiggingFinding(
                "red_line_seam",
                "error",
                f"red line guide seam {rl.guide_seam} is not in 1..{n}",
                "rigging",
            )
        )
    elif parachute is None:
        findings.append(
            RiggingFinding(
                "red_line_parachute",
                "warning",
                "the red line is not routed: it needs a valid parachute",
                "rigging",
            )
        )
    else:
        phi = seam_azimuth(rl.guide_seam, n)
        conf = np.array([0.0, 0.0, parachute.geometry.confluence_height])
        guide = point(r_m, phi, z_m)
        anchor = basket_point(phi)
        route = float(np.linalg.norm(guide - conf))
        if anchor is None:
            findings.append(
                RiggingFinding(
                    "red_line_anchor",
                    "warning",
                    "the red line ends at the mouth: no flying wires, so the basket anchor "
                    "is unknown",
                    "rigging",
                )
            )
        else:
            route += float(np.linalg.norm(anchor - guide))
        line = _line_result(rl.name, rl.line, 1, route + rl.spare_length, None, required)
        add_line("rigging:red line", line)
        red = RedLineResult(line, conf, guide, anchor, route)
        if any(v.seam == rl.guide_seam for v in design.turning_vents):
            findings.append(
                RiggingFinding(
                    "red_line_vent",
                    "warning",
                    f"the red line is led down seam {rl.guide_seam}, which has a turning vent",
                    "rigging",
                )
            )

    # -- turning vents -------------------------------------------------------------
    vents: list[TurningVentResult] = []
    for vent in design.turning_vents:
        target = "turning_vents"
        if not 1 <= vent.seam <= n:
            findings.append(
                RiggingFinding(
                    "vent_seam", "error", f"{vent.name}: seam {vent.seam} is not in 1..{n}", target
                )
            )
            continue
        span = _row_span(design, vent.rows)
        if span is None:
            findings.append(
                RiggingFinding(
                    "vent_rows",
                    "error",
                    f"{vent.name}: rows {', '.join(vent.rows)} are not consecutive design rows",
                    target,
                )
            )
            continue
        s0, s1 = span
        s1 = min(s1, profile.meridian_length)
        ccw = vent.direction == "counterclockwise"
        jet = vent_jet(
            profile,
            s0,
            s1,
            vent.opening_width,
            vent.discharge_coefficient.value,
            rho_a,
            rho_i,
            op.ambient_temperature,
            op.internal_temperature,
            ccw,
        )
        sources.add(vent.discharge_coefficient.source)
        phi = seam_azimuth(vent.seam, n)
        mid = point(jet.mean_radius, phi, jet.mean_height)
        end = basket_point(phi)
        if end is None:
            end = point(r_m, phi, z_m)
        control = _line_result(
            f"{vent.name} control line",
            vent.control_line,
            1,
            float(np.linalg.norm(mid - end)),
            None,
            required,
        )
        add_line("turning_vents:control lines", control)
        if parachute is not None and s1 > parachute.geometry.attachment_s:
            findings.append(
                RiggingFinding(
                    "vent_parachute",
                    "error",
                    f"{vent.name} reaches above the shroud-line attachment",
                    target,
                )
            )
        vents.append(TurningVentResult(vent.name, vent.seam, phi, s0, s1, ccw, jet, control))
    torque = sum(v.jet.torque for v in vents)
    side = side_force(
        [v.jet.thrust for v in vents],
        [v.azimuth for v in vents],
        [v.counterclockwise for v in vents],
    )
    thrust = sum(v.jet.thrust for v in vents)
    if vents and side > 0.1 * thrust:
        findings.append(
            RiggingFinding(
                "vent_balance",
                "warning",
                f"turning vents are unbalanced: net side force {side:.0f} N with all vents "
                "open (place them in opposite pairs turning the same way)",
                "turning_vents",
            )
        )
    if vents and abs(torque) < 0.05 * sum(abs(v.jet.torque) for v in vents):
        findings.append(
            RiggingFinding(
                "vent_cancel",
                "warning",
                "turning vents cancel each other: net torque is almost zero",
                "turning_vents",
            )
        )
    return RiggingOutputs(
        parachute=parachute,
        red_line=red,
        flying_wires=wires,
        turning_vents=vents,
        net_torque=torque,
        net_side_force=side,
        total_heat_loss=sum(v.jet.heat_loss for v in vents),
        masses=masses,
        sources=tuple(sorted(sources)),
        findings=findings,
    )


def rigging_polylines(
    design: DesignDocument, outputs: RiggingOutputs
) -> dict[str, list[FloatArray]]:
    """3-D polylines of the rigging for display, m (keyed by element kind).

    Returns
    -------
    dict of str to list of ndarray
        ``parachute`` (edge ring and panel seams), ``shroud_lines``,
        ``centralizing_lines``, ``red_line``, ``flying_wires`` (legs, wires and frame) and
        ``turning_vents`` (slots); each array has shape (k, 3).
    """
    from envelopelab.project.gore_design import design_profile

    out: dict[str, list[FloatArray]] = {}
    if design.gores is None:
        return out
    n = design.gores.count
    envelope = design_profile(design)
    r_m, z_m = float(envelope.radius_at(0.0)), float(envelope.height_at(0.0))
    pr = outputs.parachute
    if pr is not None:
        g = pr.geometry
        ring = np.linspace(0.0, 2.0 * math.pi, 97)
        edge_ring = np.column_stack(
            (
                g.edge_radius * np.cos(ring),
                g.edge_radius * np.sin(ring),
                np.full_like(ring, g.edge_height),
            )
        )
        seams: list[FloatArray] = [edge_ring]
        shrouds: list[FloatArray] = []
        centrals: list[FloatArray] = []
        s = np.linspace(0.0, g.profile.meridian_length, 40)
        rr, zz = g.profile.radius_at(s), g.profile.height_at(s)
        for i in range(pr.panel_count):
            phi = 2.0 * math.pi * i / pr.panel_count
            seams.append(np.column_stack((rr * math.cos(phi), rr * math.sin(phi), zz)))
            e = point(g.edge_radius, phi, g.edge_height)
            shrouds.append(np.vstack((e, point(g.attachment_radius, phi, g.attachment_height))))
            centrals.append(np.vstack((e, [0.0, 0.0, g.confluence_height])))
        out["parachute"] = seams
        out["shroud_lines"] = shrouds
        out["centralizing_lines"] = centrals
    rl = outputs.red_line
    if rl is not None:
        pts = [rl.confluence, rl.guide] + ([rl.anchor] if rl.anchor is not None else [])
        out["red_line"] = [np.vstack(pts)]
    fw = outputs.flying_wires
    if fw is not None:
        wg = fw.geometry
        lines: list[FloatArray] = []
        for j, group in enumerate(wg.seams):
            cara = wg.carabiners[j]
            for seam in group:
                top = point(r_m, seam_azimuth(seam, n), z_m)
                lines.append(np.vstack((top, cara)))
            lines.append(np.vstack((cara, wg.frame_points[wg.wire_frame_point[j]])))
        lines.append(np.vstack((wg.frame_points, wg.frame_points[:1])))
        out["flying_wires"] = lines
    vents: list[FloatArray] = []
    for v in outputs.turning_vents:
        s = np.linspace(v.s0, v.s1, 20)
        rr, zz = envelope.radius_at(s), envelope.height_at(s)
        vents.append(np.column_stack((rr * math.cos(v.azimuth), rr * math.sin(v.azimuth), zz)))
    if vents:
        out["turning_vents"] = vents
    return out
