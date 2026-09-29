# Licenses

- Project code: GPL-3.0-only
- Documentation and tests: GPL-3.0-only unless explicitly noted otherwise.

## Third-party dependencies

| Package | Use | License |
|---|---|---|
| NumPy | array math (geometry, atmosphere) | BSD-3-Clause |
| SciPy | cubic and smoothing splines (geometry); sparse solves, KD-trees (assembly) | BSD-3-Clause |
| ezdxf | DXF pattern import (`envelopelab.io.pattern_import`) | MIT |
| Gmsh (Python API and library) | panel triangulation (`envelopelab.assembly.mesh`) | GPL-2.0-or-later (with linking exceptions) |
| PyYAML | build-pack YAML mapping files | MIT |
| types-PyYAML (dev) | type stubs for mypy | Apache-2.0 |
| Open3D (optional extra `registration`) | point-to-plane ICP registration of reference meshes (`envelopelab.io.reference_mesh`); a SciPy ICP is used when it is not installed | MIT |
| PySide6 and shiboken6 (optional extra `gui`) | desktop application (`app/envelopelab_app`), see ADR-0007 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PyVista (optional extra `gui`) | 3D view | MIT |
| pyvistaqt (optional extra `gui`) | PyVista inside Qt | MIT |
| QtPy (via pyvistaqt) | Qt binding shim | MIT |
| VTK (via PyVista) | 3D rendering | BSD-3-Clause |
| scooby (via PyVista) | environment report | MIT |
| pytest-qt (dev) | headless GUI tests | MIT |
| pymdown-extensions (via mkdocs-material) | `arithmatex` math in docs | MIT |
| MathJax (loaded from jsDelivr by the docs site) | equation rendering | Apache-2.0 |

## External programs (optional, not bundled)

| Program | Use | License |
|---|---|---|
| CalculiX CrunchiX (`ccx`) | verification solver, run as a separate process by `solvers/calculix_adapter` (see `docs/dev/calculix-installation.md`); not linked, imported or distributed | GPL-2.0-or-later |
