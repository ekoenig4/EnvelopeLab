# Developer setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,docs]"
pre-commit install
python scripts/verify.py
```

On Linux the Gmsh wheel needs a few system libraries (ADR-0003):

```bash
sudo apt-get install -y libglu1-mesa libxcursor1 libxft2 libxinerama1
```

## Desktop application

```bash
python -m pip install -e ".[dev,docs,gui]"
envelopelab                   # the application (app/envelopelab_app)
```

The GUI (ADR-0007) is a view of `envelopelab.project`; it contains no engineering math.
GUI tests (`tests/gui`, pytest-qt) run headless on Qt's `offscreen` platform (set by
`tests/gui/conftest.py`). On Linux, Qt needs `libegl1 libxkbcommon0 libfontconfig1`.
The PyVista renderer test runs only with a display:

```bash
QT_QPA_PLATFORM=xcb ENVELOPELAB_TEST_3D=1 xvfb-run -a pytest tests/gui/test_gui_renderer.py
```

`python scripts/generate_project_schema_docs.py` regenerates
docs/formats/project-file.md (a test fails when it is stale).

Generated pages: `python scripts/generate_validation_docs.py` (docs/validation/) and
`python scripts/generate_pattern_mapping_docs.py` (docs/formats/pattern-import-mapping.md).
Tests fail when either is stale. The generic pattern fixtures are rebuilt with
`python tests/fixtures/generate_generic_fixtures.py`.
