"""GUI tests: the shared theme (style sheet, status banner and chip)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from envelopelab_app.theme import (
    STATUS_ORDER,
    STATUS_STYLES,
    StatusBanner,
    StatusChip,
    apply_theme,
    stylesheet,
    worst,
)


def _luminance(hex_colour: str) -> float:
    rgb = [int(hex_colour[i : i + 2], 16) / 255.0 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("kind", list(STATUS_STYLES))
def test_status_text_is_readable_and_has_its_own_symbol(kind: str) -> None:
    s = STATUS_STYLES[kind]
    assert _contrast(s.text, s.background) >= 4.5  # WCAG AA for body text
    assert _contrast(s.chip_text, s.chip_background) >= 4.5
    symbols = [v.symbol for v in STATUS_STYLES.values()]
    assert symbols.count(s.symbol) == 1  # never told apart by colour alone


def test_worst_status_orders_by_severity() -> None:
    assert worst(["ok", "stale", "fail"]) == "fail"
    assert worst(["info", "error", "fail"]) == "error"
    assert worst([]) is None
    assert set(STATUS_ORDER) == set(STATUS_STYLES)


def test_banner_shows_hides_and_reports_its_text(qtbot: QtBot) -> None:
    apply_theme(QApplication.instance())  # type: ignore[arg-type]
    host = QWidget()
    qtbot.addWidget(host)
    banner = StatusBanner()
    QVBoxLayout(host).addWidget(banner)
    host.show()
    assert banner.isHidden() and banner.text() == ""
    hits: list[bool] = []
    banner.actionTriggered.connect(lambda: hits.append(True))
    banner.set_status("error", "Not converged — values are not final.", "residual 3e-4", "Retry")
    assert not banner.isHidden() and banner.property("status") == "error"
    assert "values are not final" in banner.text() and "3e-4" in banner.text()
    banner.action.click()
    assert hits == [True]
    banner.set_status("stale", "Stale result.")
    assert banner.action.isHidden()
    banner.clear()
    assert banner.isHidden() and banner.kind is None
    with pytest.raises(ValueError):
        banner.set_status("unknown", "x")


def test_chip_text_carries_the_status_symbol(qtbot: QtBot) -> None:
    chip = StatusChip("stale", "Stale")
    qtbot.addWidget(chip)
    assert chip.text() == f"{STATUS_STYLES['stale'].symbol} Stale"
    chip.set_status("ok", "")
    assert chip.isHidden()


def test_stylesheet_covers_every_status() -> None:
    css = stylesheet()
    for kind in STATUS_STYLES:
        assert f"[status='{kind}']" in css
