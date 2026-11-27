"""Self-contained 3D viewer page for a build pack (one HTML file, no network, no library).

The page draws the parts of the balloon (the design surface, the inflated result of a
run, the special shapes and the rigging) with a small WebGL renderer written for it:
orbit, pan and zoom with the mouse, standard views, layer check boxes, the colourings
the 3D view of the application offers (factor of safety, deviation from design, ...)
with their legend, gore numbers, and the run's status banner. It opens in any current
browser from the pack folder, offline: the scene data is embedded (base64 Float32 /
Uint8 arrays) and no file is fetched.

Safety: the status banner is generated from the same facts as the application's banner
(:class:`SceneStatus`); a stale or unconverged result is never coloured by a field and
says so on its layer and in the banner; a preview result is labelled *preview*.

What is drawn is decided by the caller: :func:`design_scene` gives the design surface,
its seams, gore numbers and the rigging from the design alone; the application adds the
result layers and their colourings (``envelopelab_app.pack_scene``). Every colour is
given per triangle or per point as RGB, so the page only draws; no value is computed in
the browser.
"""

from __future__ import annotations

import base64
import html
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from envelopelab.solvers.membrane import FloatArray

if TYPE_CHECKING:
    from envelopelab.design.model import DesignDocument
    from envelopelab.export.scale_model import ScaleModel
    from envelopelab.features.primitives import PrimitiveDesign
    from envelopelab.rigging import RiggingOutputs

VIEWER_FORMAT = "envelopelab-viewer/2"
#: What the balloon can be drawn as, in the order the page offers them (the
#: application's 3D view *Shape* choice): every object as designed, or as inflated by
#: the latest preview or CalculiX run.
STATES: tuple[tuple[str, str], ...] = (
    ("design", "Designed"),
    ("envelopelab-preview", "Inflated (preview)"),
    ("calculix", "Inflated (CalculiX)"),
)
#: The state a page opens on when the caller gives none: the first, in this order, that
#: some object has (CalculiX's inflated shape, else the preview's, else the design).
OPENING_ORDER = ("calculix", "envelopelab-preview", "design")
#: Banner colours per status (background, border, text), the same as the application's
#: theme (``envelopelab_app.theme.STATUS_STYLES``; a test keeps them equal).
STATUS_COLORS = {
    "ok": ("#e9f2fb", "#1d5fb4", "#0f2f57"),
    "info": ("#e9f2fb", "#1d5fb4", "#0f2f57"),
    "stale": ("#eceff3", "#6b7280", "#1f2933"),
    "fail": ("#fff1e6", "#d9480f", "#6b2504"),
    "error": ("#fdecec", "#b42318", "#6e1610"),
}
STATUS_SYMBOLS = {"ok": "✓", "info": "i", "stale": "◷", "fail": "▲", "error": "✕"}
#: Layer colours of the parts the design alone gives (hex).
DESIGN_COLOR = "#b8c4d0"
#: A special shape as designed (the application's shape layer colour).
SHAPE_COLOR = "#e7298a"
SEAM_COLOR = "#44505c"
RIGGING_COLOR = "#7b4fa6"


@dataclass
class Legend:
    """The key of a colouring: a title and (colour, label) entries, lowest first."""

    title: str
    entries: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Coloring:
    """Colours of one mesh for one field.

    Attributes
    ----------
    key : str
        Field key (the same on every mesh that has it, e.g. ``fos_warp``).
    title : str
        Name in the *Colour by* list.
    rgb : ndarray of uint8, shape (k, 3)
        Colour per triangle (``location`` "face") or per point ("point").
    location : {"face", "point"}
    legend : Legend
    """

    key: str
    title: str
    rgb: np.ndarray
    location: str
    legend: Legend


@dataclass
class SceneMesh:
    """A surface: points (m) and triangles, a layer colour and optional colourings.

    ``note`` is the layer's status ("", "stale", "not converged", "preview" ...), shown
    on its row; a stale or unconverged result is given no colourings. ``role`` is
    ``design``, ``result`` or ``other``.

    ``obj`` is the object on the balloon it draws (the page's *Objects* list, as in the
    application's 3D view): ``envelope``, ``shape:<name>``, ``overlay:<name>`` or
    ``rigging``. ``state`` is what it draws that object as: ``design``, or a solver's
    inflated result (``envelopelab-preview``, ``calculix``); None for a part drawn in
    every state (the rigging). The page shows, for each ticked object, its parts of the
    chosen state, else (that run did not solve it) its designed parts. A colouring key
    ``<field>@<state>`` on a designed part is that state's field drawn on the design
    (the deviation).
    """

    key: str
    name: str
    group: str
    points: FloatArray
    triangles: np.ndarray
    color: str = DESIGN_COLOR
    visible: bool = True
    note: str = ""
    face_rgb: np.ndarray | None = None
    colorings: dict[str, Coloring] = field(default_factory=dict)
    role: str = "other"
    smooth: bool = True
    obj: str = "envelope"
    state: str | None = "design"


@dataclass
class SceneLines:
    """Polylines (m), each of shape (k, 3), drawn in one colour; ``obj`` and ``state``
    as for :class:`SceneMesh`."""

    key: str
    name: str
    group: str
    polylines: list[FloatArray]
    color: str = SEAM_COLOR
    visible: bool = True
    role: str = "other"
    obj: str = "envelope"
    state: str | None = "design"


@dataclass(frozen=True)
class SceneStatus:
    """The banner: a status kind (keys of :data:`STATUS_COLORS`), a title and a message."""

    kind: str
    title: str
    message: str = ""


@dataclass
class Scene:
    """Everything the viewer page draws.

    Attributes
    ----------
    title : str
        Page title (the design name).
    meshes, lines : list
        Parts, in layer-list order.
    labels : list of (str, ndarray)
        Text placed at a point (m): gore numbers.
    status : SceneStatus
        The banner.
    notes : list of str
        Lines under the viewer (what is shown, provenance, safety notice).
    initial : str
        Colouring shown when the page opens ("" for layer colours).
    state : str
        What the balloon is drawn as when the page opens (keys of :data:`STATES`; ""
        picks the first of :data:`OPENING_ORDER` that some part has).
    statuses : dict of str to SceneStatus
        The banner of each state (the run it shows); ``status`` for a state not listed.
    """

    title: str
    meshes: list[SceneMesh] = field(default_factory=list)
    lines: list[SceneLines] = field(default_factory=list)
    labels: list[tuple[str, FloatArray]] = field(default_factory=list)
    status: SceneStatus = field(
        default_factory=lambda: SceneStatus("info", "Design only.", "No solver result shown.")
    )
    notes: list[str] = field(default_factory=list)
    initial: str = ""
    state: str = ""
    statuses: dict[str, SceneStatus] = field(default_factory=dict)

    def coloring_titles(self) -> dict[str, str]:
        """Every colouring key with its title, in first-seen order (a field drawn on the
        design for one state, ``<field>@<state>``, is listed as its field)."""
        out: dict[str, str] = {}
        for mesh in self.meshes:
            for key, c in mesh.colorings.items():
                out.setdefault(key.split("@", 1)[0], c.title)
        return out

    def states(self) -> list[str]:
        """The states some part is drawn in, in :data:`STATES` order (``design``
        always)."""
        have = {m.state for m in self.meshes} | {ln.state for ln in self.lines}
        return [k for k, _t in STATES if k == "design" or k in have]

    def opening_state(self) -> str:
        """The state the page opens on (:attr:`state`, else :data:`OPENING_ORDER`)."""
        states = self.states()
        if self.state in states:
            return self.state
        return next(k for k in OPENING_ORDER if k in states)

    def objects(self) -> list[tuple[str, str, str]]:
        """Every object with a part: (key, label, group), envelope first, then the
        special shapes, the overlays and the rest (the application's Objects list)."""
        keys: list[str] = []
        for obj in [*(m.obj for m in self.meshes), *(ln.obj for ln in self.lines)]:
            if obj not in keys:
                keys.append(obj)

        def rank(key: str) -> int:
            if key == "envelope":
                return 0
            if key.startswith("shape:"):
                return 1
            if key.startswith("overlay:"):
                return 2
            return 3

        out = []
        for key in sorted(keys, key=rank):
            if key.startswith("shape:"):
                out.append((key, key.removeprefix("shape:"), "Special shapes"))
            elif key.startswith("overlay:"):
                out.append((key, key.removeprefix("overlay:"), "Overlays"))
            else:
                out.append((key, key.capitalize(), ""))
        return out


def _b64(array: np.ndarray, dtype: Any) -> str:
    return base64.b64encode(np.ascontiguousarray(array, dtype=dtype).tobytes()).decode("ascii")


def _rgb(hex_colour: str) -> list[int]:
    h = hex_colour.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)]


def _expanded(mesh: SceneMesh, rgb: np.ndarray, location: str) -> np.ndarray:
    """Per-vertex colours of the triangle-expanded mesh (3 vertices per triangle)."""
    rgb = np.asarray(rgb, dtype=np.uint8)
    if location == "face":
        return np.repeat(rgb, 3, axis=0)
    out: np.ndarray = rgb[np.asarray(mesh.triangles).reshape(-1)]
    return out


def scene_data(scene: Scene) -> dict[str, Any]:
    """The scene as the JSON object the page reads (arrays base64-encoded)."""
    meshes = []
    for m in scene.meshes:
        tris = np.asarray(m.triangles, dtype=np.int64).reshape(-1, 3)
        pts = np.asarray(m.points, dtype=np.float64)
        positions = pts[tris.reshape(-1)]
        entry: dict[str, Any] = {
            "key": m.key,
            "name": m.name,
            "group": m.group,
            "note": m.note,
            "role": m.role,
            "object": m.obj,
            "state": m.state,
            "smooth": m.smooth,
            "visible": m.visible,
            "color": _rgb(m.color),
            "triangles": len(tris),
            "positions": _b64(positions, "<f4"),
            "colorings": {},
        }
        if m.face_rgb is not None:
            entry["base"] = _b64(_expanded(m, m.face_rgb, "face"), np.uint8)
        for key, c in m.colorings.items():
            entry["colorings"][key] = {
                "rgb": _b64(_expanded(m, c.rgb, c.location), np.uint8),
                "legend": {"title": c.legend.title, "entries": c.legend.entries},
            }
        meshes.append(entry)
    lines = []
    for ln in scene.lines:
        segments = [
            np.column_stack((p[:-1], p[1:])).reshape(-1, 3)
            for p in (np.asarray(q, dtype=np.float64) for q in ln.polylines)
            if len(p) >= 2
        ]
        seg = np.vstack(segments) if segments else np.zeros((0, 3))
        lines.append(
            {
                "key": ln.key,
                "name": ln.name,
                "group": ln.group,
                "role": ln.role,
                "object": ln.obj,
                "state": ln.state,
                "visible": ln.visible,
                "color": _rgb(ln.color),
                "vertices": len(seg),
                "positions": _b64(seg, "<f4"),
            }
        )
    every = [np.asarray(m.points, dtype=np.float64) for m in scene.meshes if len(m.points)]
    every += [np.asarray(p, dtype=np.float64) for ln in scene.lines for p in ln.polylines]
    pts = np.vstack(every) if every else np.zeros((1, 3))
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return {
        "format": VIEWER_FORMAT,
        "title": scene.title,
        "bounds": [lo.tolist(), hi.tolist()],
        "meshes": meshes,
        "lines": lines,
        "labels": [{"text": t, "at": np.asarray(p, dtype=float).tolist()} for t, p in scene.labels],
        "colorings": scene.coloring_titles(),
        "initial": scene.initial if scene.initial in scene.coloring_titles() else "",
        "status": _status(scene.status),
        "states": [[k, t] for k, t in STATES if k in scene.states()],
        "state": scene.opening_state(),
        "statuses": {k: _status(v) for k, v in scene.statuses.items()},
        "objects": [{"key": k, "label": t, "group": g} for k, t, g in scene.objects()],
    }


def _status(status: SceneStatus) -> dict[str, str]:
    return {
        "kind": status.kind,
        "symbol": STATUS_SYMBOLS[status.kind],
        "title": status.title,
        "message": status.message,
    }


def design_scene(
    design: DesignDocument,
    rigging: RiggingOutputs | None = None,
    status: SceneStatus | None = None,
    colours: Any = None,
    model: ScaleModel | None = None,
    shapes: Sequence[PrimitiveDesign] = (),
) -> Scene:
    """The parts a design gives without a solver run.

    Parameters
    ----------
    design : DesignDocument
        Standard-gore design, m.
    rigging : RiggingOutputs, optional
        Its rigging outputs, for the parachute, lines and flying wires.
    status : SceneStatus, optional
        The banner (default: design only, no solver result).
    colours : PanelColours, optional
        Panel colours (ADR-0055): coloured panels are drawn in their colour, the others
        in the design colour.
    model : ScaleModel, optional
        ``design`` is a scale model's (already scaled): the banner says so (unless
        ``status`` is given) and the basket is drawn at the model's scale.
    shapes : sequence of PrimitiveDesign
        Special shapes placed on the design, drawn as designed (:func:`shape_parts`),
        each an object of its own.

    Returns
    -------
    Scene
        The design surface (the shape as cut and sewn, not inflated), its vertical and
        horizontal seams, gore numbers at the widest section, and the rigging.
    """
    from envelopelab.project.gore_design import display_surface

    surface = display_surface(design)
    scene = Scene(title=design.meta.name or "EnvelopeLab design")
    if status is None and model is not None:
        status = model_status(model.label())
    if status is not None:
        scene.status = status
    shade = np.array(_rgb(DESIGN_COLOR), dtype=np.float64)
    gores = np.asarray(surface.face_gore)
    face_rgb = np.where((gores % 2 == 0)[:, None], shade * 0.88, shade).astype(np.uint8)
    if colours is not None and not colours.is_empty():
        from envelopelab.project.colours import envelope_face_colours, face_halves

        assert design.gores is not None
        painted, mask = envelope_face_colours(
            colours,
            surface.row_letters,
            surface.face_row,
            surface.face_gore,
            face_halves(surface.points, surface.faces, design.gores.count),
            [r.letter for r in design.gores.panel_rows if r.half_gore],
        )
        face_rgb[mask] = np.round(painted[mask] * 255.0).astype(np.uint8)
    scene.meshes.append(
        SceneMesh(
            "design",
            "Design surface",
            "Design",
            np.asarray(surface.points),
            np.asarray(surface.faces),
            face_rgb=face_rgb,
            role="design",
        )
    )
    scene.lines.append(
        SceneLines(
            "seams",
            "Seams",
            "Design",
            [*surface.vertical_seams, *surface.horizontal_seams],
            role="design",
        )
    )
    points = np.asarray(surface.points)
    widest = float(np.max(np.hypot(points[:, 0], points[:, 1])))
    for k in range(1, int(gores.max()) + 1):
        centre = np.asarray(surface.points)[np.asarray(surface.faces)[gores == k]].reshape(-1, 3)
        r = np.hypot(centre[:, 0], centre[:, 1])
        ring = centre[r > 0.98 * r.max()]
        at = ring.mean(axis=0)
        at[:2] *= 1.04 * widest / max(float(np.hypot(at[0], at[1])), 1e-9)
        scene.labels.append((f"G{k}", at))
    if rigging is not None:
        from envelopelab.rigging import rigging_polylines

        lines = rigging_polylines(design, rigging)
        flat = [p for kind in lines.values() for p in kind]
        if flat:
            scene.lines.append(
                SceneLines(
                    "rigging", "Rigging", "Rigging", flat, RIGGING_COLOR, obj="rigging", state=None
                )
            )
        wires = lines.get("flying_wires", [])
        if wires:
            scale = 1.0 if model is None else model.factor
            scene.meshes.append(basket(min(float(np.min(w[:, 2])) for w in wires), scale))
    for shape in shapes:
        mesh, seams = shape_parts(shape)
        scene.meshes.append(mesh)
        if seams is not None:
            scene.lines.append(seams)
    return scene


def shape_parts(shape: PrimitiveDesign) -> tuple[SceneMesh, SceneLines | None]:
    """A special shape as designed (:func:`envelopelab.features.scene.designed_display`,
    m): its skin, object ``shape:<name>`` in state ``design``, and its seams and rim
    (None when it has none)."""
    from envelopelab.features.scene import designed_display

    display = designed_display(shape)
    name = shape.primitive.name
    obj = f"shape:{name}"
    mesh = SceneMesh(
        obj,
        f"{name} (designed)",
        "Design",
        np.asarray(display.points),
        np.asarray(display.triangles),
        SHAPE_COLOR,
        role="design",
        obj=obj,
    )
    seams = [np.asarray(q) for q in display.seams]
    if len(display.rim):
        seams.append(np.asarray(display.rim))
    lines = (
        SceneLines(f"{obj}:seams", f"{name} seams", "Design", seams, role="design", obj=obj)
        if seams
        else None
    )
    return mesh, lines


def model_status(scale: str) -> SceneStatus:
    """The banner of a scale model's 3D view (``scale`` e.g. ``1:20``)."""
    return SceneStatus(
        "info",
        f"Scale model {scale}.",
        "Designed shape at model size; no simulation results (loads and stresses do not "
        "scale with the patterns).",
    )


def scale_scene(scene: Scene, factor: float, scale: str) -> Scene:
    """A full-size 3D view at a scale model's size: every object in every Shape state of
    ``scene`` (designed and inflated), the same objects, rows and states, geometrically
    scaled.

    Lengths scale by ``factor``; loads, stresses and factors of safety do not, so every
    analysis colouring is dropped (the fabric colours stay) and each inflated state's
    banner says it is the full-size run's shape scaled, keeping the run's own status
    kind (a stale, unconverged or failing run still shows as such) and its part notes.

    Parameters
    ----------
    scene : Scene
        The full-size view (positions in m).
    factor : float
        Model length / full-size length, -, in (0, 1].
    scale : str
        The model's label, e.g. ``1:20``.

    Returns
    -------
    Scene
        A new scene, positions in m at model size; ``scene`` is not changed.
    """
    if not 0.0 < factor <= 1.0:
        raise ValueError(f"scale factor must be in (0, 1], got {factor}")
    na = (
        "Shape of the full-size run scaled by the model's factor; loads, stresses and "
        "factors of safety are n/a for a scale model."
    )
    out = Scene(
        title=f"{scene.title} - scale model {scale}",
        labels=[(t, np.asarray(p, dtype=np.float64) * factor) for t, p in scene.labels],
        notes=[
            f"Scale model {scale}: every object is drawn at model size. The inflated "
            "shapes are the full-size runs' shapes scaled; their analysis colourings are "
            "left out (they do not scale).",
            *scene.notes,
        ],
        initial="",
        state=scene.state,
    )
    for m in scene.meshes:
        out.meshes.append(
            SceneMesh(
                m.key,
                m.name,
                m.group,
                np.asarray(m.points, dtype=np.float64) * factor,
                np.asarray(m.triangles),
                m.color,
                m.visible,
                m.note,
                None if m.face_rgb is None else np.asarray(m.face_rgb),
                {},
                m.role,
                m.smooth,
                m.obj,
                m.state,
            )
        )
    for ln in scene.lines:
        out.lines.append(
            SceneLines(
                ln.key,
                ln.name,
                ln.group,
                [np.asarray(p, dtype=np.float64) * factor for p in ln.polylines],
                ln.color,
                ln.visible,
                ln.role,
                ln.obj,
                ln.state,
            )
        )
    out.statuses["design"] = model_status(scale)
    for state in out.states():
        if state == "design":
            continue
        full = scene.statuses.get(state, scene.status)
        kind = full.kind if full.kind not in ("ok", "info") else "info"
        message = f"{full.title} {full.message}".strip()
        out.statuses[state] = SceneStatus(
            kind, f"Scale model {scale}: {_state_title(state)}.", f"{na} Full-size run: {message}"
        )
    out.status = out.statuses.get(out.opening_state(), out.statuses["design"])
    return out


def _state_title(state: str) -> str:
    return dict(STATES).get(state, state)


def model_shape_scene(design: DesignDocument, shape: PrimitiveDesign, scale: str) -> Scene:
    """The 3D view of one special shape of a scale model: the shape as designed at model
    size (:func:`envelopelab.features.scene.designed_display`, m) with its seams, and the
    scale-model banner (:func:`model_status`); never a simulation result.

    Parameters
    ----------
    design : DesignDocument
        The scaled design (its name titles the view).
    shape : PrimitiveDesign
        The shape placed on the scaled envelope.
    scale : str
        The scale, e.g. ``1:20``.
    """
    name = shape.primitive.name
    scene = Scene(title=f"{design.meta.name} - {name}")
    mesh, seams = shape_parts(shape)
    scene.meshes.append(mesh)
    if seams is not None:
        scene.lines.append(seams)
    scene.status = model_status(scale)
    return scene


#: Basket drawn under the burner frame (display only, m; source: assumed).
BASKET_SIZE = (1.3, 1.3, 1.1)
BASKET_COLOR = "#a8743a"


def basket(frame_height: float, scale: float = 1.0) -> SceneMesh:
    """A basket box (display only) hanging under the burner frame at ``frame_height`` m,
    its size times ``scale`` (dimensionless; a scale model's factor)."""
    w, d, h = (scale * v for v in BASKET_SIZE)
    top = frame_height - 0.25 * scale
    x, y = w / 2, d / 2
    pts = np.array(
        [[sx * x, sy * y, top - h * sz] for sz in (0, 1) for sy in (-1, 1) for sx in (-1, 1)]
    )
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = np.array([t for a, b, c, e in quads for t in ((a, b, c), (a, c, e))])
    return SceneMesh(
        "basket",
        "Basket",
        "Rigging",
        pts,
        tris,
        BASKET_COLOR,
        smooth=False,
        obj="rigging",
        state=None,
    )


def _escape_json(data: Mapping[str, Any]) -> str:
    # Inside <script>: no "</" may appear (a label could hold one).
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


def render_html(scene: Scene) -> str:
    """The viewer page (one self-contained HTML document)."""
    data = scene_data(scene)
    bg, border, text = STATUS_COLORS[scene.status.kind]
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in scene.notes)
    title = html.escape(scene.title)
    return (
        _page()
        .replace("__TITLE__", title)
        .replace("__BANNER_BG__", bg)
        .replace("__BANNER_BORDER__", border)
        .replace("__BANNER_TEXT__", text)
        .replace("__NOTES__", notes)
        .replace("__DATA__", _escape_json(data))
    )


def write_viewer(scene: Scene, path: str | Path) -> Path:
    """Write :func:`render_html` of ``scene`` to ``path`` (UTF-8)."""
    out = Path(path)
    out.write_text(render_html(scene), encoding="utf-8")
    return out


def read_scene(path: str | Path) -> dict[str, Any]:
    """The scene object embedded in a viewer page (for the pack QA and tests)."""
    text = Path(path).read_text(encoding="utf-8")
    start = text.index('<script id="scene" type="application/json">') + len(
        '<script id="scene" type="application/json">'
    )
    end = text.index("</script>", start)
    return dict(json.loads(text[start:end]))


def decoded(entry: Mapping[str, Any], key: str = "positions") -> np.ndarray:
    """A base64 Float32 array of a scene entry, shape (k, 3)."""
    raw = base64.b64decode(entry[key])
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 3)


def legend_entries(colors: Sequence[str], labels: Sequence[str]) -> list[tuple[str, str]]:
    """(colour, label) pairs for a :class:`Legend`."""
    return list(zip(colors, labels, strict=True))


def _page() -> str:
    """The page template (``viewer_page.html`` next to this module)."""
    from importlib.resources import files

    return (files("envelopelab.export") / "viewer_page.html").read_text(encoding="utf-8")
