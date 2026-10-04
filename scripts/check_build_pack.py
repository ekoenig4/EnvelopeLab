"""Build-pack output QA (AGENTS.md §6.6): export a generic sample pack and check it.

Exports the envelope rows of a generic standard-gore design with a dome and a leaned
tube on it to a temporary directory and runs :func:`envelopelab.export.qa.check_pack`.
Exits non-zero when any check fails. Run by ``scripts/verify.py``.
"""

from __future__ import annotations

import sys
import tempfile

from envelopelab.export.build_pack import export_build_pack
from envelopelab.export.qa import check_pack
from envelopelab.features.primitives import (
    Dome,
    EnvelopeSurface,
    Placement,
    Revolved,
    Tube,
    design_primitive,
)
from envelopelab.project.gore_design import standard_gore_design


def main() -> int:
    design = standard_gore_design("generic sample", 2000.0, 17.0, 16.0, 12, 6)
    surface = EnvelopeSurface.from_design(design)
    shapes = [
        design_primitive(Dome("dome", Placement(3, 12.0, across=0.5), 1.0, 1.2, 16), surface),
        design_primitive(Tube("tube", Placement(7, 10.0, lean_deg=20), 0.8, 0.3, 2.0), surface),
        design_primitive(
            Revolved("bulb", Placement(10, 11.0), ((0.4, 0.0), (0.7, 0.5), (0.0, 1.2))),
            surface,
        ),
    ]
    with tempfile.TemporaryDirectory() as out:
        export_build_pack(design, shapes, out)
        findings = check_pack(out)
    for f in findings:
        print(f"FAIL {f.file}: {f.check}: {f.message}")
    print(f"build-pack QA: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
