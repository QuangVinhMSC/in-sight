"""Cell operations (phase 3) against the fake device: Insert/Delete, Cut/Paste, Clear, Undo/Redo,
Find/Replace, Hide/Unhide and cell selection mode."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from conftest import pump_until
from insight_studio import sheet_ops as ops
from insight_studio.cell_dialogs import FindDialog, InsertDeleteDialog
from insight_studio.qtasync import spawn, wait


@pytest.fixture
def sheet(window, qapp):
    win, fake, errors = window
    fake.expressions.update({"A1": "5", "A2": "EditInt(0,100)", "B3": "A1+1", "C3": "$A$2*2", "D5": "B3"})
    fake.names.update({"A1": "Five"})
    fake.values["A2"] = 7
    fake.conditions["B3"] = "A2"
    wait(spawn(win.device.refresh_sheet()))
    wait(spawn(win.device.latest_result()))
    pump_until(qapp, lambda: all(loc in win.model.results for loc in ("A1", "A2", "B3", "C3", "D5")))
    return win, fake, errors


def _idle(win, qapp):
    pump_until(qapp, lambda: not win.model.pending and (win._write_tail is None or win._write_tail.done()))


def _select(win, block):
    win.sheet.select_block(block)


def test_insert_row_moves_cells_names_states_values_and_undo(sheet, qapp):
    win, fake, errors = sheet
    before = dict(fake.expressions)
    win.apply_insert_delete((1, 0, 1, 25), ops.ENTIRE_ROW, delete=False)
    pump_until(qapp, lambda: fake.expressions.get("B4") == "A2+1")
    _idle(win, qapp)
    assert fake.expressions == {"A0": "AcquireImage()", "A2": "5", "A3": "EditInt(0,100)", "B4": "A2+1",
                                "C4": "$A$3*2", "D6": "B4"}
    assert fake.names == {"A0": "Image", "A2": "Five"}
    assert fake.conditions == {"B4": "A3"}
    assert fake.values.get("A3") == 7                       # control value restored after the move
    assert win.act_undo.isEnabled() and "Insert row 1" in win.act_undo.toolTip()

    win.undo()
    pump_until(qapp, lambda: fake.expressions == before)
    _idle(win, qapp)
    assert fake.names == {"A0": "Image", "A1": "Five"} and fake.conditions == {"B3": "A2"}
    assert fake.values.get("A2") == 7
    assert win.act_redo.isEnabled()
    win.redo()
    pump_until(qapp, lambda: fake.expressions.get("D6") == "B4" and "D5" not in fake.expressions)
    _idle(win, qapp)
    assert not errors


def test_delete_shift_up_makes_ref_errors(sheet, qapp):
    win, fake, errors = sheet
    win.apply_insert_delete((1, 0, 1, 0), ops.SHIFT_UP, delete=True)    # delete A1
    pump_until(qapp, lambda: fake.expressions.get("A1") == "EditInt(0,100)")
    _idle(win, qapp)
    assert fake.expressions["B3"] == "#REF+1" and fake.expressions["C3"] == "$A$1*2"
    assert "A2" not in fake.expressions and fake.conditions == {"B3": "A1"}
    assert fake.names == {"A0": "Image"}                    # the named cell was deleted
    assert fake.values.get("A1") == 7


def test_insert_refuses_to_push_cells_off_the_sheet(sheet, qapp, monkeypatch):
    win, fake, errors = sheet
    fake.expressions["A599"] = "1"
    wait(spawn(win.device.refresh_expressions()))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert win.apply_insert_delete((5, 0, 5, 0), ops.SHIFT_DOWN, delete=False) is None
    assert warned and "A599" in warned[0]


def test_cut_paste_moves_and_references_follow(sheet, qapp):
    win, fake, errors = sheet
    _select(win, (1, 0, 1, 0))                              # A1 (named Five)
    win.cut_cells()
    assert win.sheet.cut_block == (1, 0, 1, 0)
    assert fake.expressions["A1"] == "5"                    # nothing moves before Paste
    win.sheet.select_location("F1")
    win.sheet.paste()
    pump_until(qapp, lambda: fake.expressions.get("F1") == "5" and "A1" not in fake.expressions)
    _idle(win, qapp)
    assert fake.expressions["B3"] == "F1+1" and fake.names.get("F1") == "Five"
    assert win.sheet.cut_block is None
    win.undo()
    pump_until(qapp, lambda: fake.expressions.get("A1") == "5" and "F1" not in fake.expressions)
    _idle(win, qapp)
    assert fake.expressions["B3"] == "A1+1" and fake.names.get("A1") == "Five"
    assert not errors


def test_copy_paste_copies_cell_states_like_references(sheet, qapp):
    win, fake, errors = sheet
    _select(win, (3, 1, 3, 1))                              # B3: "A1+1", state "A2"
    win.copy_cells()
    pump_until(qapp, lambda: "conditions\": {\"0,0\"" in bytes(
        QApplication.clipboard().mimeData().data(win.sheet.MIME).data()).decode())
    win.sheet.select_location("C10")
    win.sheet.paste()
    pump_until(qapp, lambda: fake.expressions.get("C10") == "B8+1")
    _idle(win, qapp)
    assert fake.conditions.get("C10") == "B9"


def test_clear_all_and_undo_restores_name_state_and_value(sheet, qapp):
    win, fake, errors = sheet
    _select(win, (1, 0, 3, 1))                              # A1:B3
    win._clear_selected("Clear All")
    pump_until(qapp, lambda: not ({"A1", "A2", "B3"} & set(fake.expressions)))
    _idle(win, qapp)
    assert "A1" not in fake.names and "B3" not in fake.conditions
    win.undo()
    pump_until(qapp, lambda: {"A1", "A2", "B3"} <= set(fake.expressions))
    _idle(win, qapp)
    assert fake.names.get("A1") == "Five" and fake.conditions.get("B3") == "A2" and fake.values.get("A2") == 7


def test_edit_undo_redo(sheet, qapp):
    win, fake, errors = sheet
    win._commit_expression("E1", "42")
    pump_until(qapp, lambda: fake.expressions.get("E1") == "42")
    _idle(win, qapp)
    win._commit_expression("E1", "43")
    pump_until(qapp, lambda: fake.expressions.get("E1") == "43")
    _idle(win, qapp)
    win.undo()
    pump_until(qapp, lambda: fake.expressions.get("E1") == "42")
    _idle(win, qapp)
    win.undo()
    pump_until(qapp, lambda: "E1" not in fake.expressions)
    _idle(win, qapp)
    assert not win.act_undo.isEnabled()
    win.redo()
    pump_until(qapp, lambda: fake.expressions.get("E1") == "42")


def test_find_and_replace_all(sheet, qapp):
    win, fake, errors = sheet
    win.show_find()
    dlg = win.find_dialog
    assert isinstance(dlg, FindDialog) and dlg.windowTitle() == "Find - Inspection"
    win.sheet.select_location("A0")
    dlg.find_box.setEditText("a1")
    dlg.btn_next.click()
    assert win.sheet.current_location() == "B3"
    dlg.btn_next.click()                                    # wraps around (only one match)
    assert win.sheet.current_location() == "B3"
    dlg.look_in.setCurrentText(ops.LOOK_NAMES)
    dlg.find_box.setEditText("five")
    dlg.btn_next.click()
    assert win.sheet.current_location() == "A1"
    assert dlg.find_box.itemText(0) == "five" and dlg.find_box.findText("a1") >= 0   # history

    dlg.look_in.setCurrentText(ops.LOOK_EXPRESSIONS)
    dlg.find_box.setEditText("$A$2")
    dlg.replace_box.setEditText("$A$1")
    dlg.btn_replace_all.click()
    pump_until(qapp, lambda: fake.expressions.get("C3") == "$A$1*2")
    _idle(win, qapp)
    win.undo()
    pump_until(qapp, lambda: fake.expressions.get("C3") == "$A$2*2")

    win.device.state["softOnline"] = True
    win.device.state["online"] = True
    win._update_actions()
    assert not dlg.btn_replace.isEnabled()                 # Replace only offline


def test_hide_unhide_rows_view_only(sheet, qapp):
    win, fake, errors = sheet
    _select(win, (2, 0, 3, 25))
    win.hide_rows_columns()
    assert win.sheet.isRowHidden(2) and win.sheet.isRowHidden(3)
    _select(win, (1, 0, 4, 25))
    menu = win.build_cell_menu()
    unhide = next(a for a in menu.findChildren(type(menu.actions()[0])) if a.text() == "Unhide")
    assert unhide.isEnabled()
    win.unhide_rows_columns()
    assert not win.sheet.isRowHidden(2) and not win.sheet.isRowHidden(3)


def test_insert_reference_into_empty_cell(sheet, qapp):
    win, fake, errors = sheet
    win.sheet.select_location("E2")
    win.act_abs_ref.trigger()
    assert win.sheet.in_selection_mode and not win.image.isVisible()
    win.sheet.select_location("A1")
    QTest.keyClick(win.sheet, Qt.Key.Key_Return)
    pump_until(qapp, lambda: fake.expressions.get("E2") == "$A$1")
    assert not win.sheet.in_selection_mode and win.sheet.current_location() == "E2"


def test_insert_relative_range_while_editing_formula_bar(sheet, qapp):
    win, fake, errors = sheet
    win.sheet.select_location("E2")
    win.formula.setFocus()
    win.formula.setText("Sum()")
    win.formula.setCursorPosition(4)
    win.act_rel_ref.trigger()
    win.sheet.select_block((1, 0, 2, 0))                    # A1:A2
    QTest.keyClick(win.sheet, Qt.Key.Key_Return)
    assert win.formula.text() == "Sum(A1:A2)" and win.formula.cursorPosition() == 9
    assert "E2" not in fake.expressions                     # still editing
    win.act_rel_ref.trigger()
    QTest.keyClick(win.sheet, Qt.Key.Key_Escape)             # cancel keeps the text
    assert win.formula.text() == "Sum(A1:A2)" and not win.sheet.in_selection_mode


def test_insert_delete_dialog(qapp):
    dlg = InsertDeleteDialog(delete=False)
    assert dlg.windowTitle() == "Insert ❒Inspection" and dlg.mode() == ops.SHIFT_DOWN
    assert [b.text() for b in dlg.buttons.values()] == ["Shift cells right", "Shift cells down", "Entire row",
                                                        "Entire column"]
    dlg = InsertDeleteDialog(delete=True, default=ops.ENTIRE_COLUMN)
    assert dlg.windowTitle() == "Delete ❒Inspection" and dlg.mode() == ops.ENTIRE_COLUMN
    assert dlg.buttons[ops.SHIFT_LEFT].text() == "Shift cells left"
