"""Regenerate docs/formats/pattern-import-mapping.md from the mapping and assembly models."""

from __future__ import annotations

from pathlib import Path

from envelopelab.io.mapping_docs import render_mapping_docs

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = "tests/fixtures/special_shape/build-pack.yaml"
TARGET = ROOT / "docs" / "formats" / "pattern-import-mapping.md"


def main() -> None:
    example = (ROOT / EXAMPLE).read_text(encoding="utf-8")
    TARGET.write_text(render_mapping_docs(example, EXAMPLE), encoding="utf-8")


if __name__ == "__main__":
    main()
