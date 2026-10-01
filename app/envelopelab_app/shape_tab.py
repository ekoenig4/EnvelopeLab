"""New-design wizard tab: a design from a shape file, holding any three values."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envelopelab.design.model import DesignDocument
from envelopelab.io.shape_file import UNITS, ShapeFile, ShapeFileError, load_shape_file
from envelopelab.project.shape_family import (
    HELD_COUNT,
    QUANTITIES,
    ShapeSolution,
    shape_design,
    solve_shape,
    station_points,
)

#: Display units per unit system and dimension (factors come from ``envelopelab.io``).
UNIT_SYSTEMS: dict[str, dict[str, str]] = {
    "SI (m, m³)": {"length": "m", "volume": "m^3", "fraction": ""},
    "Imperial (ft, ft³)": {"length": "ft", "volume": "ft^3", "fraction": ""},
}
HOLD, NAME, VALUE, UNIT = range(4)
OK_STYLE = "color: #1b5e20;"
ERROR_STYLE = "color: #b00020;"


class ShapeFileTab(QWidget):
    """Load a shape file, choose the held values, solve, and build the design."""

    def __init__(self, fabrics: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.shape_file: ShapeFile | None = None
        self.solution: ShapeSolution | None = None
        self._stale = True
        self._filling = False

        self.path = QLineEdit()
        self.path.setPlaceholderText("e.g. tests/fixtures/smalley_90k/shape.yaml")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        load = QPushButton("Load")
        load.clicked.connect(lambda: self.load(self.path.text().strip()))
        file_row = QHBoxLayout()
        file_row.addWidget(self.path)
        file_row.addWidget(browse)
        file_row.addWidget(load)
        self.about = QLabel("Load a shape file to see its values.")
        self.about.setWordWrap(True)

        self.units = QComboBox()
        self.units.addItems(list(UNIT_SYSTEMS))
        self.units.currentIndexChanged.connect(self._fill_values)
        self.table = QTableWidget(len(QUANTITIES), 4)
        self.table.setHorizontalHeaderLabels(["Hold", "Quantity", "Value", "Unit"])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(NAME, QHeaderView.ResizeMode.Stretch)
        for row, quantity in enumerate(QUANTITIES.values()):
            hold = QTableWidgetItem()
            hold.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            hold.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, HOLD, hold)
            label = QTableWidgetItem(quantity.label)
            label.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, NAME, label)
            self.table.setItem(row, VALUE, QTableWidgetItem(""))
            unit = QTableWidgetItem("")
            unit.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, UNIT, unit)
        self.table.itemChanged.connect(self._item_changed)

        self.gores = QSpinBox()
        self.gores.setRange(3, 200)
        self.gores.valueChanged.connect(self._mark_stale)
        self.allowance = QDoubleSpinBox()
        self.allowance.setRange(0.0, 200.0)
        self.allowance.setDecimals(1)
        self.allowance.setSuffix(" mm per edge")
        self.allowance.valueChanged.connect(self._mark_stale)
        self.rows = QSpinBox()
        self.rows.setRange(1, 26)
        self.rows.setValue(12)
        self.fabric = QComboBox()
        self.fabric.addItems(fabrics)
        self.name = QLineEdit()
        solve = QPushButton("Solve")
        solve.clicked.connect(self.solve)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.stations = QLabel()
        self.stations.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Gores N", self.gores)
        form.addRow("Seam allowance", self.allowance)
        form.addRow("Panel rows", self.rows)
        form.addRow("Fabric", self.fabric)
        form.addRow("Units", self.units)
        layout = QVBoxLayout(self)
        layout.addLayout(file_row)
        layout.addWidget(self.about)
        layout.addWidget(
            QLabel(
                f"Tick <b>Hold</b> on exactly {HELD_COUNT} values; typing a value holds it. "
                "<b>Solve</b> finds the others."
            )
        )
        layout.addWidget(self.table)
        layout.addWidget(solve)
        layout.addWidget(self.status)
        layout.addWidget(self.stations)
        layout.addLayout(form)

    # ------------------------------------------------------------------ helpers

    def cell(self, row: int, column: int) -> QTableWidgetItem:
        """Table item (every cell is created in ``__init__``)."""
        item = self.table.item(row, column)
        assert item is not None
        return item

    def _unit(self, name: str) -> str:
        return UNIT_SYSTEMS[self.units.currentText()][QUANTITIES[name].dimension]

    def _factor(self, name: str) -> float:
        return UNITS[QUANTITIES[name].dimension][self._unit(name)]

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Shape file", "", "Shape files (*.yaml *.yml)")
        if path:
            self.path.setText(path)
            self.load(path)

    def _set_status(self, text: str, ok: bool) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(OK_STYLE if ok else ERROR_STYLE)

    def _mark_stale(self) -> None:
        self._stale = True

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        self._stale = True
        if item.column() == VALUE:
            self._filling = True
            self.cell(item.row(), HOLD).setCheckState(Qt.CheckState.Checked)
            self._filling = False
        self._show_hold_count()

    def held_names(self) -> list[str]:
        """Names of the ticked quantities, in table order."""
        names = list(QUANTITIES)
        return [
            names[row]
            for row in range(self.table.rowCount())
            if self.cell(row, HOLD).checkState() == Qt.CheckState.Checked
        ]

    def _show_hold_count(self) -> None:
        count = len(self.held_names())
        if count != HELD_COUNT:
            self._set_status(f"Hold exactly {HELD_COUNT} values ({count} held).", False)
        else:
            self._set_status("Press Solve.", True)

    def _fill_values(self) -> None:
        if self.solution is None or self.shape_file is None:
            return
        self._filling = True
        for row, name in enumerate(QUANTITIES):
            value = self.solution.values[name] / self._factor(name)
            self.cell(row, VALUE).setText(f"{value:.6g}")
            self.cell(row, UNIT).setText(self._unit(name))
        self._filling = False
        lines = []
        length_unit = self._unit("gore_length")
        factor = self._factor("gore_length")
        for p in station_points(self.shape_file.shape, self.solution.parameters):
            lines.append(
                f"{p.name} (s = {p.station:g}): radius {p.radius / factor:.4g} {length_unit}, "
                f"{p.height / factor:.4g} {length_unit} above the mouth"
            )
        self.stations.setText("Named stations: " + "; ".join(lines) if lines else "")

    # ------------------------------------------------------------------ actions

    def load(self, path: str) -> bool:
        """Load a shape file and solve its own design; errors are shown in the tab."""
        try:
            sf = load_shape_file(path)
            solution = sf.solve()
        except (ShapeFileError, ValueError, OSError) as exc:
            self._set_status(str(exc), False)
            return False
        self.shape_file = sf
        self.path.setText(str(path))
        self.name.setText(sf.name)
        self.about.setText(
            f"<b>{sf.name}</b> — {sf.description}"
            + (f"<br>Source: {sf.reference}" if sf.reference else "")
            + f"<br>Profile: {sf.shape.s.size} stations ({sf.shape.source})."
        )
        self.gores.setValue(sf.gore_count)
        self.allowance.setValue(sf.seam_allowance * 1000.0)
        self._filling = True
        for row, name in enumerate(QUANTITIES):
            state = Qt.CheckState.Checked if name in sf.hold else Qt.CheckState.Unchecked
            self.cell(row, HOLD).setCheckState(state)
        self._filling = False
        self._show_solution(solution)
        return solution.converged

    def solve(self) -> ShapeSolution | None:
        """Solve with the held values in the table; the result is shown in the tab."""
        if self.shape_file is None:
            self._set_status("Load a shape file first.", False)
            return None
        hold: dict[str, float] = {}
        for row, name in enumerate(QUANTITIES):
            if self.cell(row, HOLD).checkState() != Qt.CheckState.Checked:
                continue
            text = self.cell(row, VALUE).text().strip()
            try:
                hold[name] = float(text) * self._factor(name)
            except ValueError:
                self._set_status(f"{QUANTITIES[name].label}: {text!r} is not a number.", False)
                return None
        start = self.shape_file.start() if self.solution is None else self.solution.parameters
        start = replace(
            start, gore_count=self.gores.value(), seam_allowance=self.allowance.value() / 1000.0
        )
        try:
            solution = solve_shape(self.shape_file.shape, start, hold)
        except ValueError as exc:
            self._set_status(str(exc), False)
            return None
        self._show_solution(solution)
        return solution

    def _show_solution(self, solution: ShapeSolution) -> None:
        self.solution = solution
        self._stale = False
        self._fill_values()
        free = ", ".join(f.replace("_", " ") for f in solution.free) or "nothing"
        if solution.converged:
            self._set_status(
                f"Converged: solved {free} ({solution.message}, {solution.iterations} iterations).",
                True,
            )
        else:
            worst = ", ".join(
                f"{QUANTITIES[k].label} off by {v / self._factor(k):.4g} {self._unit(k)}"
                for k, v in solution.errors.items()
            )
            self._set_status(
                f"NOT CONVERGED — no design can be made from this. {solution.message}. {worst}",
                False,
            )

    def design(self) -> DesignDocument:
        """The design of the current values (solving first when they changed).

        Raises
        ------
        ValueError
            When nothing is loaded or the values do not solve.
        """
        if self.shape_file is None:
            raise ValueError("load a shape file first")
        if self._stale or self.solution is None:
            if self.solve() is None:
                raise ValueError(self.status.text())
        assert self.solution is not None
        if not self.solution.converged:
            raise ValueError(self.status.text())
        return shape_design(
            self.name.text().strip() or self.shape_file.name,
            self.shape_file.shape,
            self.solution,
            row_count=self.rows.value(),
            fabric_id=self.fabric.currentText() or "ripstop_nylon",
        )
