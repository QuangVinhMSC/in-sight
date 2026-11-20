"""Grid fidelity (phase 2): in-cell controls, markers, tooltips, headers, editing, context menu."""

from conftest import pump_until
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from insight_studio import cells
from insight_studio.sheet import ERROR_TIP

CONTROLS = {
    "A2": 'Button("Test")', "A3": 'CheckBox("On")', "A4": 'ListBox("Item1","Item2","Item3")',
    "A5": "EditInt(0,100)", "A6": "EditFloat(0,10)", "A7": "EditString(8)",
    "A8": 'EditRegion($A$0,0,0,0,1,1,1,1,"Region",2)', "A9": "1/0+bogus", "B5": "A5*2",
}


def _setup(win, fake, qapp):
    win._paste_cells(dict(CONTROLS))
    pump_until(qapp, lambda: not win.model.pending and all(loc in win.model.results for loc in CONTROLS))


def _part_pos(win, loc, part):
    index = win.model.index(*cells.parse_address(loc))
    parts = win.delegate.parts(index, win.sheet.visualRect(index), win.sheet.font())
    return parts[part].center()


def _click(win, loc, part):
    QTest.mouseClick(win.sheet.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     _part_pos(win, loc, part))


def test_controls_are_drawn_as_widgets(window, qapp):
    win, fake, errors = window
    _setup(win, fake, qapp)
    kinds = {loc: win.delegate.kind(win.model.index(*cells.parse_address(loc))) for loc in CONTROLS}
    assert kinds == {"A2": "button", "A3": "checkbox", "A4": "listbox", "A5": "editint", "A6": "editfloat",
                     "A7": "editstring", "A8": "graphic", "A9": None, "B5": None}
    assert win.model.data(win.model.index(9, 0)) == "#ERR"
    assert not errors


def test_checkbox_button_and_spin_write_values(window, qapp):
    win, fake, errors = window
    _setup(win, fake, qapp)
    _click(win, "A3", "check")
    pump_until(qapp, lambda: fake.values.get("A3") == 1)
    pump_until(qapp, lambda: (win.model.results["A3"] or {}).get("data") == 1)
    _click(win, "A3", "check")
    pump_until(qapp, lambda: fake.values.get("A3") == 0)

    _click(win, "A2", "button")
    pump_until(qapp, lambda: fake.button_presses == ["A2"])
    assert win.delegate.pressed is None  # released look

    _click(win, "A5", "up")
    pump_until(qapp, lambda: fake.values.get("A5") == 1)
    pump_until(qapp, lambda: win.model.results["A5"]["data"] == 1)
    _click(win, "A5", "down")
    pump_until(qapp, lambda: fake.values.get("A5") == 0)
    pump_until(qapp, lambda: win.model.results["A5"]["data"] == 0)
    _click(win, "A5", "down")  # already at Min: nothing written
    qapp.processEvents()
    assert fake.values.get("A5") == 0
    assert not errors


def test_listbox_popup_picks_an_item(window, qapp):
    win, fake, errors = window
    _setup(win, fake, qapp)
    _click(win, "A4", "drop")
    menu = win.sheet._listbox_menu
    pump_until(qapp, lambda: menu.isVisible())
    assert [a.text() for a in menu.actions()] == ["Item1", "Item2", "Item3"]
    assert menu.actions()[0].isChecked()
    menu.actions()[2].trigger()
    menu.close()
    pump_until(qapp, lambda: fake.values.get("A4") == 2)
    pump_until(qapp, lambda: win.model.data(win.model.index(4, 0)) == "Item3")
    assert not errors


def test_value_editor_in_cell(window, qapp):
    win, fake, errors = window
    _setup(win, fake, qapp)
    QTest.mouseDClick(win.sheet.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      _part_pos(win, "A6", "field"))
    editor = win.sheet._value_editor
    assert editor is not None and editor.objectName() == "valueEditor"
    assert win.sheet.state() != win.sheet.State.EditingState  # not the expression editor
    editor.lineEdit().selectAll()
    QTest.keyClicks(editor, "7.25")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    pump_until(qapp, lambda: fake.values.get("A6") == 7.25)
    assert win.sheet._value_editor is None

    win.sheet.select_location("A7")  # second click on the current cell opens the box
    _click(win, "A7", "field")
    editor = win.sheet._value_editor
    QTest.keyClicks(editor, "abc")
    QTest.keyClick(editor, Qt.Key.Key_Escape)  # cancels
    assert win.sheet._value_editor is None
    qapp.processEvents()
    assert "A7" not in fake.values
    assert not errors


def test_controls_locked_while_unavailable(window, qapp):
    win, fake, errors = window
    _setup(win, fake, qapp)
    win.sheet.controls_enabled = False
    _click(win, "A3", "check")
    qapp.processEvents()
    assert "A3" not in fake.values
    assert not errors


def test_graphic_button_enters_interactive_graphics(window, qapp):
    win, fake, errors = window
    _setup(win, fake, qapp)
    _click(win, "A8", "button")
    pump_until(qapp, lambda: win.image.editor is not None)
    assert win.sheet.current_location() == "A8"
    win.cancel_graphic()
    pump_until(qapp, lambda: win.image.editor is None)
    assert not errors


def test_name_marker_tooltips_and_structures(window, qapp):
    win, fake, errors = window
    _setup(win, fake, qapp)
    a0 = win.model.index(0, 0)
    assert win.model.data(a0) == "❒Image"
    assert win.model.data(a0, Qt.ItemDataRole.ToolTipRole) == "Image"  # the cell name
    assert win.model.data(a0, Qt.ItemDataRole.FontRole) is None or \
        not win.model.data(a0, Qt.ItemDataRole.FontRole).italic()
    assert win.model.data(win.model.index(9, 0), Qt.ItemDataRole.ToolTipRole) == ERROR_TIP
    assert win.model.data(win.model.index(5, 1), Qt.ItemDataRole.ToolTipRole) is None
    assert not errors


def test_active_headers_follow_selection(window, qapp):
    win, _fake, errors = window
    win.sheet.select_location("C7")
    h, v = win.sheet.horizontalHeader(), win.sheet.verticalHeader()
    assert h.is_active(2) and v.is_active(7)
    assert not h.is_active(0) and not v.is_active(0)
    assert not errors


def test_typing_starts_edit_and_mirrors_formula_bar(window, qapp):
    win, fake, errors = window
    _setup(win, fake, qapp)
    win.sheet.select_location("B5")
    win.sheet.setFocus()
    assert not win.act_accept.isEnabled()
    QTest.keyClick(win.sheet, "7")
    editor = win.sheet.editor_widget()
    assert editor is not None and editor.text() == "7"  # typing replaces the cell
    assert win.formula.text() == "7"
    assert win.act_accept.isEnabled() and win.act_cancel.isEnabled()
    win.act_cancel.trigger()
    assert win.sheet.editor_widget() is None
    pump_until(qapp, lambda: win.formula.text() == "A5*2")
    assert not win.act_accept.isEnabled()

    QTest.keyClick(win.sheet, "9")
    win.act_accept.trigger()
    pump_until(qapp, lambda: fake.expressions.get("B5") == "9")
    assert not errors


def _menu_layout(menu):
    out = []
    for a in menu.actions():
        if a.isSeparator():
            out.append("--")
        elif a.menu() is not None:
            out.append(f"{a.text()} > " + "|".join(x.text() for x in a.menu().actions()))
        else:
            out.append(a.text())
    return out


def _find(menu, text):
    for a in menu.actions():
        if a.text() == text:
            return a
        if a.menu() is not None:
            found = _find(a.menu(), text)
            if found is not None:
                return found
    return None


def test_context_menu_matches_isvs(window, qapp):
    win, fake, errors = window
    win.sheet.select_location("D4")
    QApplication.clipboard().clear()
    win._update_actions()
    menu = win.build_cell_menu()
    assert _menu_layout(menu) == [
        "Cut", "Copy", "Paste", "--",
        "Insert…", "Delete…", "Clear > All|Contents|Formats|Comments", "--",
        "Insert Function…", "Insert Absolute Reference…", "Insert Relative Reference…", "Insert Comment…",
        "Insert Cell Name…", "Insert Getters", "--",
        "Cell Graphic…", "Cell State…", "IP Licensing > Protect Cells|Unprotect Cells", "--",
        "Format > Cell(s)|Row Height…|Column Width…|Hide|Unhide", "--",
        "Import Snippet…", "Export Snippet…", "--",
        "Publish to EasyView > Selected|Named", "--",
        "Create Custom View",
    ]
    # an empty cell (ISVS live/07): no paste without clipboard, no name, graphic or comment
    assert not _find(menu, "Paste").isEnabled()
    assert _find(menu, "Insert Function…").isEnabled()
    for text in ("Insert Cell Name…", "Cell Graphic…", "Cell State…", "Insert Comment…", "Formats", "Protect Cells"):
        assert not _find(menu, text).isEnabled(), text
    assert "HMI API" in _find(menu, "Insert Comment…").toolTip()
    assert "Not implemented" in _find(menu, "Insert Getters").toolTip()
    assert _find(menu, "Insert…").isEnabled() and _find(menu, "Delete…").isEnabled()

    # a cell with a function that has a property sheet offers Edit Function…; one without
    # (A0: AcquireImage()) keeps Insert Function…; Clear > Contents clears the cell
    win._paste_cells({"D5": "EditInt(0,100)"})
    pump_until(qapp, lambda: win.model.expressions.get("D5") and not win.model.pending)
    win.sheet.select_location("D5")
    win._update_actions()
    menu = win.build_cell_menu()
    assert _find(menu, "Edit Function…") is not None and _find(menu, "Insert Function…") is None
    if win.catalog.get("AcquireImage"):  # known to have no inputs (needs the generated catalog)
        win.sheet.select_location("A0")
        win._update_actions()
        menu = win.build_cell_menu()
        assert _find(menu, "Edit Function…") is None and _find(menu, "Insert Function…") is not None
    assert _find(menu, "Edit Cell Name…").isEnabled()         # A0 is named "Image" (ISVS: Edit Cell Name...)
    win._paste_cells({"D4": "'x"})
    pump_until(qapp, lambda: win.model.expressions.get("D4") == "'x" and not win.model.pending)
    win.sheet.select_location("D4")
    win._update_actions()
    _find(win.build_cell_menu(), "Contents").trigger()
    pump_until(qapp, lambda: "D4" not in fake.expressions)
    assert not errors
