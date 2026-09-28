# Developer setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,docs]"
pre-commit install
python scripts/verify.py
```

On Linux the Gmsh wheel needs a few system libraries:

```bash
sudo apt-get install -y libglu1-mesa libxcursor1 libxft2 libxinerama1
```
