"""Appendage and top-and-bottom documents of a build pack (ADR-0037).

Generated from the placed special shapes, the design and its rigging outputs:

* per special shape ``<slug>-<shape>.pdf`` (REF): the specification (kind, placement,
  rim and footprint, fabric, checks), the cut list of its skin pieces, the match marks
  (number, skin piece, envelope gore and row, position on the panel) and its feed holes;
* per special shape ``<slug>-<shape>-build.pdf`` (REF): the build procedure generated
  from the shape's data (cut, mark, sew the skin, feed holes, tape and sew the rim,
  inspect), each step naming the sheet to work from, with blank *builder notes* lines
  for the shop's own detail;
* ``<slug>-turning-vents.pdf`` and ``<slug>-vent-panels.pdf`` when the design has
  turning vents: placement, opening, jet thrust and torque, air and heat loss, control
  lines; and which panels of which gores carry a vent;
* ``<slug>-parachute.pdf``: parachute pattern data and every rigging length (shroud and
  centralising lines, crown and centre rings, red-line pull) with factors of safety;
* ``<slug>-scoop.pdf``: the scoop, the flying wires (each wire's length), the crow's-foot
  legs and the red line, with factors of safety.

A factor of safety below the requirement is printed ``FAILS``; one that is not assessed
says so.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from envelopelab.export.documents import rigging_table
from envelopelab.export.shop import (
    A3_LANDSCAPE,
    PackContext,
    Pages,
    _range,
    _slug,
    both,
    ft_in,
    mm,
    shape_rows,
)

if TYPE_CHECKING:
    from envelopelab.features.primitives import PrimitiveDesign

NOTE_LINES = 3  # blank builder-notes lines per build step


def shape_files(ctx: PackContext, p: PrimitiveDesign) -> tuple[str, str, str]:
    """(spec, build) file names of a special shape, and its skin-piece sheets in words."""
    stem = _slug(p.primitive.name)
    return (
        ctx.file(f"{stem}.pdf"),
        ctx.file(f"{stem}-build.pdf"),
        ctx.shape_pieces(p.primitive.name),
    )


def write_shape_spec(ctx: PackContext, p: PrimitiveDesign, path: Path) -> Path:
    """``<slug>-<shape>.pdf``: spec, skin cut list, match marks, feed holes, checks."""
    prim = p.primitive
    gores, rows = shape_rows(p)
    doc = Pages(A3_LANDSCAPE, f"{ctx.design.meta.name} - special shape {prim.name}")
    doc.title(
        f"{prim.name.upper()} - SPECIFICATION",
        type(prim).__name__.upper(),
        f"gores {_range(gores)}, rows {_range(rows)} - {len(p.pieces)} skin pieces - "
        f"{len(p.marks)} match marks",
    )
    place = prim.placement
    rim = sum(a.length for a in p.attachment)
    spec = [
        ("Kind", type(prim).__name__),
        (
            "Placement",
            f"gore {place.gore}, {place.tape_position:.3f} m up the load tape, across "
            f"{place.across:.2f}, lean {place.lean_deg:g} deg",
        ),
        ("Envelope panels", f"gores {_range(gores)}, rows {_range(rows)}"),
        ("Rim / footprint line", f"{both(rim)} marked on {len(p.attachment)} panel runs"),
        ("Skin pieces", f"{len(p.pieces)} (cut list below)"),
        ("Feed holes", f"{len(p.feed_holes)} (envelope panels, below)"),
    ]
    doc.kv(spec)
    doc.heading("SKIN CUT LIST", x=doc.margin)
    doc.table(
        ["Piece", "Cut", "Finished W x H (mm)", "Surface area (m2)", "Sheet"],
        [
            [
                c.label,
                str(c.cut_count),
                f"{c.size[0] * 1000:.0f} x {c.size[1] * 1000:.0f}",
                f"{c.surface_area:.3f}",
                ctx.template_for(c.label),
            ]
            for c in p.pieces
        ],
        [2, 1, 2, 2, 4],
    )
    doc.heading("MATCH MARKS", x=doc.margin)
    doc.table(
        ["Mark", "Skin piece", "Envelope gore", "Row", "Position on the panel (mm)"],
        [
            [
                str(m.number),
                m.piece,
                str(m.gore),
                m.row,
                f"x {m.host_xy[0] * 1000:+.0f}, y {m.host_xy[1] * 1000:.0f}",
            ]
            for m in p.marks
        ],
        [1, 2, 1.5, 1, 3],
        row_height=14,
    )
    if p.feed_holes:
        doc.heading("FEED HOLES (ENVELOPE ONLY)", x=doc.margin)
        doc.table(
            ["Gore", "Row", "Centre on the panel (mm)", "Finished diameter"],
            [
                [
                    str(h.gore),
                    h.row,
                    f"x {h.centre_xy[0] * 1000:+.0f}, y {h.centre_xy[1] * 1000:.0f}",
                    mm(2 * h.radius),
                ]
                for h in p.feed_holes
            ],
            [1, 1, 3, 2],
        )
    if p.checks:
        doc.heading("DESIGN CHECKS", x=doc.margin)
        fails = {k for k, c in enumerate(p.checks) if not c.passed}
        doc.table(
            ["Check", "Value", "Limit", "Result", "Note"],
            [
                [
                    c.name,
                    f"{c.value:.3g} {c.unit}",
                    f"{c.limit:.3g} {c.unit}",
                    "ok" if c.passed else ("FAILS" if c.severity == "error" else "WARNING"),
                    c.message,
                ]
                for c in p.checks
            ],
            [2.5, 1.5, 1.5, 1, 5],
            fails,
        )
    return doc.save(path)


def build_steps(ctx: PackContext, p: PrimitiveDesign) -> list[tuple[str, str]]:
    """The build procedure of a special shape: (step, what to do, naming its sheet)."""
    prim = p.primitive
    spec, _build, patterns = shape_files(ctx, p)
    gores, rows = shape_rows(p)
    marked = sorted(
        {
            t.name
            for t in ctx.templates
            if any(o.source.startswith(f"{prim.name}-mark-") for pg in t.pages for o in pg.overlays)
        }
    )
    steps = [
        (
            "PRINT & CHECK",
            f"Print {patterns} at 100 % and measure both calibration lines on every page.",
        ),
        (
            "CUT THE SKIN",
            f"Cut the {len(p.pieces)} skin pieces from {patterns}; mark each with its label "
            "and the numbered match marks on its rim.",
        ),
        (
            "MARK THE ENVELOPE",
            f"On the panels of gores {_range(gores)}, rows {_range(rows)}, mark the footprint "
            f"line, the side ticks and the {len(p.marks)} numbered match marks from "
            + (", ".join(marked) if marked else "the marked panel sheets")
            + " before the envelope is assembled.",
        ),
    ]
    if p.feed_holes:
        steps.append(
            (
                "FEED HOLES",
                "Cut and hem the feed holes in the ENVELOPE panels only: "
                + "; ".join(
                    f"gore {h.gore} panel {h.row} O{mm(2 * h.radius)}" for h in p.feed_holes
                )
                + f" (positions on {spec}).",
            )
        )
    tips = [c for c in p.pieces if c.rim is None]
    steps.append(
        (
            "SEW THE SKIN",
            "Sew the skin pieces to each other side by side"
            + (f", then the tops to the tip piece {tips[0].label}" if tips else "")
            + " (seams in the sewing schedule).",
        )
    )
    ease = sum(abs(e) for e in p.mark_ease) if len(p.mark_ease) else 0.0
    steps.append(
        (
            "TAPE THE FOOTPRINT",
            f"Sew the {ctx.design.tapes.hole.tape_class} along the marked footprint line "
            f"({sum(a.length for a in p.attachment):.2f} m), caught into the gore load tapes "
            "where it crosses them.",
        )
    )
    steps.append(
        (
            "SEW THE RIM",
            f"Sew the skin rim onto the footprint line, matching marks 1-{len(p.marks)}; work "
            f"the ease ({ease * 1000:.0f} mm in all) evenly between the marks.",
        )
    )
    steps.append(
        (
            "INSPECT",
            "Check every seam, the mark alignment and the feed holes; sign the shape's sheet "
            f"of {ctx.file('build-log.pdf')}.",
        )
    )
    return steps


def write_shape_build(ctx: PackContext, p: PrimitiveDesign, path: Path) -> Path:
    """``<slug>-<shape>-build.pdf``: the generated build procedure with notes lines."""
    prim = p.primitive
    doc = Pages(A3_LANDSCAPE, f"{ctx.design.meta.name} - {prim.name} build procedure")
    doc.title(
        f"{prim.name.upper()} - BUILD PROCEDURE",
        "",
        "generated from the design - each step names the sheet to work from - add your "
        "shop's detail on the notes lines",
    )
    for k, (step, text) in enumerate(build_steps(ctx, p), start=1):
        from envelopelab.export.shop import _wrap

        lines = _wrap(text, 150)
        doc._need(14 * (len(lines) + NOTE_LINES) + 20)
        doc.canvas.text(doc.margin, doc.y, str(k), 12, True)
        doc.canvas.text(doc.margin + 30, doc.y, step, 11, True)
        for j, line in enumerate(lines):
            doc.canvas.text(doc.margin + 220, doc.y - 13 * j, line, 9)
        doc.y -= 13 * len(lines) + 6
        for _ in range(NOTE_LINES):
            doc.canvas.text(doc.margin + 220, doc.y, "notes:", 7, color=(0.5, 0.5, 0.5))
            doc.canvas.line(
                doc.margin + 250,
                doc.y - 2,
                doc.size[0] - doc.margin,
                doc.y - 2,
                (0.75, 0.75, 0.75),
                0.4,
            )
            doc.y -= 16
        doc.y -= 8
    return doc.save(path)


def write_turning_vents(ctx: PackContext, out: Path) -> list[Path]:
    """``<slug>-turning-vents.pdf`` and ``<slug>-vent-panels.pdf``."""
    d = ctx.design
    rig = None if ctx.outputs is None else ctx.outputs.rigging
    results = {v.name: v for v in (rig.turning_vents if rig is not None else [])}
    doc = Pages(A3_LANDSCAPE, f"{d.meta.name} - turning vents")
    doc.title("TURNING VENTS - PLACEMENT AND ASSEMBLY", "", f"{len(d.turning_vents)} vents")
    rows = []
    for v in d.turning_vents:
        r = results.get(v.name)
        gores = f"{v.seam} / {v.seam % ctx.gores + 1}"
        if r is None:
            rows.append(
                [
                    v.name,
                    str(v.seam),
                    gores,
                    ", ".join(v.rows),
                    v.direction,
                    mm(v.opening_width),
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                ]
            )
            continue
        rows.append(
            [
                v.name,
                str(v.seam),
                gores,
                ", ".join(v.rows),
                v.direction,
                mm(v.opening_width),
                f"{r.jet.slot_length:.3f} m",
                f"{r.jet.area:.3f} m2",
                f"{r.jet.thrust:.1f} N / {r.jet.torque:.0f} N m",
                f"{r.jet.mass_flow:.2f} kg/s, {r.jet.heat_loss / 1000:.0f} kW",
                f"{r.control_line.length:.2f} m",
            ]
        )
    doc.table(
        [
            "Vent",
            "Seam",
            "Gores",
            "Rows",
            "Turns",
            "Opening",
            "Slot",
            "Open area",
            "Thrust / torque (open)",
            "Air / heat loss",
            "Control line",
        ],
        rows,
        [1.6, 0.7, 1, 1, 1.6, 1, 1, 1, 2, 2, 1.2],
    )
    if rig is not None and rig.turning_vents:
        doc.kv(
            [
                ("Net turning torque", f"{rig.net_torque:.0f} N m (all vents fully open)"),
                ("Net side force", f"{rig.net_side_force:.1f} N"),
            ]
        )
    first = doc.save(out / ctx.file("turning-vents.pdf"))
    panels = Pages(A3_LANDSCAPE, f"{d.meta.name} - vent panels")
    panels.title(
        "VENT PANELS", "", "the panels that carry a vent: mark the vent on them before assembly"
    )
    prow = []
    for v in d.turning_vents:
        for row in v.rows:
            for g in (v.seam, v.seam % ctx.gores + 1):
                prow.append(
                    [
                        f"gore {g}",
                        f"panel {row}",
                        v.name,
                        f"seam {v.seam}",
                        "left of the seam" if g == v.seam else "right of the seam",
                    ]
                )
    panels.table(["Gore", "Panel", "Vent", "Seam", "Side"], prow, [1, 1, 2, 1, 2])
    return [first, panels.save(out / ctx.file("vent-panels.pdf"))]


def write_parachute(ctx: PackContext, path: Path) -> Path:
    """``<slug>-parachute.pdf``: parachute pattern data and rigging lengths."""
    d = ctx.design
    g = d.gores
    assert g is not None
    rig = None if ctx.outputs is None else ctx.outputs.rigging
    doc = Pages(A3_LANDSCAPE, f"{d.meta.name} - parachute")
    pr = None if rig is None else rig.parachute
    doc.title(
        "PARACHUTE - PATTERN DATA & RIGGING",
        "",
        f"cut from {ctx.file('parachute-panel.pdf')}"
        + (f" and {ctx.file('parachute-centre.pdf')}" if pr is not None and pr.centre_panel else "")
        if pr is not None
        else "no parachute",
    )
    rows = [
        (
            "Parachute hole diameter",
            f"{both(g.parachute_hole_diameter)} (radius {mm(g.parachute_hole_diameter / 2)})",
        ),
        ("Seal overlap", f"{both(g.seal_overlap)} (along the fabric, all round)"),
    ]
    if pr is not None:
        geo = pr.geometry
        rows += [
            ("Parachute diameter", both(geo.diameter)),
            ("Radial panels", f"{pr.panel_count}"),
            ("Fabric", f"{geo.meridian_length:.3f} m edge to apex, {geo.area:.2f} m2"),
            ("Crown pressure", f"{pr.crown_pressure:.1f} Pa"),
            ("Shroud-line load (static)", f"{pr.force:.0f} N"),
            ("Shroud lines", f"{both(pr.shroud.length)} x{pr.shroud.count}"),
            ("Centralising lines", f"{both(pr.centralizing.length)} x{pr.centralizing.count}"),
        ]
        op = pr.opening
        seal = "NOT REACHABLE" if op.seal_open_travel is None else f"{op.seal_open_travel:.3f} m"
        full = "NOT REACHABLE" if op.full_open_travel is None else f"{op.full_open_travel:.3f} m"
        rows.append(("Red-line pull", f"seal open {seal}, fully open {full}"))
    if rig is not None and rig.red_line is not None:
        rows.append(
            (
                "Red line",
                f"{rig.red_line.line.length:.2f} m / "
                f"{ft_in(rig.red_line.line.length)} (route {rig.red_line.route_length:.2f} m "
                "+ spare)",
            )
        )
    doc.kv(rows)
    table = rigging_table(rig)
    keep = [k for k, r in enumerate(table.rows) if r[0] in ("parachute", "red line")]
    doc.heading("LINES AND RINGS", x=doc.margin)
    doc.table(
        table.columns,
        [table.rows[k] for k in keep],
        [1.2, 1.6, 0.6, 1.1, 0.9, 1, 1, 0.9, 0.7, 0.8, 1, 0.8],
        {i for i, k in enumerate(keep) if k in table.fails},
    )
    return doc.save(path)


def write_scoop(ctx: PackContext, path: Path) -> Path:
    """``<slug>-scoop.pdf``: scoop, flying wires (each wire), legs and red line."""
    d = ctx.design
    rig = None if ctx.outputs is None else ctx.outputs.rigging
    doc = Pages(A3_LANDSCAPE, f"{d.meta.name} - scoop and mouth rigging")
    doc.title("SCOOP, MOUTH RIGGING & FLYING WIRES")
    sc = None if rig is None else rig.scoop
    if sc is not None:
        last = sc.first_gore + sc.gore_count - 1
        doc.kv(
            [
                ("Scoop", f"gores {sc.first_gore}-{last}, {sc.zone}"),
                ("Slant length", both(sc.slant_length)),
                ("Bottom radius", both(sc.bottom_radius)),
                (
                    "Panel (finished)",
                    f"{mm(sc.panel.top_width)} at the mouth, "
                    f"{mm(sc.panel.bottom_width)} at the bottom",
                ),
                ("Mass", f"{sc.mass.total_mass:.2f} kg"),
                ("Wind load", "not assessed"),
            ]
        )
    else:
        doc.kv([("Scoop", "none")])
    fw = None if rig is None else rig.flying_wires
    if fw is not None:
        doc.kv(
            [
                ("Flying wires", f"{fw.wires.count}, {fw.geometry.group_size} load tapes each"),
                ("Suspended weight", f"{fw.suspended_weight:.0f} N"),
                ("Limit weight", f"{fw.limit_weight:.0f} N"),
            ]
        )
        doc.heading("FLYING-WIRE LENGTHS", x=doc.margin)
        doc.table(
            ["Wire", "Length", "English", "Limit tension"],
            [
                [str(k), f"{length:.3f} m", ft_in(length), f"{t:.0f} N"]
                for k, (length, t) in enumerate(
                    zip(fw.geometry.wire_lengths, fw.wire_tensions, strict=False), start=1
                )
            ],
            [1, 2, 2, 2],
            row_height=14,
        )
    table = rigging_table(rig)
    keep = [k for k, r in enumerate(table.rows) if r[0] == "flying wires"]
    if keep:
        doc.heading("WIRES AND LEGS", x=doc.margin)
        doc.table(
            table.columns,
            [table.rows[k] for k in keep],
            [1.2, 1.6, 0.6, 1.1, 0.9, 1, 1, 0.9, 0.7, 0.8, 1, 0.8],
            {i for i, k in enumerate(keep) if k in table.fails},
        )
    if fw is None and sc is None:
        doc.kv([("Flying wires", "none defined: the basket is not attached")])
    return doc.save(path)
