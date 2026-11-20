"""ISVS look & layout (phase 1): toolbars, overlay/split view, image display modes, session title."""

from conftest import pump_until
from PySide6.QtGui import QColor, QImage

from insight_studio import cells, icons
from insight_studio.image_view import TEXT_FIXED, TEXT_SCALE, saturation_mask
from insight_studio.workspace import CELL_ALPHA_LEVELS, DEFAULT_TRANSPARENCY


def test_isvs_tooltips_and_shortcuts(window):
    win, _fake, errors = window
    assert win.act_new.toolTip() == "New Job (Ctrl+N)"
    assert win.act_save_as.shortcut().toString() == "F12"
    assert win.act_trigger.toolTip() == "Trigger (F5)"
    assert win.act_online.toolTip().startswith("Go Online (Ctrl+F8)")
    assert win.act_zoom_in.toolTip() == "Zoom In (Shift+Add)"
    assert win.act_change_split.shortcut().toString() == "Shift+F7"
    assert win.act_show_grid.shortcut().toString() == "Shift+F6"
    assert win.act_graphics.shortcut().toString() == "Ctrl+Shift+G"
    assert win.act_insert.shortcut().toString() == "Ctrl+Shift+F"
    assert win.act_edit_graphic.shortcut().toString() == "F9"
    # formats are read-only through the SDK: the formatting tools stay disabled
    assert not win.act_bold.isEnabled() and "read" in win.act_bold.toolTip()
    assert not win.font_box.isEnabled()
    assert not errors


def test_all_toolbar_icons_render():
    for name in icons.names():
        assert not icons.icon(name).pixmap(16, 16).isNull(), name


def test_session_tab_and_status(window, qapp):
    win, fake, errors = window
    pump_until(qapp, lambda: win.session_tabs.count() == 1)
    assert win.session_tabs.tabText(0) == "untitled@fake-insight"
    assert win.windowTitle().startswith("untitled@fake-insight")
    assert win.online_box.text() == "Offline"
    assert win.user_label.text() == "admin"
    assert win.health_labels["Model"].text() == "FAKE-IS2800"
    win.disconnect_device()
    pump_until(qapp, lambda: win.session_tabs.count() == 0)
    assert win.online_box.text() == "Not connected"
    assert not errors


def test_overlay_is_default_and_view_toggles(window, qapp):
    win, _fake, errors = window
    area = win.area
    assert area.overlay and area.grid_visible()
    assert win.sheet.cell_alpha == CELL_ALPHA_LEVELS[DEFAULT_TRANSPARENCY] < 255
    assert win.sheet.geometry() == win.image.geometry()  # grid drawn over the image

    win.act_more_transparent.trigger()
    assert win.sheet.cell_alpha == CELL_ALPHA_LEVELS[DEFAULT_TRANSPARENCY + 1]
    win.act_less_transparent.trigger()
    win.act_less_transparent.trigger()
    assert win.sheet.cell_alpha == 255
    assert not win.act_less_transparent.isEnabled()

    win.act_show_grid.trigger()  # Show Pixel Values mode
    assert not area.grid_visible() and win.image.isVisible()
    win.act_show_grid.trigger()
    assert area.grid_visible()

    win.act_change_split.trigger()  # split: image above an opaque grid
    assert not area.overlay and win.act_change_split.isChecked()
    assert win.sheet.cell_alpha == 255
    assert win.image.geometry().bottom() < win.sheet.geometry().top()
    assert not win.act_show_grid.isEnabled()
    assert not win.act_more_transparent.isEnabled()
    win.act_change_split.trigger()
    assert area.overlay and win.sheet.cell_alpha == CELL_ALPHA_LEVELS[area.transparency]
    assert not errors


def test_view_state_is_restored(window, qapp):
    win, _fake, _errors = window
    win.act_change_split.trigger()
    state = win.area.save_state()
    win.act_change_split.trigger()
    win.area.restore_state(state)
    assert not win.area.overlay


def test_image_zoom_modes(window, qapp):
    win, _fake, errors = window
    img = win.image
    assert img.zoom_mode == "fit" and win.act_fit.isChecked()
    win.act_zoom_1to1.trigger()
    assert img.zoom_mode == "1:1" and abs(img.scale_factor() - 1.0) < 1e-9
    assert win.act_zoom_1to1.isChecked() and not win.act_fit.isChecked()
    win.act_zoom_fill.trigger()
    vp = img.viewport().rect()
    shown = img.transform().mapRect(img.sceneRect())
    assert shown.width() >= vp.width() - 2 and shown.height() >= vp.height() - 2
    win.act_zoom_in.trigger()
    assert img.zoom_mode == "" and not win.act_zoom_fill.isChecked()
    win.act_rotate.trigger()
    assert img.rotation == 90
    win.act_fit.trigger()
    shown = img.transform().mapRect(img.sceneRect())
    assert shown.width() <= vp.width() and shown.height() <= vp.height()
    assert not errors


def test_pixel_values_text(window):
    win, _fake, _errors = window
    img = win.image
    text = img.pixel_text(10.4, 20.7)
    assert text.startswith("Approximate (") and "@(10,20) = " in text
    win.act_zoom_1to1.trigger()
    assert not img.pixel_text(10, 20).startswith("Approximate")
    assert img.pixel_text(-1, 5) == ""


def test_saturation_mask_marks_low_and_high_pixels():
    src = QImage(4, 1, QImage.Format.Format_RGB32)
    for x, c in enumerate([(0, 0, 0), (128, 128, 128), (250, 10, 10), (5, 5, 5)]):
        src.setPixelColor(x, 0, QColor(*c))
    mask = saturation_mask(src)
    assert [mask.pixelIndex(x, 0) for x in range(4)] == [2, 0, 1, 2]
    assert QColor.fromRgba(mask.color(1)).red() == 255 and QColor.fromRgba(mask.color(2)).blue() == 255


def test_show_saturation_and_text_scale(window, qapp):
    win, _fake, errors = window
    win.act_saturation.trigger()
    assert win.image._saturation.isVisible() and not win.image._saturation.pixmap().isNull()
    win.text_scale_actions[TEXT_SCALE].trigger()
    assert win.image.text_scale_mode == TEXT_SCALE
    win.text_scale_actions[TEXT_FIXED].trigger()
    assert win.image.text_scale_mode == TEXT_FIXED
    assert not errors


def test_grid_size(window):
    win, _fake, _errors = window
    win.grid_size.setCurrentIndex(win.grid_size.findText("200%"))
    win.grid_size.activated.emit(win.grid_size.currentIndex())
    assert win.sheet.columnWidth(5) == 128 and win.sheet.rowHeight(5) == 40
    win.sheet.set_zoom(1.0)
    assert win.sheet.columnWidth(5) == 64 and win.sheet.rowHeight(5) == 20


def test_accept_cancel_formula_bar(window, qapp):
    win, fake, errors = window
    win.sheet.select_location("C2")
    assert not win.act_accept.isEnabled()
    win.formula.setText("'hello")
    win.formula.textEdited.emit("'hello")
    assert win.act_accept.isEnabled() and win.act_cancel.isEnabled()
    win.act_cancel.trigger()
    assert win.formula.text() == "" and not win.act_accept.isEnabled()
    win.formula.setText("'hello")
    win.formula.textEdited.emit("'hello")
    win.act_accept.trigger()
    pump_until(qapp, lambda: fake.expressions.get("C2") == "'hello")
    assert not errors


def test_graphic_editing_hides_overlaid_grid(window, qapp):
    win, fake, errors = window
    win._paste_cells({"C5": 'EditRegion($A$0,0,0,0,1,1,1,1,"Region",2)'})
    pump_until(qapp, lambda: cells.editable_graphic(win.model.results.get("C5")) is not None)
    win.sheet.select_location("C5")
    win.act_edit_graphic.trigger()
    pump_until(qapp, lambda: win.image.editor is not None)
    assert not win.area.grid_visible()
    assert "Interactive Graphics Mode" in win.area.pixel_strip.text()
    assert win.act_accept.shortcut().toString() == "Return"
    win.act_cancel.trigger()
    pump_until(qapp, lambda: win.image.editor is None)
    assert win.area.grid_visible() and win.area.pixel_strip.text() == ""
    assert win.act_accept.shortcut().isEmpty()
    assert not errors


def test_repeating_trigger(window, qapp, monkeypatch):
    win, fake, errors = window
    import insight_studio.main_window as mw

    win._repeat_timer.setInterval(10)
    start = win.device.result.get("id")
    win.act_repeat.trigger()
    pump_until(qapp, lambda: (win.device.result.get("id") or 0) >= (start or 0) + 3)
    win.act_repeat.trigger()
    assert not win.act_repeat.isChecked() and not win._repeat_timer.isActive()
    assert mw.REPEAT_TRIGGER_MS == 500
    assert not errors


def test_insert_function_on_function_cell_opens_property_sheet(window, qapp, monkeypatch):
    from insight_studio.functions_ui import InsertFunctionDialog
    from insight_studio.qtasync import spawn, wait

    win, fake, errors = window
    fake.expressions["B1"] = "EditInt(0,100)"
    wait(spawn(win.device.refresh_sheet()))
    pump_until(qapp, lambda: win.model.expressions.get("B1"))
    win.sheet.select_location("B1")
    win.act_insert.trigger()
    assert win.property_sheet is not None and win.property_sheet.isVisible()
    win.property_sheet.reject()
    # A0 holds AcquireImage(), which has no property sheet: the Insert Function dialog opens
    if win.catalog.get("AcquireImage"):  # known to have no inputs (needs the generated catalog)
        opened = []
        monkeypatch.setattr(InsertFunctionDialog, "exec", lambda dlg: opened.append(dlg) or 0)
        win.sheet.select_location("A0")
        win.act_insert.trigger()
        assert opened
    assert not errors


def test_save_image_as(window, tmp_path, monkeypatch):
    win, _fake, _errors = window
    from PySide6.QtWidgets import QFileDialog

    target = tmp_path / "shot"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "PNG (*.png)"))
    assert win.act_save_image.isEnabled()
    win.act_save_image.trigger()
    saved = tmp_path / "shot.png"
    assert saved.exists() and QImage(str(saved)).width() == 640
