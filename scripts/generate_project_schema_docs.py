"""Generate docs/formats/project-file.md from the project-file model.

Run from the repository root: ``python scripts/generate_project_schema_docs.py``. A test
fails when the committed page is stale.
"""

from __future__ import annotations

from pathlib import Path

from envelopelab.project.format_docs import render_project_docs


def main() -> None:
    Path("docs/formats/project-file.md").write_text(render_project_docs(), encoding="utf-8")


if __name__ == "__main__":
    main()
