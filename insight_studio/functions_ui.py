"""Functions panel and Insert Function dialog, laid out like the ones in In-Sight Vision Suite.

Both show the toolbox category tree of the catalog (Edge AI, Vision Tools ▸ Bead …) with an icon
per category, and a description pane: the category's or function's description from the In-Sight
help installed on this computer (only the signature without it).

* **Functions panel** (right dock): "Filter:" box, tree of categories with their functions,
  description pane ("All functions" when nothing is selected). Double-click/Enter inserts the
  function into the current cell; functions can be dragged onto a cell.
* **Insert Function ❒Inspection** (Ctrl+Shift+F, 674×432): category tree on the left ("All" at
  the top), the functions of the selected category and its subcategories on the right, below
  them the title, the bold short signature and the description. Insert is enabled only when a
  function is selected; F1 opens the help of the selection.
"""

from __future__ import annotations

from typing import Optional, Union

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import cells
from .catalog import Catalog, Category, FunctionInfo, describe_category, describe_function
from .icons import category_icon

FUNCTION_MIME = "application/x-insight-studio-function"  # drag payload: the function name
ROLE = Qt.ItemDataRole.UserRole
ALL_FUNCTIONS = "All functions"
SHEET_NAME = "Inspection"

Selection = Union[FunctionInfo, Category, None]


def function_mime(f: FunctionInfo) -> QMimeData:
    mime = QMimeData()
    mime.setData(FUNCTION_MIME, f.name.encode("utf-8"))
    mime.setText(f.name)
    return mime


def function_html(f: FunctionInfo) -> str:
    """Bold short signature and the help's description."""
    text = f"<b>{_esc(f.short_signature)}</b>"
    desc = describe_function(f)
    if desc:
        text += f"<br>{_esc(desc)}"
    return text


def category_html(c: Category) -> str:
    desc = describe_category(c)
    return _esc(desc) if desc else f"{_esc(c.name)} functions"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _function_icon(f: FunctionInfo, within: tuple[str, ...] = ()):
    """A function shows the icon of its category (the one inside ``within`` when it has several)."""
    path = next((p for p in f.paths if p[:len(within)] == within), f.paths[0] if f.paths else ())
    return category_icon(path)


# ---------------------------------------------------------------------------- Functions panel
class _FunctionTree(QTreeWidget):
    """Tree whose function items can be dragged onto the spreadsheet."""

    def mimeData(self, items) -> QMimeData:
        f = items[0].data(0, ROLE) if items else None
        if isinstance(f, FunctionInfo):
            return function_mime(f)
        return QMimeData()

    def mimeTypes(self) -> list[str]:
        return [FUNCTION_MIME]

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction


class FunctionsPanel(QWidget):
    """Filter, toolbox tree and description pane (the ISVS Functions panel)."""

    functionActivated = Signal(object)  # FunctionInfo: insert it into the current cell
    helpRequested = Signal(object)  # FunctionInfo / Category

    def __init__(self, catalog: Catalog, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("functionsPanel")
        self.catalog = catalog
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(QLabel("Filter:"))
        self.filter = QLineEdit()
        self.filter.setObjectName("functionFilter")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._populate)
        row.addWidget(self.filter, 1)
        lay.addLayout(row)
        self.tree = _FunctionTree()
        self.tree.setObjectName("functionTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemActivated.connect(self._activated)
        self.tree.currentItemChanged.connect(self._describe)
        self.tree.setToolTip("Double-click a function, or drag it onto a cell, to insert it")
        self.desc = QLabel(ALL_FUNCTIONS)
        self.desc.setObjectName("functionDescription")
        self.desc.setWordWrap(True)
        self.desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.desc.setContentsMargins(6, 6, 6, 6)
        self.desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.desc.setMinimumHeight(90)  # signature + two lines of description, as in ISVS
        split = QSplitter(Qt.Orientation.Vertical)
        split.setObjectName("functionSplit")
        split.addWidget(self.tree)
        split.addWidget(self.desc)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setCollapsible(0, False)
        lay.addWidget(split, 1)
        help_sc = QShortcut(QKeySequence("F1"), self.tree, context=Qt.ShortcutContext.WidgetShortcut)
        help_sc.activated.connect(lambda: self.selection() and self.helpRequested.emit(self.selection()))
        self._populate("")

    def set_catalog(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._populate(self.filter.text())

    # ------------------------------------------------------------------ tree
    def _populate(self, text: str = "") -> None:
        text = (text or "").strip().lower()
        self.tree.clear()
        if self.catalog.categories:
            for cat in self.catalog.tree():
                item = self._category_item(cat, text)
                if item is not None:
                    self.tree.addTopLevelItem(item)
        else:  # catalog without a tree: a flat list
            for f in self.catalog.functions:
                if not text or text in f.name.lower():
                    self.tree.addTopLevelItem(self._function_item(f, ()))
        if text:
            self.tree.expandAll()
        self._describe(None)

    def _category_item(self, cat: Category, text: str) -> Optional[QTreeWidgetItem]:
        item = QTreeWidgetItem([cat.name])
        item.setIcon(0, category_icon(cat.path))
        item.setData(0, ROLE, cat)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        for sub in cat.children:
            child = self._category_item(sub, text)
            if child is not None:
                item.addChild(child)
        for f in self.catalog.direct_functions(cat.path):
            if not text or text in f.name.lower():
                item.addChild(self._function_item(f, cat.path))
        if text and item.childCount() == 0:
            return None
        return item

    @staticmethod
    def _function_item(f: FunctionInfo, path: tuple[str, ...]) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f.name])
        item.setIcon(0, category_icon(path) if path else _function_icon(f))
        item.setData(0, ROLE, f)
        item.setToolTip(0, f.short_signature)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        return item

    def selection(self) -> Selection:
        item = self.tree.currentItem()
        return item.data(0, ROLE) if item is not None else None

    def select_function(self, name: str) -> bool:
        """Selects the first item of function ``name`` (expanding its category)."""
        for item in self._items():
            f = item.data(0, ROLE)
            if isinstance(f, FunctionInfo) and f.name.lower() == name.lower():
                self.tree.setCurrentItem(item)
                return True
        return False

    def _items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            yield item
            stack[0:0] = [item.child(i) for i in range(item.childCount())]

    def _activated(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        f = item.data(0, ROLE)
        if isinstance(f, FunctionInfo):
            self.functionActivated.emit(f)

    def _describe(self, item: Optional[QTreeWidgetItem], *_args) -> None:
        sel = item.data(0, ROLE) if item is not None else None
        if isinstance(sel, FunctionInfo):
            self.desc.setText(function_html(sel))
        elif isinstance(sel, Category):
            self.desc.setText(f"<b>{_esc(sel.name)}</b><br>{category_html(sel)}")
        else:
            self.desc.setText(ALL_FUNCTIONS)


# ---------------------------------------------------------------------------- Insert Function dialog
class InsertFunctionDialog(QDialog):
    """``Insert Function ❒Inspection``: category tree, function list, description, Insert/Cancel."""

    helpRequested = Signal(object)  # FunctionInfo / Category

    def __init__(self, catalog: Catalog, target: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("insertFunctionDialog")
        self.catalog = catalog
        self.target = target
        self.setWindowTitle(f"Insert Function {cells.STRUCTURE_GLYPH}{SHEET_NAME}")
        self.resize(674, 432)
        self._path: tuple[str, ...] = ()

        self.tree = QTreeWidget()
        self.tree.setObjectName("categoryTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setRootIsDecorated(True)
        self.all_item = QTreeWidgetItem(["All"])
        self.all_item.setIcon(0, category_icon(()))
        self.all_item.setData(0, ROLE, ())
        self.tree.addTopLevelItem(self.all_item)
        for cat in catalog.tree():
            self.all_item.addChild(self._category_item(cat))
        self.all_item.setExpanded(True)
        self.tree.currentItemChanged.connect(self._category_changed)
        self.tree.itemClicked.connect(lambda item, _c: self._category_changed(item))

        self.list = QListWidget()
        self.list.setObjectName("functionList")
        self.list.setIconSize(QSize(16, 16))
        self.list.setUniformItemSizes(True)
        self.list.currentItemChanged.connect(self._function_changed)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.tree)
        top.addWidget(self.list)
        top.setSizes([300, 340])
        top.setCollapsible(0, False)
        top.setCollapsible(1, False)

        self.title = QLabel()
        self.title.setObjectName("insertFunctionTitle")
        tf = QFont(self.font())
        tf.setPointSizeF(tf.pointSizeF() * 1.25)
        self.title.setFont(tf)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setObjectName("insertFunctionRule")
        self.description = QLabel()
        self.description.setObjectName("insertFunctionDescription")
        self.description.setWordWrap(True)
        self.description.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.description.setMinimumHeight(60)

        self.insert_button = QPushButton("Insert")
        self.insert_button.setObjectName("insertButton")
        self.insert_button.setDefault(True)
        self.insert_button.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.insert_button)
        buttons.addWidget(cancel)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(top, 1)
        lay.addSpacing(8)
        lay.addWidget(self.title)
        lay.addWidget(rule)
        lay.addWidget(self.description)
        lay.addLayout(buttons)

        QShortcut(QKeySequence("F1"), self, activated=self._help)
        self.tree.setCurrentItem(self.all_item)
        self._category_changed(self.all_item)
        self.tree.setFocus()

    def _category_item(self, cat: Category) -> QTreeWidgetItem:
        item = QTreeWidgetItem([cat.name])
        item.setIcon(0, category_icon(cat.path))
        item.setData(0, ROLE, cat.path)
        for sub in cat.children:
            item.addChild(self._category_item(sub))
        return item

    # ------------------------------------------------------------------ selection
    def _category_changed(self, item: Optional[QTreeWidgetItem], *_args) -> None:
        if item is None:
            return
        self._path = tuple(item.data(0, ROLE) or ())
        self.list.blockSignals(True)
        self.list.clear()
        for f in self.catalog.functions_in(self._path):
            it = QListWidgetItem(_function_icon(f, self._path), f.name)
            it.setData(ROLE, f)
            self.list.addItem(it)
        self.list.setCurrentRow(-1)
        self.list.blockSignals(False)
        self._show(self.catalog.find_category(self._path) if self._path else None)

    def _function_changed(self, item: Optional[QListWidgetItem], *_args) -> None:
        f = item.data(ROLE) if item is not None else None
        if f is not None:
            self._show(f)

    def _show(self, sel: Selection) -> None:
        if isinstance(sel, FunctionInfo):
            self.title.setText(sel.name)
            self.description.setText(function_html(sel))
            self.insert_button.setEnabled(True)
            return
        if isinstance(sel, Category):
            self.title.setText(sel.name)
            self.description.setText(category_html(sel))
        else:
            self.title.setText("All")
            self.description.setText(ALL_FUNCTIONS)
        self.insert_button.setEnabled(False)

    def selected(self) -> Optional[FunctionInfo]:
        item = self.list.currentItem()
        return item.data(ROLE) if item is not None and item.isSelected() else None

    def select_category(self, path: tuple[str, ...]) -> bool:
        stack = [self.all_item]
        while stack:
            item = stack.pop()
            if tuple(item.data(0, ROLE) or ()) == tuple(path):
                self.tree.setCurrentItem(item)
                return True
            stack += [item.child(i) for i in range(item.childCount())]
        return False

    def select_function(self, name: str) -> bool:
        for i in range(self.list.count()):
            if self.list.item(i).text().lower() == name.lower():
                self.list.setCurrentRow(i)
                return True
        return False

    def accept(self) -> None:
        if self.selected() is None:
            return
        super().accept()

    def _help(self) -> None:
        sel: Selection = self.selected() or (self.catalog.find_category(self._path) if self._path else None)
        if sel is not None:
            self.helpRequested.emit(sel)
