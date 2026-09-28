# AGENTS.md — EnvelopeLab

## 1. Project summary
EnvelopeLab is a free, open-source (GPL-3.0) desktop application for designing, editing,
simulating and producing build packs for hot air balloon envelopes (standard gore designs
and special shapes) for experimental, recreational, crewed flight, plus scale models for
physical testing.

**Top priority: physics fidelity.** The app predicts how a design will actually look and
carry load when inflated, starting from the flat patterns that will be sewn.

**Safety:** EnvelopeLab is a design aid, not certified engineering software. Factor-of-safety
(FoS) failures, temperature exceedances and unconverged solves must be shown clearly and
never hidden. The builder is responsible for airworthiness.

## 2. Hard rules
- Use only free/open-source dependencies. Add each one to `LICENSES.md` in the same commit
  that introduces it.
- Python 3.11+. `envelopelab/` contains pure, typed, tested functions. `app/` (GUI) never
  contains engineering math.
- Use SI units internally (m, N, Pa, kg, K). Convert only at input/output boundaries.
- Never hard-code a specific design. Reference designs live only in `tests/fixtures/`.
- Every material value and physical constant carries a source tag:
  `datasheet | measured | assumed`.
- Never present an unconverged or unverified result as final, in code, docs or chat.
- If a requirement is ambiguous, ask ONE clarifying question before coding.

## 3. Repository layout
    src/envelopelab/   core library, installed as `envelopelab`
                       (now: atmosphere, geometry, mass_estimate, design, materials,
                       commands, validation, io, assembly, solvers (preview
                       dynamic-relaxation solver); planned: export)
    tests/             unit/, property/, benchmarks/, regression/, fixtures/ (planned: gui/)
    docs/              MkDocs site: user/, theory/, validation/, dev/, formats/, adr/
    scripts/           dev utilities: verify.py, generate_validation_docs.py,
                       generate_design_schema_docs.py, generate_pattern_mapping_docs.py
    solvers/           adapters for external solvers: calculix_adapter (CalculiX
                       verification solver, installed as `calculix_adapter`);
                       planned: Gmsh, Meshroom
    app/               planned: PySide6 GUI

Paths written as `envelopelab/...` elsewhere in this file mean `src/envelopelab/...`.
Create a planned directory only when the first code for it lands.

## 4. Environment setup
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -e ".[dev,docs]"
    pre-commit install

## 5. Working loop (every task)
1. **Plan:** restate the task, list assumptions, propose the files to touch, and name the
   tests that will prove it works.
2. **Implement:** make the smallest change that meets the task.
3. **Verify:** run the checks in §6. Fix failures before moving on.
4. **Document:** update the docs listed in §7.
5. **Commit:** follow §8.
6. **Report:** summarize what changed, the exact commands run and their results, what is
   still unfinished, and known limitations.

## 6. Running code and verifying results

### 6.1 Commands
    ruff check . && ruff format --check .      # lint + format
    mypy src solvers tests                     # types (strict; config in pyproject.toml)
    pytest -m "not slow" -q                    # fast suite, run after every change
    pytest -q                                  # full suite, run before every commit
    python scripts/generate_validation_docs.py # regenerate docs/validation/ benchmark pages
    mkdocs build --strict                      # docs must build without warnings
    python scripts/verify.py                   # ruff, format, mypy, full pytest, mkdocs

Mark tests that take more than a few seconds with `@pytest.mark.slow` (the marker is
registered in `pyproject.toml`). Benchmark pages under `docs/validation/` are generated
from `envelopelab.validation`; a test fails when a committed page is stale, so regenerate
and commit it with any change that moves a benchmark value. Build-pack output QA (§6.6)
will be added to `verify.py` together with the export code.

### 6.2 Verification rules
- **Run it, don't assume it.** Never say code works without running it. Quote the
  command and a summary of its output (pass/fail counts, key numbers).
- If you cannot run something (missing solver, no display), say so explicitly and
  describe what remains unverified.
- Every bug fix starts with a test that fails, then the fix that makes it pass.
- Fix the root cause. Never weaken a tolerance, skip a test or mark it `xfail` without
  an explanation in the commit body and a linked issue.

### 6.3 Test tiers
| Tier | Purpose | Example |
|---|---|---|
| Unit | Single functions | ISA density at 1,000 m |
| Property (hypothesis) | Invariants | save/load round trip is lossless |
| Analytical benchmarks | Physics vs. closed form | see 6.4 |
| Convergence | Mesh/step independence | 3 refinements, Richardson estimate |
| Cross-solver | Preview solver vs. CalculiX | agreement within stated tolerance |
| Regression (golden) | Detect unintended changes | reference fixture volume, seam audit |
| Output QA | Build-pack correctness | calibration lines, labels, scale |
| GUI smoke | App launches, main flows run | pytest-qt, headless |

### 6.4 Required physics benchmarks (must pass before any solver change merges)
- Pressurized spherical membrane: sigma = p*r/(2t) (stress resultant p*r/2)
- Pressurized cylinder: hoop resultant = p*r, axial = p*r/2
- Hydrostatic differential pressure dp(h) = (rho_amb - rho_int)*g*h vs. hand calculation
- Lift L = V*(rho_amb - rho_int)*g vs. a documented hand calculation
- Cable under uniform load: catenary sag vs. analytic
- Tension-field wrinkling: a known benchmark with compressive stress below tolerance
- Global equilibrium: resultant pressure force = mouth/tape reactions within 0.5 %

Default tolerances (override only with justification): geometry 1 mm or 0.1 %,
volume/area 0.1 % (analytic cases), stresses 2 % (analytic), preview vs. CalculiX 5 %,
residual norm < 1e-6 relative.

### 6.5 Solver result requirements
Every solve returns and logs: convergence status, iterations, final residual, mesh size
(nodes/elements), material sources, load case and run time. Results are saved with
metadata (git commit, dependency versions, random seed, design content hash) so any run
can be reproduced.

### 6.6 Build-pack output QA (automated in `scripts/verify.py`)
- Each 1:1 sheet's calibration line is measured from the exported geometry. Its label
  (e.g., "must measure 500 mm at 1:1, ticks every 100 mm") must be generated from the same
  value, never typed as text.
- DXF units are set and correct. PDF page size matches the target roll width (e.g., 60 in).
- Sewn edge pairs match in length within tolerance (default 3 mm).
- Every file in the pack's index exists, and every file is listed in the index.
- Each sheet header (panel, cut count, fabric, finished size) matches the design data.

### 6.7 Golden files
Regression outputs live in `tests/regression/golden/`. Updating a golden file requires:
the reason in the commit body, a before/after numeric diff, and the `physics` or `fix` type.

## 7. Documentation

### 7.1 In code
- NumPy-style docstrings on every public function. **Every parameter and return value
  states its units.**
- Physics functions include: the governing equation (LaTeX), assumptions, valid range, and
  a reference (textbook, paper or standard).
- Comments explain *why*, not *what*. No commented-out code.

### 7.2 Docs site (MkDocs + Material, `docs/`)
- `user/`: how-to guides, workflow walkthroughs and screenshots for builders. No derivations.
- `theory/`: one page per physics or geometry module: governing equations, assumptions,
  valid range, references. Keep it in step with the module docstrings.
- `validation/`: benchmark and convergence results. Tables are generated from the test
  suite (e.g. `scripts/generate_validation_docs.py`), never typed by hand; a test fails
  when a generated page is stale.
- `dev/`: setup, architecture, contributing and release notes for developers.
- `formats/`: file formats (design schema, build-pack layout). Generated from code where
  possible (`scripts/generate_design_schema_docs.py`).
- `adr/`: Architecture Decision Records `ADR-NNNN-title.md` (Status, Date, Context,
  Decision, Consequences). Add one for every new dependency with a runtime role, solver
  choice, file-format change or change to a hard rule. Never rewrite an accepted ADR;
  supersede it with a new one.
- Every new page goes in the `mkdocs.yml` nav. Equations use `pymdownx.arithmatex`
  (`\( \)` inline, `\[ \]` display).

### 7.3 What to update with each change
| Change | Update |
|---|---|
| New or changed physics/geometry | Docstrings, `theory/` page, benchmark + regenerated `validation/` page |
| New public API | Docstrings; `user/` guide if builders use it |
| Schema or file format | Migration + test, regenerated `formats/` page, ADR if breaking |
| New dependency | `pyproject.toml`, `LICENSES.md` (same commit), ADR if it has a runtime role |
| Any user-visible change | `CHANGELOG.md` under `[Unreleased]` |

### 7.4 Changelog
`CHANGELOG.md` follows Keep a Changelog. Add one line per user-visible change under
`[Unreleased]`. Any change that alters numerical results (`physics` commits, golden updates)
says what changed and by how much.

## 8. Commits and branches

### 8.1 Commit messages
Use Conventional Commits: `type(scope): summary`, imperative mood, summary <= 72 characters.

| Type | Use for |
|---|---|
| `feat` | New capability that does not change existing numerical results |
| `physics` | Any change to an equation, constant, solver setting or tolerance that changes results |
| `fix` | Bug fix (starts with a failing test, §6.2) |
| `docs` | Documentation only |
| `test` | Tests only |
| `refactor` | No behavior change, results bit-identical |
| `perf` | Faster, results unchanged within tolerance |
| `build` / `ci` / `chore` | Packaging, CI, tooling |

Scope is the package area: `atmosphere`, `geometry`, `solvers`, `io`, `export`, `app`,
`materials`, `design`, `docs`.

The commit body must state, when they apply:
- why the change was made (not only what);
- any tolerance change, skipped or `xfail` test, with the reason and the linked issue
  (§6.2);
- any golden-file update, with the reason and a before/after numeric diff (§6.7);
- any new dependency and its license (§2);
- any breaking change, as a `BREAKING CHANGE:` footer.

### 8.2 Commit rules
- One logical change per commit. Tests, docs and code for that change go in the same commit.
- Run `pytest -q` (full suite) before every commit; `python scripts/verify.py` must pass
  before pushing.
- Never commit generated build output (`site/`, caches, `.venv/`), secrets or large
  binaries. Generated docs pages that are part of the site (`validation/`, `formats/`)
  are committed and must be current.
- Never rewrite published history on a shared branch.

### 8.3 Branches and pull requests
- Branch from `main`: `type/short-description` (e.g. `physics/isa-humidity`).
  Branch names assigned by a tool or session (e.g. `claude/...`, `copilot/...`) are
  allowed as-is; keep the assigned name rather than renaming it. The commit and PR rules
  below apply to them unchanged.
- Keep `main` green. Merge only through a pull request with CI passing on every OS and
  Python version in the matrix.
- PR description: what changed and why, the commands run and their results (§5 step 6),
  what is unfinished, known limitations, and links to issues for pending or skipped tests.
- A `physics` PR lists every affected benchmark with its before/after values, and must
  pass the §6.4 benchmarks.
