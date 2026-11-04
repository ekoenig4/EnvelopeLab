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
    from envelopelab.rigging import RiggingOutputs

VIEWER_FORMAT = "envelopelab-viewer/1"
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
    ``design`` (shown for the deviation from design, hidden for a result field, as in the
    application), ``result`` (the reverse) or ``other`` (left as it is).
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


@dataclass
class SceneLines:
    """Polylines (m), each of shape (k, 3), drawn in one colour."""

    key: str
    name: str
    group: str
    polylines: list[FloatArray]
    color: str = SEAM_COLOR
    visible: bool = True
    role: str = "other"


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

    def coloring_titles(self) -> dict[str, str]:
        """Every colouring key with its title, in first-seen order."""
        out: dict[str, str] = {}
        for mesh in self.meshes:
            for key, c in mesh.colorings.items():
                out.setdefault(key, c.title)
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
        "status": {
            "kind": scene.status.kind,
            "symbol": STATUS_SYMBOLS[scene.status.kind],
            "title": scene.status.title,
            "message": scene.status.message,
        },
    }


def design_scene(
    design: DesignDocument,
    rigging: RiggingOutputs | None = None,
    status: SceneStatus | None = None,
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

    Returns
    -------
    Scene
        The design surface (the shape as cut and sewn, not inflated), its vertical and
        horizontal seams, gore numbers at the widest section, and the rigging.
    """
    from envelopelab.project.gore_design import display_surface

    surface = display_surface(design)
    scene = Scene(title=design.meta.name or "EnvelopeLab design")
    if status is not None:
        scene.status = status
    shade = np.array(_rgb(DESIGN_COLOR), dtype=np.float64)
    gores = np.asarray(surface.face_gore)
    face_rgb = np.where((gores % 2 == 0)[:, None], shade * 0.88, shade).astype(np.uint8)
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
            scene.lines.append(SceneLines("rigging", "Rigging", "Rigging", flat, RIGGING_COLOR))
        wires = lines.get("flying_wires", [])
        if wires:
            scene.meshes.append(basket(min(float(np.min(w[:, 2])) for w in wires)))
    return scene


#: Basket drawn under the burner frame (display only, m; source: assumed).
BASKET_SIZE = (1.3, 1.3, 1.1)
BASKET_COLOR = "#a8743a"


def basket(frame_height: float) -> SceneMesh:
    """A basket box (display only) hanging under the burner frame at ``frame_height`` m."""
    w, d, h = BASKET_SIZE
    top = frame_height - 0.25
    x, y = w / 2, d / 2
    pts = np.array(
        [[sx * x, sy * y, top - h * sz] for sz in (0, 1) for sy in (-1, 1) for sx in (-1, 1)]
    )
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = np.array([t for a, b, c, e in quads for t in ((a, b, c), (a, c, e))])
    return SceneMesh("basket", "Basket", "Rigging", pts, tris, BASKET_COLOR, smooth=False)


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
