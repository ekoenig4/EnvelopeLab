# Installing the CalculiX verification solver

The verification workflow runs **CalculiX CrunchiX** (`ccx`, GPL-2.0-or-later) as a
separate program. EnvelopeLab writes a CalculiX input deck, starts `ccx` in a working
directory and reads its text output back; it never links or imports CalculiX. Nothing
else in EnvelopeLab (geometry, editing, pattern import, the preview solver, build-pack
export) needs CalculiX, and the Python package has no CalculiX dependency to install.

Version 2.20 or newer is required; the benchmarks are run with 2.21. An older `ccx` is
found but refused: **Run CalculiX** stays disabled and the status bar says *CalculiX too
old*, because older builds can crash on EnvelopeLab's models.

## Install `ccx`

| Platform | Command |
|---|---|
| Debian, Ubuntu 24.04 (also under WSL) | `sudo apt-get install calculix-ccx` (2.21) |
| Ubuntu 22.04 (also under WSL) | its `calculix-ccx` is 2.17, too old: use conda-forge (below) |
| Any OS with conda | `conda install -c conda-forge calculix` |
| Windows, macOS | the conda-forge package, or a build from <https://www.calculix.de> |

Check it:

```bash
ccx -v          # prints "This is Version 2.21" (or newer)
```

## Tell EnvelopeLab where `ccx` is

EnvelopeLab looks, in order, at

1. the `executable` field of `CalculixSettings`,
2. the environment variable `ENVELOPELAB_CCX` (full path of the executable),
3. `ccx`, `ccx_2.22`, `ccx_2.21`, `ccx_2.20` or `ccx.exe` on `PATH`.

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
