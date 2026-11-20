"""Spreadsheet model (26 x 600 cells) and view."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QDoubleSpinBox,
    QHeaderView,
    QLineEdit,
    QMenu,
    QSpinBox,
    QTableView,
    QWidget,
)

from . import cells
from .functions_ui import FUNCTION_MIME
from .cell_controls import CLICK_KINDS, EXPR_ROLE, NAME_ROLE, PENDING_ROLE, RESULT_ROLE, VALUE_KINDS  # noqa: F401

ERROR_COLOR = QColor(220, 50, 50)
DISABLED_COLOR = QColor(150, 150, 150)
PENDING_COLOR = QColor(140, 140, 200)
ERROR_TIP = "#ERR: the function could not be evaluated (the In-Sight HMI API does not report why)"

# ISVS grid defaults
DEFAULT_COL_WIDTH = 64
DEFAULT_ROW_HEIGHT = 20
DEFAULT_FONT = ("Arial", 9.0)
CELL_COLOR = QColor(212, 212, 212)
SELECTED_COLOR = QColor(218, 228, 244)


def default_font(zoom: float = 1.0) -> QFont:
    font = QFont(DEFAULT_FONT[0])
    font.setPointSizeF(DEFAULT_FONT[1] * zoom)
    return font


def _with_alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(min(c.alpha(), alpha))
    return c


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
        self.cell_alpha = 255  # < 255 while the grid is overlaid on the image
        self.zoom = 1.0  # Grid Size

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
            return cells.grid_text(result, expr, fmt.decimals if fmt else None)
        if role in (Qt.ItemDataRole.EditRole, EXPR_ROLE):
            return expr
        if role == RESULT_ROLE:
            return result
        if role == NAME_ROLE:
            return self.names.get(loc)
        if role == PENDING_ROLE:
            return loc in self.pending
        if role == Qt.ItemDataRole.ToolTipRole:
            # ISVS: the tooltip names the cell; error cells explain the error
            lines = []
            if loc in self.names:
                lines.append(self.names[loc])
            if cells.is_error(result) and loc not in self.pending:
                lines.append(ERROR_TIP)
            return "\n".join(lines) or None
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
            color = None
            if cells.result_kind(result) == "ColorLabelResult":
                rgba = cells.argb_to_rgba(result.get("backColor"))
                if rgba and rgba[3] > 0:
                    color = QColor(*rgba)
            if color is None and fmt and fmt.back and fmt.back[3] > 0:
                color = QColor(*fmt.back)
            return QBrush(_with_alpha(color, self.cell_alpha)) if color is not None else None
        if role == Qt.ItemDataRole.FontRole:
            if fmt and (fmt.bold or fmt.italic or fmt.font_size or fmt.font_name):
                font = default_font(self.zoom)
                if fmt.font_name:
                    font.setFamily(fmt.font_name)
                font.setBold(fmt.bold)
                font.setItalic(fmt.italic)
                if fmt.font_size:
                    font.setPointSizeF(float(fmt.font_size) * self.zoom)
                return font
            if loc in self.pending:
                font = default_font(self.zoom)
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


HEADER_BACK = QColor("#f0f0f0")
HEADER_ACTIVE = QColor("#fff200")  # ISVS: yellow row/column header of the selected cells
HEADER_LINE = QColor("#b0b0b0")


class SheetHeader(QHeaderView):
    """Row/column header: flat sections, the ones of the selected cells in yellow (text not bold)."""

    def is_active(self, section: int) -> bool:
        view = self.parent()
        sel = view.selectionModel() if isinstance(view, QTableView) else None
        if sel is None:
            return False
        cur = sel.currentIndex()
        if self.orientation() == Qt.Orientation.Horizontal:
            return (cur.isValid() and cur.column() == section) or sel.columnIntersectsSelection(section, QModelIndex())
        return (cur.isValid() and cur.row() == section) or sel.rowIntersectsSelection(section, QModelIndex())

    def paintSection(self, painter: QPainter, rect, section: int) -> None:
        if not rect.isValid():
            return
        painter.save()
        painter.fillRect(rect, HEADER_ACTIVE if self.is_active(section) else HEADER_BACK)
        painter.setPen(HEADER_LINE)
        painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setPen(QColor(0, 0, 0))
        painter.setFont(self.font())
        model = self.model()
        text = str(model.headerData(section, self.orientation())) if model is not None else ""
        align = Qt.AlignmentFlag.AlignHCenter if self.orientation() == Qt.Orientation.Horizontal \
            else Qt.AlignmentFlag.AlignRight
        painter.drawText(rect.adjusted(2, 0, -3, 0), int(align | Qt.AlignmentFlag.AlignVCenter), text)
        painter.restore()


SELECT_RED = QColor(230, 0, 0)  # cell selection mode: outline of the referenced cells
SELECT_DEST = QColor(255, 205, 205)  # cell selection mode: the cell that receives the reference
CUT_PEN = QColor(40, 40, 40)


class SheetView(QTableView):
    """Spreadsheet grid with clipboard support (expressions shift like a spreadsheet)."""

    # Paste: {"target": [row, col], "cells": {"dr,dc": expr}, "conditions": {"dr,dc": cond},
    # "source": [row, col] | None, "cut": bool, "block": [r0, c0, r1, c1] | None}
    pasteRequested = Signal(dict)
    clearRequested = Signal(list)  # [locations]
    selectionModeFinished = Signal(object)  # cell selection mode: range text ("B3", "B3:C5") or None
    contextMenuRequested = Signal(QPoint)  # global position; the current cell is the one clicked
    valueRequested = Signal(str, object)  # in-cell control operated: location, new value
    graphicRequested = Signal(str)  # edit-graphic button (EditRegion, ...) clicked
    functionDropped = Signal(str, str)  # a function dragged from the Functions panel: location, name

    MIME = "application/x-insight-studio-cells"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sheet")
        self.setHorizontalHeader(SheetHeader(Qt.Orientation.Horizontal, self))
        self.setVerticalHeader(SheetHeader(Qt.Orientation.Vertical, self))
        self._zoom = 1.0
        self._cell_alpha = 255
        self._format_widths: list[int] = []
        self._format_heights: list[int] = []
        self.controls_enabled = True  # in-cell controls can be operated (set by the main window)
        self._pressed_index = None
        self._press_part = ""
        self._value_editor: Optional[QWidget] = None
        self._listbox_menu: Optional[QMenu] = None
        self.cut_block: Optional[tuple[int, int, int, int]] = None  # cells marked by Cut (moved on Paste)
        self._select_dest: Optional[tuple[int, int]] = None  # cell selection mode: destination cell
        self.viewport().setAutoFillBackground(False)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(False)
        self.setFont(default_font())
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                             | QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setMinimumSectionSize(4)
        self.verticalHeader().setMinimumSectionSize(4)
        self.horizontalHeader().setDefaultSectionSize(DEFAULT_COL_WIDTH)
        self.verticalHeader().setDefaultSectionSize(DEFAULT_ROW_HEIGHT)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.horizontalHeader().setHighlightSections(True)
        self.verticalHeader().setHighlightSections(True)
        self.horizontalHeader().setSectionsClickable(True)
        self.verticalHeader().setSectionsClickable(True)
        self.setWordWrap(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        # The main window may route these through its own handlers (e.g. Copy also reads cell states).
        self.handlers: dict[str, object] = {}
        for seq, key, slot in ((QKeySequence.StandardKey.Copy, "copy", self.copy_selection),
                               (QKeySequence.StandardKey.Cut, "cut", self.cut_selection),
                               (QKeySequence.StandardKey.Paste, "paste", self.paste),
                               (QKeySequence.StandardKey.Delete, "clear", self.clear_selection)):
            act = QAction(self)
            act.setShortcut(seq)
            act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            act.triggered.connect(lambda _c=False, k=key, f=slot: None if self.in_selection_mode
                                  else (self.handlers.get(k) or f)())
            self.addAction(act)

    # Set by the main window: True for cells that open a property sheet instead of the
    # in-cell editor when double-clicked (training tools).
    opens_on_double_click = None

    def edit(self, *args):
        if len(args) == 3 and self.in_selection_mode:
            return False
        if (len(args) == 3 and args[1] == QAbstractItemView.EditTrigger.DoubleClicked
                and self.opens_on_double_click is not None and self.opens_on_double_click(args[0])):
            return False
        if len(args) == 3:
            self.close_value_editor(commit=True)
        return super().edit(*args)

    def setModel(self, model) -> None:
        super().setModel(model)
        if isinstance(model, SheetModel):
            model.cell_alpha = self._cell_alpha
            model.zoom = self._zoom

    def apply_sheet_format(self, widths: list[int], heights: list[int]) -> None:
        self._format_widths, self._format_heights = list(widths), list(heights)
        z = self._zoom
        default_w = self.horizontalHeader().defaultSectionSize()
        for c, w in enumerate(widths):
            self.setColumnWidth(c, round(w * z) if w > 0 else default_w)
        for r, h in enumerate(heights):
            if h > 0:
                self.setRowHeight(r, round(h * z))

    # ------------------------------------------------------------------ look
    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        """Grid Size: scales the cells, headers and fonts."""
        self._zoom = max(0.25, min(4.0, float(zoom)))
        self.setFont(default_font(self._zoom))
        for header in (self.horizontalHeader(), self.verticalHeader()):
            header.setFont(default_font(self._zoom))
        self.horizontalHeader().setDefaultSectionSize(round(DEFAULT_COL_WIDTH * self._zoom))
        self.verticalHeader().setDefaultSectionSize(round(DEFAULT_ROW_HEIGHT * self._zoom))
        for c in range(cells.NUM_COLS):
            self.setColumnWidth(c, self.horizontalHeader().defaultSectionSize())
        for r in range(cells.NUM_ROWS):
            self.setRowHeight(r, self.verticalHeader().defaultSectionSize())
        self.apply_sheet_format(self._format_widths, self._format_heights)
        model = self.model()
        if isinstance(model, SheetModel):
            model.zoom = self._zoom
            model._all_changed()

    @property
    def cell_alpha(self) -> int:
        return self._cell_alpha

    def set_cell_alpha(self, alpha: int) -> None:
        """Opacity of the cells (255 = opaque); lower values let the image behind show through."""
        self._cell_alpha = max(0, min(255, int(alpha)))
        sel = SELECTED_COLOR
        self.setStyleSheet(f"QTableView#sheet {{ selection-background-color: "
                           f"rgba({sel.red()},{sel.green()},{sel.blue()},{self._cell_alpha}); }}")
        model = self.model()
        if isinstance(model, SheetModel):
            model.cell_alpha = self._cell_alpha
            model._all_changed()
        self.viewport().update()

    def paintEvent(self, event) -> None:
        p = QPainter(self.viewport())
        p.fillRect(event.rect(), _with_alpha(CELL_COLOR, self._cell_alpha))
        p.end()
        super().paintEvent(event)
        if self.cut_block is not None:
            rect = self._block_rect(self.cut_block)
            if rect is not None:
                p = QPainter(self.viewport())
                p.setPen(QPen(CUT_PEN, 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rect.adjusted(1, 1, -2, -2))
                p.end()
        if self._select_dest is not None:
            self._paint_selection_mode()
            return
        idx = self.currentIndex()
        if idx.isValid():  # ISVS outlines the active cell in black
            r = self.visualRect(idx)
            if r.isValid() and r.intersects(event.rect()):
                p = QPainter(self.viewport())
                p.setPen(QPen(QColor(0, 0, 0), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r.adjusted(0, 0, -1, -1))
                p.end()

    def _block_rect(self, block):
        model = self.model()
        r0, c0, r1, c1 = block
        a = self.visualRect(model.index(r0, c0))
        b = self.visualRect(model.index(r1, c1))
        if not a.isValid() and not b.isValid():
            return None
        return a.united(b)

    def _paint_selection_mode(self) -> None:
        p = QPainter(self.viewport())
        dest = self.visualRect(self.model().index(*self._select_dest))
        if dest.isValid():
            p.fillRect(dest.adjusted(1, 1, -1, -1), SELECT_DEST)
            text = self.model().index(*self._select_dest).data(Qt.ItemDataRole.DisplayRole)
            if text:
                p.setPen(QColor(0, 0, 0))
                p.drawText(dest.adjusted(3, 0, -3, 0), int(Qt.AlignmentFlag.AlignVCenter), str(text))
        block = self.selection_block()
        rect = self._block_rect(block) if block else None
        if rect is not None:
            p.setPen(QPen(SELECT_RED, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect.adjusted(1, 1, -1, -1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(SELECT_RED)
            h = 6
            for pt in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                p.drawRect(pt.x() - h // 2 + 1, pt.y() - h // 2 + 1, h, h)
        p.end()

    def selectionChanged(self, selected, deselected) -> None:
        super().selectionChanged(selected, deselected)
        if self._select_dest is not None or self.cut_block is not None:
            self.viewport().update()

    def currentChanged(self, current, previous) -> None:
        super().currentChanged(current, previous)
        for idx in (previous, current):  # repaint the old and new outline (it overlaps the grid lines)
            if idx.isValid():
                self.viewport().update(self.visualRect(idx).adjusted(-2, -2, 2, 2))
        self.horizontalHeader().viewport().update()
        self.verticalHeader().viewport().update()

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

    def selection_block(self) -> Optional[tuple[int, int, int, int]]:
        """The selected rectangle (row0, col0, row1, col1); the current cell when nothing is
        selected; None for a selection made of several rectangles."""
        ranges = [r for r in self.selectionModel().selection() if r.isValid()]
        if len(ranges) > 1:
            # Qt may split one rectangle into several ranges; accept them if they tile a rectangle
            idxs = self.selectedIndexes()
            r0, r1 = min(i.row() for i in idxs), max(i.row() for i in idxs)
            c0, c1 = min(i.column() for i in idxs), max(i.column() for i in idxs)
            if len(idxs) != (r1 - r0 + 1) * (c1 - c0 + 1):
                return None
            return r0, c0, r1, c1
        if ranges:
            r = ranges[0]
            return r.top(), r.left(), r.bottom(), r.right()
        cur = self.currentIndex()
        if cur.isValid():
            return cur.row(), cur.column(), cur.row(), cur.column()
        return None

    def select_block(self, block: tuple[int, int, int, int], current: Optional[tuple[int, int]] = None) -> None:
        from PySide6.QtCore import QItemSelection, QItemSelectionModel

        r0, c0, r1, c1 = block
        model = self.model()
        cur = current or (r0, c0)
        self.selectionModel().setCurrentIndex(model.index(*cur), QItemSelectionModel.SelectionFlag.NoUpdate)
        sel = QItemSelection(model.index(r0, c0), model.index(r1, c1))
        self.selectionModel().select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.viewport().update()

    def _selection_block(self) -> Optional[tuple[int, int, dict[str, str]]]:
        block = self.selection_block()
        if block is None:
            return None
        r0, c0, r1, c1 = block
        model = self.model()
        out = {}
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                out[f"{r - r0},{c - c0}"] = model.data(model.index(r, c), EXPR_ROLE) or ""
        return r0, c0, out

    def copy_selection(self, conditions: Optional[dict[str, str]] = None, cut: bool = False) -> bool:
        """Copies the selected rectangle. ``conditions``: cell states by location (copied like
        references). ``cut`` marks the cells: they move when pasted (references follow them)."""
        sel = self._selection_block()
        if not sel:
            return False
        r0, c0, block = sel
        import json

        from PySide6.QtCore import QMimeData

        conds = {}
        for key in block:
            dr, dc = map(int, key.split(","))
            cond = (conditions or {}).get(cells.address(r0 + dr, c0 + dc))
            if cond:
                conds[key] = cond
        rows_n = 1 + max(int(k.split(",")[0]) for k in block)
        cols_n = 1 + max(int(k.split(",")[1]) for k in block)
        doc = {"row": r0, "col": c0, "cells": block, "conditions": conds, "cut": cut,
               "block": [r0, c0, r0 + rows_n - 1, c0 + cols_n - 1]}
        mime = QMimeData()
        mime.setData(self.MIME, json.dumps(doc).encode())
        # Plain text: tab separated expressions for other applications.
        lines = ["\t".join(block.get(f"{r},{c}", "") for c in range(cols_n)) for r in range(rows_n)]
        mime.setText("\n".join(lines))
        self.set_cut_block(tuple(doc["block"]) if cut else None)
        QApplication.clipboard().setMimeData(mime)
        return True

    def cut_selection(self) -> None:
        self.copy_selection(cut=True)

    def set_cut_block(self, block: Optional[tuple[int, int, int, int]]) -> None:
        """Cells marked by Cut get a dashed outline until they are pasted (or Escape)."""
        if block != self.cut_block:
            self.cut_block = block
            self.viewport().update()

    def clear_selection(self) -> None:
        locs = [loc for loc in self.selected_locations() if self.model().expressions.get(loc)]
        if locs:
            self.clearRequested.emit(locs)

    def can_paste(self) -> bool:
        mime = QApplication.clipboard().mimeData()
        return mime is not None and (mime.hasFormat(self.MIME) or (mime.hasText() and bool(mime.text())))

    def clipboard_doc(self) -> Optional[dict]:
        import json

        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(self.MIME):
            return None
        try:
            return json.loads(bytes(mime.data(self.MIME).data()).decode())
        except ValueError:
            return None

    def paste(self) -> None:
        target = self.currentIndex()
        if not target.isValid():
            return
        mime = QApplication.clipboard().mimeData()
        doc = self.clipboard_doc()
        out: dict
        if doc is not None:
            out = {"target": [target.row(), target.column()], "cells": doc.get("cells") or {},
                   "conditions": doc.get("conditions") or {}, "source": [doc["row"], doc["col"]],
                   "cut": bool(doc.get("cut")), "block": doc.get("block")}
        elif mime is not None and mime.hasText():
            block = {}
            for r, line in enumerate(mime.text().splitlines()):
                for c, expr in enumerate(line.split("\t")):
                    block[f"{r},{c}"] = expr
            out = {"target": [target.row(), target.column()], "cells": block, "conditions": {}, "source": None,
                   "cut": False, "block": None}
        else:
            return
        if out["cells"]:
            self.pasteRequested.emit(out)

    # ------------------------------------------------------------------ hide / unhide (view only)
    def hide_sections(self, block: tuple[int, int, int, int], rows: bool) -> None:
        r0, c0, r1, c1 = block
        if rows:
            for r in range(r0, r1 + 1):
                self.setRowHidden(r, True)
        else:
            for c in range(c0, c1 + 1):
                self.setColumnHidden(c, True)

    def unhide_sections(self, block: tuple[int, int, int, int], rows: bool) -> int:
        """Shows the hidden rows/columns inside ``block`` (select A and D to show B and C)."""
        r0, c0, r1, c1 = block
        n = 0
        for i in (range(r0, r1 + 1) if rows else range(c0, c1 + 1)):
            hidden = self.isRowHidden(i) if rows else self.isColumnHidden(i)
            if hidden:
                (self.setRowHidden if rows else self.setColumnHidden)(i, False)
                n += 1
        return n

    def has_hidden(self, block: tuple[int, int, int, int], rows: bool) -> bool:
        r0, c0, r1, c1 = block
        if rows:
            return any(self.isRowHidden(r) for r in range(r0, r1 + 1))
        return any(self.isColumnHidden(c) for c in range(c0, c1 + 1))

    # ------------------------------------------------------------------ cell selection mode
    @property
    def in_selection_mode(self) -> bool:
        return self._select_dest is not None

    def begin_selection_mode(self, dest: str, start: Optional[str] = None) -> None:
        """Cell selection mode (ISVS): pick the referenced cell(s) with the mouse or Shift+arrows;
        the destination cell is light red, the picked range has a red outline. Enter or a
        double-click accepts, Escape cancels; :attr:`selectionModeFinished` reports the result."""
        rc = cells.parse_address(dest)
        if rc is None:
            return
        self.close_value_editor()
        self._select_dest = rc
        start_rc = cells.parse_address(start) if start else None
        if start_rc is not None:
            self.select_block((*start_rc, *start_rc))
        self.setFocus()
        self.viewport().update()

    def finish_selection_mode(self, accept: bool) -> None:
        if self._select_dest is None:
            return
        dest, self._select_dest = self._select_dest, None
        block = self.selection_block() if accept else None
        text = None
        if block is not None:
            text = cells.address(block[0], block[1])
            if block[:2] != block[2:]:
                text += ":" + cells.address(block[2], block[3])
        self.select_block((*dest, *dest))
        self.viewport().update()
        self.selectionModeFinished.emit(text)

    def keyPressEvent(self, event) -> None:
        if self.in_selection_mode:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.finish_selection_mode(True)
                return
            if event.key() == Qt.Key.Key_Escape:
                self.finish_selection_mode(False)
                return
        elif event.key() == Qt.Key.Key_Escape and self.cut_block is not None:
            self.set_cut_block(None)
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        if self.in_selection_mode:
            return
        idx = self.indexAt(event.pos())
        if not idx.isValid():
            return
        if not self.selectionModel().isSelected(idx):  # right-click outside the selection selects the cell
            self.setCurrentIndex(idx)
        self.contextMenuRequested.emit(event.globalPos())

    # ------------------------------------------------------------------ function drag & drop
    def _function_drop_index(self, event):
        if self.in_selection_mode or not event.mimeData().hasFormat(FUNCTION_MIME):
            return None
        index = self.indexAt(event.position().toPoint())
        return index if index.isValid() else None

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(FUNCTION_MIME) and not self.in_selection_mode:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        index = self._function_drop_index(event)
        if index is None:
            event.ignore()
            return
        if index != self.currentIndex():
            self.setCurrentIndex(index)  # the target cell follows the mouse, as in ISVS
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        index = self._function_drop_index(event)
        if index is None:
            event.ignore()
            return
        name = bytes(event.mimeData().data(FUNCTION_MIME)).decode("utf-8", "replace")
        event.acceptProposedAction()
        self.functionDropped.emit(cells.address(index.row(), index.column()), name)

    # ------------------------------------------------------------------ in-cell expression editor
    def editor_widget(self) -> Optional[QWidget]:
        """The open in-cell expression editor, if any."""
        if self.state() != QAbstractItemView.State.EditingState:
            return None
        return self.indexWidget(self.currentIndex())

    def commit_editor(self) -> bool:
        editor = self.editor_widget()
        if editor is None:
            return False
        self.commitData(editor)
        self.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        self.setFocus()
        return True

    def cancel_editor(self) -> bool:
        editor = self.editor_widget()
        if editor is None:
            return False
        self.closeEditor(editor, QAbstractItemDelegate.EndEditHint.RevertModelCache)
        self.setFocus()
        return True

    # ------------------------------------------------------------------ in-cell controls
    def _control_part(self, index, pos: QPoint) -> Optional[str]:
        delegate = self.itemDelegate()
        if not index.isValid() or not hasattr(delegate, "hit_part"):
            return None
        if delegate.kind(index) not in CLICK_KINDS:
            return None
        return delegate.hit_part(index, self.visualRect(index), pos, self.font())

    def _control_usable(self, index) -> bool:
        result = index.data(RESULT_ROLE) or {}
        return self.controls_enabled and not result.get("disabled") and not cells.is_error(result)

    def _location(self, index) -> str:
        return cells.address(index.row(), index.column())

    def _set_pressed(self, index) -> None:
        delegate = self.itemDelegate()
        old = getattr(delegate, "pressed", None)
        delegate.pressed = (index.row(), index.column()) if index is not None and index.isValid() else None
        for rc in (old, delegate.pressed):
            if rc is not None:
                self.viewport().update(self.visualRect(self.model().index(*rc)))

    def _control_press(self, event) -> bool:
        """Mouse press on an in-cell control. Returns True when the control took the click."""
        if event.button() != Qt.MouseButton.LeftButton or event.modifiers() & (
                Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
            return False
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        part = self._control_part(index, pos)
        if part is None or not self._control_usable(index):
            return False
        kind = self.itemDelegate().kind(index)
        was_current = index == self.currentIndex()
        if part == "field" and kind in VALUE_KINDS and not was_current:
            return False  # first click selects the cell (and may start a drag selection)
        if not was_current or len(self.selectedIndexes()) != 1:
            self.setCurrentIndex(index)
        if part in ("button", "check"):
            self._press_part = part
            self._set_pressed(index if part == "button" else None)
            self._pressed_index = index
        elif kind == "listbox":
            self.show_listbox(index)
        elif part in ("up", "down"):
            self.step_value(index, 1 if part == "up" else -1)
        elif part == "field" and kind in VALUE_KINDS and was_current:
            self.open_value_editor(index)
        return True

    def mousePressEvent(self, event) -> None:
        self._pressed_index = None
        if self.editor_widget() is None and not self.in_selection_mode and self._control_press(event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        if self.in_selection_mode:
            if index.isValid():  # a double-click accepts a single-cell reference
                self.select_block((index.row(), index.column(), index.row(), index.column()))
                self.finish_selection_mode(True)
            event.accept()
            return
        part = self._control_part(index, pos)
        if part is not None and self._control_usable(index):
            kind = self.itemDelegate().kind(index)
            if kind in VALUE_KINDS and part == "field":
                self.open_value_editor(index)
            else:
                self._control_press(event)  # a quick second click operates the control again
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pressed_index is not None:
            if self._press_part == "button":  # pressed look only while the mouse is over the button
                over = self.indexAt(event.position().toPoint()) == self._pressed_index
                self._set_pressed(self._pressed_index if over else None)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        index, self._pressed_index = self._pressed_index, None
        if index is None:
            super().mouseReleaseEvent(event)
            return
        self._set_pressed(None)
        pos = event.position().toPoint()
        if self.indexAt(pos) == index and self._control_part(index, pos) == self._press_part:
            loc = self._location(index)
            result = index.data(RESULT_ROLE) or {}
            if self._press_part == "check":
                self.valueRequested.emit(loc, 0 if result.get("data") else 1)
            elif cells.control_kind(result) == "graphic":
                self.graphicRequested.emit(loc)
            else:
                self.valueRequested.emit(loc, "1")  # Button press (as the Cognex HMI sample does)
        event.accept()

    def show_listbox(self, index) -> QMenu:
        """Drop-down list of a ListBox cell; picking an entry writes its index."""
        result = index.data(RESULT_ROLE) or {}
        loc = self._location(index)
        menu = QMenu(self)
        menu.setObjectName("listboxPopup")
        rect = self.visualRect(index)
        menu.setMinimumWidth(rect.width())
        current = result.get("data")
        for i, text in enumerate(result.get("options") or []):
            act = menu.addAction(str(text))
            act.setCheckable(True)
            act.setChecked(str(i) == str(current))
            act.triggered.connect(lambda _c=False, v=i: self.valueRequested.emit(loc, v))
        if current is not None and menu.actions():
            try:
                menu.setActiveAction(menu.actions()[int(current)])
            except (ValueError, IndexError):
                pass
        self._listbox_menu = menu
        menu.popup(self.viewport().mapToGlobal(rect.bottomLeft()))
        return menu

    def step_value(self, index, direction: int) -> None:
        """Spin arrows of an EditInt/EditFloat cell: one step up or down within Min..Max."""
        result = index.data(RESULT_ROLE) or {}
        try:
            value = float(result.get("data") or 0) + direction
        except (TypeError, ValueError):
            return
        lo, hi = result.get("min"), result.get("max")
        if lo is not None:
            value = max(float(lo), value)
        if hi is not None:
            value = min(float(hi), value)
        if cells.result_kind(result) == "EditIntResult":
            value = int(round(value))
        if value != result.get("data"):
            self.valueRequested.emit(self._location(index), value)

    def open_value_editor(self, index) -> Optional[QWidget]:
        """Edits the value of an EditInt/EditFloat/EditString cell in a box over the cell."""
        self.close_value_editor()
        result = index.data(RESULT_ROLE) or {}
        kind = cells.control_kind(result)
        data = result.get("data")
        if kind == "editint":
            w = QSpinBox(self.viewport())
            w.setRange(int(result.get("min", -2147483648)), int(result.get("max", 2147483647)))
            w.setValue(int(data or 0))
        elif kind == "editfloat":
            w = QDoubleSpinBox(self.viewport())
            fmt = self.model().formats.get(self._location(index)) if isinstance(self.model(), SheetModel) else None
            w.setDecimals(fmt.decimals if fmt and fmt.decimals is not None else 3)
            w.setRange(float(result.get("min", -1e12)), float(result.get("max", 1e12)))
            w.setValue(float(data or 0))
        elif kind == "editstring":
            w = QLineEdit("" if data is None else str(data), self.viewport())
            if result.get("maxLength"):
                w.setMaxLength(int(result["maxLength"]))
            if result.get("maskInput"):
                w.setEchoMode(QLineEdit.EchoMode.Password)
        else:
            return None
        w.setObjectName("valueEditor")
        if kind != "editstring":
            w.setAlignment(Qt.AlignmentFlag.AlignRight)
            w.setKeyboardTracking(False)
        w.setFont(self.font())
        w.setGeometry(self.visualRect(index))
        w.setProperty("location", self._location(index))
        w.setProperty("initial", w.text())
        w.installEventFilter(self)
        line = w if isinstance(w, QLineEdit) else w.lineEdit()
        line.returnPressed.connect(lambda: self.close_value_editor(commit=True))
        self._value_editor = w
        w.show()
        w.setFocus()
        line.selectAll()
        return w

    def close_value_editor(self, commit: bool = False, refocus: bool = True) -> None:
        w, self._value_editor = self._value_editor, None
        if w is None:
            return
        if commit and w.text() != w.property("initial"):
            if isinstance(w, QSpinBox):
                value = w.value()
            elif isinstance(w, QDoubleSpinBox):
                value = round(w.value(), w.decimals())
            else:
                value = w.text()
            self.valueRequested.emit(str(w.property("location")), value)
        w.removeEventFilter(self)
        w.hide()
        w.deleteLater()
        if refocus:
            self.setFocus()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._value_editor:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.close_value_editor()
                return True
            if event.type() == QEvent.Type.FocusOut:
                focus = QApplication.focusWidget()
                if focus is None or not obj.isAncestorOf(focus):
                    # like a spreadsheet: leaving the box keeps the value
                    self.close_value_editor(commit=True, refocus=False)
                return False
        return super().eventFilter(obj, event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.close_value_editor()
        super().scrollContentsBy(dx, dy)
