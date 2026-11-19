"""Main window: image + spreadsheet editor for In-Sight spreadsheet jobs."""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import Coroutine, Optional

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QImage, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import __version__, cells
from .catalog import Catalog, FunctionInfo, find_help_file
from .cogsocket import CogSocketError
from .device import DeviceError, InSightDevice
from .dialogs import ConnectDialog, DeviceFilesDialog, InsertFunctionDialog, SetValueDialog
from .editors import round_graphic
from .image_view import ImageView
from .qtasync import set_unhandled_error_hook, spawn
from .sheet import RESULT_ROLE, SheetModel, SheetView

log = logging.getLogger(__name__)

JOB_FILTER = "In-Sight job (*.jobx *.job);;All files (*)"
IMAGE_FILTER = "Images (*.bmp *.jpg *.jpeg *.png);;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Insight Studio")
        self.resize(1400, 900)
        self.device = InSightDevice(self)
        self.device.auto_ready = False
        self.catalog = Catalog.load()
        self._result_gen = 0
        self._editing_location: Optional[str] = None
        self._log_traffic = False

        self._build_ui()
        self._build_actions()
        self._connect_device()
        set_unhandled_error_hook(self._on_unhandled_error)
        self._update_actions()
        self._restore_state()

    # ================================================================== UI construction
    def _build_ui(self) -> None:
        self.model = SheetModel(self)
        self.model.expressionEdited.connect(self._commit_expression)

        self.sheet = SheetView()
        self.sheet.setModel(self.model)
        self.sheet.selectionModel().currentChanged.connect(self._on_current_cell)
        self.sheet.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.sheet.pasteRequested.connect(self._paste_cells)
        self.sheet.clearRequested.connect(self._clear_cells)
        self.sheet.contextMenuForCell.connect(self._extend_cell_menu)
        self.sheet.doubleClicked.connect(self._on_cell_double_clicked)

        self.image = ImageView()
        self.image.mouseMovedImage.connect(
            lambda x, y: self.coord_label.setText(f"x {x:.1f}  y {y:.1f}"))

        # formula bar
        self.name_box = QLineEdit()
        self.name_box.setFixedWidth(160)
        self.name_box.setPlaceholderText("Cell or name")
        self.name_box.setToolTip("Type a cell address or name and press Enter to go there")
        self.name_box.returnPressed.connect(self._goto_name_box)
        self.formula = QLineEdit()
        self.formula.setPlaceholderText("Expression (e.g. EditInt(0,255), 'text, A1*2) — Enter to commit, Esc to revert")
        self.formula.returnPressed.connect(self._commit_formula_bar)
        self.formula.installEventFilter(self)
        fx = QLabel("ƒx")
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 2, 4, 2)
        bl.addWidget(self.name_box)
        bl.addWidget(fx)
        bl.addWidget(self.formula, 1)

        self.banner = QLabel()
        self.banner.setStyleSheet("background:#fff3cd;color:#664d03;padding:4px")
        self.banner.setVisible(False)
        self.banner.setWordWrap(True)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.image)
        self.splitter.addWidget(self.sheet)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([520, 340])

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.banner)
        cl.addWidget(bar)
        cl.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        # docks
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        log_box = QWidget()
        ll = QVBoxLayout(log_box)
        ll.setContentsMargins(0, 0, 0, 0)
        self.traffic_check = QCheckBox("Show CogSocket traffic")
        self.traffic_check.toggled.connect(lambda on: setattr(self, "_log_traffic", on))
        ll.addWidget(self.traffic_check)
        ll.addWidget(self.log_view)
        self.log_dock = self._dock("Log", log_box, Qt.DockWidgetArea.BottomDockWidgetArea)

        self.names_list = QListWidget()
        self.names_list.itemActivated.connect(
            lambda it: self.sheet.select_location(it.data(Qt.ItemDataRole.UserRole)))
        self.names_dock = self._dock("Cell names", self.names_list, Qt.DockWidgetArea.RightDockWidgetArea)

        func_box = QWidget()
        fl = QVBoxLayout(func_box)
        fl.setContentsMargins(0, 0, 0, 0)
        self.func_search = QLineEdit()
        self.func_search.setPlaceholderText("Search functions…")
        self.func_list = QListWidget()
        self.func_search.textChanged.connect(self._fill_functions)
        self.func_list.itemActivated.connect(self._insert_function_item)
        self.func_list.setToolTip("Double-click to put the function in the formula bar of the current cell")
        fl.addWidget(self.func_search)
        fl.addWidget(self.func_list)
        self.func_dock = self._dock("Functions", func_box, Qt.DockWidgetArea.RightDockWidgetArea)
        self._fill_functions("")
        self.resizeDocks([self.log_dock], [130], Qt.Orientation.Vertical)
        self.resizeDocks([self.names_dock, self.func_dock], [260, 260], Qt.Orientation.Horizontal)
        self.resizeDocks([self.names_dock, self.func_dock], [180, 400], Qt.Orientation.Vertical)

        # status bar
        self.conn_label = QLabel("Not connected")
        self.state_label = QLabel("")
        self.job_label = QLabel("")
        self.coord_label = QLabel("")
        for w in (self.coord_label, self.job_label, self.state_label, self.conn_label):
            self.statusBar().addPermanentWidget(w)

    def _dock(self, title: str, widget: QWidget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "_"))
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _act(self, text: str, slot, shortcut=None, icon=None, checkable=False, tip=None) -> QAction:
        act = QAction(text, self)
        if icon is not None:
            act.setIcon(self.style().standardIcon(icon) if isinstance(icon, QStyle.StandardPixmap) else icon)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.setCheckable(checkable)
        if tip:
            act.setStatusTip(tip)
            act.setToolTip(tip)
        act.triggered.connect(slot)
        return act

    def _build_actions(self) -> None:
        SP = QStyle.StandardPixmap
        self.act_connect = self._act("&Connect…", self.connect_dialog, "Ctrl+K", SP.SP_DriveNetIcon)
        self.act_disconnect = self._act("&Disconnect", self.disconnect_device, None, SP.SP_DialogCloseButton)
        self.act_upload = self._act("Open Job from PC…", self.upload_job, "Ctrl+O", SP.SP_DialogOpenButton,
                                    tip="Load a .jobx file from this computer into the device")
        self.act_download = self._act("Save Job to PC…", self.download_job, "Ctrl+Shift+S", SP.SP_DialogSaveButton,
                                      tip="Save the device's active job as a .jobx file on this computer")
        self.act_new = self._act("&New Job", self.new_job, "Ctrl+N", SP.SP_FileIcon)
        self.act_open_dev = self._act("Open Job on Device…", self.open_job_on_device)
        self.act_save_dev = self._act("&Save Job on Device", self.save_job_on_device, "Ctrl+S")
        self.act_save_dev_as = self._act("Save Job on Device As…", lambda: self.save_job_on_device(ask=True))
        self.act_quit = self._act("E&xit", self.close, "Ctrl+Q")

        self.act_online = self._act("Online", self.toggle_online, "Ctrl+F8", SP.SP_MediaPlay, checkable=True,
                                    tip="Toggle the device online (run) / offline")
        self.act_live = self._act("Live Video", self.toggle_live, None, SP.SP_MediaSeekForward, checkable=True)
        self.act_trigger = self._act("Trigger", self.trigger, "F5", SP.SP_BrowserReload,
                                     tip="Manual trigger (acquire an image)")
        self.act_load_image = self._act("Load Image…", self.load_image, None, SP.SP_FileDialogContentsView,
                                        tip="Send a BMP/JPEG image to the device as the current image")

        self.act_insert = self._act("Insert Function…", self.insert_function, "Shift+F3",
                                    tip="Choose a spreadsheet function for the current cell")
        self.act_name = self._act("Cell Name…", self.set_cell_name, "Ctrl+Shift+N")
        self.act_value = self._act("Set Value…", self.set_cell_value, "Ctrl+Shift+V")
        self.act_edit_graphic = self._act("Edit Graphic", self.edit_graphic, "Ctrl+G",
                                          tip="Interactively edit the region/shape of an Edit* cell")
        self.act_accept_graphic = self._act("Accept Graphic", self.accept_graphic, "Return", SP.SP_DialogApplyButton)
        self.act_cancel_graphic = self._act("Cancel Graphic", self.cancel_graphic, "Escape", SP.SP_DialogCancelButton)
        self.act_refresh = self._act("Refresh Sheet", self.refresh_sheet, "Ctrl+R")

        self.act_fit = self._act("Fit Image", self.image.fit, "Ctrl+0")
        self.act_zoom_in = self._act("Zoom In", lambda: self.image.zoom(1.25), "Ctrl+=")
        self.act_zoom_out = self._act("Zoom Out", lambda: self.image.zoom(0.8), "Ctrl+-")
        self.act_graphics = self._act("Show Graphics", self.image.set_show_graphics, None, checkable=True)
        self.act_graphics.setChecked(True)
        self.act_help_fn = self._act("Help for Function in Cell", self.help_for_cell, "F1")

        m = self.menuBar().addMenu("&File")
        for a in (self.act_connect, self.act_disconnect, None, self.act_upload, self.act_download, None,
                  self.act_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = self.menuBar().addMenu("&Job")
        for a in (self.act_new, self.act_open_dev, self.act_save_dev, self.act_save_dev_as):
            m.addAction(a)
        m = self.menuBar().addMenu("&Edit")
        for a in (self.act_insert, self.act_name, self.act_value, self.act_edit_graphic, None, self.act_refresh):
            m.addSeparator() if a is None else m.addAction(a)
        m = self.menuBar().addMenu("&Sensor")
        for a in (self.act_online, self.act_live, self.act_trigger, self.act_load_image):
            m.addAction(a)
        m = self.menuBar().addMenu("&View")
        for a in (self.act_fit, self.act_zoom_in, self.act_zoom_out, self.act_graphics):
            m.addAction(a)
        m.addSeparator()
        for d in (self.log_dock, self.names_dock, self.func_dock):
            m.addAction(d.toggleViewAction())
        m = self.menuBar().addMenu("&Help")
        m.addAction(self.act_help_fn)
        m.addAction(self._act("About", self.about))

        tb = QToolBar("Main")
        tb.setObjectName("main_toolbar")
        self.addToolBar(tb)
        for a in (self.act_connect, self.act_disconnect, None, self.act_new, self.act_upload, self.act_download,
                  None, self.act_online, self.act_live, self.act_trigger, self.act_load_image, None,
                  self.act_fit):
            tb.addSeparator() if a is None else tb.addAction(a)

        self.edit_bar = QToolBar("Graphic editing")
        self.edit_bar.setObjectName("edit_toolbar")
        self.edit_label = QLabel()
        self.edit_bar.addWidget(self.edit_label)
        self.edit_bar.addAction(self.act_accept_graphic)
        self.edit_bar.addAction(self.act_cancel_graphic)
        self.addToolBar(self.edit_bar)
        self.edit_bar.setVisible(False)

    # ================================================================== device wiring
    def _connect_device(self) -> None:
        d = self.device
        d.connectedChanged.connect(self._on_connected_changed)
        d.stateChanged.connect(lambda _s: self._update_state())
        d.jobInfoChanged.connect(lambda job: self.job_label.setText(f"Job: {job.get('name') or '(unnamed)'}"))
        d.jobLoadingChanged.connect(self._on_job_loading)
        d.editorAttachedChanged.connect(self._on_editor_attached)
        d.resultChanged.connect(self._on_result)
        d.expressionsChanged.connect(self._on_expressions)
        d.cellNamesChanged.connect(self._on_names)
        d.sheetFormatChanged.connect(self._on_sheet_format)
        d.message.connect(self.log)
        d.traffic.connect(self._on_traffic)

    def run(self, coro: Coroutine, what: str) -> None:
        """Runs a device operation and reports failures to the user."""
        fut = spawn(coro, report_errors=False)

        def done(f) -> None:
            exc = f.exception()
            if exc is not None:
                self._show_error(what, exc)

        fut.add_done_callback(done)

    def _show_error(self, what: str, exc: BaseException) -> None:
        if isinstance(exc, (CogSocketError, DeviceError)):
            text = str(exc)
        else:
            text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            log.error("%s failed:\n%s", what, "".join(traceback.format_exception(exc)))
        self.log(f"ERROR: {what}: {text}")
        QMessageBox.warning(self, "Insight Studio", f"{what} failed:\n\n{text}")

    def _on_unhandled_error(self, exc: BaseException) -> None:
        self.log(f"ERROR: {exc}")
        log.error("Unhandled: %s", "".join(traceback.format_exception(exc)))

    def log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        self.statusBar().showMessage(text, 5000)

    def _on_traffic(self, direction: str, text: str) -> None:
        if self._log_traffic:
            arrow = "→" if direction == "send" else "←"
            self.log_view.appendPlainText(f"{arrow} {text[:2000]}")

    # ================================================================== connection
    def connect_dialog(self) -> None:
        dlg = ConnectDialog(self)
        if dlg.exec() != ConnectDialog.DialogCode.Accepted:
            return
        host, user, password = dlg.values()
        dlg.remember()
        self.conn_label.setText(f"Connecting to {host}…")
        self.log(f"Connecting to {host} as {user}…")

        async def go() -> None:
            await self.device.connect_to(host, user, password)

        self.run(go(), f"Connecting to {host}")

    def disconnect_device(self) -> None:
        self.cancel_graphic()
        self.run(self.device.disconnect_from(), "Disconnect")

    def _on_connected_changed(self, connected: bool) -> None:
        if connected:
            info = self.device.info
            self.conn_label.setText(f"{info.name or self.device.host} · {info.model} · {info.firmware} "
                                    f"· {self.device.access_level}")
            self.image.set_coordinate_mode(info.uses_xy)
            self.setWindowTitle(f"Insight Studio — {info.name or self.device.host}")
        else:
            self.conn_label.setText("Not connected")
            self.state_label.setText("")
            self.job_label.setText("")
            self.model.clear()
            self.image.clear()
            self.names_list.clear()
            self.setWindowTitle("Insight Studio")
            self._end_graphic_edit_ui()
        self._update_state()
        self._update_actions()

    def _update_state(self) -> None:
        d = self.device
        if not d.connected:
            self.act_online.setChecked(False)
            self.act_live.setChecked(False)
            return
        self.act_online.setChecked(d.online)
        self.act_live.setChecked(d.live_mode)
        blockers = [k for k in ("nativeOnline", "discreteOnline", "ffpOnline") if d.state.get(k) is False]
        text = "ONLINE" if d.online else "Offline"
        if d.soft_online and not d.online and blockers:
            text += f" (blocked by {', '.join(blockers)})"
        if d.live_mode:
            text += " · Live"
        self.state_label.setText(text)
        self.state_label.setStyleSheet("color: #198754; font-weight: bold" if d.online else "")
        self._update_actions()

    def _on_job_loading(self, loading: bool) -> None:
        self.log("Job loading…" if loading else "Job loaded")
        if loading:
            self.model.clear()

    def _on_editor_attached(self, attached: bool) -> None:
        self.model.read_only = attached
        self.banner.setText("An editor (In-Sight Vision Suite / Explorer / VisionView) is attached to this "
                            "device. Editing is disabled while it is connected.")
        self.banner.setVisible(attached)
        self._update_actions()

    def _update_actions(self) -> None:
        d = self.device
        connected = d.connected
        writable = connected and not d.read_only
        offline = writable and not d.online
        editing = self._editing_location is not None
        self.act_connect.setEnabled(not connected)
        self.act_disconnect.setEnabled(connected)
        for a in (self.act_upload, self.act_new, self.act_open_dev):
            a.setEnabled(offline and not editing)
        for a in (self.act_download, self.act_save_dev, self.act_save_dev_as, self.act_refresh):
            a.setEnabled(connected and not editing)
        self.act_online.setEnabled(writable and not editing)
        self.act_live.setEnabled(offline and not editing)
        self.act_trigger.setEnabled(writable and not d.live_mode and not editing)
        self.act_load_image.setEnabled(offline and not editing)
        for a in (self.act_insert, self.act_name):
            a.setEnabled(offline and not editing)
        loc = self.sheet.current_location()
        result = self.model.results.get(loc) if loc else None
        self.act_value.setEnabled(writable and cells.is_value_editable(result) and not editing)
        self.act_edit_graphic.setEnabled(writable and cells.editable_graphic(result) is not None and not editing)
        self.act_accept_graphic.setEnabled(editing)
        self.act_cancel_graphic.setEnabled(editing)
        self.formula.setReadOnly(not offline or editing)
        self.model.read_only = not offline or editing

    # ================================================================== results
    def _on_result(self, result: dict) -> None:
        self.model.set_results(self.device.cell_results())
        self._result_gen += 1
        gen = self._result_gen
        self.run(self._render_result(result, gen), "Displaying result")
        self._update_actions()
        status = {1: "Pass", 2: "Fail", 3: "Warn"}.get(result.get("jobStatus"))
        if status:
            self.statusBar().showMessage(f"Result {result.get('id')}: {status}", 3000)

    async def _render_result(self, result: dict, gen: int) -> None:
        try:
            view = result.get("acqImageView") or {}
            layers = view.get("layers") or []
            main_img: Optional[QImage] = None
            extra: list = []
            graphics: list[dict] = []
            svgs: list[bytes] = []
            for layer in layers:
                t = layer.get("$type")
                if t == "ImageLayer" and layer.get("url"):
                    data = await self.device.http_get(layer["url"])
                    img = QImage.fromData(data)
                    if img.isNull():
                        self.log(f"Could not decode image from {layer['url']}")
                        continue
                    tr = layer.get("transform") or {}
                    if main_img is None and not tr:
                        main_img = img
                    else:
                        extra.append((img, float(tr.get("tx", 0)), float(tr.get("ty", 0))))
                elif t == "GraphicsLayer":
                    if isinstance(layer.get("graphics"), list):
                        graphics.extend(layer["graphics"])
                    elif layer.get("url"):
                        try:
                            body = await self.device.http_get(layer["url"])
                            parsed = json.loads(body.decode("utf-8") or "[]")
                            if isinstance(parsed, dict):
                                parsed = parsed.get("graphics") or parsed.get("body") or []
                            graphics.extend(parsed if isinstance(parsed, list) else [])
                        except (ValueError, DeviceError) as e:
                            self.log(f"Graphics not retrieved: {e}")
                elif t == "SVGLayer" and layer.get("url"):
                    try:
                        svgs.append(await self.device.http_get(layer["url"]))
                    except DeviceError as e:
                        self.log(f"SVG layer not retrieved: {e}")
            if gen != self._result_gen:
                return  # a newer result arrived meanwhile
            if main_img is not None:
                self.image.set_image(main_img)
            self.image.set_extra_images(extra)
            self.image.set_svg_layers(svgs)
            self.image.set_graphics(graphics)
        finally:
            # Ask for the next result once this one has been drawn (throttles the stream).
            if self.device.connected and gen == self._result_gen:
                try:
                    self.device.ready()
                except (RuntimeError, DeviceError):
                    pass  # socket went away (e.g. during shutdown)

    def _on_expressions(self, exprs: dict) -> None:
        self.model.set_expressions(exprs)
        self._on_current_cell()

    def _on_names(self, names: dict) -> None:
        self.model.set_names(names)
        self.names_list.clear()
        for loc, name in sorted(names.items(), key=lambda kv: kv[1].lower()):
            item = QListWidgetItem(f"{name}    {loc}")
            item.setData(Qt.ItemDataRole.UserRole, loc)
            self.names_list.addItem(item)
        self._on_current_cell()

    def _on_sheet_format(self, fmt: dict) -> None:
        widths, heights, formats = cells.parse_sheet_format(fmt)
        self.model.set_formats(formats)
        self.sheet.apply_sheet_format(widths, heights)

    # ================================================================== sheet editing
    def _on_current_cell(self, *_args) -> None:
        loc = self.sheet.current_location()
        if not loc:
            return
        name = self.model.names.get(loc)
        self.name_box.setText(f"{loc}  {name}" if name else loc)
        self.formula.setText(self.model.expressions.get(loc, ""))
        self.formula.setProperty("location", loc)
        self._update_actions()

    def _on_selection_changed(self, *_args) -> None:
        self.image.set_selected_sources(set(self.sheet.selected_locations()))

    def _goto_name_box(self) -> None:
        text = self.name_box.text().strip().split()[0] if self.name_box.text().strip() else ""
        loc = text.upper() if cells.parse_address(text) else self.model.location_of_name(text)
        if loc:
            self.sheet.select_location(loc.replace("$", ""))
            self.sheet.setFocus()
        else:
            self.log(f"No cell named '{text}'")

    def _commit_formula_bar(self) -> None:
        loc = self.formula.property("location") or self.sheet.current_location()
        if not loc or self.formula.isReadOnly():
            return
        text = self.formula.text()
        if text == self.model.expressions.get(loc, ""):
            self.sheet.setFocus()
            return
        self.model.mark_pending(loc, text)
        self._commit_expression(loc, text)
        self.sheet.setFocus()

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        if obj is self.formula and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._on_current_cell()
            self.sheet.setFocus()
            return True
        return super().eventFilter(obj, event)

    def _commit_expression(self, loc: str, expr: str) -> None:
        async def go() -> None:
            try:
                await self.device.set_cell_expression(loc, expr)
                self.log(f"{loc} ← {expr}" if expr else f"{loc} cleared")
            finally:
                self.model.pending.pop(loc, None)
                self.model.set_expressions(self.device.expressions)

        self.run(go(), f"Setting {loc}")

    def _paste_cells(self, items: dict) -> None:
        if self.model.read_only:
            return
        for loc, expr in items.items():
            self.model.mark_pending(loc, expr)

        async def go() -> None:
            try:
                await self.device.set_cell_expressions(items)
                self.log(f"Pasted {len(items)} cell(s)")
            finally:
                self.model.clear_pending()

        self.run(go(), "Paste")

    def _clear_cells(self, locations: list) -> None:
        if self.model.read_only:
            return
        self._paste_cells({loc: "" for loc in locations})

    def _on_cell_double_clicked(self, index) -> None:
        result = self.model.data(index, RESULT_ROLE)
        if cells.editable_graphic(result) and not self.model.read_only:
            self.edit_graphic()

    def _extend_cell_menu(self, loc: str, menu: QMenu) -> None:
        menu.addAction(self.act_insert)
        menu.addAction(self.act_name)
        if self.act_value.isEnabled():
            menu.addAction(self.act_value)
        if self.act_edit_graphic.isEnabled():
            menu.addAction(self.act_edit_graphic)
        fn = cells.function_name(self.model.expressions.get(loc, ""))
        if fn and self.catalog.get(fn):
            menu.addAction(f"Help for {fn}", self.help_for_cell)

    def refresh_sheet(self) -> None:
        async def go() -> None:
            await self.device.refresh_sheet()
            await self.device.latest_result()

        self.run(go(), "Refresh")

    # ------------------------------------------------------------------ functions
    def _fill_functions(self, text: str) -> None:
        self.func_list.clear()
        for f in self.catalog.search(text):
            item = QListWidgetItem(f.name)
            item.setToolTip(f.signature)
            item.setData(Qt.ItemDataRole.UserRole, f)
            self.func_list.addItem(item)

    def _insert_function_item(self, item: QListWidgetItem) -> None:
        self._put_function_in_formula(item.data(Qt.ItemDataRole.UserRole))

    def insert_function(self) -> None:
        loc = self.sheet.current_location()
        if not loc:
            return
        dlg = InsertFunctionDialog(self.catalog, loc, self)
        if dlg.exec() == InsertFunctionDialog.DialogCode.Accepted and dlg.selected():
            self._put_function_in_formula(dlg.selected())

    def _put_function_in_formula(self, f: FunctionInfo) -> None:
        if self.formula.isReadOnly():
            self.log("Go offline to edit the job")
            return
        text = f.insert_text()
        self.formula.setText(text)
        self.formula.setFocus()
        if not f.template and text.endswith("()"):
            self.formula.setCursorPosition(len(text) - 1)
        self.statusBar().showMessage(f"{f.signature} — press Enter to write it to the cell", 10000)

    def help_for_cell(self) -> None:
        loc = self.sheet.current_location()
        fn = cells.function_name(self.model.expressions.get(loc or "", ""))
        info = self.catalog.get(fn) if fn else None
        if not info:
            self.log("No function in the current cell")
            return
        path = find_help_file(info)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, "Help", f"{info.signature}\n\n(The In-Sight Vision Suite help is "
                                                  "not installed on this computer.)")

    # ------------------------------------------------------------------ names / values
    def set_cell_name(self) -> None:
        loc = self.sheet.current_location()
        if not loc:
            return
        current = self.model.names.get(loc, "")
        name, ok = QInputDialog.getText(self, "Cell name", f"Symbolic name for {loc}:", text=current)
        if not ok or not name.strip() or name.strip() == current:
            return
        name = name.strip()
        if cells.looks_like_address(name):
            QMessageBox.warning(self, "Cell name", "A cell name must not look like a cell address.")
            return
        self.run(self.device.set_cell_name(loc, name), f"Naming {loc}")

    def set_cell_value(self) -> None:
        loc = self.sheet.current_location()
        result = self.model.results.get(loc or "")
        if not loc or not cells.is_value_editable(result):
            return
        dlg = SetValueDialog(loc, result, self)
        if dlg.exec() == SetValueDialog.DialogCode.Accepted:
            self.run(self.device.set_cell_value(loc, dlg.value()), f"Setting value of {loc}")

    # ------------------------------------------------------------------ graphic editing
    def edit_graphic(self) -> None:
        loc = self.sheet.current_location()
        graphic = cells.editable_graphic(self.model.results.get(loc or ""))
        if not loc or graphic is None:
            return

        async def go() -> None:
            target = graphic
            try:
                editing = await self.device.begin_edit(loc)
                # API 3.0 devices return an "Editing<Type>" object whose data is the graphic.
                if isinstance(editing, dict) and isinstance(editing.get("data"), dict) \
                        and editing["data"].get("$type") == graphic.get("$type"):
                    target = editing["data"]
            except CogSocketError as e:
                self.log(f"beginEdit not available ({e}); editing locally")
            try:
                self.image.begin_edit(target)
            except ValueError as e:
                await self.device.end_edit()
                raise DeviceError(str(e)) from e
            self._editing_location = loc
            self.edit_label.setText(f"  Editing {graphic.get('$type')} in {loc}: drag the shape or its "
                                    "handles, then Accept  ")
            self.edit_bar.setVisible(True)
            self._update_actions()

        self.run(go(), f"Editing graphic {loc}")

    def accept_graphic(self) -> None:
        loc = self._editing_location
        editor = self.image.editor
        if not loc or editor is None:
            return
        value = round_graphic(editor.value)

        async def go() -> None:
            try:
                await self.device.set_cell_value(loc, value)
                self.log(f"{loc} graphic updated")
            finally:
                await self._finish_edit()

        self.run(go(), f"Updating {loc}")

    def cancel_graphic(self) -> None:
        if self._editing_location is None:
            return
        self.run(self._finish_edit(), "Cancel edit")

    async def _finish_edit(self) -> None:
        self._end_graphic_edit_ui()
        if self.device.connected:
            try:
                await self.device.end_edit()
            except CogSocketError as e:
                self.log(f"endEdit: {e}")

    def _end_graphic_edit_ui(self) -> None:
        self.image.end_edit()
        self._editing_location = None
        self.edit_bar.setVisible(False)
        self._update_actions()

    # ================================================================== sensor
    def toggle_online(self) -> None:
        want = not self.device.online
        self.act_online.setChecked(self.device.online)
        self.run(self.device.set_soft_online(want), "Going online" if want else "Going offline")

    def toggle_live(self) -> None:
        want = not self.device.live_mode
        self.act_live.setChecked(self.device.live_mode)
        self.run(self.device.set_live_mode(want), "Live video")

    def trigger(self) -> None:
        self.run(self.device.trigger(), "Trigger")

    def load_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load image into the device", self._last_dir(), IMAGE_FILTER)
        if not path:
            return
        self._remember_dir(path)
        p = Path(path)
        data = p.read_bytes()
        ctype = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/bmp"
        if p.suffix.lower() not in (".jpg", ".jpeg", ".bmp"):
            img = QImage(path)
            if img.isNull():
                QMessageBox.warning(self, "Load image", "Unsupported image file.")
                return
            from PySide6.QtCore import QBuffer, QIODevice

            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, "BMP")
            data, ctype = bytes(buf.data().data()), "image/bmp"
        self.run(self.device.load_image(data, ctype, p.name), f"Loading image {p.name}")

    # ================================================================== jobs
    def _confirm_replace_job(self) -> bool:
        return QMessageBox.question(
            self, "Replace job",
            "This replaces the active job on the device. Unsaved changes on the device will be lost.\n\n"
            "Continue?") == QMessageBox.StandardButton.Yes

    def new_job(self) -> None:
        if self._confirm_replace_job():
            self.run(self.device.create_new_job(), "New job")

    def upload_job(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open job", self._last_dir(), JOB_FILTER)
        if not path or not self._confirm_replace_job():
            return
        self._remember_dir(path)
        p = Path(path)
        data = p.read_bytes()

        async def go() -> None:
            await self.device.upload_job(p.name, data)
            self.log(f"Loaded {p.name} ({len(data)} bytes) into the device")

        self.run(go(), f"Opening {p.name}")

    def download_job(self) -> None:
        default = self.device.job.get("name") or "job.jobx"
        if not str(default).lower().endswith((".jobx", ".job")):
            default = f"{default}.jobx"
        path, _ = QFileDialog.getSaveFileName(self, "Save job to this computer",
                                              str(Path(self._last_dir()) / default), JOB_FILTER)
        if not path:
            return
        self._remember_dir(path)
        p = Path(path)

        async def go() -> None:
            # saveJobData renames the device's active job to the name it is given, so pass the
            # current name to leave the device unchanged.
            data = await self.device.download_job(str(self.device.job.get("name") or p.name))
            p.write_bytes(data)
            self.log(f"Saved {p} ({len(data)} bytes)")

        self.run(go(), f"Saving {p.name}")

    def open_job_on_device(self) -> None:
        async def go() -> None:
            files = await self.device.list_files()
            jobs = [f for f in files if str(f.get("name", "")).lower().endswith((".job", ".jobx"))
                    or int(f.get("attributes", 1)) & 8]
            dlg = DeviceFilesDialog(jobs, save=False, parent=self)
            if dlg.exec() != DeviceFilesDialog.DialogCode.Accepted or not dlg.filename():
                return
            if not self._confirm_replace_job():
                return
            await self.device.load_job(dlg.filename())
            self.log(f"Loading {dlg.filename()} on the device…")

        self.run(go(), "Open job on device")

    def save_job_on_device(self, ask: bool = False) -> None:
        name = str(self.device.job.get("name") or "")

        async def go() -> None:
            target = name
            if ask or not target:
                files = await self.device.list_files()
                dlg = DeviceFilesDialog(files, save=True, default_name=target or "job.jobx", parent=self)
                if dlg.exec() != DeviceFilesDialog.DialogCode.Accepted or not dlg.filename():
                    return
                target = dlg.filename()
            await self.device.save_job(target)
            self.log(f"Saved job as {target} on the device")

        self.run(go(), "Save job on device")

    # ================================================================== misc
    def _last_dir(self) -> str:
        return str(QSettings().value("paths/last_dir", str(Path.home())))

    def _remember_dir(self, path: str) -> None:
        QSettings().setValue("paths/last_dir", str(Path(path).parent))

    def about(self) -> None:
        QMessageBox.about(
            self, "About Insight Studio",
            f"<b>Insight Studio {__version__}</b><br>Spreadsheet job editor for Cognex In-Sight devices, "
            "built on the public In-Sight HMI API (Web SDK) and PySide6.<br><br>"
            "Not affiliated with or endorsed by Cognex. In-Sight is a trademark of Cognex Corporation.")

    def _restore_state(self) -> None:
        s = QSettings()
        geo = s.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        st = s.value("window/state")
        if st is not None:
            self.restoreState(st)
        sp = s.value("window/splitter")
        if sp is not None:
            self.splitter.restoreState(sp)

    def closeEvent(self, event) -> None:
        s = QSettings()
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/state", self.saveState())
        s.setValue("window/splitter", self.splitter.saveState())
        if self.device.connected:
            spawn(self.device.disconnect_from())
        super().closeEvent(event)
