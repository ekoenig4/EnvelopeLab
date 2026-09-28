from __future__ import annotations

from pathlib import Path

from envelopelab.io.mapping_docs import ASSEMBLY_MODELS, IMPORT_MODELS, render_mapping_docs

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "formats" / "pattern-import-mapping.md"
EXAMPLE = "tests/fixtures/special_shape/build-pack.yaml"


def test_every_field_is_documented() -> None:
    missing = [
        f"{model.__name__}.{name}"
        for model in (*IMPORT_MODELS, *ASSEMBLY_MODELS)
        for name, field in model.model_fields.items()
        if not field.description
    ]
    assert not missing


def test_generated_page_is_current() -> None:
    example = (ROOT / EXAMPLE).read_text(encoding="utf-8")
    assert PAGE.read_text(encoding="utf-8") == render_mapping_docs(example, EXAMPLE), (
        "docs/formats/pattern-import-mapping.md is stale; "
        "run python scripts/generate_pattern_mapping_docs.py"
    )
