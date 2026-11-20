"""Dialogs of the cell operations: Insert / Delete (ISVS live/09, live/10), Find (help image), Cell
State and Cell Names (survey on Windows 2026-11-20, live/119…122)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
import re

from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import cells
from . import sheet_ops as ops

SHEET_NAME = "Inspection"  # the name of the (only) sheet of a spreadsheet job, as ISVS shows it


class InsertDeleteDialog(QDialog):
    """``Insert - Inspection`` / ``Delete - Inspection``: four radio buttons, OK / Cancel (300×173)."""

    def __init__(self, delete: bool, default: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("deleteDialog" if delete else "insertDialog")
        self.setWindowTitle(f"{'Delete' if delete else 'Insert'} - {SHEET_NAME}")  # Windows: " - " (Wine drew ❒)
        self.setFixedSize(300, 173)
        choices = ([("Shift cells left", ops.SHIFT_LEFT), ("Shift cells up", ops.SHIFT_UP)] if delete else
                   [("Shift cells right", ops.SHIFT_RIGHT), ("Shift cells down", ops.SHIFT_DOWN)])
        choices += [("Entire row", ops.ENTIRE_ROW), ("Entire column", ops.ENTIRE_COLUMN)]
        default = default or (ops.SHIFT_UP if delete else ops.SHIFT_DOWN)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(1)
        for i, (text, mode) in enumerate(choices):
            if i == 2:
                layout.addSpacing(6)
            rb = QRadioButton(text)
            rb.setChecked(mode == default)
            self.group.addButton(rb)
            self.buttons[mode] = rb
            layout.addWidget(rb)
        layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok, cancel = QPushButton("OK"), QPushButton("Cancel")
        ok.setDefault(True)
        for b in (ok, cancel):
            b.setMinimumWidth(80)
            row.addWidget(b)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        layout.addLayout(row)

    def mode(self) -> str:
        return next(m for m, b in self.buttons.items() if b.isChecked())


class FindDialog(QDialog):
    """``Find - Inspection``: non-modal, keeps the search history of the session."""

    findRequested = Signal(bool)  # forward
    replaceRequested = Signal()
    replaceAllRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("findDialog")
        self.setWindowTitle(f"Find - {SHEET_NAME}")
        self.setModal(False)
        self.find_box = self._history_box()
        self.replace_box = self._history_box()
        self.order = QComboBox()
        self.order.addItems([ops.ROWS_FIRST, ops.COLUMNS_FIRST])
        self.look_in = QComboBox()
        self.look_in.addItems([ops.LOOK_EXPRESSIONS, ops.LOOK_VALUES, ops.LOOK_COMMENTS, ops.LOOK_NAMES])
        # Comments are not available through the HMI API
        self.look_in.model().item(2).setEnabled(False)
        self.look_in.setItemData(2, "Cell comments are not available through the In-Sight HMI API",
                                 Qt.ItemDataRole.ToolTipRole)
        self.match_case = QCheckBox("Match case")
        self.match_entire = QCheckBox("Match entire")
        self.btn_next = QPushButton("Find Next")
        self.btn_prev = QPushButton("Find Previous")
        self.btn_replace = QPushButton("Replace")
        self.btn_replace_all = QPushButton("Replace All")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(lambda: self._find(True))
        self.btn_prev.clicked.connect(lambda: self._find(False))
        self.btn_replace.clicked.connect(self._replace)
        self.btn_replace_all.clicked.connect(self._replace_all)
        self.look_in.currentIndexChanged.connect(lambda _i: self.set_replace_allowed(self._replace_allowed))
        self._replace_allowed = True

        g = QGridLayout(self)
        g.setContentsMargins(4, 4, 4, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(3)
        g.addWidget(QLabel("Find:"), 0, 0, 1, 3)
        g.addWidget(self.find_box, 1, 0, 1, 3)
        g.addWidget(self.btn_next, 1, 3)
        g.addWidget(QLabel("Replace:"), 2, 0, 1, 3)
        g.addWidget(self.btn_prev, 2, 3)
        g.addWidget(self.replace_box, 3, 0, 1, 3)
        g.addWidget(self.btn_replace, 3, 3)
        g.addWidget(QLabel("Search Order:"), 4, 0)
        g.addWidget(self.order, 4, 1)
        g.addWidget(self.match_case, 4, 2)
        g.addWidget(self.btn_replace_all, 4, 3)
        g.addWidget(QLabel("Look in:"), 5, 0)
        g.addWidget(self.look_in, 5, 1)
        g.addWidget(self.match_entire, 5, 2)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)
        g.setRowStretch(6, 1)
        self.resize(375, self.sizeHint().height())

    @staticmethod
    def _history_box() -> QComboBox:
        box = QComboBox()
        box.setEditable(True)
        box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return box

    @staticmethod
    def _remember(box: QComboBox) -> None:
        text = box.currentText()
        if not text:
            return
        i = box.findText(text, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive)
        if i >= 0:
            box.removeItem(i)
        box.insertItem(0, text)
        box.setCurrentIndex(0)

    # ------------------------------------------------------------------ state
    def what(self) -> str:
        return self.find_box.currentText()

    def with_(self) -> str:
        return self.replace_box.currentText()

    def look(self) -> str:
        return self.look_in.currentText()

    def by_rows(self) -> bool:
        return self.order.currentText() == ops.ROWS_FIRST

    def set_replace_allowed(self, allowed: bool) -> None:
        """Replace works only offline, and not on values (they are results)."""
        self._replace_allowed = allowed
        ok = allowed and self.look() in (ops.LOOK_EXPRESSIONS, ops.LOOK_NAMES)
        for b in (self.btn_replace, self.btn_replace_all):
            b.setEnabled(ok)
        self.replace_box.setEnabled(ok)

    # ------------------------------------------------------------------ buttons
    def _find(self, forward: bool) -> None:
        self._remember(self.find_box)
        self.findRequested.emit(forward)

    def _replace(self) -> None:
        self._remember(self.find_box)
        self._remember(self.replace_box)
        self.replaceRequested.emit()

    def _replace_all(self) -> None:
        self._remember(self.find_box)
        self._remember(self.replace_box)
        self.replaceAllRequested.emit()


# ---------------------------------------------------------------------------- Cell State
_SINGLE_CELL = re.compile(r"\$?([A-Za-z])\$?(\d{1,3})")


class CellStateDialog(QDialog):
    """``Cell State - Inspection`` (survey live/121, live/122; help): "Cell Range: B1", ◉ Enabled
    ○ Disabled ○ Conditionally Enabled (◉ Absolute ○ Relative, Cell Reference [ ] [Select Cell...]).
    OK is greyed while Conditionally Enabled has no valid reference. :meth:`condition` is what
    ``setCellCondition`` takes: ``""`` enabled, ``"0"`` disabled, a reference conditional."""

    selectCellRequested = Signal()  # the caller hides the dialog, picks a cell, calls set_reference

    def __init__(self, cell_range: str, condition: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Cell State - {SHEET_NAME}")
        self.cell_range = cell_range
        self.enabled = QRadioButton("Enabled")
        self.disabled = QRadioButton("Disabled")
        self.conditional = QRadioButton("Conditionally Enabled")
        self.absolute = QRadioButton("Absolute")
        self.relative = QRadioButton("Relative")
        self.reference = QLineEdit()
        self.select_button = QPushButton("Select Cell...")
        self.select_button.clicked.connect(self.selectCellRequested.emit)
        state = QButtonGroup(self)
        for b in (self.enabled, self.disabled, self.conditional):
            state.addButton(b)
        mode = QButtonGroup(self)
        mode.addButton(self.absolute)
        mode.addButton(self.relative)

        box = QGroupBox("Cell State")
        v = QVBoxLayout(box)
        v.addWidget(self.enabled)
        v.addWidget(self.disabled)
        v.addWidget(self.conditional)
        sub = QGridLayout()
        sub.setContentsMargins(20, 0, 0, 0)
        sub.addWidget(self.absolute, 0, 0)
        sub.addWidget(self.relative, 0, 1)
        sub.addWidget(QLabel("Cell Reference:"), 1, 0)
        sub.addWidget(self.reference, 1, 1)
        sub.addWidget(self.select_button, 1, 2)
        v.addLayout(sub)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Cell Range: {cell_range}"))
        layout.addWidget(box)
        layout.addWidget(self.buttons)

        cond = (condition or "").strip()
        if cond == "":
            self.enabled.setChecked(True)
        elif cond == "0":
            self.disabled.setChecked(True)
        else:
            self.conditional.setChecked(True)
            self.reference.setText(cond.replace("$", ""))
        (self.relative if cond and "$" not in cond and cond != "0" else self.absolute).setChecked(True)
        for w in (self.enabled, self.disabled, self.conditional):
            w.toggled.connect(self._update)
        self.reference.textChanged.connect(self._update)
        self._update()

    def _valid_reference(self) -> bool:
        m = _SINGLE_CELL.fullmatch(self.reference.text().strip())
        return bool(m) and cells.parse_address(f"{m.group(1).upper()}{m.group(2)}") is not None

    def _update(self) -> None:
        cond = self.conditional.isChecked()
        for w in (self.absolute, self.relative, self.reference, self.select_button):
            w.setEnabled(cond)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not cond or self._valid_reference())

    def set_reference(self, loc: Optional[str]) -> None:
        """The cell picked after Select Cell... (None: cancelled); the first cell of a range."""
        if loc:
            self.reference.setText(loc.split(":")[0].replace("$", ""))
            self.conditional.setChecked(True)

    def condition(self) -> str:
        if self.enabled.isChecked():
            return ""
        if self.disabled.isChecked():
            return "0"
        m = _SINGLE_CELL.fullmatch(self.reference.text().strip())
        if not m:
            return ""
        col, row = m.group(1).upper(), m.group(2)
        return f"${col}${row}" if self.absolute.isChecked() else f"{col}{row}"


# ---------------------------------------------------------------------------- Cell Names
NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,126}")
SUGGESTED_NAME = "Result"


def valid_cell_name(name: str) -> bool:
    """ISVS's name rules: a letter first, letters/digits/underscores, at most 127 characters and
    not a cell address (``1abc``, ``A1`` are refused, survey §6.4)."""
    return bool(NAME_RE.fullmatch(name)) and not cells.looks_like_address(name)


def suggested_name(used) -> str:
    """``Result``, then ``Result01``, ``Result02``… (survey live/119)."""
    used = {u.lower() for u in used}
    if SUGGESTED_NAME.lower() not in used:
        return SUGGESTED_NAME
    n = 1
    while f"{SUGGESTED_NAME}{n:02d}".lower() in used:
        n += 1
    return f"{SUGGESTED_NAME}{n:02d}"


class CellNamesDialog(QDialog):
    """``Cell Names`` (survey live/119…120): every name of the job in a *Name | Location* table, [Add]
    [Rename] [Delete] [Auto Name], OK / Cancel. Opened for a cell without a name, a row for it is
    added with a suggested name and put in edit mode; an invalid name is silently reverted. [Add]
    asks for a cell in the spreadsheet (``addCellRequested``, then :meth:`add_location`).
    :meth:`changes` gives {location: new name, "" = removed} for OK."""

    addCellRequested = Signal()

    def __init__(self, names: dict[str, str], current: Optional[str] = None,
                 has_contents=lambda loc: True, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cell Names")
        self.resize(360, 320)
        self.original = dict(names)
        self.has_contents = has_contents
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Location"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for loc, name in sorted(names.items(), key=lambda kv: cells.parse_address(kv[0]) or (0, 0)):
            self._add_row(loc, name)
        self.table.itemChanged.connect(self._name_edited)

        self.add_button = QPushButton("Add")
        self.rename_button = QPushButton("Rename")
        self.delete_button = QPushButton("Delete")
        self.auto_button = QPushButton("Auto Name")
        self.auto_button.setEnabled(False)
        self.auto_button.setToolTip("Not available yet: what ISVS's Auto Name does was not recorded")
        self.add_button.clicked.connect(self.addCellRequested.emit)
        self.rename_button.clicked.connect(self._rename)
        self.delete_button.clicked.connect(self._delete)
        side = QVBoxLayout()
        for b in (self.add_button, self.rename_button, self.delete_button, self.auto_button):
            side.addWidget(b)
        side.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        top = QHBoxLayout()
        top.addWidget(self.table, 1)
        top.addLayout(side)
        layout = QVBoxLayout(self)
        layout.addLayout(top, 1)
        layout.addWidget(self.buttons)
        self.table.itemSelectionChanged.connect(self._update)
        if current:
            self.add_location(current)
        self._update()

    # ------------------------------------------------------------------ rows
    def _add_row(self, loc: str, name: str) -> int:
        blocked = self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, name)  # last valid name (reverted to)
        where = QTableWidgetItem(loc)
        where.setFlags(where.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, item)
        self.table.setItem(row, 1, where)
        self.table.blockSignals(blocked)
        return row

    def _row_of(self, loc: str) -> Optional[int]:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 1).text() == loc:
                return r
        return None

    def names(self) -> dict[str, str]:
        """{location: name} as the table shows it now."""
        return {self.table.item(r, 1).text(): self.table.item(r, 0).text() for r in range(self.table.rowCount())}

    def add_location(self, loc: Optional[str]) -> None:
        """A row for ``loc`` (a named cell's row is selected instead) in edit mode."""
        if not loc:
            return
        loc = loc.split(":")[0].replace("$", "").upper()
        if cells.parse_address(loc) is None or not self.has_contents(loc):
            return
        row = self._row_of(loc)
        if row is None:
            row = self._add_row(loc, suggested_name(self.names().values()))
        self.table.selectRow(row)
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))

    def _name_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        text = item.text().strip()
        blocked = self.table.blockSignals(True)
        if valid_cell_name(text):
            item.setText(text)
            item.setData(Qt.ItemDataRole.UserRole, text)
        else:  # ISVS: no message, the previous name comes back
            item.setText(item.data(Qt.ItemDataRole.UserRole) or "")
        self.table.blockSignals(blocked)

    def _rename(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.editItem(self.table.item(row, 0))

    def _delete(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
        self._update()

    def _update(self) -> None:
        has = self.table.currentRow() >= 0
        self.rename_button.setEnabled(has)
        self.delete_button.setEnabled(has)

    def changes(self) -> dict[str, str]:
        now = self.names()
        out = {loc: "" for loc in self.original if loc not in now}
        out.update({loc: name for loc, name in now.items() if self.original.get(loc) != name})
        return out
