"""Generic starting values for a new parachute, red line, flying wires and turning vents.

Every value here is a generic default the builder is expected to review; line
strengths and masses are tagged ``assumed`` and must be replaced with datasheet or
measured values before building. Sizes scale with the design (hole, mouth and maximum
diameters), so scale models get proportionate rigging.
"""

from __future__ import annotations

from typing import Any

from envelopelab.design.model import (
    DesignDocument,
    FlyingWireSpec,
    LineSpec,
    ParachuteSpec,
    RedLineSpec,
    RingSpec,
    ScoopSpec,
    TurningVentSpec,
)


def _line(name: str, strength: float, linear_mass: float) -> LineSpec:
    note = "generic value; replace with the datasheet of the line used"
    return LineSpec.model_validate(
        {
            "class": name,
            "strength": {"value": strength, "source": "assumed", "note": note},
            "linear_mass": {"value": linear_mass, "source": "assumed", "note": note},
        }
    )


def shroud_line() -> LineSpec:
    """Generic shroud line (braided polyester, ~4 mm): 4500 N, 0.012 kg/m, assumed."""
    return _line("shroud line", 4500.0, 0.012)


def centralizing_line() -> LineSpec:
    """Generic centralising line (~3 mm): 2500 N, 0.008 kg/m, assumed."""
    return _line("centralising line", 2500.0, 0.008)


def red_line_cord() -> LineSpec:
    """Generic red line (~6 mm braided): 8000 N, 0.025 kg/m, assumed."""
    return _line("red line", 8000.0, 0.025)


def flying_wire_cable() -> LineSpec:
    """Generic flying wire (4 mm 7x19 stainless cable): 8900 N, 0.062 kg/m, assumed."""
    return _line("flying wire", 8900.0, 0.062)


def control_line_cord() -> LineSpec:
    """Generic turning-vent control line (~4 mm): 3000 N, 0.010 kg/m, assumed."""
    return _line("turning vent line", 3000.0, 0.010)


def _ring(name: str, strength: float, linear_mass: float, safety: float, rule: str) -> RingSpec:
    note = "generic value; replace with the datasheet of the ring used"
    return RingSpec.model_validate(
        {
            "class": name,
            "strength": {"value": strength, "source": "assumed", "note": note},
            "linear_mass": {"value": linear_mass, "source": "assumed", "note": note},
            "required_safety_factor": {"value": safety, "source": "assumed", "note": rule},
        }
    )


def crown_ring() -> RingSpec:
    """Generic crown ring: 8 mm aluminium rod (6061-T6, yield 276 MPa): 13.9 kN,
    0.136 kg/m, factor of safety 1.5 (14 CFR 31.25(a)); all assumed."""
    return _ring("aluminium rod ring 8 mm", 13900.0, 0.136, 1.5, "14 CFR 31.25(a), metal part")


def centre_ring() -> RingSpec:
    """Generic parachute centre ring: 6 mm stainless rod (200 MPa): 5.6 kN, 0.226 kg/m,
    factor of safety 1.5 (14 CFR 31.25(a)); all assumed."""
    return _ring("stainless rod ring 6 mm", 5600.0, 0.226, 1.5, "14 CFR 31.25(a), metal part")


def _gores(design: DesignDocument) -> Any:
    if design.gores is None:
        raise ValueError("rigging defaults need a standard-gore design")
    return design.gores


def default_parachute(design: DesignDocument) -> ParachuteSpec:
    """A parachute with one shroud line per load tape (or per second tape above 24 gores).

    Shroud lines attach half a hole diameter below the parachute edge; the confluence is
    one hole diameter below the crown opening; billow 0.1; a crown ring at the rim and a
    centre ring of 5 % of the hole diameter (at least 50 mm) at the apex.
    """
    g = _gores(design)
    count = g.count if g.count <= 24 or g.count % 2 else g.count // 2
    hole = g.parachute_hole_diameter
    return ParachuteSpec(
        panel_count=count,
        billow=0.1,
        zone=None,
        shroud_attachment=round(0.5 * hole, 4),
        centralizing_depth=round(1.0 * hole, 4),
        shroud_line=shroud_line(),
        centralizing_line=centralizing_line(),
        crown_ring=crown_ring(),
        centre_ring=centre_ring(),
        centre_ring_diameter=round(max(0.05, 0.05 * hole), 4),
    )


def default_red_line(design: DesignDocument) -> RedLineSpec:
    """A red line led down seam 1 with 0.4 mouth diameters of spare length."""
    g = _gores(design)
    return RedLineSpec(
        name="red line",
        guide_seam=1,
        spare_length=round(0.4 * g.mouth_diameter, 4),
        line=red_line_cord(),
    )


def default_flying_wires(design: DesignDocument) -> FlyingWireSpec:
    """Flying wires to a four-point burner frame.

    Wire count: the first of 8, 4, 6 and 3 that divides the gore count (multiples of the
    four frame points first; else one wire per gore). Frame radius 0.18, frame drop 0.6 and
    crow's-foot drop 0.1 mouth diameters.
    """
    g = _gores(design)
    count = next((c for c in (8, 4, 6, 3) if g.count % c == 0), g.count)
    d = g.mouth_diameter
    return FlyingWireSpec(
        count=count,
        frame_points=4,
        frame_radius=round(0.18 * d, 4),
        frame_drop=round(0.6 * d, 4),
        frame_azimuth_deg=45.0,
        crows_foot_drop=round(0.1 * d, 4) if g.count // count > 1 else 0.0,
        wire=flying_wire_cable(),
    )


def turning_vent_pair(design: DesignDocument) -> list[TurningVentSpec]:
    """Two opposite turning vents that both turn the balloon counter-clockwise.

    They sit a quarter and three quarters of the way round from seam N, in the panel row
    that holds the equator, with a gap width of 2 % of the maximum diameter and the
    sharp-edged-slot discharge coefficient 0.61 (assumed).
    """
    from envelopelab.project.gore_design import design_profile

    g = _gores(design)
    profile = design_profile(design)
    s_eq = float(profile.s[int(profile.r.argmax())])
    start = 0.0
    letter = g.panel_rows[-1].letter
    for row in g.panel_rows:
        if start <= s_eq < start + row.finished_height:
            letter = row.letter
            break
        start += row.finished_height
    quarter = max(1, round(g.count / 4))
    seams = (quarter, (quarter + g.count // 2 - 1) % g.count + 1)
    width = round(0.02 * profile.max_width, 4)
    return [
        TurningVentSpec(
            name=f"turning vent {i + 1}",
            seam=seam,
            rows=[letter],
            direction="counterclockwise",
            opening_width=width,
            discharge_coefficient={  # type: ignore[arg-type]
                "value": 0.61,
                "source": "assumed",
                "note": "sharp-edged slot, White, Fluid Mechanics",
            },
            control_line=control_line_cord(),
        )
        for i, seam in enumerate(seams)
    ]


def default_scoop(design: DesignDocument) -> ScoopSpec:
    """A half scoop from gore 1 over half the gores, 0.4 mouth diameters deep, 10 deg flare,
    in the mouth row's fabric."""
    g = _gores(design)
    return ScoopSpec(
        first_gore=1,
        gore_count=max(1, g.count // 2),
        height=round(0.4 * g.mouth_diameter, 4),
        flare_deg=10.0,
        zone=None,
    )


def with_default_rigging(design: DesignDocument) -> DesignDocument:
    """``design`` with a default parachute, red line and flying wires where undefined."""
    if design.gores is None:
        return design
    updated = design.model_copy(deep=True)
    if updated.parachute is None:
        updated.parachute = default_parachute(design)
    if updated.rigging.red_line is None:
        updated.rigging.red_line = default_red_line(design)
    if updated.rigging.flying_wires is None:
        updated.rigging.flying_wires = default_flying_wires(design)
    return DesignDocument.model_validate(updated.model_dump(by_alias=True, mode="json"))
