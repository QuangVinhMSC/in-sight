"""Dialogs of the cell operations: Insert / Delete (ISVS live/09, live/10) and Find (help image)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import cells
from . import sheet_ops as ops

SHEET_NAME = "Inspection"  # the name of the (only) sheet of a spreadsheet job, as ISVS shows it


class InsertDeleteDialog(QDialog):
    """``Insert ❒Inspection`` / ``Delete ❒Inspection``: four radio buttons, OK / Cancel (300×173)."""

    def __init__(self, delete: bool, default: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("deleteDialog" if delete else "insertDialog")
        self.setWindowTitle(f"{'Delete' if delete else 'Insert'} {cells.STRUCTURE_GLYPH}{SHEET_NAME}")
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
