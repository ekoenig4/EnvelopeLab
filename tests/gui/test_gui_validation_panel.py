"""GUI tests: the Validation / Warnings panel in the shared design."""

from __future__ import annotations

from envelopelab_app.main_window import MainWindow
from envelopelab_app.panels.validation import count_text
from envelopelab_app.theme import STATUS_STYLES


def test_count_text() -> None:
    assert count_text("error", 0) == ""
    assert count_text("error", 1) == "1 error"
    assert count_text("warning", 3) == "3 warnings"
    assert count_text("info", 2) == "2 notes"


def test_chips_symbols_and_filters(gore_window: MainWindow) -> None:
    panel = gore_window.validation
    findings = panel.findings
    assert findings, "the fixture has warnings (no parachute, no flying wires, ...)"
    warnings = sum(f.severity == "warning" for f in findings)
    assert panel.chips["warning"].kind == "fail"
    assert count_text("warning", warnings) in panel.chips["warning"].text()
    assert panel.clear_chip.isHidden()  # there are findings
    # Each row starts with its severity's symbol; messages() keeps the tagged form.
    symbol = STATUS_STYLES["fail"].symbol
    assert any(text.startswith(symbol) for text in panel.shown())
    assert all(m.startswith("[") for m in panel.messages())
    # Hiding warnings filters the list, not the counts or messages().
    panel.filters["warning"].setChecked(False)
    assert len(panel.shown()) == len(findings) - warnings
    assert len(panel.messages()) == len(findings)
    assert count_text("warning", warnings) in panel.chips["warning"].text()
    panel.filters["warning"].setChecked(True)
    assert len(panel.shown()) == len(findings)
