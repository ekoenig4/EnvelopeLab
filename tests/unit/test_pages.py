"""Unit tests: platform-tolerant comparison of generated validation pages."""

from __future__ import annotations

from envelopelab.validation.pages import page_differences

PAGE = "| 1200 | 1164 | yes | 0.985 | 1346 |\nChange: 5.7 %, 3.1 %\nError 0.0002\n"


def test_identical_pages_match() -> None:
    assert page_differences(PAGE, PAGE) == []


def test_platform_round_off_is_accepted() -> None:
    # Observed Linux x86-64 vs macOS arm64 difference of the preview page.
    fresh = PAGE.replace("0.985", "0.986").replace("5.7 %, 3.1 %", "5.9 %, 3.2 %")
    assert page_differences(PAGE, fresh) == []


def test_real_changes_are_reported() -> None:
    assert page_differences(PAGE, PAGE.replace("0.985", "0.995"))  # 1 %
    assert page_differences(PAGE, PAGE.replace("5.7 %", "6.4 %"))
    assert page_differences(PAGE, PAGE.replace("1164", "1165"))  # integers exact
    assert page_differences(PAGE, PAGE.replace("yes", "**no**"))
    assert page_differences(PAGE, PAGE + "extra\n")
