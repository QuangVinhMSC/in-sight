"""Phase 4: catalog tree, Functions panel, Insert Function dialog, inserting functions."""

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest

from insight_studio import cells
from insight_studio.catalog import DATA, Catalog, FunctionInfo, default_expression
from insight_studio.functions_ui import FUNCTION_MIME, FunctionsPanel, InsertFunctionDialog
from insight_studio.helpdoc import function_tables, parse_html, short_description

from conftest import pump_until

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_catalog  # noqa: E402

# Top-level toolbox categories as ISVS 26.1 lists them for the IS8902CX (live/14, live/16)
ISVS_TOP = ["Edge AI", "Vision Tools", "Geometry", "Graphics", "Mathematics", "Robotics String Functions", "Text",
            "Coordinate Transforms", "Input/Output", "Clocked Data Storage", "Vision Data Access", "White Balance",
            "Structures", "Scripting", "Arrays and Objects"]
ISVS_VISION = ["Bead", "Blob", "Color", "Edge", "Histogram", "ID", "Image", "InspectEdge", "OCV/OCR", "Pattern Match"]


# functions.json is generated from the local ISVS help (tools/build_catalog.py) and not in the repository
needs_catalog = pytest.mark.skipif(not DATA.is_file(), reason="no function catalog (run tools/build_catalog.py)")


@pytest.fixture(scope="module")
def catalog():
    if not DATA.is_file():
        pytest.skip("no function catalog (run tools/build_catalog.py)")
    return Catalog.load()


# ---------------------------------------------------------------------------- catalog
def test_toolbox_tree_matches_isvs(catalog):
    assert [c.name for c in catalog.tree()] == ISVS_TOP
    vision = catalog.find_category(("Vision Tools",))
    assert [c.name for c in vision.children] == ISVS_VISION
    # categories without subcategories have no expand box in ISVS
    for name in ("Edge AI", "Robotics String Functions", "Clocked Data Storage", "White Balance", "Structures",
                 "Scripting"):
        assert not catalog.find_category((name,)).children, name
    assert {c.name for c in catalog.categories if c.hidden} == {"Advanced AI", "Focus"}


def test_functions_of_categories(catalog):
    assert [f.name for f in catalog.functions_in(("Vision Tools", "Pattern Match"))] == \
        ["FindPatMaxRedLine", "SortPatterns", "TrainPatMaxRedLine"]
    all_names = [f.name for f in catalog.functions_in(())]
    assert all_names[:5] == ["Abs", "Accumulate", "ACos", "AcquireImage", "And"]  # sorted like ISVS
    assert "AutoFocus" not in all_names                              # Focus: device specific, hidden
    assert catalog.get("AutoFocus") is not None                      # … but still known
    # functions documented in tables (Math, Logic, String, Vision Data Access pages)
    assert catalog.get("Abs").paths == [("Mathematics", "Math")]
    assert catalog.get("Abs").signature == "Abs(Value)"
    assert set(catalog.get("If").paths) == {("Mathematics", "Logic"), ("Mathematics", "Lookup")}
    assert ("Vision Data Access", "Blobs") in catalog.get("GetX").paths
    assert "Concatenate" in [f.name for f in catalog.functions_in(("Text",))]
    # category pages are not functions
    for name in ("Math", "Logic", "Image", "Bead", "Statistics"):
        assert catalog.get(name) is None, name
    assert catalog.get("TrainPatMaxRedLine").has_property_sheet
    assert not catalog.get("Abs").has_property_sheet
    assert "GetModelHealth" in catalog.get("EdgeAIClassify").getters
    assert catalog.get("TrainPatMaxRedLine").enable["Coarse Granularity"] == {"param": "Auto Select Coarse",
                                                                              "values": [0]}


def test_short_signature(catalog):
    assert catalog.get("TrainPatMaxRedLine").short_signature == \
        "TrainPatMaxRedLine(Image, Fixture, Pattern Region, ...)"
    assert catalog.get("Sum").short_signature == "Sum(Value1, [Value2, ...])"


@needs_catalog
def test_catalog_has_no_help_prose():
    doc = json.loads(DATA.read_text(encoding="utf-8"))

    def walk(o):
        if isinstance(o, dict):
            assert "description" not in o
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)


def test_default_expression(catalog):
    expr = default_expression(catalog.get("TrainPatMaxRedLine"), (800, 600))
    # as ISVS inserted it on the IS8902CX (live/17): region centred on the 800x600 image
    assert expr.startswith("TrainPatMaxRedLine($A$0,0,0,0,180,140,440,320,0,0,0,0,0,1,1,4,1,20,")
    assert len(expr.split(",")) == 22
    assert default_expression(catalog.get("EditInt")) == "EditInt(0,255)"  # known template
    assert default_expression(catalog.get("Abs")) is None                   # no property sheet
    info = FunctionInfo("Tool", None, "x", inputs=[{"name": "Image", "kind": "image"},
                                                     {"name": "Patterns", "kind": "text"}])
    assert default_expression(info) is None                               # no default for Patterns


# ---------------------------------------------------------------------------- help parsing
PAGE = """<html><body><h1>Math</h1>
<p>Math functions provide <a href="x.htm" class="MCXref">Thing</a><a href="#" class="MCTextPopup MCTextPopupHotSpot">function<span
class="MCTextPopupBody popupBody">Functions are tools.</span></a> helpers. Second sentence here. Third one.</p>
<table><tr><th>Function</th><th>Description</th></tr>
<tr><td>Abs(Value)</td><td><p>Returns the absolute value of <i>Value</i> .</p></td></tr>
<tr><td>GetIsUnclassified</td><td>Sets the mode.</td></tr>
</table></body></html>"""


def test_function_tables_and_descriptions():
    assert function_tables(parse_html(PAGE)) == [("Abs", "Value"), ("GetIsUnclassified", None)]
    assert short_description(PAGE, "Abs") == "Returns the absolute value of Value."
    assert short_description(PAGE) == "Math functions provide Thing function helpers. Second sentence here."


def test_toc_parser():
    js = "define({numchunks:1,tree:{n:[{i:0,c:0,n:[{i:1,c:2}]}]},t:['It\\'s','b']})"
    assert build_catalog._js_object(js) == {"numchunks": 1, "tree": {"n": [{"i": 0, "c": 0, "n": [{"i": 1, "c": 2}]}]},
                                            "t": ["It's", "b"]}
    assert build_catalog.category_name("InspectEdge Functions", top=False) == "InspectEdge"
    assert build_catalog.category_name("EdgeAIClassify Vision Data Access functions", top=False) == "EdgeAIClassify"
    assert build_catalog.category_name("Edge AI Tools", top=True) == "Edge AI"


# ---------------------------------------------------------------------------- widgets
def test_insert_function_dialog(catalog, qapp):
    dlg = InsertFunctionDialog(catalog, "B2")
    assert dlg.windowTitle() == f"Insert Function {cells.STRUCTURE_GLYPH}Inspection"
    assert (dlg.width(), dlg.height()) == (674, 432)
    assert dlg.all_item.isExpanded()
    assert [dlg.all_item.child(i).text(0) for i in range(dlg.all_item.childCount())] == ISVS_TOP
    assert dlg.list.count() == len(catalog.functions_in(()))
    assert not dlg.insert_button.isEnabled()                    # nothing to insert while a category is selected
    assert dlg.select_category(("Vision Tools",))
    assert dlg.title.text() == "Vision Tools" and not dlg.insert_button.isEnabled()
    assert dlg.list.count() == len(catalog.functions_in(("Vision Tools",)))
    assert dlg.select_category(("Vision Tools", "Pattern Match"))
    assert dlg.select_function("TrainPatMaxRedLine")
    assert dlg.insert_button.isEnabled()
    assert dlg.title.text() == "TrainPatMaxRedLine"
    assert "<b>TrainPatMaxRedLine(Image, Fixture, Pattern Region, ...)</b>" in dlg.description.text()
    assert dlg.selected().name == "TrainPatMaxRedLine"
    dlg.select_category(("Mathematics",))                       # back to a category: Insert disabled again
    assert dlg.selected() is None and not dlg.insert_button.isEnabled()
    dlg.deleteLater()


def test_functions_panel_filter_and_drag(catalog, qapp):
    panel = FunctionsPanel(catalog)
    tops = [panel.tree.topLevelItem(i).text(0) for i in range(panel.tree.topLevelItemCount())]
    assert tops == ISVS_TOP
    assert panel.desc.text() == "All functions"
    panel.filter.setText("patmax")
    names = []
    for item in panel._items():
        f = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(f, FunctionInfo):
            names.append(f.name)
    assert names == ["FindPatMaxRedLine", "TrainPatMaxRedLine"]
    assert panel.select_function("TrainPatMaxRedLine")
    assert "TrainPatMaxRedLine(Image" in panel.desc.text()
    mime = panel.tree.mimeData([panel.tree.currentItem()])
    assert bytes(mime.data(FUNCTION_MIME)) == b"TrainPatMaxRedLine"
    activated = []
    panel.functionActivated.connect(activated.append)
    panel._activated(panel.tree.currentItem())
    assert [f.name for f in activated] == ["TrainPatMaxRedLine"]
    panel.filter.clear()
    assert panel.tree.topLevelItemCount() == len(ISVS_TOP)
    panel.deleteLater()


# ---------------------------------------------------------------------------- inserting
@pytest.fixture
def offline(window, qapp):
    if not DATA.is_file():
        pytest.skip("no function catalog (run tools/build_catalog.py)")
    win, fake, errors = window
    win.catalog = Catalog.load()
    assert not win.model.read_only  # the fake vision system starts offline
    return win, fake, errors


def test_insert_tool_opens_property_sheet_cancel_restores(offline, qapp):
    win, fake, errors = offline
    win.sheet.select_location("D5")
    win.insert_function_into("D5", win.catalog.get("TrainPatMaxRedLine"))
    pump_until(qapp, lambda: win.property_sheet is not None)
    w, h = win._image_size()
    x, y = round((w - 440) / 2), round((h - 320) / 2)
    assert fake.expressions["D5"].startswith(f"TrainPatMaxRedLine($A$0,0,0,0,{x},{y},440,320,0,0,")
    ps = win.property_sheet
    assert ps.location == "D5" and ps.original_expression == ""
    ps.reject()                                                   # Cancel: the cell is empty again
    pump_until(qapp, lambda: "D5" not in fake.expressions and win.property_sheet is None)
    assert not win.history.can_undo()                             # nothing to undo after Cancel
    assert not errors


def test_insert_tool_ok_is_one_undo_step(offline, qapp):
    win, fake, errors = offline
    win.sheet.select_location("D6")
    win.insert_function_into("D6", win.catalog.get("FindLine"))
    pump_until(qapp, lambda: win.property_sheet is not None)
    win.property_sheet.accept()
    pump_until(qapp, lambda: win.property_sheet is None)
    assert fake.expressions["D6"].startswith("FindLine($A$0,0,0,0,")
    win.undo()
    pump_until(qapp, lambda: "D6" not in fake.expressions)
    assert not errors


def test_insert_plain_function_goes_to_formula_bar(offline, qapp):
    win, fake, errors = offline
    win.sheet.select_location("E2")
    win.insert_function_into("E2", win.catalog.get("Abs"))
    assert win.formula.text() == "Abs()"
    assert win.formula.cursorPosition() == len("Abs(")
    assert win.property_sheet is None
    assert "E2" not in fake.expressions


def test_drop_function_on_cell(offline, qapp):
    win, fake, errors = offline
    mime = QMimeData()
    mime.setData(FUNCTION_MIME, b"Abs")
    sheet = win.sheet
    rect = sheet.visualRect(win.model.index(3, 2))                # C3
    ev = QDropEvent(QPointF(rect.center()), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    sheet.dropEvent(ev)
    assert ev.isAccepted()
    assert win.sheet.current_location() == "C3"
    assert win.formula.text() == "Abs()"


def test_autocomplete_pick_opens_property_sheet(offline, qapp):
    win, fake, errors = offline
    win.sheet.select_location("F7")
    win.formula.clear()
    win.formula.setFocus()
    for ch in "TrainPatMaxR":
        QTest.keyClick(win.formula, ch)
    popup = win.formula.completer_.popup()
    assert popup.isVisible()
    QTest.keyClick(popup, Qt.Key.Key_Return)
    pump_until(qapp, lambda: win.property_sheet is not None)
    assert win.property_sheet.location == "F7"
    assert fake.expressions["F7"].startswith("TrainPatMaxRedLine($A$0,")
    win.property_sheet.reject()
    pump_until(qapp, lambda: "F7" not in fake.expressions and win.property_sheet is None)
    assert not errors


def test_insert_function_dialog_from_window(offline, qapp, monkeypatch):
    win, fake, errors = offline
    win.sheet.select_location("G9")
    chosen = []

    def fake_exec(dlg):
        chosen.append(dlg)
        dlg.select_category(("Mathematics", "Math"))
        dlg.select_function("Sqrt")
        return InsertFunctionDialog.DialogCode.Accepted

    monkeypatch.setattr(InsertFunctionDialog, "exec", fake_exec)
    win.insert_function()
    assert chosen and win.formula.text() == "Sqrt()"
