# Installing the CalculiX verification solver

The verification workflow runs **CalculiX CrunchiX** (`ccx`, GPL-2.0-or-later) as a
separate program. EnvelopeLab writes a CalculiX input deck, starts `ccx` in a working
directory and reads its text output back; it never links or imports CalculiX. Nothing
else in EnvelopeLab (geometry, editing, pattern import, the preview solver, build-pack
export) needs CalculiX, and the Python package has no CalculiX dependency to install.

Version 2.20 or newer is required; the benchmarks are run with 2.21.

## Install `ccx`

### Windows

The simplest way is the Windows build from the CalculiX site. No installer and no admin
rights are needed.

1. Download the Windows zip, `calculix_2.23_4win.zip` (or `calculix_2.22_4win.zip`), from
   the CalculiX download page, <https://www.dhondt.de> (also reachable as
   <https://www.calculix.de>).
2. Unzip it to a folder without spaces, for example `C:\CalculiX`.
3. Find the solver in the unzipped folder: **`ccx_static.exe`** (Explorer: search the
   folder for `ccx`). Use the static one. `ccx_dynamic.exe` also needs the Intel MKL DLLs
   next to it.
4. Check it in a command prompt; the folder may be one level deeper, depending on the
   zip:

    ```bat
    C:\CalculiX\ccx_static.exe -v
    ```

    It prints `This is Version 2.23` (or 2.22). If Windows SmartScreen asks, allow it
    to run.
5. Tell EnvelopeLab where it is, in one of these ways:
    * **In the app (easiest):** **File ▸ Preferences ▸ CalculiX executable ▸ Browse…**,
      choose `ccx_static.exe`, press OK. EnvelopeLab looks for it again at once.
    * **For all programs:** set the user environment variable `ENVELOPELAB_CCX` to the
      full path (it takes effect in programs started afterwards):

        ```bat
        setx ENVELOPELAB_CCX "C:\CalculiX\ccx_static.exe"
        ```

    * **On PATH:** add the folder to your user `PATH`. EnvelopeLab looks for `ccx.exe`,
      `ccx_static.exe` and `ccx_dynamic.exe` there.

The status bar then shows *CalculiX 2.23* (instead of *CalculiX not found*) and
**Run CalculiX** is enabled. **Simulation ▸ Detect CalculiX again** repeats the search.
A change to `PATH` or `ENVELOPELAB_CCX` reaches EnvelopeLab only when it is started again.

If you already use **PrePoMax**, its `Solver` folder has a CalculiX executable: point the
preference at it the same way.

**With conda instead** (Miniforge or Anaconda): conda-forge has Windows builds.

```bat
conda create -n calculix -c conda-forge calculix
conda activate calculix
where ccx
```

`where ccx` prints the full path of the executable. Put that path in **Preferences ▸
CalculiX executable** (or `ENVELOPELAB_CCX`): EnvelopeLab runs from its own virtualenv,
not from the conda environment, so it needs the full path.

### Linux and macOS

| Platform | Command |
|---|---|
| Debian, Ubuntu | `sudo apt-get install calculix-ccx` (also done by `scripts/install_env.sh`) |
| Fedora | `sudo dnf install calculix-ccx` |
| Any OS with conda | `conda install -c conda-forge calculix` |
| Other | a build from <https://www.calculix.de> |

Check it:

```bash
ccx -v          # prints "This is Version 2.21" (or newer)
```

## How EnvelopeLab finds `ccx`

EnvelopeLab looks, in order, at

1. the **CalculiX executable** preference in the app, or the `executable` field of
   `CalculixSettings` in scripts;
2. the environment variable `ENVELOPELAB_CCX` (full path of the executable);
3. `ccx`, `ccx_2.23`, `ccx_2.22`, `ccx_2.21`, `ccx_2.20`, `ccx_static` or `ccx_dynamic` on
   `PATH` (with `.exe` on Windows).

The executable is accepted when `<executable> -v` prints a version. A path may be in
quotes, use `%VARIABLES%` or `~`, or name the folder that holds the program. A path that
does not work does not stop the search: the next place is tried.

## When EnvelopeLab says CalculiX is not found

The **Runs** panel (and the tooltip of *CalculiX not found* in the status bar) lists every
place EnvelopeLab looked and why each failed. The same report from a command prompt, in
the EnvelopeLab folder:

```bat
.venv\Scripts\python -m calculix_adapter
.venv\Scripts\python -m calculix_adapter "C:\CalculiX\ccx_static.exe"
```

The second form also tries the given path first, as the app does with its preference.
The command ends with exit code 0 when a working `ccx` is found.

| Report says | Cause and fix |
|---|---|
| `does not exist (a relative path …)` | The setting is not a full path, e.g. `calculix/ccx/ccx.exe`. Use the full path starting with the drive, e.g. `C:\Program Files\CalculiX\ccx\ccx.exe`. |
| `does not exist` | Typing error, or the file has another name: check it in Explorer and copy its path (Shift + right-click ▸ *Copy as path*). |
| `ran but printed no version (exit code 3221225781: a DLL it needs is missing …)` | The program needs DLLs that are not beside it or on `PATH`. Use `ccx_static.exe`, or start EnvelopeLab with that folder on `PATH`. |
| `ran but printed no version` (other) | The program is not CalculiX, or a version older than 2.x. Run it with `-v` yourself to see what it prints. |
| `could not be started` | Blocked by Windows or antivirus, or not a program for this computer. Run it once by hand and allow it. |
| `ENVELOPELAB_CCX` is not listed at all | The variable is not set for this program: check the spelling (`ENVELOPELAB_CCX`, with a **B**), and start EnvelopeLab again from a new window after `setx` or a change in *Environment Variables*. |
| `no ccx program on PATH` | The folder on `PATH` must be the one that holds the program itself, and EnvelopeLab must be started after `PATH` was changed. |

```python
from calculix_adapter import find_calculix

print(find_calculix())  # CalculixInstallation(executable=..., version='2.21') or None
```

When nothing is found, `require_calculix()` and `run_calculix()` raise
`CalculixNotFoundError` with these installation instructions.

## Tests without CalculiX

The CalculiX tests live in `tests/calculix/`. Without `ccx` every test that needs the solver
is **skipped** with the message "CalculiX verification tests skipped, ccx not installed",
so a missing solver is never reported as a passing verification. The tests that do not
need `ccx` (detection, deck writing, output parsing, and the check that the generated page
matches its saved data) always run.

The page `docs/validation/preview-vs-calculix.md` and its plot are rendered from the saved
study data `docs/validation/preview-vs-calculix.json`. Regenerate all three, where `ccx` is
installed, with

```bash
python scripts/generate_validation_docs.py calculix   # several minutes
```

The slow test `tests/calculix/test_validation.py::test_recomputed_results_reproduce_the_page`
reruns the study and fails when the committed page no longer matches.

CI installs `calculix-ccx` on the Linux runners, so the verification benchmarks run there;
the macOS and Windows jobs skip them.

## Running a verification solve

```python
from calculix_adapter import CalculixSettings, run_calculix
from envelopelab.solvers.dynamic_relaxation import solve
from envelopelab.solvers.simulation import from_preview
from envelopelab.validation.comparison import compare_results

preview = solve(model)  # interactive preview
result = run_calculix(
    model,
    CalculixSettings(),  # verification
    start_positions=preview.positions,
)
print(result.summary())  # status, height, volume, ...
print(compare_results(from_preview(model, preview), result).to_markdown())
```

`result.converged` is True only when every convergence criterion of the adapter was met
(see [the theory page](../theory/verification-solver.md)); otherwise `result.findings`
contains an error that says which one failed, and the result must not be used as final.

## Reproducibility

`run_calculix` runs CalculiX with one thread (`OMP_NUM_THREADS=1`,
`CCX_NPROC_STIFFNESS=1`, `CCX_NPROC_EQUATION_SOLVER=1`) so that repeated runs give the
same numbers, and records the CalculiX version and path in the run manifest
(`SimulationResult.manifest`). Keep the working files of a run by passing `workdir`.
