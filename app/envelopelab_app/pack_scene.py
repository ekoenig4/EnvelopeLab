"""The build pack's 3D view, taken from what the application's 3D view shows.

:func:`scene_from_view` starts from :func:`envelopelab.export.viewer.design_scene` (the
design surface, seams, gore numbers and rigging) and adds the special shapes as
designed and every part of the run chosen in the 3D view (the envelope and the shapes
solved with it), each with the colourings of every field the view can show for it, in
the same colours and on the same shared scales (:mod:`envelopelab_app.result_view`).
The page's banner is the view's banner. A stale or unconverged part gets no colouring
and says so on its row, as in the view.

Display only: the values come from the view's result fields; this module turns them
into colours.
"""

from __future__ import annotations

import numpy as np

from envelopelab.export.viewer import (
    Coloring,
    Legend,
    Scene,
    SceneLines,
    SceneMesh,
    SceneStatus,
    design_scene,
    legend_entries,
)
from envelopelab.project.deviation import interpolate_on_mesh
from envelopelab.project.run_fields import SAFETY_FIELDS
from envelopelab.solvers.results import ResultField
from envelopelab_app.panels.view3d import (
    DISPLAY_UNITS,
    FOS_LIMIT,
    FOS_LIMIT_SOURCE,
    LAYER_COLORS,
    SHORT_TITLES,
    View3DPanel,
)
from envelopelab_app.result_view import diverging_rgb, fos_bands, wrinkle_bands

#: Continuous colour ramp of the other fields (viridis at five stops, low to high).
CONTINUOUS_STOPS = ("#440154", "#3b528b", "#21918c", "#5ec962", "#fde725")


def _hex_rgb(colour: str) -> np.ndarray:
    h = colour.lstrip("#")
    return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float64)


def ramp(t: np.ndarray, stops: tuple[str, ...] = CONTINUOUS_STOPS) -> np.ndarray:
    """RGB (uint8, shape (n, 3)) of ``t`` in [0, 1] on ``stops``, linearly; NaN grey."""
    rgb = np.array([_hex_rgb(c) for c in stops])
    t = np.asarray(t, dtype=np.float64)
    x = np.clip(np.nan_to_num(t, nan=0.0), 0.0, 1.0) * (len(stops) - 1)
    i = np.minimum(x.astype(int), len(stops) - 2)
    f = (x - i)[:, None]
    out = rgb[i] * (1.0 - f) + rgb[i + 1] * f
    out[~np.isfinite(t)] = (199, 199, 199)
    result: np.ndarray = np.rint(out).astype(np.uint8)
    return result


def _title(field: ResultField) -> str:
    scale, unit = DISPLAY_UNITS.get(field.name, (1.0, field.unit))
    del scale
    return SHORT_TITLES.get(field.name, field.name) + (f" [{unit}]" if unit != "-" else "")


def _location(field: ResultField) -> str:
    return "face" if field.location == "triangle" else "point"


def coloring(field: ResultField, shared: np.ndarray) -> Coloring:
    """The colours of one part for ``field``; ``shared`` is every part's values of the
    field together (one scale for the whole run)."""
    values = np.asarray(field.values, dtype=np.float64)
    title = _title(field)
    if field.name in SAFETY_FIELDS:
        bands = fos_bands(values, FOS_LIMIT)
        rgb = np.array([_hex_rgb(bands.colors[i]) for i in bands.index], dtype=np.uint8)
        legend = Legend(
            f"{title} (limit {FOS_LIMIT:g}, {FOS_LIMIT_SOURCE})",
            legend_entries(bands.colors, bands.labels),
        )
        return Coloring(field.name, title, rgb.reshape(-1, 3), _location(field), legend)
    if field.name == "wrinkle_state":
        bands = wrinkle_bands(values)
        rgb = np.array([_hex_rgb(bands.colors[i]) for i in bands.index], dtype=np.uint8)
        legend = Legend(title, legend_entries(bands.colors, bands.labels))
        return Coloring(field.name, title, rgb.reshape(-1, 3), _location(field), legend)
    scale = DISPLAY_UNITS.get(field.name, (1.0, field.unit))[0]
    finite = shared[np.isfinite(shared)] * scale
    if field.name == "deviation":
        limit = max(float(np.abs(finite).max()), 1e-3) if finite.size else 1.0
        rgb = deviation_rgb(values * scale, limit)
        ticks = [-limit, -limit / 2, 0.0, limit / 2, limit]
        legend = Legend(
            "Deviation [mm]: + outside the design, - inside",
            [
                (
                    "#{:02x}{:02x}{:02x}".format(*deviation_rgb(np.array([t]), limit)[0]),
                    f"{t:+.0f}" if abs(t) >= 0.5 else "0",
                )
                for t in ticks
            ],
        )
        return Coloring(field.name, title, rgb, _location(field), legend)
    lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    if hi <= lo:
        hi = lo + 1.0
    rgb = ramp((values * scale - lo) / (hi - lo))
    steps = np.linspace(lo, hi, len(CONTINUOUS_STOPS))
    legend = Legend(title, legend_entries(CONTINUOUS_STOPS, [f"{t:.3g}" for t in steps]))
    return Coloring(field.name, title, rgb, _location(field), legend)


def deviation_rgb(mm: np.ndarray, limit: float) -> np.ndarray:
    """Diverging colours of deviations (mm) on a symmetric scale of ``limit`` mm."""
    out = np.empty((len(mm), 3), dtype=np.uint8)
    for k, v in enumerate(np.asarray(mm, dtype=np.float64)):
        if not np.isfinite(v):
            out[k] = (199, 199, 199)
            continue
        out[k] = np.rint(np.array(diverging_rgb(v / limit)) * 255.0).astype(np.uint8)
    return out


def scene_from_view(view: View3DPanel) -> Scene:
    """The build pack's 3D scene from the view (see the module docstring)."""
    controller = view.controller
    design = controller.design
    if design is None or design.gores is None:
        raise ValueError("the 3D view of a build pack needs a standard-gore design")
    scene = design_scene(design, controller.rigging)
    by_key = {m.key: m for m in scene.meshes}
    # The view's design surface carries the row fabric colours; use them.
    layer = view.layers.get("design")
    if layer is not None and layer.face_colors is not None and "design" in by_key:
        mesh = by_key["design"]
        if len(layer.faces) == len(mesh.triangles):
            mesh.face_rgb = np.asarray(layer.face_colors, dtype=np.uint8)
    for key, layer in view.layers.items():
        if not key.startswith("shape:"):
            continue
        scene.meshes.append(
            SceneMesh(
                key,
                layer.short,
                "Design",
                layer.points,
                layer.faces,
                LAYER_COLORS["shape"],
                face_rgb=layer.face_colors,
                role="design",
            )
        )
        seams = [p for lines in layer.polylines.values() for p in lines]
        if seams:
            scene.lines.append(
                SceneLines(f"{key}:seams", f"{layer.short} seams", "Design", seams, role="design")
            )
    parts = view.parts()
    for part in parts:
        layer = view.layers[part]
        notes = []
        if not layer.converged:
            notes.append("NOT CONVERGED: values are not final")
        if layer.stale:
            notes.append("stale: the design has changed since this run")
        if layer.kind == "envelopelab-preview" or (
            part.startswith("shape-sim:") and "preview" in layer.label.lower()
        ):
            notes.append("preview")
        mesh = SceneMesh(
            part,
            layer.short,
            "Result",
            layer.points,
            layer.faces,
            "#c7c7c7" if layer.stale else LAYER_COLORS[layer.kind],
            note=", ".join(notes),
            face_rgb=None if layer.stale else layer.face_colors,
            role="result",
        )
        fields = view.part_fields.get(part, {})
        for name, field in fields.items():
            mesh.colorings[name] = coloring(field, view._shared_values(name))
            if name == "deviation":
                design_key = view._design_key(part)
                design_mesh = next((m for m in scene.meshes if m.key == design_key), None)
                if design_mesh is not None and not layer.stale:
                    on_design = interpolate_on_mesh(
                        design_mesh.points, layer.points, layer.faces, field.values
                    )
                    on = ResultField("deviation", "node", on_design, "m", field.description)
                    design_mesh.colorings["deviation"] = coloring(
                        on, view._shared_values("deviation")
                    )
        scene.meshes.append(mesh)
    if parts:  # a run is shown: its results, not the design surfaces under them
        for mesh_item in scene.meshes:
            if mesh_item.role == "design":
                mesh_item.visible = False
        for line_item in scene.lines:
            if line_item.role == "design":
                line_item.visible = False
    scene.status = SceneStatus(
        view.banner.kind or "info",
        view.banner.title.text() if view.banner.kind else "Design only.",
        view.banner.message.text() if view.banner.kind else "No solver result shown.",
    )
    record = view._records.get(parts[0]) if parts else None
    if record is not None:
        scene.notes.append(
            f"Run {record.run_id}: {record.status}, {record.iterations} iterations, residual "
            f"{record.residual:.2e}, mesh {record.n_nodes} nodes / {record.n_elements} "
            f"elements, load case {record.load_case}, materials "
            f"{', '.join(record.material_sources) or '-'}."
        )
    scene.notes.append(
        "The design surface is the shape as cut and sewn (not inflated); the result layers "
        "are solver results. Factors of safety are banded against the required "
        f"{FOS_LIMIT:g} ({FOS_LIMIT_SOURCE}); anything below it is orange and labelled FAIL."
    )
    scene.notes.append(
        "EnvelopeLab is a design aid, not certified engineering software. The builder is "
        "responsible for airworthiness."
    )
    titles = scene.coloring_titles()
    scene.initial = next((k for k in ("fos_warp", "n1") if k in titles), "")
    return scene


def status_line(view: View3DPanel) -> str:
    """The view's banner in one line, for the pack's cover."""
    if not view.banner.kind:
        return "No solver result: the pack shows the design only."
    return f"{view.banner.title.text()} {view.banner.message.text()}".strip()
