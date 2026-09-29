#!/usr/bin/env bash
# Set up an EnvelopeLab environment: system libraries, CalculiX, a virtualenv and the
# Python package, then check that the library and the desktop application start.
#
#   bash scripts/install_env.sh              # everything (dev, docs and gui extras)
#   bash scripts/install_env.sh --help       # options
#
# Works as root (containers) or with sudo. System packages: apt (Debian, Ubuntu; tested),
# dnf (Fedora), pacman (Arch), zypper (openSUSE) (package names for the latter three are
# best effort, see docs/user/installation.md). Portable to bash 3.2 (macOS).
set -euo pipefail

# --- package lists (docs/user/installation.md shows the same lists; a test checks) ------
# Gmsh wheel (panel meshing): OpenGL/X11 client libraries.
APT_GMSH="libglu1-mesa libxcursor1 libxft2 libxinerama1"
# Qt 6 (PySide6) xcb platform plugin and VTK (PyVista) rendering.
APT_QT="libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libdbus-1-3 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 libxcb-xinerama0 libxcb-shape0"
APT_PYTHON="python3 python3-venv python3-pip"
APT_CALCULIX="calculix-ccx"
APT_XVFB="xvfb xauth"
APT_REGISTRATION="libusb-1.0-0"

DNF_GMSH="mesa-libGLU libXcursor libXft libXinerama"
DNF_QT="mesa-libEGL mesa-libGL libxkbcommon libxkbcommon-x11 fontconfig dbus-libs xcb-util-cursor xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil"
DNF_PYTHON="python3 python3-pip"
DNF_CALCULIX="calculix-ccx"
DNF_XVFB="xorg-x11-server-Xvfb xorg-x11-xauth"
DNF_REGISTRATION="libusb1"

PACMAN_GMSH="glu libxcursor libxft libxinerama"
PACMAN_QT="libglvnd mesa libxkbcommon libxkbcommon-x11 fontconfig dbus xcb-util-cursor xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil"
PACMAN_PYTHON="python python-pip"
PACMAN_CALCULIX=""  # CalculiX is only in the AUR (calculix); see docs/dev/calculix-installation.md
PACMAN_XVFB="xorg-server-xvfb xorg-xauth"
PACMAN_REGISTRATION="libusb"

ZYPPER_GMSH="libGLU1 libXcursor1 libXft2 libXinerama1"
ZYPPER_QT="libEGL1 libGL1 libxkbcommon0 libxkbcommon-x11-0 fontconfig libdbus-1-3 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 libxcb-xinerama0 libxcb-shape0"
ZYPPER_PYTHON="python311 python311-pip"
ZYPPER_CALCULIX=""  # not in the main repositories; see docs/dev/calculix-installation.md
ZYPPER_XVFB="xvfb-run xauth"
ZYPPER_REGISTRATION="libusb-1_0-0"

# --- options -------------------------------------------------------------------------
EXTRAS="dev,docs,gui"
VENV=".venv"
PYTHON="${PYTHON:-python3}"
PM=""
DO_SYSTEM=1
DO_PYTHON=1
DO_CALCULIX=1
DO_XVFB=1
DO_REGISTRATION=0
DO_CHECK=1
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: bash scripts/install_env.sh [options]

  --extras LIST          pip extras to install (default: dev,docs,gui)
  --venv DIR             virtualenv directory (default: .venv; "none" installs into
                         the current Python environment)
  --python EXE           Python >= 3.11 used to create the virtualenv (default: python3)
  --package-manager PM   apt, dnf, pacman or zypper (default: detected)
  --system-only          only install system packages
  --no-system            skip system packages (no root/sudo needed)
  --no-calculix          do not install the CalculiX verification solver (ccx)
  --no-xvfb              do not install Xvfb (virtual display for headless 3D tests)
  --registration         also install the optional Open3D registration backend
  --no-check             skip the final checks
  --dry-run              print the commands instead of running them
  -h, --help             this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --extras) EXTRAS="$2"; shift 2 ;;
        --venv) VENV="$2"; shift 2 ;;
        --python) PYTHON="$2"; shift 2 ;;
        --package-manager) PM="$2"; shift 2 ;;
        --system-only) DO_PYTHON=0; DO_CHECK=0; shift ;;
        --no-system) DO_SYSTEM=0; shift ;;
        --no-calculix) DO_CALCULIX=0; shift ;;
        --no-xvfb) DO_XVFB=0; shift ;;
        --registration) DO_REGISTRATION=1; shift ;;
        --no-check) DO_CHECK=0; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
FAILED=""

say() { printf '\n==> %s\n' "$*"; }
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '+ %s\n' "$*"
    else
        "$@"
    fi
}

# --- system packages -----------------------------------------------------------------
detect_pm() {
    for candidate in apt-get dnf pacman zypper; do
        if command -v "$candidate" >/dev/null 2>&1; then
            case "$candidate" in apt-get) echo apt ;; *) echo "$candidate" ;; esac
            return
        fi
    done
    echo none
}

SUDO=""
if [ "$(id -u 2>/dev/null || echo 0)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

pm_update() {
    case "$PM" in
        apt) run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update ;;
        dnf) : ;;
        pacman) run $SUDO pacman -Sy --noconfirm ;;
        zypper) run $SUDO zypper --non-interactive refresh ;;
    esac
}

# pm_install GROUP PACKAGES...: a group that fails is reported at the end, not fatal, so
# one package name that differs on this distribution does not stop the rest.
pm_install() {
    group="$1"; shift
    [ $# -gt 0 ] || return 0
    say "system packages ($group): $*"
    case "$PM" in
        apt) cmd="$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends" ;;
        dnf) cmd="$SUDO dnf install -y" ;;
        pacman) cmd="$SUDO pacman -S --needed --noconfirm" ;;
        zypper) cmd="$SUDO zypper --non-interactive install --no-recommends" ;;
    esac
    # shellcheck disable=SC2086
    if ! run $cmd "$@"; then
        FAILED="$FAILED $group"
        echo "!! could not install the $group packages; see docs/user/installation.md" >&2
    fi
}

packages() {  # packages PM GROUP -> the list for that package manager
    upper="$(echo "$1" | tr '[:lower:]' '[:upper:]')"
    eval "echo \${${upper}_$2}"
}

if [ "$DO_SYSTEM" -eq 1 ]; then
    [ -n "$PM" ] || PM="$(detect_pm)"
    case "$PM" in
        apt|dnf|pacman|zypper)
            if [ -z "$SUDO" ] && [ "$(id -u 2>/dev/null || echo 0)" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
                echo "system packages need root or sudo; rerun as root or with --no-system" >&2
                exit 1
            fi
            say "installing system packages with $PM"
            pm_update
            # shellcheck disable=SC2046
            pm_install python $(packages "$PM" PYTHON)
            # shellcheck disable=SC2046
            pm_install gmsh $(packages "$PM" GMSH)
            # shellcheck disable=SC2046
            pm_install qt $(packages "$PM" QT)
            if [ "$DO_CALCULIX" -eq 1 ]; then
                list="$(packages "$PM" CALCULIX)"
                if [ -n "$list" ]; then
                    # shellcheck disable=SC2086
                    pm_install calculix $list
                else
                    echo "!! CalculiX is not packaged for $PM; see docs/dev/calculix-installation.md" >&2
                    FAILED="$FAILED calculix"
                fi
            fi
            if [ "$DO_XVFB" -eq 1 ]; then
                # shellcheck disable=SC2046
                pm_install xvfb $(packages "$PM" XVFB)
            fi
            if [ "$DO_REGISTRATION" -eq 1 ]; then
                # shellcheck disable=SC2046
                pm_install registration $(packages "$PM" REGISTRATION)
            fi
            ;;
        none)
            if [ "$(uname -s)" = "Darwin" ]; then
                echo "macOS: no system libraries are needed for the Python wheels."
                echo "For CalculiX see docs/dev/calculix-installation.md (e.g. Homebrew)."
            else
                echo "!! no supported package manager found; install the libraries listed in docs/user/installation.md" >&2
                FAILED="$FAILED system"
            fi
            ;;
        *) echo "unsupported package manager: $PM" >&2; exit 2 ;;
    esac
fi

# --- Python environment --------------------------------------------------------------
if [ "$DO_PYTHON" -eq 1 ]; then
    cd "$REPO"
    if [ "$DRY_RUN" -eq 0 ]; then
        if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            echo "EnvelopeLab needs Python >= 3.11; $PYTHON is $("$PYTHON" -V 2>&1 || echo missing)." >&2
            echo "Install a newer Python and pass it with --python." >&2
            exit 1
        fi
    fi
    if [ "$VENV" = "none" ]; then
        PY="$PYTHON"
    else
        say "virtualenv $VENV"
        [ -d "$VENV" ] || run "$PYTHON" -m venv "$VENV"
        if [ -x "$VENV/bin/python" ] || [ "$DRY_RUN" -eq 1 ]; then
            PY="$VENV/bin/python"
        else
            PY="$VENV/Scripts/python.exe"  # Windows (Git Bash)
        fi
    fi
    say "pip install -e .[$EXTRAS]"
    run "$PY" -m pip install --upgrade pip
    run "$PY" -m pip install -e ".[$EXTRAS]"
    if [ "$DO_REGISTRATION" -eq 1 ]; then
        run "$PY" -m pip install -e ".[registration]"
    fi
    if case ",$EXTRAS," in *,dev,*) true ;; *) false ;; esac && [ -d .git ] && [ "$DRY_RUN" -eq 0 ]; then
        "$PY" -m pre_commit install >/dev/null 2>&1 || true
    fi
fi

# --- checks --------------------------------------------------------------------------
if [ "$DO_CHECK" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
    say "checks"
    "$PY" -c 'import envelopelab; print("envelopelab: ok")'
    "$PY" - <<'EOF'
try:
    from calculix_adapter import find_calculix
except ImportError:
    print("CalculiX adapter: not installed")
else:
    found = find_calculix()
    print(f"CalculiX: {found.version} at {found.executable}" if found else
          "CalculiX: ccx not found (Run CalculiX will be disabled; see docs/dev/calculix-installation.md)")
EOF
    case ",$EXTRAS," in
        *,gui,*)
            # Start the main window headless: proves Qt, PySide6 and the app import and run.
            QT_QPA_PLATFORM=offscreen "$PY" - <<'EOF'
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

app = QApplication([])
from envelopelab_app.main_window import MainWindow

with tempfile.TemporaryDirectory() as tmp:
    settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("preferences/recovery_dir", str(Path(tmp) / "recovery"))
    window = MainWindow(settings, enable_3d=False, interactive=False)
    window.show()
    app.processEvents()
    window.close()
print("desktop application: starts (headless check)")
EOF
            if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
                echo "No display: run the app with a virtual display, e.g."
                echo "  QT_QPA_PLATFORM=xcb xvfb-run -a envelopelab --no-3d"
            fi
            ;;
    esac
fi

if [ -n "$FAILED" ]; then
    echo
    echo "Finished with problems in:$FAILED (see docs/user/installation.md)." >&2
    exit 1
fi
say "done"
if [ "$DO_PYTHON" -eq 1 ] && [ "$VENV" != "none" ]; then
    echo "Activate with: source $VENV/bin/activate   then run: envelopelab"
fi
