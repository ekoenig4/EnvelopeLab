"""Viewpoints of the 3D view (camera maths, no renderer needed)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab_app.camera import VIEWS, gore_step, turn_about_axis, view_pose
from envelopelab_app.main_window import MainWindow

BOUNDS = (-9.0, 9.0, -9.0, 9.0, 0.0, 15.0)  # a full-size envelope, m


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_every_view_looks_at_the_centre_and_fits_the_scene(view: str) -> None:
    pose = view_pose(BOUNDS, view, 30.0)
    assert pose.focal_point == pytest.approx([0.0, 0.0, 7.5])
    sight = pose.focal_point - pose.position
    radius = 0.5 * math.sqrt(18.0**2 + 18.0**2 + 15.0**2)
    # The scene's bounding sphere fits the 30 deg view angle, with the margin.
    half_angle = math.asin(radius / float(np.linalg.norm(sight)))
    assert math.degrees(2.0 * half_angle) < 30.0
    # The up vector is square to the line of sight.
    assert abs(float(np.dot(sight, pose.view_up))) < 1e-9 * float(np.linalg.norm(sight))


def test_side_views_keep_the_mouth_down_and_top_bottom_look_along_the_axis() -> None:
    front = view_pose(BOUNDS, "front")
    assert front.position[1] < 0.0 and front.view_up == pytest.approx([0.0, 0.0, 1.0])
    top = view_pose(BOUNDS, "top")
    bottom = view_pose(BOUNDS, "bottom")
    assert top.position[:2] == pytest.approx([0.0, 0.0]) and top.position[2] > 15.0
    assert bottom.position[:2] == pytest.approx([0.0, 0.0]) and bottom.position[2] < 0.0
    with pytest.raises(ValueError, match="unknown view"):
        view_pose(BOUNDS, "under")


def test_a_gore_step_turns_the_camera_one_gore_about_the_axis() -> None:
    front = view_pose(BOUNDS, "front")
    step = gore_step(20)
    assert step == pytest.approx(math.radians(18.0))
    turned = turn_about_axis(front, step)
    before = math.atan2(front.position[1], front.position[0])
    after = math.atan2(turned.position[1], turned.position[0])
    assert math.degrees(after - before) == pytest.approx(18.0)
    assert turned.position[2] == pytest.approx(front.position[2])
    back = turn_about_axis(turned, -step)
    assert back.position == pytest.approx(front.position)
    with pytest.raises(ValueError):
        gore_step(0)


def test_view_controls_are_there_and_harmless_without_a_renderer(
    gore_window: MainWindow,
) -> None:
    view = gore_window.view3d
    assert view.plotter is None
    expected = {"front", "back", "right", "left", "top", "bottom", "iso", "fit"}
    assert expected | {"gore_prev", "gore_next"} == set(view.view_buttons)
    for button in view.view_buttons.values():
        button.click()
    view.orthographic.setChecked(True)
