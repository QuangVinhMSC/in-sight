"""Smoke test of the main window against the fake device (offscreen)."""

import pytest
from PySide6.QtCore import QDeadlineTimer, QSettings

from insight_studio import cells
from insight_studio.devtools.fake_insight import FakeInSight
from insight_studio.main_window import MainWindow
from insight_studio.qtasync import wait


def pump_until(qapp, cond, timeout_ms=4000):
    deadline = QDeadlineTimer(timeout_ms)
    while not cond():
        if deadline.hasExpired():
            raise TimeoutError("condition not met")
        qapp.processEvents()


@pytest.fixture
def window(qapp, tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    fake = FakeInSight(0)
    win = MainWindow()
    win.show()
    errors = []
    win._show_error = lambda what, exc: errors.append(f"{what}: {exc}")
    wait(win.device.connect_to(fake.host, "admin", ""))
    pump_until(qapp, lambda: not win.image._pixmap.pixmap().isNull())
    yield win, fake, errors
    win.close()
    fake.tcp.close()


def test_connect_shows_image_and_sheet(window, qapp):
    win, fake, errors = window
    assert win.model.expressions["A0"] == "AcquireImage()"
    idx = win.model.index(0, 0)
    assert win.model.data(idx) == "Image"
    assert win.image._pixmap.pixmap().width() == 640
    assert win.names_list.count() == 1
    assert not errors


def test_formula_bar_commit(window, qapp):
    win, fake, errors = window
    win.sheet.select_location("B3")
    win.formula.setText("EditInt(0,10)")
    win._commit_formula_bar()
    pump_until(qapp, lambda: win.model.expressions.get("B3") == "EditInt(0,10)")
    pump_until(qapp, lambda: "B3" in win.model.results)
    assert fake.expressions["B3"] == "EditInt(0,10)"
    win.sheet.select_location("B3")
    assert win.act_value.isEnabled()
    assert not errors


def test_copy_paste_shifts_references(window, qapp):
    win, fake, errors = window
    win._paste_cells({"A1": "5", "B1": "A1*2"})
    pump_until(qapp, lambda: fake.expressions.get("B1") == "A1*2")
    win.sheet.select_location("B1")
    win.sheet.copy_selection()
    win.sheet.select_location("B2")
    win.sheet.paste()
    pump_until(qapp, lambda: fake.expressions.get("B2") == "A2*2")
    assert not errors


def test_edit_region_graphic(window, qapp):
    win, fake, errors = window
    win._paste_cells({"C5": 'EditRegion($A$0,0,0,0,1,1,1,1,"Region",2)'})
    pump_until(qapp, lambda: cells.editable_graphic(win.model.results.get("C5")) is not None)
    win.sheet.select_location("C5")
    assert win.act_edit_graphic.isEnabled()
    win.edit_graphic()
    pump_until(qapp, lambda: win.image.editor is not None)
    ed = win.image.editor
    ed._move_by(type(ed.handles[0].pos())(10, 20))
    ed._region_size(type(ed.handles[0].pos())(400, 300))
    win.accept_graphic()
    pump_until(qapp, lambda: isinstance(fake.values.get("C5"), dict))
    v = fake.values["C5"]
    assert (v["x"], v["y"]) == (110.0, 100.0)
    assert (v["w"], v["h"]) == (290.0, 200.0)
    assert v["$type"] == "Region"
    pump_until(qapp, lambda: win.image.editor is None)
    pump_until(qapp, lambda: any(str(m.get("path", "")).endswith("/endEdit") for m in fake.received))
    assert not errors


def test_online_disables_editing(window, qapp):
    win, fake, errors = window
    win.toggle_online()
    pump_until(qapp, lambda: win.device.online)
    pump_until(qapp, lambda: win.formula.isReadOnly())
    assert not win.act_insert.isEnabled()
    win.toggle_online()
    pump_until(qapp, lambda: not win.device.online)
    assert not win.formula.isReadOnly()
    assert not errors


def test_job_roundtrip_through_pc(window, qapp, tmp_path, monkeypatch):
    win, fake, errors = window
    win._paste_cells({"D1": "'saved"})
    pump_until(qapp, lambda: fake.expressions.get("D1") == "'saved")
    target = tmp_path / "my.jobx"
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    win.download_job()
    pump_until(qapp, lambda: target.exists() and target.stat().st_size > 0)
    fake.reset_job()
    win.upload_job()
    pump_until(qapp, lambda: fake.expressions.get("D1") == "'saved")
    pump_until(qapp, lambda: win.model.expressions.get("D1") == "'saved")
    assert not errors
