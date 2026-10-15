# Installation

EnvelopeLab needs **Python 3.11 or newer**. The Python dependencies are installed with
`pip`; on Linux a few system libraries are needed as well (the Qt, VTK and Gmsh wheels
link against them). The CalculiX verification solver is an optional separate program.

## Quick install on Windows

Windows needs no system libraries. You need [Git](https://git-scm.com/download/win), and
Python 3.11 or newer (the script can install Python 3.12 for you). In a command prompt or
PowerShell:

```bat
git clone https://github.com/ekoenig4/EnvelopeLab.git
cd EnvelopeLab
scripts\install_env.cmd -InstallPython -Shortcut
```

You can also double-click `scripts\install_env.cmd` in Explorer. It runs
`scripts\install_env.ps1` with PowerShell's execution policy bypassed for that one run, so
it works where PowerShell reports *"running scripts is disabled on this system"*; nothing is
changed permanently. The script

1. finds Python 3.11 or newer (the `py` launcher first, preferring 3.12 and 3.13), or, with
   `-InstallPython`, installs Python 3.12 for your user with `winget`;
2. creates the virtualenv `.venv` and runs `pip install -e ".[gui,fast]"`;
3. checks that the library and Gmsh import, reports whether CalculiX (`ccx`) was found, and
   starts the main window headless to prove Qt works;
4. with `-Shortcut`, puts an *EnvelopeLab* shortcut on your desktop.

| Option | Effect |
|---|---|
| `-InstallPython` | install Python 3.12 with winget when no suitable Python is found |
| `-Shortcut` | desktop shortcut to the application |
| `-Dev` | also the test and docs tools (`dev,docs` extras) and the pre-commit hooks |
| `-Extras gui` | only the application, without the compiled solver kernel |
| `-Venv DIR` | another virtualenv directory |
| `-Python C:\path\to\python.exe` | the Python used to create the virtualenv |
| `-NoCheck`, `-DryRun` | skip the checks; print the commands without running them |

Then start the application from the shortcut, or with `.venv\Scripts\envelopelab.exe`.
CalculiX is optional and installed separately: see
[CalculiX on Windows](../dev/calculix-installation.md#windows).

To activate the virtualenv in PowerShell yourself (`.venv\Scripts\Activate.ps1`), allow
local scripts once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use
`.venv\Scripts\activate.bat` in a command prompt.

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
3. creates the virtualenv `.venv` and runs `pip install -e ".[dev,docs,gui,fast]"`;
4. checks that the library imports, reports whether `ccx` was found, and starts the main
   window headless to prove Qt works.

It stops with a non-zero exit code and lists what failed when any group of packages could
not be installed. Useful options (`--help` lists all):

| Option | Effect |
|---|---|
| `--extras gui` | only the application (no test and docs tools) |
| `--extras gui,fast` | the application with the compiled solver kernel (3-4x faster previews) |
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
explanation. On Linux, `scripts/install_env.sh` installs it. On Windows, download the
Windows zip from the CalculiX site, unzip it, and choose its `ccx_static.exe` in
**File ▸ Preferences ▸ CalculiX executable ▸ Browse…**; step by step in
[CalculiX installation](../dev/calculix-installation.md#windows). After installing, use
**Simulation ▸ Detect CalculiX again** or restart.

## Starting the application

```bash
envelopelab                 # or: python -m envelopelab_app
envelopelab my.elproj       # open a project
envelopelab --no-3d         # without the PyVista 3D renderer (no OpenGL needed)
envelopelab --software-gl   # software OpenGL (Mesa llvmpipe): slower, works everywhere
envelopelab --hardware-gl   # GPU OpenGL even where software is the default (WSL)
```

Under **WSL** (Windows Subsystem for Linux, WSLg) the application sets up the display
by itself and says so on start-up:

* **Software OpenGL**, because the WSL GPU driver draws the window black.
* **Qt's X11 platform** (`xcb`): WSLg is a Wayland session, and the 3D view's render
  window needs X11 there; under Wayland it crashes the application. The same applies in
  any Linux Wayland session that also has an X server (XWayland).

Your own `LIBGL_ALWAYS_SOFTWARE` and `QT_QPA_PLATFORM` settings are always respected.
WSL 2 with Ubuntu 24.04 is tested in CI, but on GitHub's Windows runners without the WSLg
desktop.

On a machine without a display (a container, a server over SSH), run it on a virtual
display:

```bash
QT_QPA_PLATFORM=xcb xvfb-run -a -s "-screen 0 1920x1200x24" envelopelab
```

## Troubleshooting

**The application crashes or closes without a message.** EnvelopeLab writes a crash log
on every start. A crash in Qt, the 3D view or the OpenGL driver leaves the Python stack of
every thread in it, below the versions and display settings it started with:

| System | Crash log |
|---|---|
| Linux, WSL | `~/.local/state/envelopelab/crash.log` (or `$XDG_STATE_HOME/envelopelab/`) |
| Windows | `%LOCALAPPDATA%\EnvelopeLab\crash.log` |
| macOS | `~/Library/Logs/EnvelopeLab/crash.log` |

The log holds the last run only, so copy it before starting again. Then:
* run `envelopelab --diagnose`, which prints the same settings and the OpenGL renderer
  that is used;
* to rule out the 3D view, start with `envelopelab --no-3d`;
* send both outputs with the steps that led to the crash.

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
