"""Function-name completion in the formula bar and the in-cell editor."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from insight_studio.catalog import Catalog, FunctionInfo
from insight_studio.completion import functions_in_expressions, search, word_at_cursor

from conftest import pump_until


@pytest.mark.parametrize("text,cursor,expected", [
    ("Edi", 3, (0, 3, "Edi")),
    ("A1+Ed", 5, (3, 5, "Ed")),
    ("EditI(0,1)", 3, (0, 5, "Edi")),        # whole identifier is replaced
    ("A1", 2, None),                          # cell reference
    ("$A$1+$B", 7, None),                     # absolute reference part
    ("Blob.Ar", 7, None),                     # structure member
    ("'Edi", 4, None),                        # text constant
    ('String("Edi', 11, None),                # inside a string literal
    ('String("a")+Ed', 14, (12, 14, "Ed")),
    ("12ab", 4, None),
    ("A1+", 3, None),
])
def test_word_at_cursor(text, cursor, expected):
    assert word_at_cursor(text, cursor) == expected


def test_word_at_cursor_forced_empty():
    assert word_at_cursor("A1+", 3, allow_empty=True) == (3, 3, "")


def test_search_prefix_first():
    funcs = [FunctionInfo(n, None, "x") for n in ("TestBlobs", "Blobs", "EditInt")]
    assert [f.name for f in search(funcs, "blob")] == ["Blobs", "TestBlobs"]


def test_functions_in_expressions():
    assert functions_in_expressions(['Count(A0,1)+Sin(B2)', '"Fake(1)"', "'Text(x)"]) == {"Count", "Sin"}


def _type(widget, text):
    for ch in text:
        QTest.keyClick(widget, ch)


@pytest.fixture
def win(window, qapp):
    w, fake, errors = window
    w.catalog = Catalog([FunctionInfo("EditInt", ["Min", "Max"], "Controls", template="EditInt(0,255)"),
                         FunctionInfo("EditFloat", ["Min", "Max"], "Controls"),
                         FunctionInfo("Sin", ["Angle"], "Math")])
    w.activateWindow()
    return w


def _popup(editor):
    return editor.completer_.popup()


def test_formula_bar_completes_function(win, qapp):
    win.sheet.select_location("C4")
    win.formula.clear()
    win.formula.setFocus()
    _type(win.formula, "edi")
    popup = _popup(win.formula)
    assert popup.isVisible()
    assert [popup.model().index(r, 0).data() for r in range(popup.model().rowCount())] == \
        ["EditFloat", "EditInt"]             # ISVS lists names only
    assert popup.model().index(0, 0).data(Qt.ItemDataRole.ToolTipRole) == "EditFloat(Min, Max)"
    QTest.keyClick(popup, Qt.Key.Key_Down)
    QTest.keyClick(popup, Qt.Key.Key_Return)
    assert not popup.isVisible()
    assert win.formula.text() == "EditInt(0,255)"          # template for a whole expression
    assert win.model.expressions.get("C4") is None       # Enter picked, did not commit


def test_formula_bar_completes_inside_expression(win, qapp):
    win.formula.setText("A1*")
    win.formula.setFocus()
    win.formula.end(False)
    _type(win.formula, "si")
    QTest.keyClick(_popup(win.formula), Qt.Key.Key_Tab)
    assert win.formula.text() == "A1*Sin()"
    assert win.formula.cursorPosition() == len("A1*Sin(")


def test_escape_closes_popup_only(win, qapp):
    win.formula.setText("")
    win.formula.setFocus()
    _type(win.formula, "Ed")
    QTest.keyClick(_popup(win.formula), Qt.Key.Key_Escape)
    assert not _popup(win.formula).isVisible()
    assert win.formula.text() == "Ed"


def test_job_functions_offered_without_catalog(win, qapp):
    win.catalog = Catalog([])
    win.formula.setText("")
    win.formula.setFocus()
    _type(win.formula, "acq")                 # A0 is AcquireImage() in the fake job
    popup = _popup(win.formula)
    assert popup.isVisible()
    assert popup.model().index(0, 0).data() == "AcquireImage"


def test_cell_editor_completes_function(win, qapp):
    win.sheet.select_location("D5")
    win.sheet.setFocus()
    QTest.keyClick(win.sheet, "e")            # starts editing the cell
    editor = qapp.focusWidget()
    assert editor is not None and hasattr(editor, "completer_")
    _type(editor, "di")
    popup = _popup(editor)
    assert popup.isVisible()
    QTest.keyClick(popup, Qt.Key.Key_Return)
    assert editor.text() == "EditFloat()"
    QTest.keyClick(editor, Qt.Key.Key_Left)
    QTest.keyClick(editor, Qt.Key.Key_Return)  # commits the cell
    pump_until(qapp, lambda: win.model.expressions.get("D5") == "EditFloat()")
