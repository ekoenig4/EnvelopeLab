"""CalculiX verification benchmarks and the generated preview-vs-CalculiX page.

The page and plot are rendered from the committed data file, so their consistency is
checked without CalculiX. Recomputing the data (sphere, cylinder, three envelope levels)
needs ``ccx`` and takes several minutes: those tests use the ``ccx`` fixture (skipped with
the installation message when CalculiX is missing) and are marked slow.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from calculix_adapter import CalculixInstallation
from calculix_adapter.validation import (
    REQUIRED,
    ValidationData,
    render_markdown,
    render_svg,
    richardson,
    run_validation,
)
from envelopelab.validation.pages import page_differences

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs" / "validation" / "preview-vs-calculix.json"
PAGE = ROOT / "docs" / "validation" / "preview-vs-calculix.md"
PLOT = ROOT / "docs" / "validation" / "preview-vs-calculix.svg"
FIXTURE = ROOT / "tests" / "fixtures" / "spherical_envelope" / "build-pack.yaml"
STALE = "is stale; run python scripts/generate_validation_docs.py calculix (needs ccx)"


def test_page_and_plot_match_the_saved_data() -> None:
    data = ValidationData.load(DATA)
    assert PAGE.read_text(encoding="utf-8") == render_markdown(data), f"{PAGE.name} {STALE}"
    assert PLOT.read_text(encoding="utf-8") == render_svg(data), f"{PLOT.name} {STALE}"


def test_saved_data_meets_the_verification_targets() -> None:
    data = ValidationData.load(DATA)
    failed = [b.name for b in data.benchmarks if not b.passed]
    assert not failed, failed
    assert len(data.levels) >= 3
    assert all(lv.preview_converged and lv.calculix_converged for lv in data.levels)
    names = " ".join(b.name for b in data.benchmarks)
    for required in ("sphere", "cylinder", *REQUIRED):
        assert required in names


def test_data_round_trip(tmp_path: Path) -> None:
    data = ValidationData.load(DATA)
    data.save(tmp_path / "x.json")
    assert ValidationData.load(tmp_path / "x.json") == data


def test_richardson_recovers_a_known_order() -> None:
    # f(h) = 1 + h^2 on h = 4, 2, 1 (ratio 2): order 2, limit 1.
    order, limit = richardson([17.0, 5.0, 2.0], 2.0) or (math.nan, math.nan)
    assert order == pytest.approx(2.0)
    assert limit == pytest.approx(1.0)
    assert richardson([1.0, 2.0, 1.5], 2.0) is None  # not monotone


@pytest.mark.slow
def test_recomputed_results_reproduce_the_page(ccx: CalculixInstallation) -> None:
    data = run_validation(FIXTURE)
    assert data.passed, [b.name for b in data.benchmarks if not b.passed]
    # Numbers within the platform tolerance of envelopelab.validation.pages (other CPU
    # architectures or CalculiX builds move the last digit of converged results).
    diffs = page_differences(PAGE.read_text(encoding="utf-8"), render_markdown(data))
    assert not diffs, f"{PAGE.name} {STALE}\n" + "\n".join(diffs)
