"""Viewpoints of the 3D view (camera maths, no renderer needed)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from envelopelab_app.camera import VIEWS, CameraPose, gore_step, turn_about_axis, view_pose
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
    assert expected | {"gore_prev", "gore_next"} <= set(view.view_buttons)
    for button in view.view_buttons.values():
        button.click()
    view.orthographic.setChecked(True)


def test_facing_a_seam_or_a_gore_centre_looks_at_the_axis_from_its_azimuth() -> None:
    from envelopelab.rigging.common import seam_azimuth
    from envelopelab_app.camera import facing, gore_centre_azimuth

    pose = facing(BOUNDS, seam_azimuth(2, 8))
    sight = pose.position - pose.focal_point
    assert math.degrees(math.atan2(sight[1], sight[0])) == pytest.approx(90.0)
    assert abs(sight[2]) < 1e-9 and pose.view_up == pytest.approx([0.0, 0.0, 1.0])
    # Gore k lies between seams k - 1 and k: gore 1 of 8 is centred at 22.5 deg.
    assert math.degrees(gore_centre_azimuth(1, 8)) == pytest.approx(22.5)
    assert math.degrees(gore_centre_azimuth(8, 8)) == pytest.approx(337.5)
    with pytest.raises(ValueError):
        gore_centre_azimuth(9, 8)


def test_zooming_to_a_box_keeps_the_direction_and_centres_it() -> None:
    from envelopelab_app.camera import fit_to_bounds

    iso = view_pose(BOUNDS, "iso")
    small = (2.0, 3.0, -1.0, 0.0, 10.0, 11.0)
    fitted = fit_to_bounds(iso, small)
    assert fitted.focal_point == pytest.approx([2.5, -0.5, 10.5])
    before = (iso.position - iso.focal_point) / np.linalg.norm(iso.position - iso.focal_point)
    after = fitted.position - fitted.focal_point
    assert after / np.linalg.norm(after) == pytest.approx(before)
    assert np.linalg.norm(after) < np.linalg.norm(iso.position - iso.focal_point)


def test_saved_views_round_trip_and_reject_damaged_data() -> None:
    from envelopelab_app.camera import pose_from_dict, pose_to_dict

    pose = view_pose(BOUNDS, "top")
    data = pose_to_dict(pose, parallel=True)
    back, parallel = pose_from_dict(data)
    assert parallel and back.position == pytest.approx(pose.position)
    assert back.view_up == pytest.approx(pose.view_up)
    with pytest.raises(ValueError, match="not a saved view"):
        pose_from_dict({"position": [0, 0]})
    with pytest.raises(ValueError, match="finite"):
        pose_from_dict({**data, "parallel_scale": float("nan")})


def test_face_zoom_and_saved_view_controls_are_harmless_without_a_renderer(
    gore_window: MainWindow,
) -> None:
    view = gore_window.view3d
    for key in ("face_seam", "face_gore", "zoom_layer", "save_view", "delete_view"):
        view.view_buttons[key].click()
    assert view.seam_number.maximum() == 8  # the fixture's gores
    assert not view.save_view("somewhere")
    assert view.saved() == []


# -- mouse navigation: the build pack page's turntable ----------------------------------


def _sight_angles(pose: CameraPose) -> tuple[float, float, float]:
    """Azimuth, elevation and roll (deg) of a camera; roll 0 means +z up on screen."""
    from envelopelab_app.camera import azimuth_elevation

    az, el = azimuth_elevation(pose)
    forward = pose.focal_point - pose.position
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, pose.view_up)
    return math.degrees(az), math.degrees(el), float(right[2])


def test_a_drag_turns_about_the_axis_and_never_rolls() -> None:
    from envelopelab_app.camera import ORBIT_RAD_PER_PIXEL, orbit

    pose = view_pose(BOUNDS, "iso")
    az0, el0, _ = _sight_angles(pose)
    turned = orbit(pose, 30.0, -12.0)
    az, el, roll = _sight_angles(turned)
    # The build pack page's rates: 0.01 rad per pixel; a drag right turns the azimuth back.
    assert az == pytest.approx(az0 - math.degrees(30 * ORBIT_RAD_PER_PIXEL))
    assert el == pytest.approx(el0 - math.degrees(12 * ORBIT_RAD_PER_PIXEL))
    assert roll == pytest.approx(0.0, abs=1e-12)  # the envelope axis stays up
    np.testing.assert_allclose(turned.focal_point, pose.focal_point)
    assert np.linalg.norm(turned.position - turned.focal_point) == pytest.approx(
        np.linalg.norm(pose.position - pose.focal_point)
    )


def test_a_drag_round_a_loop_comes_back_to_the_same_view() -> None:
    """The trackball drifts (a closed mouse path leaves the camera rolled and turned); the
    turntable returns exactly to where it started."""
    from envelopelab_app.camera import orbit

    start = view_pose(BOUNDS, "iso")
    pose = start
    for dx, dy in [(40, 0), (0, 25), (-40, 0), (0, -25)] * 20:
        for _ in range(10):
            pose = orbit(pose, dx / 10, dy / 10)
    np.testing.assert_allclose(pose.position, start.position, atol=1e-9)
    np.testing.assert_allclose(pose.view_up, start.view_up, atol=1e-9)


def test_the_camera_stops_short_of_the_axis_and_leaves_the_top_view_smoothly() -> None:
    from envelopelab_app.camera import MAX_ELEVATION, orbit

    pose = orbit(view_pose(BOUNDS, "front"), 0.0, 10_000.0)
    assert _sight_angles(pose)[1] == pytest.approx(math.degrees(MAX_ELEVATION))
    assert _sight_angles(orbit(pose, 0.0, -20_000.0))[1] == pytest.approx(
        -math.degrees(MAX_ELEVATION)
    )
    # From the top view (looking down the axis) the first drag keeps the view's up on
    # screen: the picture only tilts a little, it does not spin.
    top = view_pose(BOUNDS, "top")
    moved = orbit(top, 0.0, 0.0)
    assert float(np.dot(moved.view_up, top.view_up)) > 0.99
    bottom = view_pose(BOUNDS, "bottom")
    assert float(np.dot(orbit(bottom, 0.0, 0.0).view_up, bottom.view_up)) > 0.99


@pytest.mark.parametrize("parallel", [False, True])
def test_a_pan_moves_the_scene_with_the_mouse(parallel: bool) -> None:
    from envelopelab_app.camera import pan

    pose = view_pose(BOUNDS, "front", 30.0)
    moved = pan(pose, 100.0, 50.0, 800.0, 30.0, parallel)
    shift = moved.focal_point - pose.focal_point
    np.testing.assert_allclose(moved.position - pose.position, shift)
    distance = float(np.linalg.norm(pose.position - pose.focal_point))
    per_px = (
        2 * pose.parallel_scale / 800
        if parallel
        else 2 * distance * math.tan(math.radians(15)) / 800
    )
    # Front view: screen right is +x, screen up is +z; the scene follows the mouse, so the
    # camera moves the other way (left for a drag right, up for a drag down).
    np.testing.assert_allclose(shift, [-100 * per_px, 0.0, 50 * per_px], atol=1e-12)


def test_wheel_notches_zoom_by_the_same_factor_both_ways() -> None:
    from envelopelab_app.camera import ZOOM_PER_NOTCH, zoom

    pose = view_pose(BOUNDS, "iso")
    closer = zoom(pose, 1.0)
    d0 = np.linalg.norm(pose.position - pose.focal_point)
    assert np.linalg.norm(closer.position - closer.focal_point) == pytest.approx(
        d0 * math.exp(-ZOOM_PER_NOTCH)
    )
    assert closer.parallel_scale == pytest.approx(pose.parallel_scale * math.exp(-ZOOM_PER_NOTCH))
    back = zoom(closer, -1.0)
    np.testing.assert_allclose(back.position, pose.position)
    assert back.parallel_scale == pytest.approx(pose.parallel_scale)
