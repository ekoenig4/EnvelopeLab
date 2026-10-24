"""Camera viewpoints of the 3D view: standard views of the envelope and gore steps.

The envelope's axis is the z axis (up), the mouth at the bottom. A view is a direction
from the scene centre to the camera and an up vector; the camera stands far enough back
that a sphere around the visible scene fits the view angle. Turning the view by one gore
rotates the camera about the envelope axis by :math:`360^\\circ / N`, so the same seam or
gore centre stays where it was on the screen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

#: View name: (direction from the scene centre to the camera, view-up), unnormalised.
VIEWS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "iso": ((1.0, -1.0, 0.8), (0.0, 0.0, 1.0)),
}

#: Space left around the scene, as a factor on its bounding sphere.
MARGIN = 1.1


@dataclass(frozen=True)
class CameraPose:
    """A camera: where it stands, what it looks at and which way is up (scene units)."""

    position: FloatArray
    focal_point: FloatArray
    view_up: FloatArray
    #: Half-height of the view for a parallel (orthographic) projection.
    parallel_scale: float


def view_pose(
    bounds: tuple[float, float, float, float, float, float],
    view: str,
    view_angle_deg: float = 30.0,
) -> CameraPose:
    """The camera of a standard view that shows the whole scene.

    Parameters
    ----------
    bounds : tuple of 6 float
        Scene bounds ``(xmin, xmax, ymin, ymax, zmin, zmax)``.
    view : str
        A key of :data:`VIEWS`.
    view_angle_deg : float
        Vertical view angle of the perspective camera, deg.

    Returns
    -------
    CameraPose
        Looking at the centre of the bounds from the view's direction.
    """
    if view not in VIEWS:
        raise ValueError(f"unknown view {view!r}; one of {', '.join(VIEWS)}")
    lo = np.array(bounds[0::2], dtype=np.float64)
    hi = np.array(bounds[1::2], dtype=np.float64)
    centre = 0.5 * (lo + hi)
    radius = max(0.5 * float(np.linalg.norm(hi - lo)), 1e-6)
    direction, up = (np.array(v, dtype=np.float64) for v in VIEWS[view])
    direction /= np.linalg.norm(direction)
    up -= float(np.dot(up, direction)) * direction  # square to the line of sight
    up /= np.linalg.norm(up)
    distance = MARGIN * radius / math.sin(math.radians(view_angle_deg) / 2.0)
    return CameraPose(centre + distance * direction, centre, up, MARGIN * radius)


def _rotate_z(v: FloatArray, angle: float) -> FloatArray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1], v[2]], dtype=np.float64)


def turn_about_axis(pose: CameraPose, angle_rad: float) -> CameraPose:
    """The camera turned about the envelope (z) axis by ``angle_rad`` (counter-clockwise
    seen from above): position, focal point and view-up turn together."""
    return CameraPose(
        _rotate_z(pose.position, angle_rad),
        _rotate_z(pose.focal_point, angle_rad),
        _rotate_z(pose.view_up, angle_rad),
        pose.parallel_scale,
    )


def gore_step(gore_count: int) -> float:
    """Angle of one gore, rad (:math:`2\\pi / N`)."""
    if gore_count < 1:
        raise ValueError("an envelope has at least one gore")
    return 2.0 * math.pi / gore_count
