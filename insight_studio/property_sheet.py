"""Property sheet for a spreadsheet tool cell, laid out like the one in In-Sight Vision Suite 26.1
(``Inspection - Property Sheet - TrainPatMaxRedLine``, live screenshots ``live/17…20``, ``live/24…97``).

One row per parameter of the function (names, groups, defaults, ranges and choices come from
the In-Sight help, see :mod:`helpdoc`): a label, the value (text box with references in blue,
spin box, check box, list, or a button for event parameters) and ``= result``. Groups such as
Fixture and Region show their values as ``(x,y,…)`` and expand into one field per argument.
When a reference points at an HMI control (EditInt, CheckBox, …) the third column shows the
control itself and changes the linked cell's value; a Button can be pressed (e.g. the Train
button of a TrainPatMaxRedLine), and an Edit graphic can be edited on the image.

Parameters that only apply when another one has a certain value are greyed out (catalog
``enable`` rules). While the sheet is open its region (the selected region parameter, else the
first one) is drawn on the image in the tool's fixture, with scan arrows and a centre cross-hair
but no handles; Edit ▸ Graphic (F9) hides the sheet and edits it in Interactive Graphics Mode —
Return puts the new numbers into the sheet, Escape discards them (ISVS, survey 2026-11-20).
Maximize Region stretches it over the image.

Edits are applied to the job while the sheet is open (so results and the error mark follow), OK
keeps them and Cancel restores the expression and the linked values that were changed. (ISVS's
formula bar shows the new expression only after OK.)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from PySide6.QtCore import QPointF, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import cells, icons, theme
from .catalog import FunctionInfo, find_help_file
from .cell_dialogs import SHEET_NAME
from .editors import EDITABLE_TYPES
from .helpdoc import leaf_count, parse_inputs_file

REFERENCE_COLOR = "#5aa0ff"
_UNSET = object()  # no regionShown sent yet: the next one is sent even if it is None
LABEL_SELECTED = theme.ACCENT

# ---------------------------------------------------------------------------- expressions
_TRAINING_PREFIXES = ("train", "edgeai")
_TRAINING_WORDS = ("ocrmax", "trainfont")


def is_training_function(name: Optional[str]) -> bool:
    """Tools that train a model: TrainPatMaxRedLine, TrainPatMaxPattern, EdgeAI*, OCRMax, …"""
    n = (name or "").lower()
    return n.startswith(_TRAINING_PREFIXES) or any(w in n for w in _TRAINING_WORDS)


def split_call(expr: str) -> Optional[tuple[str, list[str]]]:
    """``"Name(a, B(1,2), "x,y")"`` -> ``("Name", ["a", "B(1,2)", '"x,y"'])``.

    None unless the whole expression is one function call.
    """
    m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", expr or "")
    if not m:
        return None
    depth, in_str, start = 1, False, m.end()
    args: list[str] = []
    i = m.end()
    while i < len(expr):
        ch = expr[i]
        if in_str:
            if ch == '"':
                if expr[i + 1:i + 2] == '"':
                    i += 2
                    continue
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                if expr[i + 1:].strip():
                    return None
                args.append(expr[start:i].strip())
                if args == [""]:
                    args = []
                return m.group(1), args
        elif ch == "," and depth == 1:
            args.append(expr[start:i].strip())
            start = i + 1
        i += 1
    return None


def join_call(name: str, args: list[str]) -> str:
    return f"{name}({','.join(args)})"


_SINGLE_REF = re.compile(r"\$?[A-Za-z]\$?\d{1,3}")


def ref_location(arg: str, location_of_name: Callable[[str], Optional[str]]) -> Optional[str]:
    """The cell an argument refers to when it is just a reference (``$A$12``, ``B3``, a name)."""
    a = arg.strip()
    if _SINGLE_REF.fullmatch(a) and cells.parse_address(a):
        return a.replace("$", "").upper()
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", a):
        return location_of_name(a)
    return None


def referenced_locations(arg: str) -> list[str]:
    """All cell references inside an argument expression (outside string literals)."""
    out: list[str] = []
    for is_str, chunk in cells._split_strings(arg):
        if is_str:
            continue
        for m in cells._REF_RE.finditer(chunk.upper()):
            loc = f"{m.group(2)}{m.group(4)}"
            if cells.parse_address(loc) and loc not in out:
                out.append(loc)
    return out


_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def _is_number(text: str) -> bool:
    return bool(_NUMBER.fullmatch(text.strip()))


def _fmt(v: float, decimals: int) -> str:
    if decimals == 0:
        return str(int(round(v)))
    text = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


# Whole-number parameters (ISVS shows them without decimals: Timeout 0, Number to Sort 6). The
# catalog says so for the sheets read in ISVS (``integer``); otherwise it is guessed from the
# name/description (the help does not tell).
_INTEGER_NAME = re.compile(r"\b(timeout|number|count|index|num|sort|results|max(imum)? (results|count|number)|"
                           r"length|size|bit|port|id)\b", re.I)


def is_integer_parameter(param: Optional[dict], description: str = "") -> bool:
    p = param or {}
    if p.get("kind") in ("bool", "enum"):
        return True
    if "integer" in p:
        return bool(p["integer"])
    name = p.get("name", "")
    return bool(_INTEGER_NAME.search(name)) or "integer" in description.lower() or \
        description.lower().startswith("number of")


# ---------------------------------------------------------------------------- regions
# Group children -> keys of the graphic they make up (help names vary between tools).
_REGION_KEYS = {
    "x": "x", "center x": "x", "y": "y", "center y": "y", "width": "w", "wide": "w", "height": "h",
    "high": "h", "angle": "angle", "curve": "curve", "radius": "radius", "inner radius": "innerRadius",
    "outer radius": "outerRadius", "x 0": "x0", "y 0": "y0", "x 1": "x1", "y 1": "y1",
}
_FIXTURE_NAMES = ({"x", "y", "theta"}, {"row", "column", "theta"})


@dataclass
class RegionSpec:
    """A parameter group that describes a graphic (Region, Circle, Annulus, Line)."""

    type: str
    keys: dict[str, int]  # graphic key -> argument index
    group: "ParamRow"


def region_spec(group: "ParamRow") -> Optional[RegionSpec]:
    if not group.children or group.label.lower() == "fixture":
        return None
    keys: dict[str, int] = {}
    for c in group.children:
        k = _REGION_KEYS.get(c.label.strip().lower())
        if k and k not in keys and c.index is not None:
            keys[k] = c.index
    if {"x0", "y0", "x1", "y1"} <= set(keys):
        return RegionSpec("Line", keys, group)
    if not {"x", "y"} <= set(keys):
        return None
    if {"w", "h"} <= set(keys):
        return RegionSpec("Region", keys, group)
    if {"innerRadius", "outerRadius"} <= set(keys):
        return RegionSpec("Annulus", keys, group)
    if "radius" in keys:
        return RegionSpec("Circle", keys, group)
    return None


def fixture_transform(x: float, y: float, theta: float) -> QTransform:
    """Fixture coordinates -> image coordinates (In-Sight: angles clockwise, y down)."""
    return QTransform().translate(x, y).rotate(theta)


def maximized_region(width: float, height: float, fixture: Optional[QTransform] = None) -> dict:
    """Maximize Region: the region covering the whole image, in fixture coordinates."""
    t = fixture or QTransform()
    o = t.inverted()[0].map(QPointF(0, 0))
    angle = -math.degrees(math.atan2(t.m12(), t.m11()))
    return {"x": o.x(), "y": o.y(), "w": float(width), "h": float(height), "angle": angle + 0.0, "curve": 0.0}


# ---------------------------------------------------------------------------- parameter rows
@dataclass
class ParamRow:
    label: str
    param: Optional[dict] = None
    index: Optional[int] = None  # argument index (leaves only)
    children: list["ParamRow"] = field(default_factory=list)
    path: tuple[str, ...] = ()
    in_group: bool = False
    parent: Optional["ParamRow"] = field(default=None, repr=False, compare=False)


def build_rows(info: Optional[FunctionInfo], nargs: int) -> tuple[list[ParamRow], Optional[str]]:
    """Parameter rows for a call with ``nargs`` arguments, plus a note when the help's
    parameter list does not match the cell (then the arguments are listed by number)."""
    inputs = info.inputs if info else None
    if inputs and leaf_count(inputs) == nargs:
        rows: list[ParamRow] = []
        i = 0
        for p in inputs:
            if p.get("children"):
                group = ParamRow(p["name"], p, path=(p["name"],))
                for c in p["children"]:
                    group.children.append(ParamRow(c["name"], c, i, path=(p["name"], c["name"]), in_group=True,
                                                   parent=group))
                    i += 1
                rows.append(group)
            else:
                rows.append(ParamRow(p["name"], p, i, path=(p["name"],)))
                i += 1
        return rows, None
    names = info.params if info and info.params and len(info.params) == nargs else None
    rows = [ParamRow(names[i] if names else f"Argument {i + 1}", None, i, path=(f"#{i}",)) for i in range(nargs)]
    note = None
    if inputs:
        note = (f"The help lists {leaf_count(inputs)} inputs for {info.name} but this cell has {nargs} "
                "arguments, so they are shown by position.")
    return rows, note


# ---------------------------------------------------------------------------- widgets
class _Spin(QDoubleSpinBox):
    """Spin box that ignores the mouse wheel unless focused (so the sheet scrolls)."""

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class _IntSpin(QSpinBox):
    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class _Combo(QComboBox):
    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


TREE_STYLE = f"""
QTreeWidget {{ background: {theme.TITLE}; alternate-background-color: {theme.TITLE}; color: {theme.TEXT};
    outline: 0; }}
QTreeWidget::item {{ height: 23px; border: 0; }}
QTreeWidget::item:selected {{ background: #5e5e5e; color: {LABEL_SELECTED}; }}
QTreeWidget QLineEdit, QTreeWidget QAbstractSpinBox, QTreeWidget QComboBox {{ background: #3a3a3a;
    border: 1px solid #6e6e6e; padding: 0 2px; }}
QTreeWidget *[current="true"] {{ border: 1px solid {LABEL_SELECTED}; }}
QTreeWidget QLineEdit[reference="true"] {{ color: {REFERENCE_COLOR}; }}
QTreeWidget QPushButton {{ padding: 1px 6px; }}
"""


class ParamTree(QTreeWidget):
    """The parameter tree: groups get ISVS's ⊞/⊟ boxes (live/18) instead of the style's arrows."""

    BOX = 9

    def drawBranches(self, painter: QPainter, rect: QRect, index) -> None:  # noqa: N802 - Qt override
        if not self.model().hasChildren(index):
            return
        b = self.BOX
        x = rect.right() - self.indentation() + (self.indentation() - b) // 2
        y = rect.top() + (rect.height() - b) // 2
        painter.save()
        painter.setPen(QPen(QColor(40, 40, 40)))
        painter.setBrush(QColor(235, 235, 235))
        painter.drawRect(QRect(x, y, b - 1, b - 1))  # covers x … x+b-1 with the 1 px pen
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        c = b // 2
        painter.drawLine(x + 2, y + c, x + b - 3, y + c)  # minus
        if not self.isExpanded(index):
            painter.drawLine(x + c, y + 2, x + c, y + b - 3)  # plus
        painter.restore()


class PropertySheet(QDialog):
    expressionChanged = Signal(str, str)  # location, expression (written to the device)
    valueRequested = Signal(str, object)  # location, value (linked control / button press)
    graphicEditRequested = Signal(str)  # location of an Edit graphic cell
    pickStarted = Signal(str)  # "abs" / "rel": pick a cell reference in cell selection mode
    helpRequested = Signal()
    functionRequested = Signal()  # Insert ▸ Function: the caller picks one and calls insert_text
    regionShown = Signal(object)  # dict(graphic, transform, flags, label) or None: drawn on the image
    regionEditRequested = Signal(object)  # F9 on a region given by numbers: the same dict, editable
    maximizeRequested = Signal(str)  # Maximize Region on a referenced EditRegion cell

    WRITE_DELAY_MS = 350

    def __init__(self, location: str, expression: str, info: Optional[FunctionInfo], model,
                 parent: Optional[QWidget] = None, previous: Optional[str] = None,
                 image_size: Optional[Callable[[], Optional[tuple[int, int]]]] = None) -> None:
        super().__init__(parent)
        parsed = split_call(expression)
        if parsed is None:
            raise ValueError(f"{location} does not contain a function")
        self.location = location
        self.model = model
        self.info = info
        self.image_size = image_size or (lambda: None)
        self.name, self.args = parsed
        # what Cancel restores: the cell before a just-inserted function, else the expression now
        self.original_expression = expression if previous is None else previous
        self._written = expression
        self._known = {expression}  # expressions this sheet wrote (their echoes are not reloaded)
        self._original_values: dict[str, Any] = {}
        self._values_ok = True
        self._expr_ok = True
        self._pick: Optional[str] = None  # "abs" / "rel" while picking a cell reference
        self._current: Optional[ParamRow] = None
        self._editors: dict[int, QWidget] = {}
        self._links: dict[int, tuple[QWidget, Optional[str]]] = {}
        self._group_items: list[tuple[QTreeWidgetItem, ParamRow]] = []
        self._disabled: set[int] = set()  # argument indexes greyed out by an enable rule
        self._shown_region: Any = _UNSET  # key of the last regionShown payload (to skip repeats)
        self._expr_mode: set[int] = set()  # arguments switched to a text box by Insert ▸ Function
        self._igm_spec: Optional[RegionSpec] = None  # the region being edited after F9
        self._descriptions = self._load_descriptions()
        self._write_timer = QTimer(self, singleShot=True, interval=self.WRITE_DELAY_MS)
        self._write_timer.timeout.connect(self._write_now)

        # "Inspection - Property Sheet - TrainPatMaxRedLine" (ISVS on Windows; under Wine the separator showed as ❒)
        self.setWindowTitle(f"{SHEET_NAME} - Property Sheet - {self.name}")
        self.setModal(False)
        self.resize(426, 720)
        self._build_ui()
        self._populate()
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    # ------------------------------------------------------------------ construction
    def _action(self, text: str, slot, shortcut: Optional[str], icon: str, tip: str = "") -> QAction:
        act = QAction(icons.icon(icon), text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
            act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        act.setToolTip(f"{tip or text} ({shortcut})" if shortcut else (tip or text))
        act.triggered.connect(slot)
        self.addAction(act)
        return act

    def _build_ui(self) -> None:
        # menus and toolbar as in ISVS (live/19): Edit, Insert, Help
        self.act_graphic = self._action("Graphic", self._edit_current_graphic, "F9", "edit_graphic", "Edit Graphic")
        self.act_maximize = self._action("Maximize Region", self._maximize, "Ctrl+Shift+M", "maximize_region")
        self.act_function = self._action("Function", self._insert_function, "Ctrl+Shift+F", "insert_function",
                                         "Insert Function")
        self.act_function.setCheckable(True)
        self.act_abs = self._action("Absolute Reference", lambda: self._start_pick("abs"), "Ctrl+Shift+A", "abs_ref",
                                    "Insert Absolute Reference")
        self.act_rel = self._action("Relative Reference", lambda: self._start_pick("rel"), "Ctrl+Shift+R", "rel_ref",
                                    "Insert Relative Reference")
        self.act_help = self._action("Property Sheet Help", self.helpRequested.emit, "F1", "help")
        self.act_default = QAction("Restore Default", self, toolTip="Set the selected parameter to its default")
        self.act_default.triggered.connect(self._restore_default)
        bar = QMenuBar(self)
        m = bar.addMenu("&Edit")
        m.addAction(self.act_graphic)
        m.addAction(self.act_maximize)
        m = bar.addMenu("&Insert")
        m.addAction(self.act_function)
        m.addAction(self.act_abs)
        m.addAction(self.act_rel)
        m = bar.addMenu("&Help")
        m.addAction(self.act_help)

        tb = QToolBar()
        tb.setIconSize(QSize(16, 16))
        for a in (self.act_abs, self.act_rel, self.act_function, self.act_graphic, self.act_maximize, self.act_help):
            tb.addAction(a)

        self.tree = ParamTree()
        self.tree.setObjectName("propertyTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(14)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setStyleSheet(TREE_STYLE)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._row_menu)
        h = self.tree.header()
        h.setStretchLastSection(True)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 112)
        self.tree.setColumnWidth(1, 165)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._select(cur))
        # (ISVS: a double-click on a row does not start editing the region — F9 does)

        self.desc_title = QLabel()
        f = QFont(self.desc_title.font())
        f.setPointSizeF(10.5)
        self.desc_title.setFont(f)
        self.desc_text = QLabel()
        self.desc_text.setWordWrap(True)
        self.desc_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.desc_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        desc = QFrame()
        desc.setObjectName("propertyDescription")
        desc.setStyleSheet(f"#propertyDescription {{ background: {theme.PANEL}; }}")
        dl = QVBoxLayout(desc)
        dl.setContentsMargins(4, 2, 4, 4)
        dl.setSpacing(1)
        dl.addWidget(self.desc_title)
        dl.addWidget(self.desc_text, 1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tree)
        split.addWidget(desc)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 1)
        split.setSizes([560, 80])

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#000000;background:#fff200;padding:2px 4px")
        self.note.setVisible(False)
        self.pick_hint = QLabel("Select the cell(s) in the spreadsheet: Enter or double-click accepts, "
                                "Escape cancels.")
        self.pick_hint.setStyleSheet("color:#000000;background:#fff200;padding:2px 4px")
        self.pick_hint.setVisible(False)

        self.error_mark = QLabel("!")
        self.error_mark.setFixedSize(20, 20)
        self.error_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_mark.setStyleSheet("background:#e02020;color:white;border-radius:10px;font-weight:bold")
        self.error_mark.setVisible(False)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        for b in self.buttons.buttons():
            b.setMinimumWidth(64)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(4, 4, 0, 0)
        bottom.addStretch(1)
        bottom.addWidget(self.error_mark)
        bottom.addWidget(self.buttons)

        layout = QVBoxLayout(self)
        layout.setMenuBar(bar)
        layout.setContentsMargins(2, 0, 2, 4)
        layout.setSpacing(2)
        layout.addWidget(tb)
        layout.addWidget(self.note)
        layout.addWidget(self.pick_hint)
        layout.addWidget(split, 1)
        layout.addLayout(bottom)

    def _load_descriptions(self) -> dict[tuple[str, ...], str]:
        """Parameter descriptions from the help installed on this computer (if any)."""
        out: dict[tuple[str, ...], str] = {}
        path = find_help_file(self.info) if self.info else None
        params = parse_inputs_file(path) if path else None
        for p in params or []:
            out[(p["name"],)] = p.get("description", "")
            for c in p.get("children") or []:
                out[(p["name"], c["name"])] = c.get("description", "")
        return out

    def _populate(self) -> None:
        self._disabled = set()
        self.tree.clear()
        self._editors.clear()
        self._links.clear()
        self._group_items.clear()
        self.rows, note = build_rows(self.info, len(self.args))
        self.note.setText(note or "")
        self.note.setVisible(bool(note))
        for row in self.rows:
            item = QTreeWidgetItem([row.label, "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.tree.addTopLevelItem(item)
            if row.children:
                for child in row.children:
                    citem = QTreeWidgetItem([child.label, "", ""])
                    citem.setData(0, Qt.ItemDataRole.UserRole, child)
                    item.addChild(citem)
                    self._add_leaf(citem, child)
                self._group_items.append((item, row))
            else:
                self._add_leaf(item, row)
        self._update_groups()
        self._fit_label_column()
        self.refresh()
        first = self.tree.topLevelItem(0)
        if first is not None:
            self.tree.setCurrentItem(first)
        self._apply_permissions()

    def _fit_label_column(self) -> None:
        """ISVS's label column is ~112 px; widened (up to 150) so that labels are not cut off."""
        fm = self.tree.fontMetrics()
        widest = 0
        for row in self.rows:
            widest = max(widest, fm.horizontalAdvance(row.label) + self.tree.indentation())
            for c in row.children:
                widest = max(widest, fm.horizontalAdvance(c.label) + 2 * self.tree.indentation())
        self.tree.setColumnWidth(0, max(112, min(150, widest + 10)))

    def _add_leaf(self, item: QTreeWidgetItem, row: ParamRow) -> None:
        editor = self._make_editor(row)
        self._editors[row.index] = editor
        self.tree.setItemWidget(item, 1, editor)
        self._make_link(item, row)

    def _make_editor(self, row: ParamRow) -> QWidget:
        i = row.index
        arg = self.args[i]
        p = row.param or {}
        kind = p.get("kind", "text")
        if kind == "event":  # ISVS: a push button named after the parameter ("Train Event")
            w = QPushButton(row.label)
            w.setToolTip(self._event_tooltip(i))
            w.clicked.connect(lambda _c=False, i=i: self._event_clicked(i))
            return w
        if i in self._expr_mode:  # Insert ▸ Function: the value as an expression (ISVS live/44)
            w = QLineEdit(arg)
            w.setProperty("reference", bool(referenced_locations(arg)))
            w.editingFinished.connect(lambda i=i, w=w: self._set_arg(i, w.text().strip()))
            return w
        if kind == "bool" and arg.strip() in ("0", "1"):
            w = QCheckBox()
            w.setChecked(arg.strip() == "1")
            w.toggled.connect(lambda on, i=i: self._set_arg(i, "1" if on else "0"))
            return w
        options = p.get("options") or []
        if kind == "enum" and arg.strip().lstrip("-").isdigit() and options:
            w = _Combo()
            for o in options:
                w.addItem(o["label"], o["value"])
            if w.findData(int(arg)) < 0:  # a value whose label is not known: listed by its number
                w.addItem(str(int(arg)), int(arg))
            w.setCurrentIndex(w.findData(int(arg)))
            w.currentIndexChanged.connect(lambda _ix, i=i, w=w: self._set_arg(i, str(w.currentData())))
            return w
        if (kind == "number" or row.in_group) and _is_number(arg):
            lo = p.get("min", -1e6)
            hi = p.get("max", 1e6)
            if "integer" in p:  # read in ISVS
                integral = bool(p["integer"]) and float(arg).is_integer()
            else:
                integral = (not row.in_group and "." not in arg and float(lo).is_integer() and float(hi).is_integer()
                            and is_integer_parameter(p, self._descriptions.get(row.path, "")))
            if integral:
                w = _IntSpin()
                w.setRange(int(lo), int(hi))
                w.setValue(int(float(arg)))
                w.valueChanged.connect(lambda v, i=i: self._set_arg(i, str(v)))
            else:
                w = _Spin()
                w.setDecimals(3)
                w.setRange(float(lo), float(hi))
                w.setValue(float(arg))
                w.valueChanged.connect(lambda v, i=i: self._set_arg(i, _fmt(v, 3)))
            w.setKeyboardTracking(False)
            w.setAlignment(Qt.AlignmentFlag.AlignRight)
            w.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
            return w
        w = QLineEdit(arg)
        is_ref = bool(ref_location(arg, self.model.location_of_name)) or bool(referenced_locations(arg))
        w.setProperty("reference", is_ref)
        w.editingFinished.connect(lambda i=i, w=w: self._set_arg(i, w.text().strip()))
        return w

    def _make_link(self, item: QTreeWidgetItem, row: ParamRow) -> None:
        """Third column: '= value', or the linked control / button / graphic editor."""
        i = row.index
        arg = self.args[i]
        p = row.param or {}
        loc = ref_location(arg, self.model.location_of_name)
        if p.get("kind") == "event":
            label = QLabel()
            self.tree.setItemWidget(item, 2, label)
            self._links[i] = (label, None)
            return
        if loc is None and referenced_locations(arg):
            buttons = [l for l in referenced_locations(arg)
                       if cells.result_kind(self.model.results.get(l)) == "ButtonResult"
                       and cells.editable_graphic(self.model.results.get(l)) is None]
            if buttons:
                box = QWidget()
                hl = QHBoxLayout(box)
                hl.setContentsMargins(0, 0, 0, 0)
                for l in buttons:
                    b = QPushButton(self.model.results[l].get("caption") or l)
                    b.setToolTip(f"Press the button in {l}")
                    b.clicked.connect(lambda _c=False, l=l: self.valueRequested.emit(l, "1"))
                    hl.addWidget(b)
                hl.addStretch(1)
                self.tree.setItemWidget(item, 2, box)
                self._links[i] = (box, None)
                return
        if loc is None:
            label = QLabel()
            self.tree.setItemWidget(item, 2, label)
            self._links[i] = (label, None)
            return
        result = self.model.results.get(loc)
        kind = cells.result_kind(result)
        graphic = cells.editable_graphic(result)
        if graphic is not None:
            b = QPushButton(f"Edit {result.get('caption') or graphic.get('$type')}…")
            supported = graphic.get("$type") in EDITABLE_TYPES
            b.setToolTip(f"Edit {loc} on the image (F9)" if supported else
                         f"Editing {graphic.get('$type')} graphics is not supported")
            b.setProperty("unsupported", not supported)
            b.clicked.connect(lambda _c=False, l=loc: self.graphicEditRequested.emit(l))
            w: QWidget = b
        elif kind == "ButtonResult":
            w = QPushButton(result.get("caption") or "Press")
            w.setToolTip(f"Press the button in {loc}")
            w.clicked.connect(lambda _c=False, l=loc: self.valueRequested.emit(l, "1"))
        elif cells.is_value_editable(result):
            w = self._control_for(loc, result)
        else:
            w = QLabel()
        self.tree.setItemWidget(item, 2, w)
        self._links[i] = (w, loc)

    def _control_for(self, loc: str, result: dict) -> QWidget:
        """A live editor for the value of the HMI control cell ``loc``."""
        kind = cells.result_kind(result)
        data = result.get("data")

        def send(value: Any) -> None:
            if loc not in self._original_values:
                self._original_values[loc] = data
            self.valueRequested.emit(loc, value)

        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(QLabel("="))
        if kind == "EditIntResult":
            w = _IntSpin()
            w.setRange(int(result.get("min", -2147483648)), int(result.get("max", 2147483647)))
            w.setValue(int(data or 0))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(send)
        elif kind == "EditFloatResult":
            w = _Spin()
            w.setDecimals(3)
            w.setRange(float(result.get("min", -1e12)), float(result.get("max", 1e12)))
            w.setValue(float(data or 0))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(send)
        elif kind == "EditStringResult":
            w = QLineEdit("" if data is None else str(data))
            w.editingFinished.connect(lambda: send(w.text()))
        elif kind == "CheckBoxResult":
            w = QCheckBox(result.get("caption") or "")
            w.setChecked(bool(data))
            w.toggled.connect(lambda on: send(1 if on else 0))
        else:  # ListBoxResult
            w = _Combo()
            w.addItems([str(o) for o in result.get("options") or []])
            w.setCurrentIndex(int(data or 0))
            w.currentIndexChanged.connect(send)
        w.setToolTip(f"Value of {loc}")
        w.setProperty("control_kind", kind)
        hl.addWidget(w, 1)
        box.setProperty("control", w)
        return box

    # ------------------------------------------------------------------ events
    def _event_targets(self, i: int) -> list[str]:
        return [l for l in referenced_locations(self.args[i])
                if cells.result_kind(self.model.results.get(l)) == "ButtonResult"
                and cells.editable_graphic(self.model.results.get(l)) is None]

    def _event_tooltip(self, i: int) -> str:
        arg = self.args[i].strip()
        if self._event_targets(i):
            return f"Event = {arg}: press the button(s) in {', '.join(self._event_targets(i))}"
        if arg not in ("", "0"):
            return f"Event = {arg}"
        return ("No event cell is referenced (0). Insert an Absolute or Relative Reference to a Button cell; "
                "training while the property sheet is open is not available through the HMI API.")

    def _event_clicked(self, i: int) -> None:
        item = self._item_for(i)
        if item is not None:
            self.tree.setCurrentItem(item)
        targets = self._event_targets(i)
        if targets and self._values_ok:
            for loc in targets:
                self.valueRequested.emit(loc, "1")
        # with no event cell ISVS does nothing visible either (survey §1.7); the tooltip explains

    # ------------------------------------------------------------------ state
    def refresh(self) -> None:
        """Updates linked values, enable rules, the region on the image and the error mark from
        the latest results."""
        expr = self.model.expressions.get(self.location, "")
        if expr and expr not in self._known and not self._write_timer.isActive():
            parsed = split_call(expr)
            if parsed is not None:  # changed elsewhere (formula bar, another client)
                self.name, self.args = parsed
                self._written = expr
                self._known.add(expr)
                self._populate()
                return
        for i, (w, loc) in self._links.items():
            arg = self.args[i]
            if loc is None:
                if isinstance(w, QLabel):
                    w.setText(self._value_text(i))
                continue
            result = self.model.results.get(loc)
            control = w.property("control") if isinstance(w, QWidget) else None
            if control is not None and result is not None and not control.hasFocus():
                self._set_control(control, result)
            elif isinstance(w, QLabel):
                w.setText(f"= {cells.grid_text(result, self.model.expressions.get(loc, ''))}"
                          if result or self.model.expressions.get(loc) else f"→ {arg}")
        for i, w in self._editors.items():
            if isinstance(w, QPushButton):
                w.setToolTip(self._event_tooltip(i))
        result = self.model.results.get(self.location)
        err = bool(result and (result.get("error") or cells.result_kind(result) == "ErrorCellResult"))
        self.error_mark.setVisible(err)
        self.error_mark.setToolTip(f"{self.location} returns #ERR. The vision system does not report the reason "
                                   "through the HMI API." if err else "")
        self._apply_enable_rules()
        self._emit_region()

    def _value_text(self, i: int) -> str:
        row = self._row_for(i)
        p = (row.param or {}) if row else {}
        arg = self.args[i].strip()
        if p.get("kind") == "event":
            return f"= {arg}" if arg not in ("", "0") else ""
        if p.get("options") and p.get("kind") != "bool" and arg.lstrip("-").isdigit():
            return f"= {arg}"  # ISVS: a list shows its value ("= 0"), a check box does not
        return ""

    @staticmethod
    def _set_control(control: QWidget, result: dict) -> None:
        data = result.get("data")
        control.blockSignals(True)
        try:
            if isinstance(control, QCheckBox):
                control.setChecked(bool(data))
            elif isinstance(control, QComboBox):
                control.setCurrentIndex(int(data or 0))
            elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
                control.setValue(type(control.value())(data or 0))
            elif isinstance(control, QLineEdit):
                control.setText("" if data is None else str(data))
        except (TypeError, ValueError):
            pass
        finally:
            control.blockSignals(False)

    def set_permissions(self, values_ok: bool, expression_ok: bool) -> None:
        """``values_ok``: linked values may be set; ``expression_ok``: the job may be edited."""
        changed = (values_ok, expression_ok) != (self._values_ok, self._expr_ok)
        self._values_ok, self._expr_ok = values_ok, expression_ok
        self._apply_permissions()
        if changed:
            self._shown_region = _UNSET
            self._emit_region()

    def _apply_permissions(self) -> None:
        for i, w in self._editors.items():
            if isinstance(w, QPushButton):  # event: presses the referenced button (a value)
                w.setEnabled(self._values_ok and i not in self._disabled)
            else:
                w.setEnabled(self._expr_ok and i not in self._disabled)
        for i, (w, _loc) in self._links.items():
            w.setEnabled(self._values_ok and not w.property("unsupported") and i not in self._disabled)
        for a in (self.act_abs, self.act_rel, self.act_default):
            a.setEnabled(self._expr_ok)
        self._update_actions()

    # ------------------------------------------------------------------ enable rules
    def _leaf_by_label(self, label: str) -> Optional[ParamRow]:
        for r in self.rows:
            for leaf in (r.children or [r]):
                if leaf.label.lower() == label.lower():
                    return leaf
        return None

    def _arg_value(self, i: int) -> Optional[float]:
        """The number an argument stands for: a literal, or the value of the referenced cell."""
        arg = self.args[i].strip()
        if _is_number(arg):
            return float(arg)
        loc = ref_location(arg, self.model.location_of_name)
        data = (self.model.results.get(loc) or {}).get("data") if loc else None
        if isinstance(data, bool):
            return float(data)
        if isinstance(data, (int, float)):
            return float(data)
        return None

    def _rule_holds(self, rule: dict) -> Optional[bool]:
        """``{"param", "values"|"not"}``, ``{"all": [...]}``, ``{"any": [...]}``; None when a value
        cannot be evaluated (then the parameter stays enabled)."""
        if "all" in rule or "any" in rule:
            results = [self._rule_holds(r) for r in rule.get("all") or rule.get("any")]
            if None in results:
                return None
            return all(results) if "all" in rule else any(results)
        ctrl = self._leaf_by_label(rule.get("param", ""))
        if ctrl is None or ctrl.index is None:
            return None
        v = self._arg_value(ctrl.index)
        if v is None:
            return None
        if "not" in rule:
            return int(v) not in rule["not"]
        return int(v) in rule.get("values", [])

    def _apply_enable_rules(self) -> None:
        rules = (self.info.enable if self.info else None) or {}
        disabled: set[int] = set()
        for target, rule in rules.items():
            leaf = self._leaf_by_label(target)
            if leaf is None or leaf.index is None:
                continue
            if self._rule_holds(rule) is False:
                disabled.add(leaf.index)
        if disabled == self._disabled:
            return
        self._disabled = disabled
        for i in self._editors:
            it = self._item_for(i)
            if it is not None:
                it.setForeground(0, QBrush(QColor(theme.TEXT_DISABLED)) if i in disabled else QBrush())
        self._apply_permissions()

    # ------------------------------------------------------------------ arguments
    def _row_for(self, index: int) -> Optional[ParamRow]:
        for r in self.rows:
            for leaf in (r.children or [r]):
                if leaf.index == index:
                    return leaf
        return None

    def _set_arg(self, i: int, text: str) -> None:
        if not text:
            text = "0"
        if self.args[i] == text:
            return
        self.args[i] = text
        self._update_groups()
        if isinstance(self._editors.get(i), QLineEdit):
            self._rebuild_link(i)  # the reference may point somewhere else now
        else:
            self.refresh()
        self._write_timer.start()

    def _rebuild_link(self, i: int) -> None:
        it = self._item_for(i)
        if it is not None:
            w = self._editors.get(i)
            if isinstance(w, QLineEdit):
                is_ref = bool(ref_location(self.args[i], self.model.location_of_name)) or \
                    bool(referenced_locations(self.args[i]))
                w.setProperty("reference", is_ref)
                w.style().unpolish(w)
                w.style().polish(w)
            self._make_link(it, self._row_for(i))
            self.refresh()
            self._apply_permissions()

    def _item_for(self, index: int) -> Optional[QTreeWidgetItem]:
        root = self.tree.invisibleRootItem()
        stack = [root.child(k) for k in range(root.childCount())]
        while stack:
            it = stack.pop()
            row: ParamRow = it.data(0, Qt.ItemDataRole.UserRole)
            if row.index == index:
                return it
            stack += [it.child(k) for k in range(it.childCount())]
        return None

    def _update_groups(self) -> None:
        for item, row in self._group_items:
            item.setText(1, "(" + ",".join(self.args[c.index] for c in row.children) + ")")

    def expression(self) -> str:
        return join_call(self.name, self.args)

    def _write_now(self) -> None:
        expr = self.expression()
        if expr != self._written and self._expr_ok:
            self._written = expr
            self._known.add(expr)
            self.expressionChanged.emit(self.location, expr)

    def _insert_function(self) -> None:
        """Insert ▸ Function (ISVS live/44): a value shown as a spin box, check box or list is
        switched to a text box holding its value (an expression); in a text box a function
        is picked and put at the cursor."""
        row = self._current
        if row is not None and row.index is not None and self._expr_ok:
            i = row.index
            if i not in self._expr_mode and not isinstance(self._editors.get(i), QLineEdit):
                self._expr_mode.add(i)
                self._populate_keep(i)
                w = self._editors.get(i)
                if isinstance(w, QLineEdit):
                    w.setFocus()
                    w.selectAll()
            else:
                self.functionRequested.emit()
        self._update_actions()

    def insert_text(self, text: str) -> bool:
        """Insert ▸ Function: puts ``text`` at the cursor of the parameter being typed in."""
        row = self._current
        w = self._editors.get(row.index) if row is not None and row.index is not None else None
        if not isinstance(w, QLineEdit) or not self._expr_ok:
            return False
        w.setFocus()
        w.insert(text)
        if text.endswith("()"):
            w.setCursorPosition(w.cursorPosition() - 1)
        return True

    # ------------------------------------------------------------------ selection / description
    def _select(self, item: Optional[QTreeWidgetItem]) -> None:
        row: Optional[ParamRow] = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self._current = row
        self._mark_current()
        if row is None:
            self.desc_title.setText("")
            self.desc_text.setText("")
            self._update_actions()
            self._emit_region()
            return
        self.desc_title.setText(row.label)
        p = row.param or {}
        parts = []
        text = self._descriptions.get(row.path, "")
        if text:
            parts.append(text)
        extra = []
        if p.get("default") is not None and "default" not in text.lower():
            extra.append(f"Default = {p['default']}.")
        if p.get("min") is not None and p.get("max") is not None and f"{_fmt(p['min'], 3)} to" not in text:
            extra.append(f"Range {_fmt(p['min'], 3)} to {_fmt(p['max'], 3)}.")
        if p.get("options") and not text:
            extra.append("; ".join(f"{o['value']} = {o['label']}" for o in p["options"]))
        if extra:
            parts.append(" ".join(extra))
        spec = self._region_for(row)
        if spec is not None and not self._region_literal(spec):
            parts.append("The region contains cell references: clear them to edit the region graphically.")
        if not self._descriptions and self.info and row.param:
            parts.append("(Install In-Sight Vision Suite to see parameter descriptions.)")
        self.desc_text.setText("\n".join(parts))
        self._update_actions()
        self._emit_region()

    def _mark_current(self) -> None:
        """ISVS: the selected row's value box gets a yellow border."""
        current = self._current.index if self._current is not None else None
        for i, w in self._editors.items():
            on = i == current and not isinstance(w, (QCheckBox, QPushButton))
            if bool(w.property("current")) != on:
                w.setProperty("current", on)
                w.style().unpolish(w)
                w.style().polish(w)

    def _on_focus_changed(self, _old, _new) -> None:
        self._update_actions()

    def _update_actions(self) -> None:
        if not hasattr(self, "act_graphic"):
            return
        spec = self._shown_spec()
        literal = spec is not None
        loc = self._current_graphic_location()
        self.act_graphic.setEnabled((literal and self._expr_ok) or (loc is not None and self._values_ok))
        cell_region = loc is not None and (cells.editable_graphic(self.model.results.get(loc)) or {}).get(
            "$type") == "Region"
        self.act_maximize.setEnabled(self.image_size() is not None and (
            (literal and spec.type == "Region" and self._expr_ok) or (cell_region and self._values_ok)))
        current = self._current.index if self._current is not None else None
        self.act_function.setEnabled(self._expr_ok and current is not None)
        self.act_function.setChecked(current in self._expr_mode)

    def _current_graphic_location(self) -> Optional[str]:
        row = self._current
        if row is None or row.index is None:
            return None
        loc = ref_location(self.args[row.index], self.model.location_of_name)
        graphic = cells.editable_graphic(self.model.results.get(loc or ""))
        if graphic is not None and graphic.get("$type") in EDITABLE_TYPES:
            return loc
        return None

    def _edit_current_graphic(self) -> None:
        """Edit ▸ Graphic (F9): a referenced Edit graphic cell goes to its Interactive Graphics
        Mode; the region drawn for the sheet (given by numbers) is edited on the image while the
        sheet steps aside (``regionEditRequested``; the caller hands the result to
        :meth:`end_region_edit`)."""
        loc = self._current_graphic_location()
        if loc and self._values_ok:
            self.graphicEditRequested.emit(loc)
            return
        spec = self._shown_spec()
        if spec is not None and self._expr_ok:
            self._igm_spec = spec
            self.regionEditRequested.emit(self._payload_for(spec))

    def end_region_edit(self, graphic: Optional[dict]) -> None:
        """Interactive Graphics Mode of the sheet's region ended: Return gives the edited
        ``graphic`` (its numbers go into the parameters), Escape None."""
        if graphic is not None:
            self.graphic_edited(graphic)
        self._igm_spec = None
        self._shown_region = _UNSET

    def _restore_default(self) -> None:
        row = self._current
        if row is None:
            return
        leaves = row.children or [row]
        for leaf in leaves:
            default = (leaf.param or {}).get("default")
            if leaf.index is None or default is None:
                continue
            self.args[leaf.index] = str(default)
        self._populate_keep(leaves[0].index if leaves and leaves[0].index is not None else 0)
        self._write_timer.start()

    def _row_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(self.act_graphic)
        menu.addAction(self.act_maximize)
        menu.addSeparator()
        menu.addAction(self.act_abs)
        menu.addAction(self.act_rel)
        menu.addSeparator()
        menu.addAction(self.act_default)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ regions on the image
    def _region_for(self, row: Optional[ParamRow]) -> Optional[RegionSpec]:
        if row is None:
            return None
        group = row if row.children else row.parent
        return region_spec(group) if group is not None else None

    def _region_literal(self, spec: RegionSpec) -> bool:
        return all(_is_number(self.args[i]) for i in spec.keys.values())

    def fixture(self) -> tuple[Optional[QTransform], str]:
        """The tool's fixture transform (None = image coordinates) and a note when the fixture
        could not be evaluated."""
        for r in self.rows:
            names = {c.label.strip().lower() for c in r.children}
            if r.label.strip().lower() == "fixture" and len(r.children) == 3 and names in _FIXTURE_NAMES:
                vals = [self._arg_value(c.index) for c in r.children]
                if any(v is None for v in vals):
                    return None, "The fixture could not be evaluated: the region is shown in image coordinates."
                if not any(vals):
                    return None, ""
                return fixture_transform(*vals), ""
        return None, ""

    def region_graphic(self, spec: RegionSpec) -> dict:
        g: dict = {"$type": spec.type}
        for k, i in spec.keys.items():
            g[k] = float(self.args[i])
        if spec.type == "Region":
            g.setdefault("angle", 0.0)
            g.setdefault("curve", 0.0)
        return g

    def _shown_spec(self) -> Optional[RegionSpec]:
        """The region drawn while the sheet is open: the selected region parameter, else the
        first one given by numbers (ISVS draws it whatever row is selected, live/25)."""
        spec = self._region_for(self._current)
        if spec is not None:
            return spec if self._region_literal(spec) else None
        for r in self.rows:
            spec = region_spec(r)
            if spec is not None and self._region_literal(spec):
                return spec
        return None

    def _region_payload(self) -> Optional[dict]:
        """What regionShown sends (None: no region given by numbers, or the sheet is hidden)."""
        spec = self._shown_spec()
        if spec is None or not self.isVisible():
            return None
        return self._payload_for(spec)

    def _payload_for(self, spec: RegionSpec) -> dict:
        transform, note = self.fixture()
        editable = self._expr_ok
        flags = {"move": editable, "resize": editable, "rotate": editable and "angle" in spec.keys,
                 "bend": editable and "curve" in spec.keys}
        return {"graphic": self.region_graphic(spec), "transform": transform, "flags": flags,
                "label": spec.group.label, "note": note}

    @staticmethod
    def _payload_key(payload: Optional[dict]) -> Optional[tuple]:
        if payload is None:
            return None
        t = payload["transform"]
        return (repr(payload["graphic"]), repr(payload["flags"]),
                None if t is None else tuple(round(v, 6) for v in _transform_values(t)))

    def _emit_region(self) -> None:
        payload = self._region_payload()
        key = self._payload_key(payload)
        if key == self._shown_region:
            return
        self._shown_region = key
        self.regionShown.emit(payload)

    def graphic_edited(self, g: dict) -> None:
        """The region was edited on the image: the numbers go into the parameters."""
        spec = self._igm_spec or self._shown_spec()
        if spec is None or not self._expr_ok or g.get("$type") != spec.type:
            return
        changed = False
        for k, i in spec.keys.items():
            if k not in g:
                continue
            text = _fmt(float(g[k]), 3)
            if self.args[i] != text:
                self.args[i] = text
                changed = True
                w = self._editors.get(i)
                if isinstance(w, (QSpinBox, QDoubleSpinBox)):
                    w.blockSignals(True)
                    w.setValue(type(w.value())(float(g[k])))
                    w.blockSignals(False)
                elif isinstance(w, QLineEdit):
                    w.setText(text)
        if changed:
            self._update_groups()
            self._shown_region = self._payload_key(self._region_payload())  # the image already shows it
            self._write_timer.start()

    def _maximize(self) -> None:
        """Maximize Region: the region covers the whole image (in the tool's fixture)."""
        size = self.image_size()
        if size is None:
            return
        loc = self._current_graphic_location()
        if loc and self._values_ok:
            self.maximizeRequested.emit(loc)
            return
        spec = self._shown_spec()
        if spec is not None and spec.type == "Region" and self._expr_ok:
            transform, _note = self.fixture()
            g = maximized_region(size[0], size[1], transform)
            for k, i in spec.keys.items():
                if k in g:
                    self.args[i] = _fmt(g[k], 3)
            cur = self._current
            if cur is not None and cur.index is not None:  # keep the selected row
                self._populate_keep(cur.index, expand=True)
            else:
                self._populate_keep(spec.group.children[0].index, expand=False)
            self._write_timer.start()

    # ------------------------------------------------------------------ cell references
    @property
    def picking(self) -> bool:
        return self._pick is not None

    def _start_pick(self, mode: Optional[str]) -> None:
        if mode is not None and (not self._expr_ok or self._current is None or self._current.index is None):
            return
        self._pick = mode
        self.pick_hint.setVisible(mode is not None)
        if mode is not None:
            self.pickStarted.emit(mode)

    def cancel_pick(self) -> None:
        self._start_pick(None)

    def insert_reference(self, loc: str) -> bool:
        """Puts a reference to ``loc`` (a cell or a range like ``B3:C5``) into the selected
        parameter (while picking)."""
        if self._pick is None or self._current is None or self._current.index is None:
            return False
        parts = loc.split(":")
        rcs = [cells.parse_address(a) for a in parts]
        if not parts or len(parts) > 2 or any(rc is None for rc in rcs):
            return False
        if self._pick == "abs":
            ref = ":".join(f"${cells.col_name(rc[1])}${rc[0]}" for rc in rcs)
        else:
            ref = ":".join(cells.address(*rc) for rc in rcs)
        i = self._current.index
        self._start_pick(None)
        self.args[i] = ref
        self._populate_keep(i)
        self._write_timer.start()
        return True

    def _populate_keep(self, index: int, expand: bool = True) -> None:
        self._shown_region = _UNSET
        self._populate()
        it = self._item_for(index)
        if it is not None:
            if it.parent() is not None:
                if expand:
                    it.parent().setExpanded(True)
                else:
                    it = it.parent()
            self.tree.setCurrentItem(it)

    # ------------------------------------------------------------------ OK / Cancel
    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._shown_region = _UNSET
        self._emit_region()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        if self._shown_region is not None:
            self._shown_region = None
            self.regionShown.emit(None)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.picking:
            self._start_pick(None)
            return
        super().keyPressEvent(e)

    def done(self, r: int) -> None:
        try:
            QApplication.instance().focusChanged.disconnect(self._on_focus_changed)
        except (RuntimeError, TypeError):
            pass
        super().done(r)

    def accept(self) -> None:
        fw = self.focusWidget()
        if isinstance(fw, QLineEdit):
            fw.editingFinished.emit()
        if self._write_timer.isActive():
            self._write_timer.stop()
        self._write_now()
        super().accept()

    def reject(self) -> None:
        self._write_timer.stop()
        if self._expr_ok and self._written != self.original_expression:
            self.expressionChanged.emit(self.location, self.original_expression)
            self._written = self.original_expression
        if self._values_ok:
            for loc, value in self._original_values.items():
                self.valueRequested.emit(loc, value)
        self._original_values.clear()
        super().reject()


def _transform_values(t: QTransform) -> tuple[float, ...]:
    return (t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy())
