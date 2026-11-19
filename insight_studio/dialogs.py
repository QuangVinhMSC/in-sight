"""Dialogs: connect, insert function, set cell value, device files."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
)

from . import cells
from .catalog import Catalog, FunctionInfo


class ConnectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to In-Sight device")
        settings = QSettings()
        recent = settings.value("connect/recent", []) or []
        if isinstance(recent, str):
            recent = [recent]
        self.host = QComboBox()
        self.host.setEditable(True)
        self.host.addItems(recent)
        self.host.setCurrentText(recent[0] if recent else "192.168.0.10")
        self.host.setToolTip("IP address or host name, optionally with :port (Web HMI port, default 80)")
        self.user = QLineEdit(settings.value("connect/user", "admin"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout()
        form.addRow("Device:", self.host)
        form.addRow("User:", self.user)
        form.addRow("Password:", self.password)
        note = QLabel("The Web HMI must be enabled on the device (ISVS ▸ Utilities ▸ HMI Settings).")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.password.setFocus()

    def values(self) -> tuple[str, str, str]:
        return self.host.currentText().strip(), self.user.text().strip(), self.password.text()

    def remember(self) -> None:
        settings = QSettings()
        host = self.host.currentText().strip()
        recent = [h for h in (settings.value("connect/recent", []) or []) if h != host]
        settings.setValue("connect/recent", [host] + recent[:9])
        settings.setValue("connect/user", self.user.text().strip())


class InsertFunctionDialog(QDialog):
    def __init__(self, catalog: Catalog, target: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Insert function into {target}")
        self.resize(520, 480)
        self.catalog = catalog
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search functions…")
        self.search.textChanged.connect(self._refresh)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        self.signature = QLabel()
        self.signature.setWordWrap(True)
        self.signature.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.signature.setMinimumHeight(48)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Insert")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.signature)
        layout.addWidget(buttons)
        self._refresh("")
        self.search.setFocus()

    def _refresh(self, text: str) -> None:
        self.list.clear()
        for f in self.catalog.search(text):
            item = QListWidgetItem(f.name)
            item.setData(Qt.ItemDataRole.UserRole, f)
            item.setToolTip(f.signature)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _show(self, item: Optional[QListWidgetItem]) -> None:
        f: Optional[FunctionInfo] = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not f:
            self.signature.setText("")
            return
        text = f"<b>{f.signature}</b>"
        if f.template:
            text += f"<br>Inserts: <code>{f.template}</code>"
        else:
            text += "<br>Inserts the function name; fill in the arguments in the formula bar."
        self.signature.setText(text)

    def selected(self) -> Optional[FunctionInfo]:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


class SetValueDialog(QDialog):
    """Edits the value of an HMI control cell (EditInt, EditFloat, EditString, CheckBox, ListBox)."""

    def __init__(self, location: str, result: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Set value of {location}")
        self.kind = cells.result_kind(result)
        data = result.get("data")
        form = QFormLayout()
        if self.kind == "EditIntResult":
            self.editor = QSpinBox()
            self.editor.setRange(int(result.get("min", -2147483648)), int(result.get("max", 2147483647)))
            self.editor.setValue(int(data or 0))
        elif self.kind == "EditFloatResult":
            self.editor = QDoubleSpinBox()
            self.editor.setDecimals(4)
            self.editor.setRange(float(result.get("min", -1e12)), float(result.get("max", 1e12)))
            self.editor.setValue(float(data or 0))
        elif self.kind == "EditStringResult":
            self.editor = QLineEdit("" if data is None else str(data))
            if result.get("maxLength"):
                self.editor.setMaxLength(int(result["maxLength"]))
            if result.get("maskInput"):
                self.editor.setEchoMode(QLineEdit.EchoMode.Password)
        elif self.kind == "CheckBoxResult":
            self.editor = QCheckBox(result.get("caption") or "")
            self.editor.setChecked(bool(data))
        elif self.kind == "ListBoxResult":
            self.editor = QComboBox()
            self.editor.addItems([str(o) for o in result.get("options") or []])
            self.editor.setCurrentIndex(int(data or 0))
        else:
            raise ValueError(f"{location} is not an editable control")
        form.addRow(f"{result.get('name') or location}:", self.editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def value(self) -> Any:
        if self.kind == "EditIntResult":
            return self.editor.value()
        if self.kind == "EditFloatResult":
            return self.editor.value()
        if self.kind == "EditStringResult":
            return self.editor.text()
        if self.kind == "CheckBoxResult":
            return 1 if self.editor.isChecked() else 0
        if self.kind == "ListBoxResult":
            return self.editor.currentIndex()
        return None


class DeviceFilesDialog(QDialog):
    """Picks a job file on the device (open) or enters a file name (save)."""

    def __init__(self, files: list[dict], save: bool, default_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save job on device" if save else "Open job on device")
        self.resize(420, 380)
        self.list = QListWidget()
        for f in files:
            if int(f.get("attributes", 1)) & 8:
                continue  # directory
            name = str(f.get("name", ""))
            item = QListWidgetItem(f"{name}    ({int(f.get('size', 0)) // 1024} KB)")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
        self.name = QLineEdit(default_name)
        self.list.currentItemChanged.connect(
            lambda it, *_: it and self.name.setText(it.data(Qt.ItemDataRole.UserRole)))
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save" if save else "Open")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Files on the device:"))
        layout.addWidget(self.list, 1)
        form = QFormLayout()
        form.addRow("File name:", self.name)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def filename(self) -> str:
        return self.name.text().strip()
