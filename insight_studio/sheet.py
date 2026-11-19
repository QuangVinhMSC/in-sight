"""Spreadsheet model (26 x 600 cells) and view."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHeaderView, QMenu, QTableView

from . import cells

EXPR_ROLE = Qt.ItemDataRole.UserRole + 1
RESULT_ROLE = Qt.ItemDataRole.UserRole + 2
NAME_ROLE = Qt.ItemDataRole.UserRole + 3

ERROR_COLOR = QColor(220, 50, 50)
DISABLED_COLOR = QColor(150, 150, 150)
EDITABLE_BACK = QColor(232, 244, 255)
GRAPHIC_BACK = QColor(232, 255, 236)
PENDING_COLOR = QColor(140, 140, 200)


class SheetModel(QAbstractTableModel):
    """Holds expressions, results, names and formats; edits are emitted, not applied locally."""

    expressionEdited = Signal(str, str)  # location, new expression

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.expressions: dict[str, str] = {}
        self.results: dict[str, dict] = {}
        self.names: dict[str, str] = {}
        self.formats: dict[str, cells.CellFormat] = {}
        self.pending: dict[str, str] = {}
        self.read_only = False

    # ------------------------------------------------------------------ updates
    def set_expressions(self, exprs: dict[str, dict]) -> None:
        self.expressions = {loc: str(v.get("expr", "")) for loc, v in exprs.items()}
        for loc in list(self.pending):
            if self.expressions.get(loc, "") == self.pending[loc]:
                del self.pending[loc]
        self._all_changed()

    def set_results(self, results: dict[str, dict]) -> None:
        self.results = results
        self._all_changed()

    def set_names(self, names: dict[str, str]) -> None:
        self.names = dict(names)
        self._all_changed()

    def set_formats(self, formats: dict[str, cells.CellFormat]) -> None:
        self.formats = formats
        self._all_changed()

    def clear(self) -> None:
        self.expressions, self.results, self.names, self.formats, self.pending = {}, {}, {}, {}, {}
        self._all_changed()

    def mark_pending(self, loc: str, expr: str) -> None:
        self.pending[loc] = expr
        r = cells.parse_address(loc)
        if r:
            idx = self.index(*r)
            self.dataChanged.emit(idx, idx)

    def clear_pending(self) -> None:
        self.pending.clear()
        self._all_changed()

    def _all_changed(self) -> None:
        self.dataChanged.emit(self.index(0, 0), self.index(cells.NUM_ROWS - 1, cells.NUM_COLS - 1))

    def location_of_name(self, name: str) -> Optional[str]:
        for loc, n in self.names.items():
            if n == name:
                return loc
        return None

    # ------------------------------------------------------------------ Qt model API
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else cells.NUM_ROWS

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else cells.NUM_COLS

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return cells.col_name(section)
        return str(section)

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not self.read_only:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        loc = cells.address(index.row(), index.column())
        expr = self.pending.get(loc, self.expressions.get(loc, ""))
        result = self.results.get(loc)
        fmt = self.formats.get(loc)

        if role == Qt.ItemDataRole.DisplayRole:
            if loc in self.pending:
                return self.pending[loc]
            if not expr and not result:
                return None
            return cells.display_text(result, expr, fmt.decimals if fmt else None)
        if role in (Qt.ItemDataRole.EditRole, EXPR_ROLE):
            return expr
        if role == RESULT_ROLE:
            return result
        if role == NAME_ROLE:
            return self.names.get(loc)
        if role == Qt.ItemDataRole.ToolTipRole:
            if not expr and not result:
                return None
            lines = [f"<b>{loc}</b>" + (f" — {self.names[loc]}" if loc in self.names else "")]
            if expr:
                lines.append(f"<code>{_html(expr)}</code>")
            if result:
                lines.append(f"<i>{cells.result_kind(result)}</i>")
            return "<br>".join(lines)
        if role == Qt.ItemDataRole.ForegroundRole:
            if loc in self.pending:
                return QBrush(PENDING_COLOR)
            if result and (result.get("error") or cells.result_kind(result) == "ErrorCellResult"):
                return QBrush(ERROR_COLOR)
            if result and result.get("disabled"):
                return QBrush(DISABLED_COLOR)
            if cells.result_kind(result) == "ColorLabelResult":
                rgba = cells.argb_to_rgba(result.get("foreColor"))
                if rgba:
                    return QBrush(QColor(*rgba))
            if cells.result_kind(result) in ("StatusResult", "StatusLightResult"):
                rgba = cells.argb_to_rgba(result.get("color"))
                if rgba:
                    return QBrush(QColor(*rgba))
            if fmt and fmt.fore and fmt.fore[3] > 0:
                return QBrush(QColor(*fmt.fore))
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            if cells.result_kind(result) == "ColorLabelResult":
                rgba = cells.argb_to_rgba(result.get("backColor"))
                if rgba and rgba[3] > 0:
                    return QBrush(QColor(*rgba))
            if fmt and fmt.back and fmt.back[3] > 0:
                return QBrush(QColor(*fmt.back))
            if cells.editable_graphic(result):
                return QBrush(GRAPHIC_BACK)
            if cells.is_value_editable(result):
                return QBrush(EDITABLE_BACK)
            return None
        if role == Qt.ItemDataRole.FontRole:
            if fmt and (fmt.bold or fmt.italic or fmt.font_size or fmt.font_name):
                font = QFont(fmt.font_name) if fmt.font_name else QFont()
                font.setBold(fmt.bold)
                font.setItalic(fmt.italic)
                if fmt.font_size:
                    font.setPointSizeF(float(fmt.font_size))
                return font
            if loc in self.pending or cells.is_structure(result):
                font = QFont()
                font.setItalic(True)
                return font
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            h = {0: Qt.AlignmentFlag.AlignLeft, 1: Qt.AlignmentFlag.AlignHCenter,
                 2: Qt.AlignmentFlag.AlignRight}
            v = {0: Qt.AlignmentFlag.AlignTop, 1: Qt.AlignmentFlag.AlignVCenter,
                 2: Qt.AlignmentFlag.AlignBottom}
            if fmt and (fmt.h_align is not None or fmt.v_align is not None):
                return int(h.get(fmt.h_align, Qt.AlignmentFlag.AlignLeft)
                           | v.get(fmt.v_align, Qt.AlignmentFlag.AlignVCenter))
            if cells.result_kind(result) in ("FloatResult", "EditFloatResult", "EditIntResult"):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return None
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or self.read_only:
            return False
        loc = cells.address(index.row(), index.column())
        text = "" if value is None else str(value)
        if text == self.expressions.get(loc, ""):
            return False
        self.mark_pending(loc, text)
        self.expressionEdited.emit(loc, text)
        return True


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SheetView(QTableView):
    """Spreadsheet grid with clipboard support (expressions shift like a spreadsheet)."""

    pasteRequested = Signal(dict)  # {location: expression}
    clearRequested = Signal(list)  # [locations]
    contextMenuForCell = Signal(str, QMenu)  # location, menu to extend

    MIME = "application/x-insight-studio-cells"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                             | QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setDefaultSectionSize(80)
        self.verticalHeader().setDefaultSectionSize(22)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setWordWrap(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        for seq, slot in ((QKeySequence.StandardKey.Copy, self.copy_selection),
                          (QKeySequence.StandardKey.Cut, self.cut_selection),
                          (QKeySequence.StandardKey.Paste, self.paste),
                          (QKeySequence.StandardKey.Delete, self.clear_selection)):
            act = QAction(self)
            act.setShortcut(seq)
            act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            act.triggered.connect(slot)
            self.addAction(act)

    def apply_sheet_format(self, widths: list[int], heights: list[int]) -> None:
        for c, w in enumerate(widths):
            self.setColumnWidth(c, w if w > 0 else self.horizontalHeader().defaultSectionSize())
        for r, h in enumerate(heights):
            if h > 0:
                self.setRowHeight(r, h)

    def current_location(self) -> Optional[str]:
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        return cells.address(idx.row(), idx.column())

    def select_location(self, loc: str) -> None:
        r = cells.parse_address(loc)
        if r:
            idx = self.model().index(*r)
            self.setCurrentIndex(idx)
            self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    def selected_locations(self) -> list[str]:
        return [cells.address(i.row(), i.column()) for i in self.selectedIndexes()]

    def _selection_block(self) -> Optional[tuple[int, int, dict[str, str]]]:
        idxs = self.selectedIndexes()
        if not idxs:
            return None
        r0 = min(i.row() for i in idxs)
        c0 = min(i.column() for i in idxs)
        model = self.model()
        block = {}
        for i in idxs:
            expr = model.data(i, EXPR_ROLE) or ""
            block[f"{i.row() - r0},{i.column() - c0}"] = expr
        return r0, c0, block

    def copy_selection(self) -> None:
        sel = self._selection_block()
        if not sel:
            return
        r0, c0, block = sel
        import json

        from PySide6.QtCore import QMimeData

        mime = QMimeData()
        mime.setData(self.MIME, json.dumps({"row": r0, "col": c0, "cells": block}).encode())
        # Plain text: tab separated expressions for other applications.
        rows = {}
        for key, expr in block.items():
            r, c = map(int, key.split(","))
            rows.setdefault(r, {})[c] = expr
        lines = []
        for r in range(max(rows) + 1):
            cols = rows.get(r, {})
            lines.append("\t".join(cols.get(c, "") for c in range(max(cols, default=-1) + 1)))
        mime.setText("\n".join(lines))
        QApplication.clipboard().setMimeData(mime)

    def cut_selection(self) -> None:
        self.copy_selection()
        self.clear_selection()

    def clear_selection(self) -> None:
        locs = [loc for loc in self.selected_locations() if self.model().expressions.get(loc)]
        if locs:
            self.clearRequested.emit(locs)

    def paste(self) -> None:
        import json

        target = self.currentIndex()
        if not target.isValid():
            return
        mime = QApplication.clipboard().mimeData()
        out: dict[str, str] = {}
        if mime.hasFormat(self.MIME):
            doc = json.loads(bytes(mime.data(self.MIME).data()).decode())
            d_row = target.row() - int(doc["row"])
            d_col = target.column() - int(doc["col"])
            for key, expr in doc["cells"].items():
                r, c = map(int, key.split(","))
                rr, cc = target.row() + r, target.column() + c
                if 0 <= rr < cells.NUM_ROWS and 0 <= cc < cells.NUM_COLS:
                    out[cells.address(rr, cc)] = cells.shift_references(expr, d_row, d_col)
        elif mime.hasText():
            for r, line in enumerate(mime.text().splitlines()):
                for c, expr in enumerate(line.split("\t")):
                    rr, cc = target.row() + r, target.column() + c
                    if 0 <= rr < cells.NUM_ROWS and 0 <= cc < cells.NUM_COLS:
                        out[cells.address(rr, cc)] = expr
        if out:
            self.pasteRequested.emit(out)

    def contextMenuEvent(self, event) -> None:
        idx = self.indexAt(event.pos())
        if not idx.isValid():
            return
        loc = cells.address(idx.row(), idx.column())
        menu = QMenu(self)
        self.contextMenuForCell.emit(loc, menu)
        menu.addSeparator()
        menu.addAction("Cut", self.cut_selection)
        menu.addAction("Copy", self.copy_selection)
        menu.addAction("Paste", self.paste)
        menu.addAction("Clear", self.clear_selection)
        menu.exec(event.globalPos())
