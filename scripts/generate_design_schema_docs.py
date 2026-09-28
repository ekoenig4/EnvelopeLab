from __future__ import annotations

import json
from pathlib import Path

from envelopelab.design.model import DesignDocument


def main() -> None:
    schema = DesignDocument.model_json_schema()
    target = Path("docs/formats/design-schema.md")
    target.write_text(
        "# Design schema\n\n"
        "_This document is auto-generated from `DesignDocument.model_json_schema()`._\n\n"
        "```json\n"
        f"{json.dumps(schema, indent=2, sort_keys=True)}\n"
        "```\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
