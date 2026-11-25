"""On-screen lift chart: paints one :class:`envelopelab.export.lift_chart.Plot`.

The plot data (curves, limit line, shaded region, second scales) comes from
:func:`envelopelab.export.lift_chart.chart_plots`, the same the PDF draws; this widget
only maps it to pixels.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from envelopelab.export.lift_chart import Plot, tick_label, ticks

#: Plot-area margins, px: left, top, right, bottom (tick labels, title, axis labels).
MARGINS = (58.0, 50.0, 58.0, 42.0)
INK = QColor("#1f2933")
MUTED = QColor("#56606b")
GRID = QColor("#d9dee4")
TINT = QColor("#fce6e3")
WHITE = QColor("#ffffff")


def screen_text(text: str) -> str:
    """Plot text with degree signs (the PDF spells them out for its Latin-1 font)."""
    return text.replace("degC", "°C").replace("degF", "°F")


def _colour(rgb: tuple[float, float, float]) -> QColor:
    return QColor.fromRgbF(*rgb)


class LiftChartView(QWidget):
    """One lift chart; :meth:`set_plot` replaces it (None: shows ``message``)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plot: Plot | None = None
        self.message = ""
        self.setMinimumSize(260, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(720, 460)

    def set_plot(self, plot: Plot | None, message: str = "") -> None:
        """Show ``plot``; without one, show ``message`` instead."""
        self.plot = plot
        self.message = message
        self.setToolTip("" if plot is None else screen_text(plot.title))
        self.update()

    def plot_rect(self) -> QRectF:
        """The plot area, px."""
        left, top, right, bottom = MARGINS
        return QRectF(left, top, self.width() - left - right, self.height() - top - bottom)

    def to_pixels(self, x: float, y: float) -> QPointF:
        """Pixel position of a data point (axis units of the plot)."""
        assert self.plot is not None
        r = self.plot_rect()
        (xa, xb), (ya, yb) = self.plot.xrange, self.plot.yrange
        return QPointF(
            r.left() + (x - xa) / (xb - xa) * r.width(),
            r.bottom() - (y - ya) / (yb - ya) * r.height(),
        )

    @staticmethod
    def _elided(painter: QPainter, text: str, width: float) -> str:
        """``text`` cut to ``width`` px with an ellipsis (the tooltip has it whole)."""
        return painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(width))

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), WHITE)
        if self.plot is None:
            painter.setPen(MUTED)
            painter.drawText(
                self.rect().adjusted(16, 16, -16, -16),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                self.message,
            )
            return
        self._draw(painter, self.plot)

    def _draw(self, painter: QPainter, plot: Plot) -> None:
        r = self.plot_rect()
        if r.width() < 20 or r.height() < 20:
            return
        (xa, xb), (ya, yb) = plot.xrange, plot.yrange
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        bold = QFont(self.font())
        bold.setBold(True)
        fm_h = painter.fontMetrics().height()
        # Shaded region above the limit.
        if plot.shade_above is not None and plot.shade_above[0] < yb:
            level = self.to_pixels(xa, max(plot.shade_above[0], ya)).y()
            painter.fillRect(QRectF(r.left(), r.top(), r.width(), level - r.top()), TINT)
        # Shaded region right of a limit (crown above its limit on the gross-lift chart).
        if plot.shade_right is not None and plot.shade_right[0] < xb:
            edge = self.to_pixels(max(plot.shade_right[0], xa), ya).x()
            painter.fillRect(QRectF(edge, r.top(), r.right() - edge, r.height()), TINT)
        # Grid and tick labels.
        painter.setFont(small)
        for x in ticks(xa, xb):
            px = self.to_pixels(x, ya).x()
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(QPointF(px, r.top()), QPointF(px, r.bottom()))
            painter.setPen(MUTED)
            painter.drawText(
                QRectF(px - 40, r.bottom() + 2, 80, fm_h),
                Qt.AlignmentFlag.AlignHCenter,
                tick_label(x),
            )
        for y in ticks(ya, yb):
            py = self.to_pixels(xa, y).y()
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(QPointF(r.left(), py), QPointF(r.right(), py))
            painter.setPen(MUTED)
            painter.drawText(
                QRectF(r.left() - 56, py - fm_h / 2, 52, fm_h),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                tick_label(y),
            )
        # English second scales: top (x) and right (y).
        if plot.x2 is not None:
            a2, b2 = sorted(plot.x2.scale * v + plot.x2.offset for v in (xa, xb))
            for t in ticks(a2, b2):
                px = self.to_pixels((t - plot.x2.offset) / plot.x2.scale, ya).x()
                painter.setPen(MUTED)
                painter.drawLine(QPointF(px, r.top()), QPointF(px, r.top() - 3))
                painter.drawText(
                    QRectF(px - 40, r.top() - 4 - fm_h, 80, fm_h),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
                    tick_label(t),
                )
        if plot.y2 is not None:
            a2, b2 = sorted(plot.y2.scale * v + plot.y2.offset for v in (ya, yb))
            for t in ticks(a2, b2):
                py = self.to_pixels(xa, (t - plot.y2.offset) / plot.y2.scale).y()
                painter.setPen(MUTED)
                painter.drawLine(QPointF(r.right(), py), QPointF(r.right() + 3, py))
                painter.drawText(
                    QRectF(r.right() + 5, py - fm_h / 2, 52, fm_h),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    tick_label(t),
                )
        # Limit and design-load lines.
        painter.save()
        painter.setClipRect(r)
        for level, text, rgb in plot.hlines:
            if ya <= level <= yb:
                py = self.to_pixels(xa, level).y()
                painter.setPen(QPen(_colour(rgb), 1.5, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(r.left(), py), QPointF(r.right(), py))
                # Under the line, clear of the label of the shaded region above it.
                painter.setFont(bold)
                painter.drawText(
                    QRectF(r.left(), py + 2, r.width() - 6, fm_h),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop),
                    self._elided(painter, screen_text(text), r.width() - 12),
                )
        painter.setFont(small)
        for level, text, rgb in plot.vlines:
            if xa <= level <= xb:
                px = self.to_pixels(level, ya).x()
                painter.setPen(QPen(_colour(rgb), 1, Qt.PenStyle.DotLine))
                painter.drawLine(QPointF(px, r.top()), QPointF(px, r.bottom()))
                painter.drawText(
                    QRectF(px - 260, r.bottom() - fm_h - 2, 256, fm_h),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom),
                    screen_text(text),
                )
        # Curves (nan breaks a line; the clip keeps them in the plot area).
        for series in plot.series:
            path = QPainterPath()
            pen_down = False
            for x, y in series.points:
                if not (math.isfinite(x) and math.isfinite(y)):
                    pen_down = False
                    continue
                p = self.to_pixels(x, y)
                if pen_down:
                    path.lineTo(p)
                else:
                    path.moveTo(p)
                    pen_down = True
            painter.setPen(QPen(_colour(series.colour), 2.0))
            painter.drawPath(path)
        if plot.shade_above is not None and plot.shade_above[0] < yb:
            painter.setFont(bold)
            painter.setPen(_colour((0.75, 0.12, 0.10)))
            painter.drawText(
                QRectF(r.left() + 6, r.top() + 4, r.width() - 12, fm_h),
                int(Qt.AlignmentFlag.AlignLeft),
                self._elided(painter, screen_text(plot.shade_above[1]), r.width() - 12),
            )
        if plot.shade_right is not None and plot.shade_right[0] < xb:
            edge = self.to_pixels(max(plot.shade_right[0], xa), ya).x()
            painter.setFont(bold)
            painter.setPen(_colour((0.75, 0.12, 0.10)))
            painter.drawText(
                QRectF(edge + 4, r.top() + 4, r.right() - edge - 8, fm_h),
                int(Qt.AlignmentFlag.AlignRight),
                self._elided(painter, screen_text(plot.shade_right[1]), r.right() - edge - 8),
            )
        painter.restore()
        painter.setPen(QPen(INK, 1))
        painter.drawRect(r)
        # Legend inside the plot, top right (bottom right for rising curves).
        painter.setFont(small)
        row = fm_h + 2
        width = max(
            (painter.fontMetrics().horizontalAdvance(screen_text(s.label)) for s in plot.series),
            default=0,
        )
        box_w, box_h = width + 34, row * len(plot.series) + 6
        bx = r.left() + 6 if plot.legend_left else r.right() - box_w - 6
        by = (
            r.bottom() - box_h - 6 - (fm_h if plot.vlines else 0)
            if plot.legend_at_bottom
            else (r.top() + 6 + (fm_h + 4 if plot.shade_above is not None else 0))
        )
        if plot.series:
            painter.fillRect(QRectF(bx, by, box_w, box_h), QColor(255, 255, 255, 235))
            painter.setPen(QPen(GRID, 1))
            painter.drawRect(QRectF(bx, by, box_w, box_h))
        for k, series in enumerate(plot.series):
            y = by + 3 + k * row
            painter.fillRect(QRectF(bx + 6, y + row / 2 - 1.5, 18, 3), _colour(series.colour))
            painter.setPen(INK)
            painter.drawText(
                QRectF(bx + 28, y, width + 4, row),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                screen_text(series.label),
            )
        # Title and axis labels.
        painter.setFont(bold)
        painter.setPen(INK)
        painter.drawText(
            QRectF(4, 2, self.width() - 8, fm_h + 2),
            int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextSingleLine),
            self._elided(painter, screen_text(plot.title), self.width() - 8),
        )
        painter.setFont(small)
        painter.setPen(MUTED)
        top_labels = r.top() - 6 - 2 * fm_h
        painter.drawText(
            QRectF(r.left() - 54, top_labels, 200, fm_h),
            int(Qt.AlignmentFlag.AlignLeft),
            screen_text(plot.ylabel),
        )
        if plot.y2 is not None:
            painter.drawText(
                QRectF(r.right() - 146, top_labels, 200, fm_h),
                int(Qt.AlignmentFlag.AlignRight),
                f"({screen_text(plot.y2.label)})",
            )
        xlabel = screen_text(plot.xlabel)
        if plot.x2 is not None:
            xlabel += f"; top scale {screen_text(plot.x2.label)}"
        painter.drawText(
            QRectF(r.left(), r.bottom() + fm_h + 2, r.width(), fm_h),
            int(Qt.AlignmentFlag.AlignHCenter),
            xlabel,
        )
