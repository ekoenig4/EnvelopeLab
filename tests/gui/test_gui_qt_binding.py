"""The Qt binding must not corrupt Python's reference counts.

PySide6 6.12.0 decrements the reference count of ``None`` once on every call of a Qt
method that returns nothing (``QPainterPath.moveTo``, ``QGraphicsPathItem.setPath``, ...).
On Python 3.11, where ``None`` is not immortal, the GUI then aborts with "Fatal Python
error: none_dealloc" after enough calls: the test run died at a different GUI test on
each machine. ``pyproject.toml`` excludes that release; this test names the cause if a
binding with the bug is installed again.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QGraphicsPathItem
from pytestqt.qtbot import QtBot


def test_void_qt_calls_keep_the_reference_count_of_none(qtbot: QtBot) -> None:
    path, item = QPainterPath(), QGraphicsPathItem()
    calls = 1000
    before = sys.getrefcount(None)
    for k in range(calls):
        path.moveTo(float(k), 0.0)
        path.lineTo(float(k), 1.0)
        item.setPath(path)
    lost = before - sys.getrefcount(None)
    # Other code may take or drop a few references meanwhile; the bug loses one per call.
    assert lost < calls // 10, (
        f"the Qt binding dropped {lost} references to None in {3 * calls} calls; this "
        "PySide6 release has a reference-count bug (6.12.0 does) and aborts Python 3.11"
    )
