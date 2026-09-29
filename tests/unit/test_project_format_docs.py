from __future__ import annotations

from pathlib import Path

from envelopelab.project.format_docs import render_project_docs

PAGE = Path(__file__).resolve().parents[2] / "docs" / "formats" / "project-file.md"


def test_generated_page_is_current() -> None:
    assert PAGE.read_text(encoding="utf-8") == render_project_docs(), (
        "docs/formats/project-file.md is stale; run python scripts/generate_project_schema_docs.py"
    )
