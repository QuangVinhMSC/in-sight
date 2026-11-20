"""Main window: image + spreadsheet editor for In-Sight spreadsheet jobs."""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import Coroutine, Optional

from PySide6.QtCore import QKeyCombination, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QImage, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, cells, icons
from . import sheet_ops as ops
from .cell_dialogs import FindDialog, InsertDeleteDialog
from .catalog import Catalog, Category, FunctionInfo, default_expression, editor_versions, find_help_file, help_file
from .property_sheet import PropertySheet, is_training_function, split_call
from .cell_controls import SheetDelegate
from .completion import ExpressionLineEdit, FunctionCompleter, functions_in_expressions
from .cogsocket import CogSocketError
from .device import DeviceError, InSightDevice
from .dialogs import ConnectDialog, DeviceFilesDialog
from .functions_ui import FunctionsPanel, InsertFunctionDialog
from .editors import edit_flags, round_graphic
from .image_view import TEXT_FIXED, TEXT_SCALE_MODES, ImageView
from .qtasync import Future, set_unhandled_error_hook, spawn
from .sheet import RESULT_ROLE, SheetModel, SheetView
from .sheet_ops import CellState
from .workspace import ImageSheetArea

log = logging.getLogger(__name__)

JOB_FILTER = "In-Sight job (*.jobx *.job);;All files (*)"
IMAGE_FILTER = "Images (*.bmp *.jpg *.jpeg *.png);;All files (*)"
SAVE_IMAGE_FILTER = "Bitmap (*.bmp);;JPEG (*.jpg);;PNG (*.png)"
APP_NAME = "Insight Studio"
UNSAVED_JOB = "[Unsaved Job]"
REPEAT_TRIGGER_MS = 500  # ISVS Repeating Trigger default interval
GRID_SIZES = [50, 75, 100, 125, 150, 200]
NOT_YET = "Not implemented yet"
NO_SDK = "Not available through the In-Sight HMI API"
NO_FORMAT = "Cell formats can be read but not changed through the In-Sight HMI API"
NO_COMMENT = "Cell comments are not available through the In-Sight HMI API"
NO_PROTECT = "Cell protection (IP licensing) is not available through the In-Sight HMI API"
NO_MULTI = "This command cannot be used on multiple selections."


class MainWindow(QMainWindow):
    STATE_VERSION = 2  # bump when the dock/toolbar layout changes

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.icon("app"))
        self.resize(1400, 900)
        self.device = InSightDevice(self)
        self.device.auto_ready = False
        self.catalog = Catalog.load()
        self._result_gen = 0
        self._editing_location: Optional[str] = None
        self._param_edit: Optional[PropertySheet] = None  # sheet whose region is edited on the image
        self._log_traffic = False
        self._job_name = ""
        self.property_sheet: Optional[PropertySheet] = None
        self.history = ops.History()
        self.find_dialog: Optional[FindDialog] = None
        self._select_purpose: Optional[dict] = None  # what cell selection mode is picking for
        self._write_tail: Optional[Future] = None  # cell writes run one after another
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setSingleShot(True)
        self._repeat_timer.setInterval(REPEAT_TRIGGER_MS)
        self._repeat_timer.timeout.connect(self._repeat_trigger_tick)

        self._build_ui()
        self._build_actions()
        self._build_session_bar_and_menus()
        self._build_toolbars()
        self._build_docks()
        self._build_status_bar()
        self._connect_device()
        QApplication.clipboard().dataChanged.connect(self._update_actions)
        set_unhandled_error_hook(self._on_unhandled_error)
        self._update_actions()
        self._update_view_actions()
        self._restore_state()

    # ================================================================== UI construction
    def _build_ui(self) -> None:
        self.model = SheetModel(self)
        self.model.expressionEdited.connect(self._commit_expression)

        self.sheet = SheetView()
        self.sheet.setModel(self.model)
        self.delegate = SheetDelegate(self._completion_functions, self._on_function_completed, self.sheet)
        self.delegate.editorTextChanged.connect(self._on_cell_editor_text)
        self.delegate.closeEditor.connect(lambda *_a: QTimer.singleShot(0, self._after_cell_editor_closed))
        self.sheet.setItemDelegate(self.delegate)
        self.sheet.selectionModel().currentChanged.connect(self._on_current_cell)
        self.sheet.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.sheet.pasteRequested.connect(self._on_paste)
        self.sheet.handlers.update({"copy": self.copy_cells, "cut": self.cut_cells})
        self.sheet.selectionModeFinished.connect(self._on_selection_mode_finished)
        self.sheet.clearRequested.connect(self._clear_cells)
        self.sheet.contextMenuRequested.connect(self._show_cell_menu)
        self.sheet.valueRequested.connect(self._write_cell_value)
        self.sheet.graphicRequested.connect(self._edit_graphic_at)
        self.sheet.functionDropped.connect(self._function_dropped)
        self.sheet.doubleClicked.connect(self._on_cell_double_clicked)
        self.sheet.opens_on_double_click = lambda index: is_training_function(
            cells.function_name(self.model.expressions.get(cells.address(index.row(), index.column()), "")))

        self.image = ImageView()
        self.image.zoomModeChanged.connect(lambda _m: self._update_view_actions())
        self.area = ImageSheetArea(self.image, self.sheet)
        self.area.viewChanged.connect(self._update_view_actions)

        # formula bar (lives in the cell editing toolbar)
        self.name_box = QComboBox()
        self.name_box.setEditable(True)
        self.name_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.name_box.setFixedWidth(120)
        self.name_box.setToolTip("Cell Name")
        self.name_box.lineEdit().returnPressed.connect(self._goto_name_box)
        self.name_box.activated.connect(lambda _i: self._goto_name_box())
        self.formula = ExpressionLineEdit()
        FunctionCompleter(self.formula, self._completion_functions, self._on_function_completed)
        self.formula.setToolTip("Formula Bar")
        self.formula.returnPressed.connect(self._commit_formula_bar)
        self.formula.textEdited.connect(lambda _t: self._update_accept_cancel())
        self.formula.installEventFilter(self)
        # Cell state indicator next to the formula bar (filled in by the Cell State feature).
        self.state_indicator = QLabel("")
        self.state_indicator.setObjectName("stateIndicator")
        self.state_indicator.setMinimumWidth(24)

        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)

        # editor area: the three spreadsheet toolbars above the grid/image
        self.editor_frame = QFrame()
        self.editor_frame.setObjectName("editorFrame")
        self._editor_layout = QVBoxLayout(self.editor_frame)
        self._editor_layout.setContentsMargins(1, 1, 1, 1)
        self._editor_layout.setSpacing(0)
        self._editor_layout.addWidget(self.area, 1)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(4, 4, 2, 2)
        cl.setSpacing(0)
        cl.addWidget(self.editor_frame, 1)
        self.setCentralWidget(central)

    def _act(self, text: str, slot=None, shortcut=None, icon: Optional[str] = None, checkable=False,
             tip_keys: Optional[str] = None, note: str = "", enabled: bool = True) -> QAction:
        """An action with an ISVS-style tooltip "Text (Shortcut)".

        ``tip_keys`` names the ISVS shortcut when it is shown but not bound here (e.g. Ctrl+C, which
        the grid and the formula bar handle themselves). ``note`` is added below the tooltip,
        e.g. why the command is unavailable.
        """
        act = QAction(text, self)
        if icon:
            act.setIcon(icons.icon(icon))
        if isinstance(shortcut, (list, tuple)):
            act.setShortcuts([QKeySequence(k) for k in shortcut])
        elif shortcut:
            act.setShortcut(QKeySequence(shortcut))
        keys = tip_keys or (shortcut if isinstance(shortcut, str) else None)
        label = text.replace("&", "")
        tip = f"{label} ({keys})" if keys else label
        if note:
            tip += f"\n{note}"
        act.setToolTip(tip)
        act.setStatusTip(tip.replace("\n", " — "))
        act.setCheckable(checkable)
        if slot is not None:
            act.triggered.connect(slot)
        if not enabled:
            act.setEnabled(False)
            act.setProperty("unavailable", True)  # never enabled by _update_actions
        return act

    def _build_actions(self) -> None:
        A = self._act
        # ---- File
        self.act_new = A("New Job", self.new_job, "Ctrl+N", "new_job")
        self.act_open = A("Open Job", self.open_job, "Ctrl+O", "open_job")
        self.act_save = A("Save Job", self.save_job_on_device, "Ctrl+S", "save_job")
        self.act_save_as = A("Save Job As", lambda: self.save_job_on_device(ask=True), "F12")
        self.act_upload = A("Open Job from PC…", self.upload_job,
                            note="Load a .jobx file from this computer into the vision system")
        self.act_download = A("Save Job to PC…", self.download_job,
                              note="Save the vision system's active job as a .jobx file on this computer")
        self.act_import_snippet = A("Import Snippet…", tip_keys="Alt+I", note=NOT_YET, enabled=False)
        self.act_export_snippet = A("Export Snippet…", tip_keys="Alt+E", note=NOT_YET, enabled=False)
        self.act_convert = A("Convert to Spreadsheet Job", note="EasyBuilder jobs are not supported", enabled=False)
        self.act_quit = A("E&xit", self.close, "Ctrl+Q")
        # aliases kept for older call sites/tests
        self.act_open_dev = self.act_open
        self.act_save_dev = self.act_save
        self.act_save_dev_as = self.act_save_as

        # ---- Sensor
        self.act_connect = A("Connect…", self.connect_dialog, "Ctrl+K", note="Connect to an In-Sight vision system")
        self.act_disconnect = A("Disconnect", self.disconnect_device)
        self.act_trigger = A("Trigger", self.trigger, "F5", "trigger")
        self.act_repeat = A("Repeating Trigger", self.toggle_repeating_trigger, icon="repeat_trigger",
                            checkable=True)
        self.act_live = A("Live Video", self.toggle_live, icon="live_video", checkable=True)
        self.act_online = A("Go Online", self.toggle_online, "Ctrl+F8", "online", checkable=True)
        self.act_online.setIconText("Online")
        self.act_result_queue = A("Result Queue Settings…", note=NOT_YET, enabled=False)
        self.act_job_status = A("Job Status Settings…", note=NOT_YET, enabled=False)
        self.act_custom_view = A("Custom View Settings…", note=NOT_YET, enabled=False)
        self.act_discrete_io = A("Discrete I/O Settings…", note=NO_SDK, enabled=False)

        # ---- Control
        self.act_load_image = A("Open Image", self.load_image, "Ctrl+Shift+O", "open_image")
        self.act_save_image = A("Save Image As", self.save_image, "Ctrl+Shift+S", "save_image")
        self.act_cut = A("Cut", self.cut_cells, None, "cut", tip_keys="Ctrl+X")
        self.act_copy = A("Copy", self.copy_cells, None, "copy", tip_keys="Ctrl+C")
        self.act_paste = A("Paste", lambda: self.sheet.paste(), None, "paste", tip_keys="Ctrl+V")
        self.act_undo = A("Undo", self.undo, "Ctrl+Z", "undo")
        self.act_redo = A("Redo", self.redo, "Ctrl+Y", "redo")
        self.act_find = A("Find", self.show_find, "Ctrl+F", "find")
        self.act_insert_cells = A("Insert…", self.insert_cells)
        self.act_delete_cells = A("Delete…", self.delete_cells)

        # ---- Image display
        shift_num = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.KeypadModifier
        self.act_zoom_in = A("Zoom In", lambda: self.image.zoom(1.25),
                             [QKeyCombination(shift_num, Qt.Key.Key_Plus)], "zoom_in", tip_keys="Shift+Add")
        self.act_zoom_out = A("Zoom Out", lambda: self.image.zoom(0.8),
                              [QKeyCombination(shift_num, Qt.Key.Key_Minus)], "zoom_out", tip_keys="Shift+Subtract")
        self.act_zoom_1to1 = A("Zoom 1:1", self.image.one_to_one,
                               [QKeyCombination(shift_num, Qt.Key.Key_Asterisk)], "zoom_1to1", checkable=True,
                               tip_keys="Shift+Multiply")
        self.act_zoom_fill = A("Zoom to Fill", self.image.fill, None, "zoom_fill", checkable=True)
        self.act_fit = A("Zoom to Fit", self.image.fit, None, "zoom_fit", checkable=True)
        self.act_rotate = A("Rotate Image", self.image.rotate_image,
                            [QKeyCombination(shift_num, Qt.Key.Key_Slash)], "rotate", tip_keys="Shift+Divide")
        self.act_saturation = A("Show Image Saturation", self.image.set_show_saturation, "Ctrl+Shift+B",
                                "saturation", checkable=True)
        self.act_change_split = A("Change Split", lambda: self.area.toggle_split(), "Shift+F7", "change_split",
                                  checkable=True)
        self.act_more_transparent = A("Increase Transparency", lambda: self.area.increase_transparency(),
                                      icon="transparency_up")
        self.act_less_transparent = A("Decrease Transparency", lambda: self.area.decrease_transparency(),
                                      icon="transparency_down")
        self.act_show_grid = A("Show Grid", self.area.set_show_grid, "Shift+F6", "show_grid", checkable=True)
        self.act_show_grid.setChecked(True)
        self.act_graphics = A("Show Graphics", self.image.set_show_graphics, "Ctrl+Shift+G", "show_graphics",
                              checkable=True)
        self.act_graphics.setChecked(True)
        self.text_scale_group = QActionGroup(self)
        self.text_scale_actions: dict[str, QAction] = {}
        for mode, label in TEXT_SCALE_MODES.items():
            a = QAction(label, self, checkable=True)
            a.triggered.connect(lambda _c=False, m=mode: self._set_text_scale(m))
            self.text_scale_group.addAction(a)
            self.text_scale_actions[mode] = a
        self.text_scale_actions[TEXT_FIXED].setChecked(True)

        # ---- Cell formatting (formats can be read but not written through the HMI API)
        self.act_bold = A("Bold", None, None, "bold", checkable=True, tip_keys="Ctrl+B", note=NO_FORMAT,
                          enabled=False)
        self.act_italic = A("Italic", None, None, "italic", checkable=True, tip_keys="Ctrl+I", note=NO_FORMAT,
                            enabled=False)
        self.act_align = {
            h: A(f"Align {label}", None, None, f"align_{label.lower()}", checkable=True, note=NO_FORMAT,
                 enabled=False)
            for h, label in ((0, "Left"), (1, "Center"), (2, "Right"))
        }
        self.act_decimal_more = A("Increase Decimal", None, None, "decimal_more", note=NO_FORMAT, enabled=False)
        self.act_decimal_less = A("Decrease Decimal", None, None, "decimal_less", note=NO_FORMAT, enabled=False)
        self.act_back_color = A("Background Color", None, None, "back_color", note=NO_FORMAT, enabled=False)
        self.act_fore_color = A("Foreground Color", None, None, "fore_color", note=NO_FORMAT, enabled=False)

        # ---- Cell dependency
        self.act_dep_more = A("Increase Dependency Levels", None, None, "dep_more", tip_keys="F11", note=NOT_YET,
                              enabled=False)
        self.act_dep_less = A("Decrease Dependency Levels", None, None, "dep_less", tip_keys="Shift+F11",
                              note=NOT_YET, enabled=False)
        self.act_dep_reset = A("Reset Dependency Levels", None, None, "dep_reset", tip_keys="Ctrl+F11",
                               note=NOT_YET, enabled=False)
        self.act_dep_errors = A("Show Dependency Errors Only", None, None, "dep_errors", tip_keys="Alt+F11",
                                note=NOT_YET, enabled=False)
        self.act_dep_first = A("Go To First Error", None, None, "dep_first_error", tip_keys="Ctrl+Shift+F11",
                               note=NOT_YET, enabled=False)

        # ---- Cell editing
        self.act_abs_ref = A("Insert Absolute Reference", lambda: self.insert_reference(True), "Ctrl+Shift+A",
                             "abs_ref")
        self.act_rel_ref = A("Insert Relative Reference", lambda: self.insert_reference(False), "Ctrl+Shift+R",
                             "rel_ref")
        self.act_insert = A("Insert Function", self.insert_function, "Ctrl+Shift+F", "insert_function")
        self.act_edit_graphic = A("Edit Cell Graphic", self.edit_graphic, "F9", "edit_graphic")
        self.act_maximize = A("Maximize Cell Region", lambda: self.maximize_region(), "Ctrl+Shift+M",
                              "maximize_region")
        self.act_cell_state = A("Edit Cell State", None, None, "cell_state", note=NOT_YET, enabled=False)
        self.act_comment = A("Insert Comment…", None, None, "comment", note=NO_COMMENT, enabled=False)
        self.act_name = A("Insert Cell Name…", self.set_cell_name, None, "cell_name")
        self.act_accept = A("Accept Changes", self.accept_changes, None, "accept", tip_keys="Return")
        self.act_cancel = A("Cancel Changes", self.cancel_changes, None, "cancel", tip_keys="Escape")
        # graphic editing (Return / Escape while Interactive Graphics Mode is active)
        self.act_accept_graphic = self.act_accept
        self.act_cancel_graphic = self.act_cancel

        # ---- extras (context menu, View, Help)
        self.act_props = A("Edit Function…", self.open_property_sheet,
                           note="Edit the parameters of the function in the cell (Property Sheet)")
        self.act_refresh = A("Refresh Sheet", self.refresh_sheet, "Ctrl+R")
        self.act_help_fn = A("Help for Function in Cell", self.help_for_cell, "F1")
        self.act_help_sheet = A("Spreadsheet Help", self.spreadsheet_help)
        self.act_snippets = A("Snippets", note=NOT_YET, enabled=False)
        self.act_profile = A("Profile Job", note=NOT_YET, enabled=False)
        self.act_easyview = A("EasyView", note=NOT_YET, enabled=False)

    def _build_session_bar_and_menus(self) -> None:
        """Title strip with the session tab (ISVS: "<job>@<sensor>") above the menu bar."""
        bar = QWidget()
        bar.setObjectName("sessionBar")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(6, 0, 6, 0)
        hl.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(icons.icon("app").pixmap(18, 18))
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        home = QToolButton()
        home.setIcon(icons.icon("home"))
        home.setIconSize(QSize(20, 20))
        home.setToolTip("Home: connect to an In-Sight vision system")
        home.clicked.connect(lambda: self.act_connect.isEnabled() and self.connect_dialog())
        self.session_tabs = QTabBar()
        self.session_tabs.setDrawBase(False)
        self.session_tabs.setExpanding(False)
        for w in (logo, title, home, self.session_tabs):
            hl.addWidget(w)
        hl.addStretch(1)

        self.menu_bar = QMenuBar()
        self.user_label = QLabel("")
        self.user_label.setContentsMargins(0, 0, 10, 0)
        self.menu_bar.setCornerWidget(self.user_label, Qt.Corner.TopRightCorner)

        def menu(title_: str, items) -> QMenu:
            m = self.menu_bar.addMenu(title_)
            for a in items:
                if a is None:
                    m.addSeparator()
                elif isinstance(a, QMenu):
                    m.addMenu(a)
                else:
                    m.addAction(a)
            return m

        menu("&File", [self.act_new, self.act_open, self.act_save, self.act_save_as, None, self.act_upload,
                       self.act_download, None, self.act_import_snippet, self.act_export_snippet, None,
                       self.act_convert, None, self.act_quit])
        menu("&Sensor", [self.act_trigger, self.act_repeat, self.act_live, self.act_online, None,
                         self.act_result_queue, self.act_job_status, self.act_custom_view, self.act_discrete_io,
                         None, self.act_connect, self.act_disconnect])
        self.view_menu = menu("&View", [self.act_snippets, self.act_profile, self.act_easyview])
        menu("&Help", [self.act_help_sheet, self.act_help_fn, None, self._act("About", self.about)])

        top = QWidget()
        vl = QVBoxLayout(top)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(bar)
        vl.addWidget(self.menu_bar)
        self.setMenuWidget(top)

    def _toolbar(self, name: str, items, movable=True) -> QToolBar:
        tb = QToolBar(name)
        tb.setObjectName(name.lower().replace(" ", "_") + "_toolbar")
        tb.setIconSize(QSize(16, 16))
        tb.setMovable(movable)
        for a in items:
            if a is None:
                tb.addSeparator()
            elif isinstance(a, QWidget):
                tb.addWidget(a)
            else:
                tb.addAction(a)
        return tb

    def _build_toolbars(self) -> None:
        # ---- top: File and Sensor blocks
        save_menu = QMenu(self)
        save_menu.addAction(self.act_save_as)
        save_menu.addAction(self.act_download)
        self.act_save.setMenu(save_menu)
        tb = self._toolbar("File", [self.act_new, self.act_open, self.act_save])
        tb.widgetForAction(self.act_save).setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.addToolBar(tb)
        tb = self._toolbar("Sensor", [self.act_trigger, self.act_repeat, self.act_live, None, self.act_online])
        tb.widgetForAction(self.act_online).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.addToolBarBreak()
        self.banner_bar = self._toolbar("Messages", [self.banner], movable=False)
        self.banner_bar.toggleViewAction().setVisible(False)
        self.addToolBar(self.banner_bar)
        self.banner_bar.setVisible(False)

        # ---- spreadsheet toolbars, row 1: control + image display
        self.text_scale_button = QToolButton()
        self.text_scale_button.setIcon(icons.icon("text_scale"))
        self.text_scale_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        ts_menu = QMenu(self.text_scale_button)
        for a in self.text_scale_actions.values():
            ts_menu.addAction(a)
        self.text_scale_button.setMenu(ts_menu)
        self.grid_size = QComboBox()
        self.grid_size.setToolTip("Grid Size")
        for pct in GRID_SIZES:
            self.grid_size.addItem(f"{pct}%", pct / 100.0)
        self.grid_size.setCurrentIndex(GRID_SIZES.index(100))
        self.grid_size.activated.connect(lambda i: self.sheet.set_zoom(self.grid_size.itemData(i)))
        row1 = self._toolbar("Spreadsheet Control", [
            self.act_load_image, self.act_save_image, None, self.act_cut, self.act_copy, self.act_paste, None,
            self.act_undo, self.act_redo, self.act_find, None,
            self.act_zoom_in, self.act_zoom_out, self.act_zoom_1to1, self.act_zoom_fill, self.act_fit,
            self.act_rotate, self.act_saturation, None, self.act_change_split, None,
            self.act_more_transparent, self.act_less_transparent, self.act_show_grid, self.act_graphics,
            self.text_scale_button, self.grid_size])

        # ---- row 2: cell formatting + cell dependency
        self.font_box = QComboBox()
        self.font_box.setEditable(True)
        self.font_box.setFixedWidth(104)
        self.font_box.addItems(["Arial", "Times New Roman", "Courier New"])
        self.font_box.setToolTip(f"Font\n{NO_FORMAT}")
        self.font_size_box = QComboBox()
        self.font_size_box.setEditable(True)
        self.font_size_box.setFixedWidth(44)
        self.font_size_box.addItems([str(v) for v in (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72)])
        self.font_size_box.setToolTip(f"Font Size\n{NO_FORMAT}")
        for w in (self.font_box, self.font_size_box):
            w.setEnabled(False)
        row2 = self._toolbar("Spreadsheet Format", [
            self.font_box, self.font_size_box, None, self.act_bold, self.act_italic, None,
            *self.act_align.values(), None, self.act_decimal_more, self.act_decimal_less, None,
            self.act_back_color, self.act_fore_color, None,
            self.act_dep_more, self.act_dep_less, self.act_dep_reset, self.act_dep_errors, self.act_dep_first])

        # ---- row 3: cell editing + formula bar
        eq = QLabel("=")
        eq.setContentsMargins(3, 0, 3, 0)
        formula_box = QWidget()
        fl = QHBoxLayout(formula_box)
        fl.setContentsMargins(0, 0, 4, 0)
        fl.setSpacing(2)
        fl.addWidget(self.name_box)
        fl.addWidget(eq)
        fl.addWidget(self.formula, 1)
        fl.addWidget(self.state_indicator)
        row3 = self._toolbar("Spreadsheet Edit", [
            self.act_abs_ref, self.act_rel_ref, self.act_insert, self.act_edit_graphic, self.act_maximize, None,
            self.act_cell_state, self.act_comment, self.act_name, None, self.act_accept, self.act_cancel, None,
            formula_box])
        formula_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.editor_toolbars = [row1, row2, row3]
        for i, tb in enumerate(self.editor_toolbars):
            tb.setMovable(False)
            self._editor_layout.insertWidget(i, tb)

    def _note(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setObjectName("placeholder")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        return label

    def _build_docks(self) -> None:
        right = Qt.DockWidgetArea.RightDockWidgetArea
        bottom = Qt.DockWidgetArea.BottomDockWidgetArea
        self.setTabPosition(right | bottom, QTabWidget.TabPosition.South)
        self.setCorner(Qt.Corner.BottomRightCorner, right)
        self.setCorner(Qt.Corner.TopRightCorner, right)
        self.setDockNestingEnabled(False)

        # Functions panel: Filter, toolbox tree, description pane
        self.functions_panel = FunctionsPanel(self.catalog)
        self.functions_panel.functionActivated.connect(self._insert_function_from_panel)
        self.functions_panel.helpRequested.connect(self._open_help_for)
        self.func_dock = self._dock("Functions", self.functions_panel, right)
        self.acq_dock = self._dock("Acquisition", self._note(
            "Acquisition settings (exposure, gain, trigger, illumination, white balance…) cannot be read or "
            "changed through the In-Sight HMI API."), right)
        self.validation_dock = self._dock("Job Validation", self._note("Job Validation: not implemented yet."),
                                          right)
        self.tabifyDockWidget(self.func_dock, self.acq_dock)
        self.tabifyDockWidget(self.acq_dock, self.validation_dock)

        self.filmstrip_dock = self._dock("Record/Playback", self._note("Record/Playback: not implemented yet."),
                                         bottom)
        self.charts_dock = self._dock("Charts", self._note(
            "Charts (Caliper, FindLine, histograms…) are not available: the In-Sight HMI API does not report "
            "chart data."), bottom)
        health = QWidget()
        form = QFormLayout(health)
        form.setContentsMargins(10, 8, 10, 8)
        self.health_labels: dict[str, QLabel] = {}
        for key in ("Vision system", "Model", "Firmware", "HMI API", "User", "State", "Job", "Editor attached"):
            lab = QLabel("—")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.health_labels[key] = lab
            form.addRow(f"{key}:", lab)
        self.health_dock = self._dock("System Health", health, bottom)

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
        self.log_dock = self._dock("Log", log_box, bottom)
        self.tabifyDockWidget(self.filmstrip_dock, self.charts_dock)
        self.tabifyDockWidget(self.charts_dock, self.health_dock)
        self.tabifyDockWidget(self.health_dock, self.log_dock)
        self.func_dock.raise_()
        self.filmstrip_dock.raise_()
        self.resizeDocks([self.func_dock], [320], Qt.Orientation.Horizontal)
        self.resizeDocks([self.filmstrip_dock], [200], Qt.Orientation.Vertical)

        m = self.view_menu
        m.addSeparator()
        for d in (self.filmstrip_dock, self.charts_dock):
            m.addAction(d.toggleViewAction())
        m.addSeparator()
        for d in (self.func_dock, self.acq_dock, self.validation_dock, self.health_dock, self.log_dock):
            m.addAction(d.toggleViewAction())
        m.addSeparator()
        m.addAction(self.act_refresh)

    def _build_status_bar(self) -> None:
        sb = self.statusBar()
        self.total_label = QLabel("Total: – ms")
        self.total_label.setToolTip("Processing times (acquisition, inspection, queue) are not reported by the "
                                    "In-Sight HMI API")
        self.online_box = QLabel("Not connected")
        self.online_box.setObjectName("onlineBox")
        self.online_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb.addPermanentWidget(self.total_label)
        sb.addPermanentWidget(self.online_box)

    def _dock(self, title: str, widget: QWidget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "_").replace("/", "_") + "_dock")
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    # ================================================================== device wiring
    def _connect_device(self) -> None:
        d = self.device
        d.connectedChanged.connect(self._on_connected_changed)
        d.stateChanged.connect(lambda _s: self._update_state())
        d.jobInfoChanged.connect(self._on_job_info)
        d.jobLoadingChanged.connect(self._on_job_loading)
        d.editorAttachedChanged.connect(self._on_editor_attached)
        d.resultChanged.connect(self._on_result)
        d.expressionsChanged.connect(self._on_expressions)
        d.cellNamesChanged.connect(self._on_names)
        d.sheetFormatChanged.connect(self._on_sheet_format)
        d.message.connect(self.log)
        d.traffic.connect(self._on_traffic)

    def run(self, coro: Coroutine, what: str):
        """Runs a device operation and reports failures to the user."""
        fut = spawn(coro, report_errors=False)

        def done(f) -> None:
            exc = f.exception()
            if exc is not None:
                self._show_error(what, exc)

        fut.add_done_callback(done)
        return fut

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
        self.log(f"Connecting to {host} as {user}…")

        async def go() -> None:
            await self.device.connect_to(host, user, password)

        self.run(go(), f"Connecting to {host}")

    def disconnect_device(self) -> None:
        self.cancel_graphic()
        self.run(self.device.disconnect_from(), "Disconnect")

    def _on_connected_changed(self, connected: bool) -> None:
        if connected:
            self.image.set_coordinate_mode(self.device.info.uses_xy)
        else:
            self._repeat_timer.stop()
            self.act_repeat.setChecked(False)
            self.model.clear()
            self.image.clear()
            self._fill_name_box()
            self._end_graphic_edit_ui()
            self._set_banner("")
            self._reset_sheet_session()
        self.user_label.setText(self.device.username if connected else "")
        self.user_label.adjustSize()
        self.menu_bar.setCornerWidget(self.user_label, Qt.Corner.TopRightCorner)  # re-layout for the new text
        self._update_session_title()
        self._update_state()
        self._update_actions()

    def _update_state(self) -> None:
        d = self.device
        box = self.online_box
        if not d.connected:
            self.act_online.setChecked(False)
            self.act_live.setChecked(False)
            box.setText("Not connected")
            box.setToolTip("")
            box.setProperty("online", False)
        else:
            self.act_online.setChecked(d.online)
            self.act_live.setChecked(d.live_mode)
            blockers = [k for k in ("nativeOnline", "discreteOnline", "ffpOnline") if d.state.get(k) is False]
            text = "Online" if d.online else "Offline"
            tip = text
            if d.soft_online and not d.online and blockers:
                tip += f" (online blocked by {', '.join(blockers)})"
            if d.live_mode:
                text += " · Live"
            box.setText(text)
            box.setToolTip(tip)
            box.setProperty("online", d.online)
        box.style().unpolish(box)
        box.style().polish(box)
        self.act_online.setText("Go Offline" if d.connected and d.online else "Go Online")
        self.act_online.setIconText("Online")
        self._update_health()
        self._update_actions()

    def _on_job_loading(self, loading: bool) -> None:
        self.log("Job loading…" if loading else "Job loaded")
        if loading:
            self.model.clear()
            self._reset_sheet_session()

    def _reset_sheet_session(self) -> None:
        """Another job: forget the undo history, the Cut mark, hidden rows/columns."""
        self.history.clear()
        self.sheet.set_cut_block(None)
        if self.sheet.in_selection_mode:
            self.sheet.finish_selection_mode(False)
        for r in range(cells.NUM_ROWS):
            if self.sheet.isRowHidden(r):
                self.sheet.setRowHidden(r, False)
        for c in range(cells.NUM_COLS):
            if self.sheet.isColumnHidden(c):
                self.sheet.setColumnHidden(c, False)
        self._update_actions()

    def _on_editor_attached(self, attached: bool) -> None:
        self.model.read_only = attached
        self._set_banner("An editor (In-Sight Vision Suite / Explorer / VisionView) is attached to this "
                         "vision system. Editing is disabled while it is connected." if attached else "")
        self._update_health()
        self._update_actions()

    def _set_banner(self, text: str) -> None:
        """The yellow message banner under the main toolbar (hidden when empty)."""
        self.banner.setText(text)
        self.banner_bar.setVisible(bool(text))

    def _update_session_title(self) -> None:
        d = self.device
        if d.connected:
            job = self._job_name.rsplit(".", 1)[0] if self._job_name else UNSAVED_JOB
            text = f"{job}@{d.info.name or d.host}"
            if self.session_tabs.count() == 0:
                self.session_tabs.addTab(text)
                close = QToolButton()
                close.setObjectName("tabClose")
                close.setText("×")
                close.setToolTip("Disconnect")
                close.clicked.connect(self.disconnect_device)
                self.session_tabs.setTabButton(0, QTabBar.ButtonPosition.RightSide, close)
            self.session_tabs.setTabText(0, text)
            self.session_tabs.setTabToolTip(0, f"{d.info.model} · firmware {d.info.firmware} · {d.host}")
            self.setWindowTitle(f"{text} - {APP_NAME}")
        else:
            while self.session_tabs.count():
                self.session_tabs.removeTab(0)
            self.setWindowTitle(APP_NAME)

    def _update_health(self) -> None:
        d = self.device
        info = d.info if d.connected else None
        values = {
            "Vision system": f"{info.name} ({d.host})" if info else "—",
            "Model": info.model if info else "—",
            "Firmware": info.firmware if info else "—",
            "HMI API": info.api_version if info else "—",
            "User": f"{d.username} [{d.access_level}]" if info else "—",
            "State": self.online_box.text() if info else "—",
            "Job": (self._job_name or UNSAVED_JOB) if info else "—",
            "Editor attached": ("Yes" if d.editor_attached else "No") if info else "—",
        }
        for key, value in values.items():
            self.health_labels[key].setText(str(value))

    def _update_actions(self) -> None:
        d = self.device
        connected = d.connected
        writable = connected and not d.read_only
        offline = writable and not d.online
        editing = self._editing_location is not None
        self.act_connect.setEnabled(not connected)
        self.act_disconnect.setEnabled(connected)
        for a in (self.act_upload, self.act_new, self.act_open):
            a.setEnabled(offline and not editing)
        for a in (self.act_download, self.act_save, self.act_save_as, self.act_refresh):
            a.setEnabled(connected and not editing)
        self.act_online.setEnabled(writable and not editing)
        self.act_live.setEnabled(offline and not editing)
        can_trigger = writable and not d.live_mode and not editing
        self.act_trigger.setEnabled(can_trigger)
        self.act_repeat.setEnabled(can_trigger)
        if not can_trigger and self.act_repeat.isChecked():
            self.act_repeat.setChecked(False)
            self._repeat_timer.stop()
        self.act_load_image.setEnabled(offline and not editing)
        self.act_save_image.setEnabled(not self.image.image().isNull())
        loc = self.sheet.current_location()
        result = self.model.results.get(loc) if loc else None
        self.act_insert.setEnabled(offline and not editing)
        # ISVS: Insert Cell Name… needs a cell with contents
        self.act_name.setEnabled(offline and not editing and bool(self.model.expressions.get(loc or "")))
        selecting = self.sheet.in_selection_mode
        has_selection = bool(loc) and not editing and not selecting
        self.act_copy.setEnabled(has_selection)
        self.act_cut.setEnabled(has_selection and offline)
        self.act_paste.setEnabled(has_selection and offline and self.sheet.can_paste())
        cell_ops = offline and not editing and not selecting
        self.act_insert_cells.setEnabled(cell_ops and bool(loc))
        self.act_delete_cells.setEnabled(cell_ops and bool(loc))
        self.act_undo.setEnabled(cell_ops and self.history.can_undo())
        self.act_redo.setEnabled(cell_ops and self.history.can_redo())
        for act, stack in ((self.act_undo, self.history.undo_stack), (self.act_redo, self.history.redo_stack)):
            verb = act.text()
            tip = f"{verb} {stack[-1].label} ({'Ctrl+Z' if act is self.act_undo else 'Ctrl+Y'})" if stack \
                else f"{verb} ({'Ctrl+Z' if act is self.act_undo else 'Ctrl+Y'})"
            act.setToolTip(tip)
        # ISVS: Find needs the overlay/grid and no Live Video
        self.act_find.setEnabled(connected and not d.live_mode and not editing)
        if self.find_dialog is not None:
            self.find_dialog.set_replace_allowed(offline and not editing)
        self.act_abs_ref.setEnabled(cell_ops and bool(loc))
        self.act_rel_ref.setEnabled(cell_ops and bool(loc))
        self.sheet.controls_enabled = writable and not editing
        self.delegate.pressed = None
        graphic = cells.editable_graphic(result)
        self.act_edit_graphic.setEnabled(writable and graphic is not None and not editing)
        # Maximize Cell Region: "only when the active cell contains a function that has an
        # associated region cell graphic"
        self.act_maximize.setEnabled(writable and not editing and (graphic or {}).get("$type") == "Region"
                                     and self._native_image_size() is not None)
        self.act_props.setEnabled(connected and self._has_property_sheet(self.model.expressions.get(loc or "", ""))
                                  and not editing)
        if self.property_sheet is not None:
            self.property_sheet.set_permissions(writable and not editing, offline and not editing)
        self.formula.setReadOnly(not offline or editing)
        self.model.read_only = not offline or editing
        self._update_accept_cancel()

    def _cell_editing(self) -> bool:
        """True while the in-cell expression editor is open."""
        return self.sheet.editor_widget() is not None

    def _formula_modified(self) -> bool:
        loc = self.formula.property("location")
        return bool(loc) and not self.formula.isReadOnly() and \
            self.formula.text() != self.model.expressions.get(loc, "")

    def _update_accept_cancel(self) -> None:
        """Accept/Cancel Changes: active while a graphic or the formula bar is being edited."""
        editing = self._editing_location is not None
        active = editing or self._formula_modified() or self._cell_editing()
        self.act_accept.setEnabled(active)
        self.act_cancel.setEnabled(active)
        # Return/Escape belong to the focused widget, except in Interactive Graphics Mode
        self.act_accept.setShortcut(QKeySequence("Return") if editing else QKeySequence())
        self.act_cancel.setShortcut(QKeySequence("Escape") if editing else QKeySequence())

    def accept_changes(self) -> None:
        if self._editing_location is not None:
            self.accept_graphic()
        elif self.sheet.commit_editor():
            pass
        elif self._formula_modified():
            self._commit_formula_bar()

    def cancel_changes(self) -> None:
        if self._editing_location is not None:
            self.cancel_graphic()
        elif self.sheet.cancel_editor():
            self._on_current_cell()
        else:
            self._on_current_cell()
            self.sheet.setFocus()

    def _update_view_actions(self) -> None:
        """Checked/enabled state of the image display buttons."""
        mode = self.image.zoom_mode
        self.act_fit.setChecked(mode == "fit")
        self.act_zoom_fill.setChecked(mode == "fill")
        self.act_zoom_1to1.setChecked(mode == "1:1")
        self.act_change_split.setChecked(not self.area.overlay)
        self.act_show_grid.setChecked(self.area.show_grid)
        self.act_show_grid.setEnabled(self.area.overlay)
        self.act_more_transparent.setEnabled(self.area.can_increase_transparency())
        self.act_less_transparent.setEnabled(self.area.can_decrease_transparency())

    def _set_text_scale(self, mode: str) -> None:
        self.image.set_text_scale_mode(mode)
        self.text_scale_button.setToolTip(f"Text Scale Mode: {TEXT_SCALE_MODES[mode]}")

    # ================================================================== results
    def _on_result(self, result: dict) -> None:
        self.model.set_results(self.device.cell_results())
        if self.property_sheet is not None:
            self.property_sheet.refresh()
        self._result_gen += 1
        gen = self._result_gen
        self.run(self._render_result(result, gen), "Displaying result")
        self._update_actions()
        status = {1: "Pass", 2: "Fail", 3: "Warn"}.get(result.get("jobStatus"))
        if status:
            self.statusBar().showMessage(f"Result {result.get('id')}: {status}", 3000)
        if self.act_repeat.isChecked() and self.act_repeat.isEnabled():
            self._repeat_timer.start()

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
                self.act_save_image.setEnabled(True)
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
        if self.property_sheet is not None:
            self.property_sheet.refresh()

    def _on_names(self, names: dict) -> None:
        self.model.set_names(names)
        self._fill_name_box()
        self._on_current_cell()

    def _fill_name_box(self) -> None:
        """The name box drop-down lists the cell names of the job."""
        text = self.name_box.currentText()
        self.name_box.blockSignals(True)
        self.name_box.clear()
        for loc, name in sorted(self.model.names.items(), key=lambda kv: kv[1].lower()):
            self.name_box.addItem(name, loc)
        self.name_box.setCurrentIndex(-1)
        self.name_box.setEditText(text)
        self.name_box.blockSignals(False)

    def _on_sheet_format(self, fmt: dict) -> None:
        widths, heights, formats = cells.parse_sheet_format(fmt)
        self.model.set_formats(formats)
        self.sheet.apply_sheet_format(widths, heights)

    # ================================================================== sheet editing
    def _on_current_cell(self, *_args) -> None:
        loc = self.sheet.current_location()
        if not loc:
            return
        if self.sheet.in_selection_mode:  # picking a reference: the formula bar keeps the edited cell
            block = self.sheet.selection_block()
            self.name_box.setEditText(ops.block_text(block) if block else loc)
            return
        name = self.model.names.get(loc)
        self.name_box.setEditText(name or loc)
        self.name_box.setToolTip(f"Cell Name ({loc})" if name else "Cell Name")
        self.formula.setText(self.model.expressions.get(loc, ""))
        self.formula.setProperty("location", loc)
        self._show_cell_format(loc)
        self._update_actions()

    def _show_cell_format(self, loc: str) -> None:
        """Mirrors the (read-only) format of the active cell in the formatting toolbar."""
        fmt = self.model.formats.get(loc)
        self.font_box.setEditText((fmt.font_name if fmt and fmt.font_name else None) or "Arial")
        size = fmt.font_size if fmt and fmt.font_size else 9
        self.font_size_box.setEditText(f"{float(size):g}")
        self.act_bold.setChecked(bool(fmt and fmt.bold))
        self.act_italic.setChecked(bool(fmt and fmt.italic))
        h = fmt.h_align if fmt else None
        for key, act in self.act_align.items():
            act.setChecked(h == key)

    def _on_selection_changed(self, *_args) -> None:
        self.image.set_selected_sources(set(self.sheet.selected_locations()))
        if self.sheet.in_selection_mode:  # the name box shows the range being picked
            block = self.sheet.selection_block()
            if block:
                self.name_box.setEditText(ops.block_text(block))

    def _goto_name_box(self) -> None:
        text = self.name_box.currentText().strip()
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
            self.cancel_changes()
            return True
        return super().eventFilter(obj, event)

    def _commit_expression(self, loc: str, expr: str, record: bool = True) -> None:
        self._apply_change(f"Edit {loc}", {loc: CellState(expr)}, record=record,
                           log=f"{loc} ← {expr}" if expr else f"{loc} cleared")

    # ------------------------------------------------------------------ writing cells (with undo)
    def _control_value(self, loc: str):
        """The value of an HMI control cell, to restore it after the cell is moved or re-created."""
        result = self.model.results.get(loc)
        if cells.is_value_editable(result):
            return result.get("data")
        graphic = cells.editable_graphic(result)
        return dict(graphic) if graphic is not None else None

    def _cache_state(self, loc: str, condition=None) -> CellState:
        expr = str(self.device.expressions.get(loc, {}).get("expr", ""))
        return CellState(expr, self.device.cell_names.get(loc, ""), condition if expr else "",
                         self._control_value(loc) if expr else None)

    async def _snapshot(self, targets: dict[str, CellState]) -> dict[str, CellState]:
        """Current states of the target cells; cell states are read where the change can alter them."""
        need = [loc for loc, t in targets.items()
                if self.device.expressions.get(loc, {}).get("expr") and (t.condition is not None or not t.expr)]
        conds = await self.device.get_cell_conditions(need)
        return {loc: self._cache_state(loc, conds.get(loc)) for loc in targets}

    async def _sheet_states(self) -> dict[str, CellState]:
        """States of every non-empty cell, with cell states (for Insert/Delete/Cut)."""
        locs = [loc for loc, v in self.device.expressions.items() if v.get("expr")]
        conds = await self.device.get_cell_conditions(locs)
        return {loc: self._cache_state(loc, conds.get(loc, "" if self.device.conditions_supported else None))
                for loc in locs}

    def _apply_change(self, label: str, targets: dict[str, CellState], record: bool = True,
                      before: Optional[dict[str, CellState]] = None, log: Optional[str] = None):
        """Writes target cell states to the device and records them for Undo."""
        if not targets or self.model.read_only and record:
            return None
        for loc, t in targets.items():
            self.model.mark_pending(loc, t.expr)
        prev, done = self._write_tail, Future()
        self._write_tail = done

        async def go() -> None:
            try:
                # one change at a time: a snapshot must see the cells as the previous change left them
                if prev is not None and not prev.done():
                    await prev
                cur = before if before is not None else await self._snapshot(targets)
                try:
                    await self.device.write_cells(targets, cur)
                finally:
                    if record:
                        self.history.push(ops.Change(label, {loc: cur.get(loc, ops.EMPTY) for loc in targets},
                                                     dict(targets)))
                self.log(log or f"{label} ({len(targets)} cell{'s' if len(targets) != 1 else ''})")
            finally:
                for loc in targets:
                    self.model.pending.pop(loc, None)
                self.model.set_expressions(self.device.expressions)
                self._update_actions()
                done.set_result(None)

        return self.run(go(), label)

    async def _writes_done(self) -> None:
        while self._write_tail is not None and not self._write_tail.done():
            await self._write_tail

    def _paste_cells(self, items: dict) -> None:
        """Writes plain expressions {location: expression} (one undo step)."""
        if self.model.read_only:
            return
        self._apply_change("Paste", {loc: CellState(expr) for loc, expr in items.items()},
                           log=f"Pasted {len(items)} cell(s)")

    def _clear_cells(self, locations: list, label: str = "Clear") -> None:
        if self.model.read_only:
            return
        self._apply_change(label, {loc: ops.EMPTY for loc in locations})

    # ------------------------------------------------------------------ clipboard
    def copy_cells(self) -> None:
        """Copy: expressions and cell states (states copy like references)."""
        if not self.sheet.copy_selection():
            return
        block = self.sheet.selection_block()
        if block is None or not self.device.connected or not self.device.conditions_supported:
            return
        locs = [loc for loc in ops.iter_block(block) if self.model.expressions.get(loc)]

        async def go() -> None:
            conds = await self.device.get_cell_conditions(locs)
            if any(conds.values()) and self.sheet.selection_block() == block:
                self.sheet.copy_selection(conds)

        if locs:
            self.run(go(), "Copy")

    def cut_cells(self) -> None:
        """Cut marks the cells; Paste moves them (references to them follow, like ISVS)."""
        if self.model.read_only:
            return
        if self.sheet.selection_block() is None:
            QMessageBox.information(self, APP_NAME, NO_MULTI)
            return
        self.sheet.cut_selection()
        self._update_actions()

    def _on_paste(self, doc: dict) -> None:
        if self.model.read_only:
            return
        tr, tc = doc["target"]
        if doc.get("cut") and doc.get("block") and self.sheet.cut_block == tuple(doc["block"]):
            self._move_cut_cells(tuple(doc["block"]), tr, tc)
            return
        sr, sc = doc["source"] if doc.get("source") else (tr, tc)
        d_row, d_col = tr - sr, tc - sc
        targets: dict[str, CellState] = {}
        for key, expr in doc["cells"].items():
            r, c = map(int, key.split(","))
            rr, cc = tr + r, tc + c
            if not (0 <= rr < cells.NUM_ROWS and 0 <= cc < cells.NUM_COLS):
                continue
            new_expr = cells.shift_references(expr, d_row, d_col) if doc.get("source") else expr
            cond = (doc.get("conditions") or {}).get(key, "") if self.device.conditions_supported else None
            targets[cells.address(rr, cc)] = CellState(
                new_expr, condition=ops.shift_condition(cond, d_row, d_col) if new_expr else None)
        self._apply_change("Paste", targets, log=f"Pasted {len(targets)} cell(s)")

    def _move_cut_cells(self, source: ops.Block, tr: int, tc: int) -> None:
        d_row, d_col = tr - source[0], tc - source[1]
        if source[2] + d_row >= cells.NUM_ROWS or source[3] + d_col >= cells.NUM_COLS:
            QMessageBox.warning(self, APP_NAME, "The cut cells do not fit at the paste location.")
            return
        self.sheet.set_cut_block(None)
        if d_row == d_col == 0:
            return
        QApplication.clipboard().clear()
        self._move_cells("Cut and Paste", ops.move_mapping(source, d_row, d_col),
                         select=(tr, tc, source[2] + d_row, source[3] + d_col))

    # ------------------------------------------------------------------ Insert / Delete (ISVS live/09, live/10)
    def _selection_or_warn(self) -> Optional[ops.Block]:
        block = self.sheet.selection_block()
        if block is None:
            QMessageBox.information(self, APP_NAME, NO_MULTI)
        return block

    def insert_cells(self) -> None:
        self._insert_or_delete(delete=False)

    def delete_cells(self) -> None:
        self._insert_or_delete(delete=True)

    def _insert_or_delete(self, delete: bool) -> None:
        if not self.act_insert_cells.isEnabled():
            return
        block = self._selection_or_warn()
        if block is None:
            return
        default = None
        if ops.is_entire_rows(block):
            default = ops.ENTIRE_ROW
        elif ops.is_entire_columns(block):
            default = ops.ENTIRE_COLUMN
        dlg = InsertDeleteDialog(delete, default, self)
        if dlg.exec() != InsertDeleteDialog.DialogCode.Accepted:
            return
        self.apply_insert_delete(block, dlg.mode(), delete)

    def apply_insert_delete(self, block: ops.Block, mode: str, delete: bool):
        verb = "Delete" if delete else "Insert"
        mapping = ops.delete_mapping(block, mode) if delete else ops.insert_mapping(block, mode)
        r0, c0, r1, c1 = ops.normalise_block(block, mode)
        area = ops.block_text((r0, c0, r1, c1))
        if mode in (ops.ENTIRE_ROW, ops.ENTIRE_COLUMN):
            what = (f"row{'s' if r1 > r0 else ''} {r0}" + (f"–{r1}" if r1 > r0 else "")) if mode == ops.ENTIRE_ROW \
                else (f"column{'s' if c1 > c0 else ''} {cells.col_name(c0)}"
                      + (f"–{cells.col_name(c1)}" if c1 > c0 else ""))
        else:
            what = area
        if not delete:
            states = {loc: CellState(str(v.get("expr", ""))) for loc, v in self.device.expressions.items()}
            lost = ops.would_lose(states, block, mode)
            if lost:
                QMessageBox.warning(self, APP_NAME, "Cannot shift non-empty cells off the spreadsheet:\n"
                                    + ", ".join(lost[:12]) + (" …" if len(lost) > 12 else ""))
                return None
        return self._move_cells(f"{verb} {what}", mapping)

    def _move_cells(self, label: str, mapping: ops.Mapping, select: Optional[ops.Block] = None):
        """Moves cells (Insert / Delete / Cut + Paste): rewrites every reference, moves names, cell
        states and control values. Trained data (dataId) and cell formats cannot be moved."""

        async def go() -> None:
            await self._writes_done()
            states = await self._sheet_states()
            targets = ops.plan_move(states, mapping)
            if not targets:
                return
            moved_data = sorted(
                (loc for loc in states if self.device.expressions.get(loc, {}).get("dataId")
                 and mapping(*ops.rc_of(loc)) != ops.rc_of(loc)), key=lambda a: ops.rc_of(a))
            formats = [loc for loc in self.model.formats if loc in targets]
            notes = []
            if moved_data:
                notes.append("These cells hold data that cannot be moved through the In-Sight HMI API (for "
                             "example a trained pattern); they will need to be trained again:\n"
                             + ", ".join(moved_data))
            if formats:
                notes.append("Cell formats (fonts, colours, decimals) stay where they are: the In-Sight HMI API "
                             "cannot change them.")
            if notes and QMessageBox.question(self, label, "\n\n".join(notes) + "\n\nContinue?") \
                    != QMessageBox.StandardButton.Yes:
                return
            fut = self._apply_change(label, targets, before={loc: states.get(loc, ops.EMPTY) for loc in targets})
            if fut is not None and select is not None:
                fut.add_done_callback(lambda _f: self.sheet.select_block(select))

        return self.run(go(), label)

    # ------------------------------------------------------------------ Undo / Redo
    def undo(self) -> None:
        self._replay(self.history.take_undo() if self.act_undo.isEnabled() else None, undo=True)

    def redo(self) -> None:
        self._replay(self.history.take_redo() if self.act_redo.isEnabled() else None, undo=False)

    def _replay(self, change: Optional[ops.Change], undo: bool) -> None:
        if change is None:
            return
        states = change.before if undo else change.after
        targets = ops.restore_targets(states) if undo else dict(states)
        self._apply_change(f"{'Undo' if undo else 'Redo'} {change.label}", targets, record=False)

    # ------------------------------------------------------------------ Find / Replace
    def show_find(self) -> None:
        if not self.act_find.isEnabled():
            return
        if self.find_dialog is None:
            dlg = FindDialog(self)
            dlg.findRequested.connect(self.find_next)
            dlg.replaceRequested.connect(self.replace_current)
            dlg.replaceAllRequested.connect(self.replace_all)
            self.find_dialog = dlg
        self._update_actions()
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()
        self.find_dialog.find_box.setFocus()
        self.find_dialog.find_box.lineEdit().selectAll()

    def _search_texts(self, look: str) -> dict[str, str]:
        if look == ops.LOOK_NAMES:
            return dict(self.model.names)
        if look == ops.LOOK_VALUES:
            out = {}
            for loc, result in self.model.results.items():
                fmt = self.model.formats.get(loc)
                out[loc] = cells.display_text(result, self.model.expressions.get(loc, ""),
                                              fmt.decimals if fmt else None)
            return out
        return {loc: e for loc, e in self.model.expressions.items() if e}

    def find_next(self, forward: bool = True) -> Optional[str]:
        dlg = self.find_dialog
        if dlg is None:
            return None
        cur = self.sheet.currentIndex()
        start = (cur.row(), cur.column()) if cur.isValid() else None
        rc = ops.find_cell(self._search_texts(dlg.look()), dlg.what(), start, forward, dlg.by_rows(),
                           dlg.match_case.isChecked(), dlg.match_entire.isChecked(),
                           is_empty=lambda loc: not self.model.expressions.get(loc))
        if rc is None:
            self.statusBar().showMessage(f"Cannot find '{dlg.what()}'", 5000)
            QApplication.beep()
            return None
        loc = cells.address(*rc)
        self.sheet.select_location(loc)
        return loc

    def _matches_current(self) -> Optional[str]:
        dlg = self.find_dialog
        loc = self.sheet.current_location()
        if dlg is None or not loc or not dlg.what():
            return None
        text = self._search_texts(dlg.look()).get(loc)
        if text is None or not ops.text_matches(text, dlg.what(), dlg.match_case.isChecked(),
                                                dlg.match_entire.isChecked()):
            return None
        return loc

    def _replacement(self, text: str) -> str:
        dlg = self.find_dialog
        return ops.replace_text(text, dlg.what(), dlg.with_(), dlg.match_case.isChecked(),
                                dlg.match_entire.isChecked())

    def replace_current(self) -> None:
        """Replace: replaces in the found cell, then finds the next one."""
        dlg = self.find_dialog
        if dlg is None or not dlg.btn_replace.isEnabled():
            return
        loc = self._matches_current()
        if loc is not None:
            self._replace_in({loc}, "Replace")
        self.find_next(True)

    def replace_all(self) -> None:
        dlg = self.find_dialog
        if dlg is None or not dlg.btn_replace_all.isEnabled() or not dlg.what():
            return
        texts = self._search_texts(dlg.look())
        locs = {loc for loc, t in texts.items()
                if ops.text_matches(t, dlg.what(), dlg.match_case.isChecked(), dlg.match_entire.isChecked())}
        if not locs:
            self.statusBar().showMessage(f"Cannot find '{dlg.what()}'", 5000)
            return
        self._replace_in(locs, "Replace All")
        self.statusBar().showMessage(f"Replaced in {len(locs)} cell(s)", 5000)

    def _replace_in(self, locs: set[str], label: str) -> None:
        if self.find_dialog.look() == ops.LOOK_NAMES:
            targets = {loc: CellState(self.model.expressions.get(loc, ""), self._replacement(self.model.names[loc]))
                       for loc in locs}
            targets = {loc: t for loc, t in targets.items() if t.expr and t.name != self.model.names.get(loc)}
        else:
            targets = {loc: CellState(self._replacement(self.model.expressions[loc])) for loc in locs}
            targets = {loc: t for loc, t in targets.items() if t.expr != self.model.expressions.get(loc)}
        self._apply_change(label, targets)

    # ------------------------------------------------------------------ cell selection mode / references
    def insert_reference(self, absolute: bool) -> None:
        """Insert Absolute / Relative Reference: pick the cell(s) in cell selection mode."""
        if not self.act_abs_ref.isEnabled():
            return
        loc = self.sheet.current_location()
        if not loc:
            return
        cell_editor = self.sheet.editor_widget()
        if cell_editor is not None:  # continue the in-cell edit in the formula bar
            text, pos = cell_editor.text(), cell_editor.cursorPosition()
            self.sheet.cancel_editor()
            self.formula.setText(text)
            self.formula.setCursorPosition(pos)
            editing = True
        else:
            editing = self.formula.hasFocus() or self._formula_modified()
        if not editing and self.model.expressions.get(loc):
            # a cell with contents: the reference is added to its formula (edited in the formula bar)
            self.formula.setText(self.model.expressions[loc])
            self.formula.setCursorPosition(len(self.formula.text()))
            editing = True
        self.begin_cell_selection({"kind": "reference", "absolute": absolute, "location": loc,
                                   "editing": editing, "text": self.formula.text(),
                                   "cursor": self.formula.cursorPosition()})

    def begin_cell_selection(self, purpose: dict, dest: Optional[str] = None, start: Optional[str] = None) -> None:
        dest = dest or purpose.get("location") or self.sheet.current_location()
        if not dest:
            return
        if self.sheet.in_selection_mode:
            self.sheet.finish_selection_mode(False)
        self._select_purpose = purpose
        self.area.set_selection_mode(True)
        self.sheet.begin_selection_mode(dest, start or dest)
        self.area.set_message("Cell selection mode: select the cell(s) to reference — Enter or double-click "
                              "accepts, Escape cancels")
        self._update_actions()

    def _on_selection_mode_finished(self, text: Optional[str]) -> None:
        purpose, self._select_purpose = self._select_purpose, None
        self.area.set_selection_mode(False)
        self.area.set_message("")
        self._update_actions()
        if purpose is None:
            return
        if purpose["kind"] == "property_sheet":
            sheet = self.property_sheet
            if sheet is not None:
                if text is None or not sheet.insert_reference(text):
                    sheet.cancel_pick()
                sheet.show()
                sheet.raise_()
            return
        loc = purpose["location"]
        self._on_current_cell()
        if text is None:
            if purpose["editing"]:
                self.formula.setText(purpose["text"])
                self.formula.setFocus()
            return
        ref = self.reference_text(text, purpose["absolute"])
        if purpose["editing"]:
            t, pos = purpose["text"], purpose["cursor"]
            self.formula.setProperty("location", loc)
            self.formula.setText(t[:pos] + ref + t[pos:])
            self.formula.setCursorPosition(pos + len(ref))
            self.formula.setFocus()
            self._update_accept_cancel()
        else:
            self._commit_expression(loc, ref)

    @staticmethod
    def reference_text(range_text: str, absolute: bool) -> str:
        if not absolute:
            return range_text
        return ":".join(f"${a[0]}${a[1:]}" for a in range_text.split(":"))

    # ------------------------------------------------------------------ Hide / Unhide (view only)
    def _hide_target(self) -> Optional[tuple[ops.Block, bool]]:
        block = self.sheet.selection_block()
        if block is None:
            return None
        if ops.is_entire_rows(block):
            return block, True
        if ops.is_entire_columns(block):
            return block, False
        return None

    def hide_rows_columns(self) -> None:
        target = self._hide_target()
        if target is not None:
            self.sheet.hide_sections(*target)
            self.log("Hidden in this view only (not stored in the job)")

    def unhide_rows_columns(self) -> None:
        target = self._hide_target()
        if target is not None:
            self.sheet.unhide_sections(*target)

    def _on_cell_double_clicked(self, index) -> None:
        loc = cells.address(index.row(), index.column())
        if is_training_function(cells.function_name(self.model.expressions.get(loc, ""))):
            self.open_property_sheet(loc)
            return
        result = self.model.data(index, RESULT_ROLE)
        if cells.editable_graphic(result) and not self.model.read_only:
            self.edit_graphic()

    # ------------------------------------------------------------------ context menu (ISVS live/07, live/08)
    def build_cell_menu(self) -> QMenu:
        """The right-click menu of the grid, with the same items and order as ISVS."""
        loc = self.sheet.current_location() or ""
        expr = self.model.expressions.get(loc, "")
        offline = self.act_insert.isEnabled()  # connected, writable, offline, not editing a graphic
        has_content = any(self.model.expressions.get(x) for x in self.sheet.selected_locations())
        menu = QMenu(self)
        menu.setObjectName("cellMenu")
        menu.setToolTipsVisible(True)

        def item(target: QMenu, text: str, slot=None, icon: Optional[str] = None, enabled: bool = True,
                 note: str = "") -> QAction:
            act = target.addAction(text)
            if icon:
                act.setIcon(icons.icon(icon))
            if slot is not None:
                act.triggered.connect(lambda _c=False: slot())
            act.setEnabled(enabled and slot is not None)
            if note:
                act.setToolTip(note)
            return act

        def submenu(text: str) -> QMenu:
            sub = menu.addMenu(text)
            sub.setToolTipsVisible(True)
            return sub

        item(menu, "Cut", self.sheet.cut_selection, "cut", self.act_cut.isEnabled())
        item(menu, "Copy", self.sheet.copy_selection, "copy", self.act_copy.isEnabled())
        item(menu, "Paste", self.sheet.paste, "paste", self.act_paste.isEnabled())
        menu.addSeparator()
        item(menu, "Insert…", self.insert_cells, enabled=self.act_insert_cells.isEnabled())
        item(menu, "Delete…", self.delete_cells, enabled=self.act_delete_cells.isEnabled())
        clear = submenu("Clear")
        item(clear, "All", lambda: self._clear_selected("Clear All"), enabled=offline and has_content,
             note="Clears the contents, names and cell states of the selected cells")
        item(clear, "Contents", lambda: self._clear_selected("Clear Contents"), enabled=offline and has_content,
             note="On the vision system a cleared cell also loses its name and cell state")
        item(clear, "Formats", note=NO_FORMAT)
        item(clear, "Comments", note=NO_COMMENT)
        menu.addSeparator()
        if self._has_property_sheet(expr):
            item(menu, "Edit Function…", lambda: self.open_property_sheet(loc), "insert_function",
                 self.act_props.isEnabled())
        else:
            item(menu, "Insert Function…", self.insert_function, "insert_function", offline)
        item(menu, "Insert Absolute Reference…", lambda: self.insert_reference(True), "abs_ref",
             self.act_abs_ref.isEnabled())
        item(menu, "Insert Relative Reference…", lambda: self.insert_reference(False), "rel_ref",
             self.act_rel_ref.isEnabled())
        item(menu, "Insert Comment…", None, "comment", note=NO_COMMENT)
        item(menu, "Insert Cell Name…", self.set_cell_name, "cell_name", self.act_name.isEnabled())
        item(menu, "Insert Getters", note=NOT_YET)
        menu.addSeparator()
        item(menu, "Cell Graphic…", self.edit_graphic, "edit_graphic", self.act_edit_graphic.isEnabled())
        item(menu, "Cell State…", None, "cell_state", note=NOT_YET)
        ip = submenu("IP Licensing")
        item(ip, "Protect Cells", note=NO_PROTECT)
        item(ip, "Unprotect Cells", note=NO_PROTECT)
        menu.addSeparator()
        fmt = submenu("Format")
        item(fmt, "Cell(s)", note=NOT_YET)
        item(fmt, "Row Height…", note=NOT_YET)
        item(fmt, "Column Width…", note=NOT_YET)
        target = self._hide_target()
        only_view = "Hidden rows/columns are a setting of this view only (not stored in the job)"
        item(fmt, "Hide", self.hide_rows_columns, enabled=target is not None,
             note=only_view if target else "Select entire rows or columns")
        item(fmt, "Unhide", self.unhide_rows_columns,
             enabled=target is not None and self.sheet.has_hidden(*target),
             note="Select the rows/columns on both sides of the hidden ones")
        menu.addSeparator()
        item(menu, "Import Snippet…", note=NOT_YET)
        item(menu, "Export Snippet…", note=NOT_YET)
        menu.addSeparator()
        easy = submenu("Publish to EasyView")
        item(easy, "Selected", note=NOT_YET)
        item(easy, "Named", note=NOT_YET)
        menu.addSeparator()
        item(menu, "Create Custom View", note=NOT_YET)
        return menu

    def _clear_selected(self, label: str) -> None:
        locs = [loc for loc in self.sheet.selected_locations() if self.model.expressions.get(loc)]
        if locs:
            self._clear_cells(locs, label)

    def _show_cell_menu(self, pos) -> None:
        self._update_actions()
        menu = self.build_cell_menu()
        menu.exec(pos)
        menu.deleteLater()

    # ------------------------------------------------------------------ in-cell controls and editor
    def _write_cell_value(self, loc: str, value) -> None:
        """An in-cell control was operated (checkbox, list, spin, edit box, button)."""
        if cells.result_kind(self.model.results.get(loc)) == "ButtonResult" and value == "1":
            self.log(f"{loc} pressed")
        else:
            self.log(f"{loc} = {value}")
        self.run(self.device.set_cell_value(loc, value), f"Setting {loc}")

    def _edit_graphic_at(self, loc: str) -> None:
        if self.sheet.current_location() != loc:
            self.sheet.select_location(loc)
        if self.act_edit_graphic.isEnabled():
            self.edit_graphic()

    def _on_cell_editor_text(self, text: str) -> None:
        """The formula bar mirrors the cell while it is typed in."""
        self.formula.setText(text)
        self._update_accept_cancel()

    def _after_cell_editor_closed(self) -> None:
        if not self._cell_editing():
            self._on_current_cell()

    def refresh_sheet(self) -> None:
        async def go() -> None:
            await self.device.refresh_sheet()
            await self.device.latest_result()

        self.run(go(), "Refresh")

    # ------------------------------------------------------------------ functions
    def _completion_functions(self) -> list[FunctionInfo]:
        """Functions offered while typing: the catalog plus functions used in the current job."""
        funcs = list(self.catalog.functions)
        for name in functions_in_expressions(self.model.expressions.values()):
            if not self.catalog.get(name):
                funcs.append(FunctionInfo(name=name, params=None, category="Used in this job"))
        return funcs

    def _on_function_completed(self, f: FunctionInfo, editor=None) -> None:
        """A function was picked from the completion list. As in ISVS, a function with a property
        sheet that makes up the whole cell opens its property sheet right away."""
        self.statusBar().showMessage(f.short_signature, 15000)
        if editor is None or not f.has_property_sheet or self.model.read_only:
            return
        text = editor.text().strip()
        if not (text.startswith(f.name) and text[len(f.name):].strip() in ("()", "(", "")
                or f.template and text == f.template):
            return
        loc = self.formula.property("location") if editor is self.formula else self.sheet.current_location()
        if not loc:
            return

        def go() -> None:
            if editor is self.formula:
                self._on_current_cell()  # drop the typed text; the insert writes the cell
            else:
                self.sheet.cancel_editor()
            self.insert_function_into(loc, f)

        QTimer.singleShot(0, go)  # after the completer has finished with the editor

    def _insert_function_from_panel(self, f: FunctionInfo) -> None:
        loc = self.sheet.current_location()
        if loc:
            self.insert_function_into(loc, f)

    def _function_dropped(self, loc: str, name: str) -> None:
        """A function was dragged from the Functions panel onto a cell."""
        f = self.catalog.get(name)
        if f is None or not loc:
            return
        self.sheet.select_location(loc)
        self.insert_function_into(loc, f)

    def insert_function(self) -> None:
        loc = self.sheet.current_location()
        if not loc:
            return
        if self._has_property_sheet(self.model.expressions.get(loc, "")):
            # ISVS: a cell that already holds a function opens its property sheet instead
            self.open_property_sheet(loc)
            return
        dlg = InsertFunctionDialog(self.catalog, loc, self)
        dlg.helpRequested.connect(self._open_help_for)
        if dlg.exec() == InsertFunctionDialog.DialogCode.Accepted and dlg.selected():
            self.insert_function_into(loc, dlg.selected())

    def _has_property_sheet(self, expr: str) -> bool:
        """The cell is one function call with a property sheet ("Edit Function…"). Functions the
        catalog does not know get one too (their arguments are listed by position)."""
        parsed = split_call(expr)
        if parsed is None:
            return False
        info = self.catalog.get(parsed[0])
        return info is None or info.has_property_sheet

    def _image_size(self) -> Optional[tuple[int, int]]:
        img = self.image.image()
        return None if img.isNull() else (img.width(), img.height())

    def insert_function_into(self, loc: str, f: FunctionInfo):
        """Inserts a function into a cell, as ISVS does: a function with a property sheet is
        written with its default arguments and its property sheet opens (Cancel restores the
        cell); any other function goes into the formula bar as ``Name()`` to be completed."""
        if self.model.read_only or self.formula.isReadOnly():
            self.log("Go offline to edit the job")
            return None
        expr = default_expression(f, self._image_size()) if f.has_property_sheet else None
        if expr is None:
            self.sheet.select_location(loc)
            self._put_function_in_formula(f)
            return None
        previous = self.model.expressions.get(loc, "")
        fut = self._apply_change(f"Insert {f.name}", {loc: CellState(expr)}, record=False,
                                 log=f"{loc} ← {expr}")
        if fut is None:
            return None

        def written(_f=None) -> None:
            # accepted (the device may echo it reformatted): the cell now holds this function
            if (cells.function_name(self.model.expressions.get(loc, "")) or "").lower() == f.name.lower():
                self.sheet.select_location(loc)
                self.open_property_sheet(loc, previous=previous)
            else:  # refused by the vision system: let the user complete it in the formula bar
                self.log(f"{f.name}: the default arguments were refused; complete the function in the formula bar")
                self.sheet.select_location(loc)
                self._put_function_in_formula(f)

        fut.add_done_callback(written)
        return fut

    def _put_function_in_formula(self, f: FunctionInfo) -> None:
        if self.formula.isReadOnly():
            self.log("Go offline to edit the job")
            return
        text = f.insert_text()
        self.formula.setText(text)
        self.formula.setFocus()
        if not f.template and text.endswith("()"):
            self.formula.setCursorPosition(len(text) - 1)
        self.statusBar().showMessage(f"{f.short_signature} — press Enter to write it to the cell", 10000)

    # ------------------------------------------------------------------ property sheet
    def _on_job_info(self, job: dict) -> None:
        self._job_name = str(job.get("name") or "")
        self._update_session_title()
        self._update_health()

    def open_property_sheet(self, loc: Optional[str] = None, previous: Optional[str] = None) -> None:
        """Opens the property sheet of a function cell. ``previous``: what Cancel restores when
        the function was just inserted (by default the cell's expression when the sheet opens)."""
        loc = loc or self.sheet.current_location()
        expr = self.model.expressions.get(loc or "", "")
        parsed = split_call(expr)
        if not loc or parsed is None:
            self.log("The cell does not contain a function")
            return
        if self.property_sheet is not None:
            self.property_sheet.close()
        sheet = PropertySheet(loc, expr, self.catalog.get(parsed[0]), self.model, self, previous=previous,
                              image_size=self._native_image_size)
        sheet.regionShown.connect(lambda payload, s=sheet: self._property_sheet_region(s, payload))
        sheet.functionRequested.connect(lambda s=sheet: self._property_sheet_function(s))
        sheet.maximizeRequested.connect(self.maximize_region)
        sheet.expressionChanged.connect(self._property_sheet_expression)
        sheet.valueRequested.connect(self._property_sheet_value)
        sheet.graphicEditRequested.connect(self._property_sheet_graphic)
        sheet.pickStarted.connect(lambda _mode, s=sheet: self._property_sheet_pick(s))
        sheet.helpRequested.connect(lambda: self._open_function_help(parsed[0]))
        sheet.finished.connect(lambda _r, s=sheet: self._property_sheet_closed(s))
        self.property_sheet = sheet
        self._update_actions()
        sheet.set_permissions(*self._property_sheet_permissions())
        sheet.show()

    def _property_sheet_permissions(self) -> tuple[bool, bool]:
        d = self.device
        writable = d.connected and not d.read_only
        editing = self._editing_location is not None
        return writable and not editing, writable and not d.online and not editing

    def _property_sheet_closed(self, sheet: PropertySheet) -> None:
        if self._param_edit is sheet:
            self._end_param_edit()
        if self.property_sheet is sheet:
            self.property_sheet = None
            if self._select_purpose and self._select_purpose.get("kind") == "property_sheet":
                self._select_purpose = None
                self.sheet.finish_selection_mode(False)
        # the whole property sheet session is one Undo step
        if sheet.result() == PropertySheet.DialogCode.Accepted and sheet._written != sheet.original_expression:
            self.history.push(ops.Change(f"Edit {sheet.location}", {sheet.location: CellState(sheet.original_expression)},
                                         {sheet.location: CellState(sheet._written)}))
            self._update_actions()
        sheet.deleteLater()

    def _property_sheet_pick(self, sheet: PropertySheet) -> None:
        """Property sheet $A$1 / A1 buttons: the sheet steps aside for cell selection mode."""
        if self.property_sheet is not sheet:
            return
        sheet.hide()
        self.begin_cell_selection({"kind": "property_sheet"}, dest=sheet.location)

    def _property_sheet_expression(self, loc: str, expr: str) -> None:
        self.model.mark_pending(loc, expr)
        self._commit_expression(loc, expr, record=False)

    def _property_sheet_value(self, loc: str, value) -> None:
        self.log(f"{loc} pressed" if value == "1" and cells.result_kind(self.model.results.get(loc)) == "ButtonResult"
                 else f"{loc} = {value}")
        self.run(self.device.set_cell_value(loc, value), f"Setting {loc}")

    def _property_sheet_region(self, sheet: PropertySheet, payload: Optional[dict]) -> None:
        """The property sheet selected (or left) a region parameter given by numbers: it is shown
        on the image without the grid and can be dragged there (Interactive Graphics Mode); the
        numbers follow in the sheet."""
        if sheet is not self.property_sheet or self._editing_location is not None:
            return
        if payload is None:
            if self._param_edit is sheet:
                self._end_param_edit()
            return
        editor = self.image.editor if self._param_edit is sheet else None
        if editor is not None and editor.value.get("$type") == payload["graphic"]["$type"] \
                and editor.flags == payload["flags"]:
            editor.set_value(payload["graphic"])
            editor.set_transform(payload["transform"])
        else:
            editor = self.image.begin_edit(payload["graphic"], payload["transform"], payload["flags"])
            editor.changed.connect(sheet.graphic_edited)
        self._param_edit = sheet
        self.area.set_grid_suppressed(True)
        hint = "drag the region or its handles" if payload["flags"].get("move") else "go offline to edit it"
        note = f" — {payload['note']}" if payload.get("note") else ""
        self.area.set_message(f"{payload['label']}: {hint}{note}")

    def _end_param_edit(self) -> None:
        if self._param_edit is None:
            return
        self._param_edit = None
        if self._editing_location is None:
            self.image.end_edit()
            self.area.set_grid_suppressed(False)
            self.area.set_message("")

    def _property_sheet_function(self, sheet: PropertySheet) -> None:
        """Property sheet Insert ▸ Function: the function goes into the parameter being typed."""
        dlg = InsertFunctionDialog(self.catalog, sheet.location, sheet)
        dlg.helpRequested.connect(self._open_help_for)
        if dlg.exec() == InsertFunctionDialog.DialogCode.Accepted and dlg.selected():
            sheet.insert_text(dlg.selected().insert_text())

    def _property_sheet_graphic(self, loc: str) -> None:
        if self.property_sheet is not None:
            self.property_sheet.hide()
        self.sheet.select_location(loc)
        fut = self.edit_graphic()

        def started(_f=None) -> None:  # editing did not start: bring the sheet back
            if self._editing_location is None and self.property_sheet is not None:
                self.property_sheet.show()

        if fut is None:
            started()
        else:
            fut.add_done_callback(started)

    def _open_function_help(self, fn: str) -> None:
        info = self.catalog.get(fn)
        if info is not None:
            self._open_help_for(info)
        else:
            QMessageBox.information(self, "Help", f"No help for {fn}.")

    def _open_help_for(self, sel) -> None:
        """F1 in the Functions panel / Insert Function dialog: the function's or category's help page."""
        rel = sel.help if isinstance(sel, (FunctionInfo, Category)) else None
        path = help_file(rel)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, "Help", f"No local help for {sel.name} (In-Sight Vision Suite is not "
                                                  "installed on this computer).")

    def spreadsheet_help(self) -> None:
        for version_dir in editor_versions():
            page = version_dir / "Docs" / "Help_InSight" / "Default.htm"
            if page.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(page)))
                return
        QMessageBox.information(self, "Help", "The In-Sight Vision Suite help is not installed on this computer.")

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

    # ------------------------------------------------------------------ graphic editing
    def edit_graphic(self):
        loc = self.sheet.current_location()
        result = self.model.results.get(loc or "")
        graphic = cells.editable_graphic(result)
        if not loc or graphic is None:
            return None
        function = cells.function_name(self.model.expressions.get(loc, ""))
        if function is None and str(result.get("name") or "").startswith("Edit"):
            function = str(result["name"])  # appendix A: the Edit* function's name

        async def go() -> None:
            target, editing = graphic, None
            try:
                editing = await self.device.begin_edit(loc)
                # API 3.0 devices return an "Editing<Type>" object whose data is the graphic.
                if isinstance(editing, dict) and isinstance(editing.get("data"), dict) \
                        and editing["data"].get("$type") == graphic.get("$type"):
                    target = editing["data"]
            except CogSocketError as e:
                self.log(f"beginEdit not available ({e}); editing locally")
            self._end_param_edit()
            try:
                self.image.begin_edit(target, flags=edit_flags(editing, result), function=function)
            except ValueError as e:
                await self.device.end_edit()
                raise DeviceError(str(e)) from e
            self._editing_location = loc
            self.area.set_grid_suppressed(True)
            kind = "masked region" if self.image.editor.masked else graphic.get("$type")
            extra = "; right-click for the menu" if self.image.editor.composite and not self.image.editor.polyline else ""
            self.area.set_message(f"Interactive Graphics Mode: {kind} in {loc} — drag the shape or its handles{extra}; "
                                  "Return accepts, Escape cancels")
            self._update_actions()

        return self.run(go(), f"Editing graphic {loc}")

    def maximize_region(self, loc: Optional[str] = None) -> None:
        """Maximize Cell Region: the region of an Edit graphic cell is resized to the image."""
        loc = loc or self.sheet.current_location()
        graphic = cells.editable_graphic(self.model.results.get(loc or ""))
        size = self._native_image_size()
        if not loc or (graphic or {}).get("$type") != "Region" or size is None:
            return
        value = dict(graphic, x=0.0, y=0.0, w=float(size[0]), h=float(size[1]), angle=0.0, curve=0.0)
        self.log(f"{loc}: region maximized to {size[0]}×{size[1]}")
        self.run(self.device.set_cell_value(loc, round_graphic(value)), f"Maximizing {loc}")

    def _native_image_size(self) -> Optional[tuple[int, int]]:
        """Image width/height in the device's graphic coordinates (row/column on old devices)."""
        size = self._image_size()
        if size is None:
            return None
        info = self.device.info if self.device.connected else None
        return size if info is None or info.uses_xy else (size[1], size[0])

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
        self.area.set_grid_suppressed(False)
        self.area.set_message("")
        self._update_actions()
        if self.property_sheet is not None and not self.property_sheet.isVisible():
            self.property_sheet.show()  # back from editing a graphic of the property sheet

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

    def toggle_repeating_trigger(self, on: bool) -> None:
        """Repeating Trigger: triggers again REPEAT_TRIGGER_MS after each result (done by this client)."""
        self._repeat_timer.stop()
        if on:
            self.trigger()

    def _repeat_trigger_tick(self) -> None:
        if self.act_repeat.isChecked() and self.act_repeat.isEnabled():
            self.trigger()

    def save_image(self) -> None:
        img = self.image.image()
        if img.isNull():
            return
        path, flt = QFileDialog.getSaveFileName(self, "Save Image As", str(Path(self._last_dir()) / "Image.bmp"),
                                                SAVE_IMAGE_FILTER)
        if not path:
            return
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix({"JPEG": ".jpg", "PNG": ".png"}.get(flt.split(" ")[0], ".bmp"))
        self._remember_dir(str(p))
        if img.save(str(p)):
            self.log(f"Image saved as {p}")
        else:
            QMessageBox.warning(self, "Save Image As", f"Could not save {p}.")

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

    def open_job(self) -> None:
        """Open Job: a job on the vision system, or (PC… button) a .jobx file on this computer."""
        self.open_job_on_device(allow_pc=True)

    def open_job_on_device(self, allow_pc: bool = False) -> None:
        async def go() -> None:
            files = await self.device.list_files()
            jobs = [f for f in files if str(f.get("name", "")).lower().endswith((".job", ".jobx"))
                    or int(f.get("attributes", 1)) & 8]
            dlg = DeviceFilesDialog(jobs, save=False, parent=self, title="Open Job",
                                    pc_button="PC…" if allow_pc else "")
            if dlg.exec() != DeviceFilesDialog.DialogCode.Accepted:
                return
            if dlg.use_pc:
                self.upload_job()
                return
            if not dlg.filename():
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
                dlg = DeviceFilesDialog(files, save=True, default_name=target or "job.jobx", parent=self,
                                        title="Save Job As", pc_button="PC…")
                if dlg.exec() != DeviceFilesDialog.DialogCode.Accepted:
                    return
                if dlg.use_pc:
                    self.download_job()
                    return
                if not dlg.filename():
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
            self.restoreState(st, self.STATE_VERSION)  # ignored when saved by an older layout
        try:
            self.area.restore_state(json.loads(str(s.value("window/view", "{}"))))
        except ValueError:
            pass
        self.banner_bar.setVisible(bool(self.banner.text()))
        self._update_view_actions()

    def closeEvent(self, event) -> None:
        s = QSettings()
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/state", self.saveState(self.STATE_VERSION))
        s.setValue("window/view", json.dumps(self.area.save_state()))
        if self.device.connected:
            spawn(self.device.disconnect_from())
        super().closeEvent(event)
