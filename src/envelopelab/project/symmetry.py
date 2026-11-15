r"""Symmetry axes and mirror twins of special shapes (ADR-0043).

A **symmetry axis** is a named meridian plane of the envelope, at a gore position
:math:`g_m` (gore widths from the first seam: gore :math:`n`'s centreline is
:math:`n - \tfrac12`, the seam after it :math:`n`). It is saved with the design state and
drawn on the envelope in the 3D view.

A **mirror twin** is a shape linked to another (its *source*) across an axis: its
``mirror`` field names the source and the axis. A twin always is the source's mirror
image (:func:`envelopelab.project.shape_groups.mirrored`): placement, lean direction, feed
holes, seam turn, panel widths, a mesh's geometry, every size and its group. It is stored
in full, so placing, checking, simulating and exporting it need nothing special.

:func:`sync_twins` keeps the link after every edit of the shapes or the axes: when an
edit changed a twin but not its source, the change goes to the source first (so editing
or dragging either side works); then every twin is made the mirror image of its source
again. Moving an axis therefore moves its twins.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

NAME_PATTERN = r"^[A-Za-z0-9_\- ]+$"


class SymmetryAxis(BaseModel):
    """A named symmetry axis: the meridian plane at a gore position.

    Attributes
    ----------
    name : str
        Axis name (unique in a project), e.g. ``Face centre``.
    line : float
        Gore position of the plane, gore widths from the first seam, in [0, N): gore
        :math:`n`'s centreline is :math:`n - 1/2`, the seam after it :math:`n`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40, pattern=NAME_PATTERN)
    line: float = Field(ge=0.0)


class MirrorLink(BaseModel):
    """What a mirror twin mirrors: its source shape and the axis it is mirrored across."""

    model_config = ConfigDict(extra="forbid")

    of: str = Field(min_length=1)
    axis: str = Field(min_length=1)


def axis_gore_label(line: float, gores: int) -> str:
    """Where an axis lies, in words (``centre of gore 6``, ``seam 6|7``, ``gore 6 +0.25``)."""
    g = line % gores
    cell = int(g // 1)
    frac = g - cell
    if abs(frac - 0.5) < 1e-9:
        return f"centre of gore {cell + 1}"
    if frac < 1e-9:
        left = cell if cell > 0 else gores
        return f"seam {left}|{cell + 1}"
    return f"gore {cell + 1} {frac - 0.5:+.2f}"


def mirrored_data(data: dict[str, Any], line: float, gores: int) -> dict[str, Any]:
    """The mirror image (JSON data) of shape data ``data`` across the axis at ``line``."""
    from pydantic import TypeAdapter

    from envelopelab.project.shape_groups import mirrored
    from envelopelab.project.shapes import ShapeSpec

    spec: ShapeSpec = TypeAdapter(ShapeSpec).validate_python(data)
    return mirrored(spec, line, gores)


def sync_twins(
    before: list[dict[str, Any]],
    shapes: list[dict[str, Any]],
    axes: list[dict[str, Any]],
    gores: int,
) -> None:
    """Make every mirror twin the mirror image of its source again (module docstring).

    Parameters
    ----------
    before : list of dict
        The shapes' data before the edit (to tell which side was edited).
    shapes : list of dict
        The shapes' data after the edit; changed in place.
    axes : list of dict
        The symmetry axes' data.
    gores : int
        Number of gores N.

    Raises
    ------
    ValueError
        For a twin of an unknown shape or axis, a twin of a twin, or two twins of one
        shape across the same axis.
    """
    lines = {a["name"]: float(a["line"]) for a in axes}
    old = {s["name"]: s for s in before}
    index = {s["name"]: i for i, s in enumerate(shapes)}
    twins = [s["name"] for s in shapes if s.get("mirror")]
    pairs: set[tuple[str, str]] = set()
    for name in twins:
        link = shapes[index[name]]["mirror"]
        if link["of"] not in index:
            raise ValueError(f"{name}: mirror of {link['of']!r}, which is not a shape")
        if link["axis"] not in lines:
            raise ValueError(f"{name}: mirrored across {link['axis']!r}, which is not an axis")
        if link["of"] == name or shapes[index[link["of"]]].get("mirror"):
            raise ValueError(f"{name}: a mirror twin cannot mirror another twin or itself")
        if (link["of"], link["axis"]) in pairs:
            raise ValueError(f"{link['of']} has two mirror twins across {link['axis']}")
        pairs.add((link["of"], link["axis"]))

    def content(data: dict[str, Any] | None) -> dict[str, Any] | None:
        # The link is not the shape: renaming an axis or a source changes only links.
        return None if data is None else {k: v for k, v in data.items() if k != "mirror"}

    # An edited twin whose source was not edited carries the edit to its source.
    for name in twins:
        twin = shapes[index[name]]
        link = twin["mirror"]
        source = shapes[index[link["of"]]]
        if content(old.get(name)) != content(twin) and content(old.get(source["name"])) == content(
            source
        ):
            new = mirrored_data(twin, lines[link["axis"]], gores)
            new.update(name=source["name"], mirror=None, group=twin.get("group"))
            shapes[index[source["name"]]] = new
    for name in twins:
        link = shapes[index[name]]["mirror"]
        source = shapes[index[link["of"]]]
        new = mirrored_data(source, lines[link["axis"]], gores)
        new.update(name=name, mirror=link, group=source.get("group"))
        shapes[index[name]] = new


def symmetry_lines(design: Any, axes: list[SymmetryAxis], samples: int = 121) -> list[Any]:
    """Every axis as a line on the envelope's display surface from the mouth to the
    crown, m (:func:`envelopelab.project.gore_design.display_points`); a little outside
    the surface so it is not hidden by it."""
    import math

    import numpy as np

    from envelopelab.project.gore_design import design_profile, display_points

    gores = design.gores.count
    length = float(design_profile(design).meridian_length)
    s = np.linspace(0.0, length, samples)
    out = []
    for axis in axes:
        theta = np.full(samples, 2.0 * math.pi * (axis.line % gores) / gores)
        pts = display_points(design, s, theta)
        radial = pts.copy()
        radial[:, 2] = 0.0
        norm = np.linalg.norm(radial, axis=1, keepdims=True)
        out.append(pts + 0.02 * np.divide(radial, norm, out=np.zeros_like(radial), where=norm > 0))
    return out


def twins_of(shapes: list[Any], name: str) -> list[Any]:
    """The mirror twins of shape ``name`` (specs or data)."""

    def link(s: Any) -> Any:
        return s.get("mirror") if isinstance(s, dict) else s.mirror

    out = []
    for s in shapes:
        m = link(s)
        if m is not None and (m["of"] if isinstance(m, dict) else m.of) == name:
            out.append(s)
    return out
