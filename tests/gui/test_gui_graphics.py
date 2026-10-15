"""OpenGL set-up at start-up: software rendering under WSL (black window otherwise)."""

from __future__ import annotations

from envelopelab_app.graphics import SOFTWARE_GL, configure_graphics, is_wsl

WSL_KERNEL = "Linux version 5.15.167.4-microsoft-standard-WSL2 (gcc 11.2.0) #1 SMP"
NATIVE_KERNEL = "Linux version 6.8.0-45-generic (buildd@lcy02-amd64-075) #45-Ubuntu SMP"


def test_wsl_is_detected_from_the_environment_or_the_kernel() -> None:
    assert is_wsl({"WSL_DISTRO_NAME": "Ubuntu"}, proc_version="")
    assert is_wsl({}, proc_version=WSL_KERNEL)
    assert not is_wsl({}, proc_version=NATIVE_KERNEL)


def test_wsl_gets_software_opengl() -> None:
    env: dict[str, str] = {}
    reason = configure_graphics(env, platform="linux", proc_version=WSL_KERNEL)
    assert env[SOFTWARE_GL] == "1" and reason is not None and "WSL" in reason


def test_native_linux_keeps_hardware_opengl() -> None:
    env: dict[str, str] = {}
    assert configure_graphics(env, platform="linux", proc_version=NATIVE_KERNEL) is None
    assert SOFTWARE_GL not in env


def test_flags_and_the_users_setting_win() -> None:
    env: dict[str, str] = {}
    assert configure_graphics(env, software=True, platform="win32") is not None
    assert env[SOFTWARE_GL] == "1"
    env = {}
    assert configure_graphics(env, hardware=True, platform="linux", proc_version=WSL_KERNEL) is None
    assert SOFTWARE_GL not in env
    env = {SOFTWARE_GL: "0"}  # set by the user: never overridden
    assert configure_graphics(env, platform="linux", proc_version=WSL_KERNEL) is None
    assert env[SOFTWARE_GL] == "0"


def test_wayland_sessions_use_the_x11_platform_the_3d_view_needs() -> None:
    from envelopelab_app.graphics import QT_PLATFORM, select_qt_platform

    # WSLg sets both: Qt would pick Wayland, where the VTK window crashes.
    env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
    reason = select_qt_platform(env, platform="linux")
    assert env[QT_PLATFORM] == "xcb" and reason is not None and "xcb" in reason
    # A choice the user made is kept; no X server, no change; not on other systems.
    kept = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", QT_PLATFORM: "wayland"}
    assert select_qt_platform(kept, platform="linux") is None and kept[QT_PLATFORM] == "wayland"
    only_wayland = {"WAYLAND_DISPLAY": "wayland-0"}
    assert select_qt_platform(only_wayland, platform="linux") is None
    assert QT_PLATFORM not in only_wayland
    assert select_qt_platform({"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}, platform="win32") is None
