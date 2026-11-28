"""Mouse navigation of the 3D view: the turntable of the build pack's 3D page.

VTK's default trackball turns the camera about the screen axes, so every drag adds a
little roll and the balloon slowly tips away from upright; it also turns less per pixel.
:class:`Turntable` replaces the interactor style's mouse handling with the build pack
page's: a left drag turns the camera about the vertical axis and raises or lowers it
(the envelope axis stays up on screen), a shift-left, middle or right drag pans, the
wheel zooms (``envelopelab_app.camera``: :func:`~envelopelab_app.camera.orbit`,
:func:`~envelopelab_app.camera.pan`, :func:`~envelopelab_app.camera.zoom`).

The handlers observe the interactor style, so VTK widgets (the view cube, the spline
handles, the section plane), which take their presses before the style, still work. The
camera moves on every mouse event but the view is drawn once per pass of the event loop,
so on a slow (software OpenGL) renderer the view keeps up with the mouse instead of
drawing every intermediate position.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import QTimer

from envelopelab_app.camera import CameraPose, orbit, pan, zoom

#: Mouse events the turntable handles on the interactor style.
EVENTS = (
    "LeftButtonPressEvent",
    "LeftButtonReleaseEvent",
    "MiddleButtonPressEvent",
    "MiddleButtonReleaseEvent",
    "RightButtonPressEvent",
    "RightButtonReleaseEvent",
    "MouseMoveEvent",
    "MouseWheelForwardEvent",
    "MouseWheelBackwardEvent",
)


class Turntable:
    """The build pack page's mouse navigation on a PyVista Qt render widget.

    Parameters
    ----------
    plotter : pyvistaqt.QtInteractor
        The render widget.

    Attributes
    ----------
    press_hook : callable or None
        Called on a left press; returning True takes the drag (its moves go to
        ``move_hook`` and its release to ``release_hook``) instead of turning the view.
        The Drag tool uses it to move a special shape.
    """

    def __init__(self, plotter: Any) -> None:
        self.plotter = plotter
        self.press_hook: Callable[[], bool] | None = None
        self.move_hook: Callable[[], object] | None = None
        self.release_hook: Callable[[], object] | None = None
        #: The drag in progress: "orbit", "pan", "hook", "style" (the style's own
        #: rubber-band selection) or None.
        self.mode: str | None = None
        #: Rubber-band selection is on (R toggles it in PyVista's picking style).
        self.selecting = False
        self._last = (0, 0)
        self._button = ""
        self._style: Any = None
        self._tags: list[int] = []
        self._render_pending = False
        self._char_tag = plotter.iren.interactor.AddObserver("CharEvent", self._char)
        self.attach()

    # -- set-up ------------------------------------------------------------------------

    def attach(self) -> None:
        """Handle the mouse on the interactor's current style.

        Call again after anything replaces the style (PyVista's picking does).
        """
        style = self.plotter.iren.interactor.GetInteractorStyle()
        if style is self._style:
            return
        self.detach()
        self._style = style
        self.mode = None
        self.selecting = False  # a new rubber-band style starts out turning the view
        # PyVista's styles call the default left-button handling from observers of their
        # own; those would turn the camera the trackball way as well.
        remove = getattr(style, "remove_observers", None)
        if callable(remove):
            remove()
        self._tags = [style.AddObserver(event, self._event) for event in EVENTS]

    def detach(self) -> None:
        """Give the mouse back to the style (its own handling)."""
        if self._style is not None:
            for tag in self._tags:
                self._style.RemoveObserver(tag)
        self._style = None
        self._tags = []

    def close(self) -> None:
        """Remove every observer (before the render window closes)."""
        self.detach()
        self.plotter.iren.interactor.RemoveObserver(self._char_tag)

    # -- events -------------------------------------------------------------------------

    def _char(self, interactor: Any, _event: str) -> None:
        style = interactor.GetInteractorStyle()
        if interactor.GetKeyCode() in ("r", "R") and style.IsA("vtkInteractorStyleRubberBandPick"):
            self.selecting = not self.selecting

    def _event(self, style: Any, event: str) -> None:
        interactor = self.plotter.iren.interactor
        position = interactor.GetEventPosition()
        if event.endswith("ButtonPressEvent"):
            if self.mode is not None:
                return  # another button's drag is in progress
            self._button = event.removesuffix("ButtonPressEvent")
            if self._button != "Left":
                self.mode = "pan"
            elif self.press_hook is not None and self.press_hook():
                self.mode = "hook"
            elif self.selecting:
                self.mode = "style"
                style.OnLeftButtonDown()
            else:
                self.mode = "pan" if interactor.GetShiftKey() else "orbit"
            self._last = position
        elif event == "MouseMoveEvent":
            self._move(style, position)
        elif event.endswith("ReleaseEvent"):
            self._release(style, event)
        elif event == "MouseWheelForwardEvent":
            self.apply(zoom(self.pose(), 1.0))
        elif event == "MouseWheelBackwardEvent":
            self.apply(zoom(self.pose(), -1.0))

    def _move(self, style: Any, position: tuple[int, int]) -> None:
        if self.mode == "hook":
            if self.move_hook is not None:
                self.move_hook()
            return
        if self.mode == "style" or self.mode is None:
            style.OnMouseMove()  # rubber band drawing; nothing when idle
            return
        # VTK's y runs up the window; the turntable's runs down, as on screen.
        dx, dy = position[0] - self._last[0], self._last[1] - position[1]
        self._last = position
        if dx == 0 and dy == 0:
            return
        if self.mode == "orbit":
            ratio = self._pixel_ratio()
            self.apply(orbit(self.pose(), dx / ratio, dy / ratio))
        else:
            camera = self.plotter.camera
            # The event positions are in device pixels (the render window can report 0 x 0
            # before its first draw, the widget cannot).
            height = float(self.plotter.height()) * self._pixel_ratio()
            self.apply(
                pan(
                    self.pose(),
                    dx,
                    dy,
                    height,
                    float(camera.view_angle),
                    bool(camera.parallel_projection),
                )
            )

    def _release(self, style: Any, event: str) -> None:
        if self.mode is None or event.removesuffix("ButtonReleaseEvent") != self._button:
            return  # not the button that started the drag
        mode, self.mode = self.mode, None
        if mode == "hook" and self.release_hook is not None:
            self.release_hook()
        elif mode == "style":
            style.OnLeftButtonUp()

    def _pixel_ratio(self) -> float:
        """Device pixels per screen point: turns per pixel are the page's on any screen."""
        ratio = getattr(self.plotter, "devicePixelRatioF", None)
        return float(ratio()) if callable(ratio) else 1.0

    # -- camera -------------------------------------------------------------------------

    def pose(self) -> CameraPose:
        """The camera now."""
        camera = self.plotter.camera
        return CameraPose(
            np.array(camera.position, dtype=float),
            np.array(camera.focal_point, dtype=float),
            np.array(camera.up, dtype=float),
            float(camera.parallel_scale),
        )

    def apply(self, pose: CameraPose) -> None:
        """Move the camera to ``pose`` and draw the view at the next pass of the event
        loop (once, however many mouse events arrive before it)."""
        camera = self.plotter.camera
        camera.position = tuple(pose.position)
        camera.focal_point = tuple(pose.focal_point)
        camera.up = tuple(pose.view_up)
        camera.parallel_scale = pose.parallel_scale
        if not self._render_pending:
            self._render_pending = True
            QTimer.singleShot(0, self.render)

    def render(self) -> None:
        """Draw the view now (the pending draw, if any)."""
        self._render_pending = False
        if self.plotter.iren is None:  # closed meanwhile
            return
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()
