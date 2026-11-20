"""Property sheet: help parsing, argument mapping and the dialog against the fake device."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from insight_studio import cells
from insight_studio.catalog import Catalog, FunctionInfo
from insight_studio.helpdoc import leaf_count, parse_inputs
from insight_studio.property_sheet import (
    build_rows,
    is_training_function,
    join_call,
    ref_location,
    referenced_locations,
    split_call,
)
from insight_studio.qtasync import spawn, wait

from conftest import pump_until

# Shaped like the Inputs table of an In-Sight help page (nested tables, popups, defaults).
HELP_PAGE = """
<html><body><h1>TrainPatMaxRedLine</h1>
<div><a class="dropDownHotspot">Inputs</a><div>
<table class="TableStyle-StandardTable">
 <tr><td>Parameter</td><td>Description</td></tr>
 <tr><td><p>Image</p></td><td><p>This parameter must reference a spreadsheet cell that contains an Image data structure.</p></td></tr>
 <tr><td><p><a class="MCTextPopup">Fixture<span class="MCTextPopupBody popupBody">A fixture is a coordinate location.</span></a></p></td>
     <td><p>Defines the ROI. The default setting is (0,0,0).</p>
     <table><tbody>
       <tr><td><p>X (default = 0)</p></td><td><p>The X-offset.</p></td></tr>
       <tr><td><p>Y (default = 0)</p></td><td><p>The Y-offset.</p></td></tr>
       <tr><td><p>Theta (default = 0)</p></td><td><p>The rotation.</p></td></tr>
     </tbody></table></td></tr>
 <tr><td><p>Pattern Region</p></td><td><p>Specifies the region.</p>
     <table><tbody>
       <tr><td><p>X</p></td><td><p>X origin.</p></td></tr>
       <tr><td><p>Y</p></td><td><p>Y origin.</p></td></tr>
       <tr><td><p>Width (default = 440)</p></td><td><p>Width.</p></td></tr>
       <tr><td><p>Height (default = 320)</p></td><td><p>Height.</p></td></tr>
       <tr><td><p>Angle (default = 0)</p></td><td><p>Angle.</p></td></tr>
       <tr><td><p>Curve (default = 0)</p></td><td><p>Curve.</p></td></tr>
     </tbody></table></td></tr>
 <tr><td><p>External Region</p></td><td><p>This parameter uses Cell References to spreadsheet cell that contains a Region.</p></td></tr>
 <tr><td><p>Pattern Origin</p></td><td><p>Origin offsets.</p>
     <table><tr><td><p>Offset X (default = 0)</p></td><td><p>x</p></td></tr>
            <tr><td><p>Offset Y (default = 0)</p></td><td><p>y</p></td></tr></table></td></tr>
 <tr><td><p>Auto Select Coarse</p></td><td><p>Auto coarse.</p>
     <table><tr><td><p>0 = OFF</p></td><td><p>off</p></td></tr>
            <tr><td><p>1 = ON (default)</p></td><td><p>on</p></td></tr></table></td></tr>
 <tr><td><p>Auto Select Fine</p></td><td><p>Auto fine.</p>
     <table><tr><td><p>0 = OFF</p></td><td><p>off</p></td></tr>
            <tr><td><p>1 = ON (default)</p></td><td><p>on</p></td></tr></table></td></tr>
 <tr><td><p>Coarse Granularity</p></td><td><p>Coarse granularity (1 to 30; 4 = default).</p></td></tr>
 <tr><td><p>Fine Granularity</p></td><td><p>Fine granularity (1 to 10; 1 = default).</p></td></tr>
 <tr><td><p>Feature Threshold</p></td><td><p>Minimum contrast (1 to 100; 20 = default).</p></td></tr>
 <tr><td><p>Train Event</p></td><td><p>Specifies Cell References to a cell containing a model training event trigger.</p></td></tr>
 <tr><td><p>Reuse Training Image</p></td><td><p>Reuse.</p>
     <table><tr><td><p>0 = OFF (default)</p></td><td><p>off</p></td></tr>
            <tr><td><p>1 = ON</p></td><td><p>on</p></td></tr></table></td></tr>
 <tr><td><p>Timeout</p></td><td><p>Time in milliseconds (0 to 30000; 0 = default).</p></td></tr>
 <tr><td><p>Show</p></td><td><p>Display mode.</p>
     <table><tr><td><p>0 = hide all (default)</p></td><td><p>a</p></td></tr>
            <tr><td><p>1 = result graphics only</p></td><td><p>b</p></td></tr>
            <tr><td><p>2 = input and result graphics</p></td><td><p>c</p></td></tr></table></td></tr>
</table></div></div>
<a class="dropDownHotspot">Outputs</a><table><tr><td>Output</td><td>Description</td></tr></table>
</body></html>
"""

TRAIN_EXPR = "TrainPatMaxRedLine($A$0,0,0,0,100,80,440,320,0,0,$C$3,0,0,$A$12,$A$12,$B$12,4,20,$F$4,0,0,0)"


def test_parse_help_inputs():
    params = parse_inputs(HELP_PAGE, keep_description=False)
    assert [p["name"] for p in params] == [
        "Image", "Fixture", "Pattern Region", "External Region", "Pattern Origin", "Auto Select Coarse",
        "Auto Select Fine", "Coarse Granularity", "Fine Granularity", "Feature Threshold", "Train Event",
        "Reuse Training Image", "Timeout", "Show"]
    by = {p["name"]: p for p in params}
    assert leaf_count(params) == 22
    assert by["Image"]["kind"] == "image"
    assert by["Fixture"]["kind"] == "group" and [c["name"] for c in by["Fixture"]["children"]] == ["X", "Y", "Theta"]
    assert "default" not in by["Fixture"]
    assert by["Pattern Region"]["kind"] == "region"
    assert by["Pattern Region"]["children"][2] == {"name": "Width", "default": "440", "kind": "number"}
    assert by["Auto Select Coarse"]["kind"] == "bool" and by["Auto Select Coarse"]["default"] == "1"
    assert by["Coarse Granularity"] == {"name": "Coarse Granularity", "min": 1.0, "max": 30.0,
                                        "default": "4", "kind": "number"}
    assert by["Train Event"]["kind"] == "event"
    assert by["External Region"]["kind"] == "reference"
    assert by["Show"]["kind"] == "enum" and [o["value"] for o in by["Show"]["options"]] == [0, 1, 2]
    assert "description" not in by["Image"]
    with_text = parse_inputs(HELP_PAGE)
    assert with_text[1]["description"].startswith("Defines the ROI")  # popup text is dropped
    assert with_text[1]["children"][0]["description"] == "The X-offset."


def test_split_and_join_call():
    expr = 'Fn($A$0,If(B1>2,1,0), "a,(b", 3)'
    name, args = split_call(expr)
    assert name == "Fn" and args == ["$A$0", "If(B1>2,1,0)", '"a,(b"', "3"]
    assert join_call(name, args) == 'Fn($A$0,If(B1>2,1,0),"a,(b",3)'
    assert split_call("AcquireImage()") == ("AcquireImage", [])
    assert split_call("Fn(1)+2") is None
    assert split_call("'text") is None


def test_references():
    names = {"Train": "F4"}.get
    assert ref_location("$A$12", names) == "A12"
    assert ref_location("b3", names) == "B3"
    assert ref_location("Train", names) == "F4"
    assert ref_location("GetX($B$3)", names) is None
    assert referenced_locations("$F$4||$D$12") == ["F4", "D12"]
    assert referenced_locations('Str("A1")+B2') == ["B2"]


def test_training_functions():
    assert all(is_training_function(n) for n in ("TrainPatMaxRedLine", "TrainPatMaxPattern", "EdgeAIClassify",
                                                 "EdgeAIRead"))
    assert not any(is_training_function(n) for n in ("FindPatMaxRedLine", "EditInt", None))


def test_build_rows_maps_groups_to_arguments():
    info = FunctionInfo("TrainPatMaxRedLine", None, "VisionTools", inputs=parse_inputs(HELP_PAGE, False))
    rows, note = build_rows(info, 22)
    assert note is None
    assert [c.index for c in rows[1].children] == [1, 2, 3]
    assert [c.index for c in rows[2].children] == [4, 5, 6, 7, 8, 9]
    assert rows[-1].label == "Show" and rows[-1].index == 21
    rows, note = build_rows(info, 16)  # cell does not match the help: shown by position
    assert [r.label for r in rows[:2]] == ["Argument 1", "Argument 2"] and "22 inputs" in note


@pytest.fixture
def job(window, qapp):
    win, fake, errors = window
    fake.expressions.update({
        "C3": "EditRegion($A$0,0,0,0,1,1,1,1)",
        "F4": 'Button("Train")',
        "A12": 'CheckBox("AutoGranularity")',
        "B12": "EditFloat(1,30)",
        "G4": TRAIN_EXPR,
    })
    wait(spawn(win.device.refresh_sheet()))
    wait(spawn(win.device.latest_result()))
    pump_until(qapp, lambda: all(loc in win.model.results for loc in ("C3", "F4", "A12", "G4")))
    win.catalog = Catalog([FunctionInfo("TrainPatMaxRedLine", None, "VisionTools",
                                        inputs=parse_inputs(HELP_PAGE, False))])
    return win, fake, errors


def test_double_click_opens_property_sheet(job, qapp):
    win, fake, errors = job
    index = win.model.index(4, 6)  # G4
    assert win.sheet.opens_on_double_click(index)          # no in-cell editor for training tools
    assert not win.sheet.opens_on_double_click(win.model.index(12, 1))
    win._on_cell_double_clicked(index)
    ps = win.property_sheet
    assert ps is not None and ps.isVisible()
    assert ps.windowTitle() == "Inspection ❒Property Sheet ❒TrainPatMaxRedLine"
    assert (ps.width(), ps.height()) == (426, 720)
    top = [ps.tree.topLevelItem(i).text(0) for i in range(ps.tree.topLevelItemCount())]
    assert top[:3] == ["Image", "Fixture", "Pattern Region"]
    assert ps.tree.topLevelItem(2).text(1) == "(100,80,440,320,0,0)"
    assert not errors


def test_property_sheet_edits_and_cancel(job, qapp):
    win, fake, errors = job
    win.open_property_sheet("G4")
    ps = win.property_sheet

    ps._editors[20].setValue(5000)                          # Timeout
    pump_until(qapp, lambda: fake.expressions["G4"].endswith(",$F$4,0,5000,0)"))

    control = ps._links[13][0].property("control")          # Auto Select Coarse -> $A$12 CheckBox
    assert ps._links[13][1] == "A12"
    control.setChecked(True)
    pump_until(qapp, lambda: fake.values.get("A12") == 1)

    train = ps._editors[18]                                 # Train Event -> Button("Train") in F4
    assert isinstance(train, QPushButton) and train.text() == "Train Event"  # ISVS: named after the parameter
    assert ps._links[18][0].text() == "= $F$4"
    train.click()
    pump_until(qapp, lambda: fake.button_presses == ["F4"])

    assert ps._links[10][1] == "C3"                         # External Region -> EditRegion
    assert ps._links[10][0].isEnabled()

    ps.reject()                                             # Cancel restores expression and value
    pump_until(qapp, lambda: fake.expressions["G4"] == TRAIN_EXPR and fake.values.get("A12") == 0)
    pump_until(qapp, lambda: win.property_sheet is None)
    assert not errors


def test_property_sheet_pick_reference_and_ok(job, qapp):
    win, fake, errors = job
    win.open_property_sheet("G4")
    ps = win.property_sheet
    ps.tree.setCurrentItem(ps._item_for(10))                # External Region
    ps.act_abs.trigger()                                    # cell selection mode: the sheet steps aside
    assert ps.picking and win.sheet.in_selection_mode and not ps.isVisible()
    win.sheet.select_location("B12")
    QTest.keyClick(win.sheet, Qt.Key.Key_Return)            # Enter accepts
    assert ps.args[10] == "$B$12" and not ps.picking
    assert ps.isVisible() and not win.sheet.in_selection_mode
    ps.accept()
    pump_until(qapp, lambda: ",$B$12," in fake.expressions["G4"] and fake.expressions["G4"].count("$B$12") == 2)
    assert not errors


def test_property_sheet_read_only_when_online(job, qapp):
    win, fake, errors = job
    win.open_property_sheet("G4")
    ps = win.property_sheet
    ps.set_permissions(values_ok=True, expression_ok=False)
    assert not ps._editors[20].isEnabled()
    assert ps._links[13][0].isEnabled()


# ---------------------------------------------------------------------------- phase 5
from PySide6.QtCore import QPointF  # noqa: E402

from insight_studio.property_sheet import (  # noqa: E402
    ParamRow,
    fixture_transform,
    is_integer_parameter,
    maximized_region,
    region_spec,
)

LITERAL_EXPR = "TrainPatMaxRedLine($A$0,0,0,0,100,80,440,320,0,0,0,0,0,1,0,4,1,20,0,0,0,0)"


def test_region_spec_and_maximize_math():
    group = ParamRow("Pattern Region", {"kind": "region"})
    group.children = [ParamRow(n, {}, i, in_group=True, parent=group)
                      for i, n in enumerate(["X", "Y", "Width", "Height", "Angle", "Curve"], start=4)]
    spec = region_spec(group)
    assert spec.type == "Region" and spec.keys == {"x": 4, "y": 5, "w": 6, "h": 7, "angle": 8, "curve": 9}
    circle = ParamRow("Region")
    circle.children = [ParamRow(n, {}, i, in_group=True) for i, n in enumerate(["Center X", "Center Y", "Radius"])]
    assert region_spec(circle).type == "Circle"
    fixture = ParamRow("Fixture")
    fixture.children = [ParamRow(n, {}, i, in_group=True) for i, n in enumerate(["X", "Y", "Theta"])]
    assert region_spec(fixture) is None
    g = maximized_region(640, 480)
    assert (g["x"], g["y"], g["w"], g["h"], g["angle"]) == (0, 0, 640, 480, 0)
    g = maximized_region(640, 480, fixture_transform(100, 50, 90))
    # image origin seen from a fixture at (100,50) turned 90° clockwise
    assert (round(g["x"], 6), round(g["y"], 6), round(g["angle"], 6)) == (-50, 100, -90)


def test_integer_parameters():
    assert is_integer_parameter({"name": "Timeout"})
    assert is_integer_parameter({"name": "Number to Sort"})
    assert not is_integer_parameter({"name": "Feature Threshold"})
    assert not is_integer_parameter({"name": "Coarse Granularity"})


@pytest.fixture
def literal_job(job, qapp):
    win, fake, errors = job
    fake.expressions["G5"] = LITERAL_EXPR
    wait(spawn(win.device.refresh_sheet()))
    wait(spawn(win.device.latest_result()))
    pump_until(qapp, lambda: "G5" in win.model.results)
    info = win.catalog.get("TrainPatMaxRedLine")
    info.enable = {"Coarse Granularity": {"param": "Auto Select Coarse", "values": [0]},
                   "Fine Granularity": {"param": "Auto Select Fine", "values": [0]}}
    win.open_property_sheet("G5")
    return win, fake, errors, win.property_sheet


def test_enable_rules_grey_out_parameters(literal_job, qapp):
    win, fake, errors, ps = literal_job
    coarse, fine = ps._editors[15], ps._editors[16]
    assert ps._editors[13].isChecked() and not ps._editors[14].isChecked()
    assert not coarse.isEnabled() and fine.isEnabled()      # Auto Select Coarse on, Fine off
    assert isinstance(ps._editors[17], type(coarse))         # Feature Threshold: 3 decimals like ISVS
    assert coarse.decimals() == 3 and coarse.text() == "4.000"
    ps._editors[13].setChecked(False)
    assert coarse.isEnabled()
    pump_until(qapp, lambda: fake.expressions["G5"] ==
               "TrainPatMaxRedLine($A$0,0,0,0,100,80,440,320,0,0,0,0,0,0,0,4,1,20,0,0,0,0)")
    assert not errors


def test_region_parameter_is_edited_on_the_image(literal_job, qapp):
    win, fake, errors, ps = literal_job
    region_item = ps.tree.topLevelItem(2)
    assert region_item.text(0) == "Pattern Region"
    ps.tree.setCurrentItem(region_item)
    ed = win.image.editor
    assert ed is not None and win._param_edit is ps and win.area._grid_suppressed
    assert (ed.g["x"], ed.g["y"], ed.g["w"], ed.g["h"]) == (100, 80, 440, 320)
    assert ps.act_maximize.isEnabled() and ps.act_graphic.isEnabled()
    ed.move_shape(ed.shapes[0], QPointF(10, 5))              # drag on the image -> numbers in the sheet
    assert ps.args[4:8] == ["110", "85", "440", "320"] and ps._editors[4].value() == 110
    assert region_item.text(1) == "(110,85,440,320,0,0)"
    assert win.image.editor is ed                              # not rebuilt while dragging
    pump_until(qapp, lambda: ",110,85,440,320,0,0," in fake.expressions["G5"])

    ps._editors[1].setValue(50)                                # fixture X: the region moves with it
    assert win.image.editor.root.transform().dx() == 50
    ps._editors[5].setValue(90)                                # typed: the graphic follows
    assert win.image.editor.g["y"] == 90

    ps.act_maximize.trigger()                                  # Maximize Region (image 640x480, fixture X 50)
    assert ps.args[4:10] == ["-50", "0", "640", "480", "0", "0"]

    ps.tree.setCurrentItem(ps.tree.topLevelItem(0))            # another parameter: grid back, no editor
    assert win.image.editor is None and not win.area._grid_suppressed
    ps.tree.setCurrentItem(ps._item_for(6))                    # a child of the region shows it too
    assert win.image.editor is not None
    ps.reject()
    pump_until(qapp, lambda: fake.expressions["G5"] == LITERAL_EXPR)
    pump_until(qapp, lambda: win.image.editor is None and not win.area._grid_suppressed)
    assert not errors


def test_region_with_reference_is_not_graphical(literal_job, qapp):
    win, fake, errors, ps = literal_job
    ps.args[4] = "$B$12"
    ps._populate_keep(4)
    assert win.image.editor is None
    assert "cell references" in ps.desc_text.text()
    assert not ps.act_graphic.isEnabled() and not ps.act_maximize.isEnabled()


def test_region_read_only_when_online(literal_job, qapp):
    win, fake, errors, ps = literal_job
    ps.set_permissions(values_ok=True, expression_ok=False)
    ps.tree.setCurrentItem(ps.tree.topLevelItem(2))
    ed = win.image.editor
    assert ed is not None and not ed.allowed("move") and not ed.allowed("resize")
    assert not ps.act_maximize.isEnabled()


def test_insert_function_into_parameter(literal_job, qapp):
    win, fake, errors, ps = literal_job
    ps.tree.setCurrentItem(ps._item_for(10))                   # External Region (text box)
    box = ps._editors[10]
    box.setFocus()
    box.selectAll()
    assert ps.insert_text("GetRegion()")
    assert box.text() == "GetRegion()" and box.cursorPosition() == len("GetRegion(")


def test_maximize_cell_region(window, qapp):
    win, fake, errors = window
    win._paste_cells({"C5": 'EditRegion($A$0,0,0,0,1,1,1,1,"Region",2)'})
    pump_until(qapp, lambda: cells.editable_graphic(win.model.results.get("C5")) is not None)
    win.sheet.select_location("C5")
    assert win.act_maximize.isEnabled()
    win.act_maximize.trigger()
    pump_until(qapp, lambda: isinstance(fake.values.get("C5"), dict))
    v = fake.values["C5"]
    assert (v["x"], v["y"], v["w"], v["h"]) == (0, 0, 640, 480)
    win.sheet.select_location("A0")
    assert not win.act_maximize.isEnabled()
    assert not errors


def test_edit_masked_region_cell(window, qapp):
    win, fake, errors = window
    win._paste_cells({"C6": 'EditMaskedRegion($A$0,0,0,0,1,1,1,1,1,1,"Mask",2)'})
    pump_until(qapp, lambda: cells.editable_graphic(win.model.results.get("C6")) is not None
               and "C6" in win.model.expressions)
    win.sheet.select_location("C6")
    win.edit_graphic()
    pump_until(qapp, lambda: win.image.editor is not None)
    ed = win.image.editor
    assert ed.masked and len(ed.shapes) == 1
    ed.add_mask(50)
    win.accept_graphic()
    pump_until(qapp, lambda: isinstance(fake.values.get("C6"), dict))
    subs = fake.values["C6"]["subregions"]
    assert [s["add"] for s in subs] == [True, False]
    assert subs[1]["shape"]["h"] == 160 and subs[1]["shape"]["x"] == 144.0
    assert not errors
