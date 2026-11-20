"""Function-name completion for expression editors (formula bar and in-cell editor).

While a function name is typed, a popup lists the names of the matching functions (names that
start with the typed text first, then names that contain it; ISVS shows names only, the
signature is the item's tooltip). Up/Down choose, Enter/Tab/click insert
``Name()`` with the cursor between the parentheses, Esc closes the list. Ctrl+Space opens the
list on demand (all functions when nothing is typed).
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter, QLineEdit, QStyledItemDelegate, QWidget

from . import cells
from .catalog import FunctionInfo

NAME_ROLE = Qt.ItemDataRole.UserRole + 1
MAX_ITEMS = 300
POPUP_MIN_WIDTH = 200
VISIBLE_ITEMS = 7  # ISVS shows seven names with a scroll bar

FunctionSource = Callable[[], Iterable[FunctionInfo]]

_IDENT_BEFORE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_IDENT_AFTER = re.compile(r"^[A-Za-z0-9_]*")
_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CELL_REF = re.compile(r"[A-Za-z]\d{1,3}")


def word_at_cursor(text: str, cursor: int, allow_empty: bool = False) -> Optional[tuple[int, int, str]]:
    """Returns ``(start, end, prefix)`` of the function name being typed at ``cursor``.

    ``start..end`` is the whole identifier around the cursor (it is replaced on completion),
    ``prefix`` the part before the cursor (it is matched). None when the cursor is not on
    something that can be a function name: inside a text constant (``'abc``) or a "string",
    on a cell reference (``A1``, ``$B$2``), a structure member (``Blob.Area``) or a number.
    """
    if text.startswith("'"):
        return None
    before = text[:cursor]
    chunks = cells._split_strings(before)
    if chunks and chunks[-1][0]:
        return None
    m = _IDENT_BEFORE.search(before)
    if m:
        start, prefix = m.start(), m.group(0)
    elif allow_empty:
        start, prefix = cursor, ""
    else:
        return None
    if start > 0 and (before[start - 1] in "$." or before[start - 1].isdigit()):
        return None
    if _CELL_REF.fullmatch(prefix):
        return None
    end = cursor + _IDENT_AFTER.match(text[cursor:]).end()
    return start, end, prefix


def functions_in_expressions(expressions: Iterable[str]) -> set[str]:
    """Names of the functions called in ``expressions`` (outside string literals)."""
    names: set[str] = set()
    for expr in expressions:
        if not expr or expr.startswith("'"):
            continue
        for is_str, chunk in cells._split_strings(expr):
            if not is_str:
                names.update(_CALL_RE.findall(chunk))
    return names


def search(functions: Iterable[FunctionInfo], prefix: str) -> list[FunctionInfo]:
    t = prefix.lower()
    funcs = sorted(functions, key=lambda f: f.name.lower())
    if not t:
        return funcs
    starts = [f for f in funcs if f.name.lower().startswith(t)]
    contains = [f for f in funcs if t in f.name.lower() and not f.name.lower().startswith(t)]
    return starts + contains


class FunctionCompleter(QCompleter):
    """Popup list of functions attached to an :class:`ExpressionLineEdit`."""

    def __init__(self, editor: "ExpressionLineEdit", source: FunctionSource,
                 on_inserted: Optional[Callable[[FunctionInfo, QLineEdit], None]] = None) -> None:
        super().__init__(editor)
        self._editor = editor
        self._source = source
        self._on_inserted = on_inserted
        self._span: Optional[tuple[int, int]] = None
        self._by_name: dict[str, FunctionInfo] = {}
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setWidget(editor)
        self.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.setCompletionRole(NAME_ROLE)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setMaxVisibleItems(VISIBLE_ITEMS)
        self.popup().setObjectName("completionPopup")
        self.activated[str].connect(self._insert)
        editor.textEdited.connect(lambda _text: self.update_popup())
        editor.completer_ = self

    def update_popup(self, force: bool = False) -> None:
        """Shows/refreshes the list for the word at the cursor (``force``: also with no word)."""
        ed = self._editor
        if ed.isReadOnly():
            self.popup().hide()
            return
        word = word_at_cursor(ed.text(), ed.cursorPosition(), allow_empty=force)
        matches = search(self._source(), word[2]) if word else []
        if not matches:
            self._span = None
            self.popup().hide()
            return
        start, end, prefix = word
        self._span = (start, end)
        self._by_name = {f.name: f for f in matches}
        self._model.clear()
        for f in matches[:MAX_ITEMS]:
            item = QStandardItem(f.name)
            item.setData(f.name, NAME_ROLE)
            item.setToolTip(f.signature)
            item.setEditable(False)
            self._model.appendRow(item)
        x = max(0, ed.cursor_x() - ed.fontMetrics().horizontalAdvance(prefix))
        width = max(POPUP_MIN_WIDTH, self.popup().sizeHintForColumn(0) + 24)
        self.complete(QRect(x, 0, width, ed.height()))
        self.popup().setCurrentIndex(self.completionModel().index(0, 0))

    def _insert(self, name: str) -> None:
        f = self._by_name.get(name)
        ed = self._editor
        if f is None or self._span is None:
            return
        start, end = self._span
        self._span = None
        text = ed.text()
        whole = start == 0 and not text[end:].strip()
        if text[end:end + 1] == "(":
            new, caret = f.name, start + len(f.name) + 1
        elif whole and f.template:
            new = f.template
            caret = start + len(new)
        else:
            new = f"{f.name}()"
            caret = start + len(new) - 1
        ed.setSelection(start, end - start)
        ed.insert(new)
        ed.setCursorPosition(caret)
        if self._on_inserted:
            self._on_inserted(f, ed)


class ExpressionLineEdit(QLineEdit):
    """Line edit that cooperates with a :class:`FunctionCompleter` popup.

    While the popup is open, the completer forwards keys here first; Enter/Tab/Esc are
    left unaccepted so the completer uses them (insert / close) instead of the line edit
    committing the expression or moving focus.
    """

    _POPUP_KEYS = {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
                   Qt.Key.Key_Escape}

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.completer_: Optional[FunctionCompleter] = None

    def popup_visible(self) -> bool:
        return bool(self.completer_ and self.completer_.popup().isVisible())

    def cursor_x(self) -> int:
        return self.cursorRect().left()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.KeyPress:
            if self.popup_visible() and e.key() in self._POPUP_KEYS:
                e.ignore()
                return False
            if (self.completer_ and e.key() == Qt.Key.Key_Space
                    and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.completer_.update_popup(force=True)
                return True
        return super().event(e)


class ExpressionDelegate(QStyledItemDelegate):
    """Sheet cell delegate whose editor completes function names."""

    def __init__(self, source: FunctionSource,
                 on_inserted: Optional[Callable[[FunctionInfo, QLineEdit], None]] = None, parent=None) -> None:
        super().__init__(parent)
        self._source = source
        self._on_inserted = on_inserted

    def createEditor(self, parent, option, index) -> QWidget:
        editor = ExpressionLineEdit(parent)
        editor.setFrame(False)
        FunctionCompleter(editor, self._source, self._on_inserted)
        return editor
