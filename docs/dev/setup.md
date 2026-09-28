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

Generated pages: `python scripts/generate_validation_docs.py` (docs/validation/) and
`python scripts/generate_pattern_mapping_docs.py` (docs/formats/pattern-import-mapping.md).
Tests fail when either is stale. The generic pattern fixtures are rebuilt with
`python tests/fixtures/generate_generic_fixtures.py`.
