# Installation

EnvelopeLab needs **Python 3.11 or newer**. The Python dependencies are installed with
`pip`; on Linux a few system libraries are needed as well (the Qt, VTK and Gmsh wheels
link against them). The CalculiX verification solver is an optional separate program.

## Quick install with the script (Linux, containers)

From a checkout of the repository:

```bash
bash scripts/install_env.sh
source .venv/bin/activate
envelopelab
```

The script

1. installs the system libraries with `apt` (Debian, Ubuntu), `dnf` (Fedora), `pacman`
   (Arch) or `zypper` (openSUSE), as root or with `sudo`;
2. installs CalculiX (`ccx`) and Xvfb (a virtual display for headless machines) where the
   distribution packages them;
3. creates the virtualenv `.venv` and runs `pip install -e ".[dev,docs,gui]"`;
4. checks that the library imports, reports whether `ccx` was found, and starts the main
   window headless to prove Qt works.

It stops with a non-zero exit code and lists what failed when any group of packages could
not be installed. Useful options (`--help` lists all):

| Option | Effect |
|---|---|
| `--extras gui` | only the application (no test and docs tools) |
| `--no-system` | skip system packages (no root needed; libraries already installed) |
| `--system-only` | only system packages (e.g. a container image layer) |
| `--no-calculix`, `--no-xvfb` | leave out CalculiX or Xvfb |
| `--venv DIR` / `--venv none` | another virtualenv, or the current Python environment |
| `--python python3.12` | the Python used to create the virtualenv |
| `--dry-run` | print the commands without running them |

A container example (Ubuntu 24.04):

```dockerfile
FROM ubuntu:24.04
COPY . /opt/envelopelab
WORKDIR /opt/envelopelab
RUN bash scripts/install_env.sh --extras gui
ENV PATH=/opt/envelopelab/.venv/bin:$PATH
```

The `apt` path is tested (CI and an Ubuntu 24.04 container). The `dnf`, `pacman` and
`zypper` package names are best effort and not tested in CI; if one fails, install the
equivalent package from the tables below and rerun with `--no-system`.

## Manual install

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[gui]"    # add dev,docs for development
```

### System libraries (Linux)

Windows and macOS need no extra libraries. On Linux install:

| Needed by | Debian / Ubuntu (`apt install`) |
|---|---|
| Python venv | `python3 python3-venv python3-pip` |
| Gmsh (meshing) | `libglu1-mesa libxcursor1 libxft2 libxinerama1 libgomp1` |
| Qt / VTK (the application) | `libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libdbus-1-3 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 libxcb-xinerama0 libxcb-shape0` |
| CalculiX (optional) | `calculix-ccx` |
| Headless display (optional) | `xvfb xauth` |

| Needed by | Fedora (`dnf install`) | Arch (`pacman -S`) | openSUSE (`zypper install`) |
|---|---|---|---|
| Gmsh | `mesa-libGLU libXcursor libXft libXinerama libgomp` | `glu libxcursor libxft libxinerama gcc-libs` | `libGLU1 libXcursor1 libXft2 libXinerama1 libgomp1` |
| Qt / VTK | `mesa-libEGL mesa-libGL libxkbcommon libxkbcommon-x11 fontconfig dbus-libs xcb-util-cursor xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil` | `libglvnd mesa libxkbcommon libxkbcommon-x11 fontconfig dbus xcb-util-cursor xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil` | `libEGL1 libGL1 libxkbcommon0 libxkbcommon-x11-0 fontconfig libdbus-1-3 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 libxcb-xinerama0 libxcb-shape0` |
| CalculiX | `calculix-ccx` | AUR `calculix` | see [CalculiX installation](../dev/calculix-installation.md) |
| Headless display | `xorg-x11-server-Xvfb xorg-x11-xauth` | `xorg-server-xvfb xorg-xauth` | `xvfb-run xauth` |

### CalculiX (optional)

Without `ccx` everything works except **Run CalculiX**, which is disabled with an
explanation. See [CalculiX installation](../dev/calculix-installation.md); after installing,
use **Simulation ▸ Detect CalculiX again** or restart.

## Starting the application

```bash
envelopelab                 # or: python -m envelopelab_app
envelopelab my.elproj       # open a project
envelopelab --no-3d         # without the PyVista 3D renderer (no OpenGL needed)
envelopelab --software-gl   # software OpenGL (Mesa llvmpipe): slower, works everywhere
envelopelab --hardware-gl   # GPU OpenGL even where software is the default (WSL)
```

Under **WSL** (Windows Subsystem for Linux, WSLg) the application selects software OpenGL
by itself and says so on start-up, because the WSL GPU driver draws the window black. An
explicit `LIBGL_ALWAYS_SOFTWARE` setting in your environment is always respected.

On a machine without a display (a container, a server over SSH), run it on a virtual
display:

```bash
QT_QPA_PLATFORM=xcb xvfb-run -a -s "-screen 0 1920x1200x24" envelopelab
```

## Troubleshooting

**`Could not load the Qt platform plugin "xcb" … xcb-cursor0 or libxcb-cursor0 is needed`,
then `no Qt platform plugin could be initialized` and an abort.** Qt 6.5 and newer need the
XCB cursor library. Install `libxcb-cursor0` (Debian/Ubuntu, openSUSE) or `xcb-util-cursor`
(Fedora, Arch), or run `bash scripts/install_env.sh`, then start again.

**`Could not load the Qt platform plugin "wayland"`.** In a Wayland session Qt tries its
Wayland plugin first; when that fails it falls back to X11 (XWayland). Once the libraries
above are installed, force X11 with `QT_QPA_PLATFORM=xcb envelopelab`.

**Still failing?** Run `QT_DEBUG_PLUGINS=1 envelopelab 2>&1 | tail -40`: the last lines
name the library that could not be loaded; install the package that provides it.

**The window opens but stays black (WSL, virtual machines, remote desktop).** The GPU OpenGL
driver cannot draw the window. Start with `envelopelab --software-gl` (the same as
`LIBGL_ALWAYS_SOFTWARE=1 envelopelab`); under WSL this is already the default. Keeping WSL
up to date (`wsl --update` in Windows PowerShell, then `wsl --shutdown`) also helps.

**The window opens but the 3D view is blank or crashes** (remote desktop, no OpenGL):
start with `envelopelab --no-3d`, or turn the 3D view off in **File ▸ Preferences**. The
layer list still shows every result and which solver it came from.

**`ModuleNotFoundError: PySide6`.** The application is an optional extra: install it with
`pip install -e ".[gui]"`.
