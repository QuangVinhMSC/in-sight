"""Dialogs: connect, device files."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


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


class DeviceFilesDialog(QDialog):
    """Picks a job file on the device (open) or enters a file name (save)."""

    def __init__(self, files: list[dict], save: bool, default_name: str = "", parent=None,
                 title: str = "", pc_button: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title or ("Save job on device" if save else "Open job on device"))
        self.use_pc = False  # True when the user chose the PC instead of the device
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
        if pc_button:
            pc = buttons.addButton(pc_button, QDialogButtonBox.ButtonRole.ActionRole)
            pc.clicked.connect(self._choose_pc)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Files on the In-Sight vision system:"))
        layout.addWidget(self.list, 1)
        form = QFormLayout()
        form.addRow("File name:", self.name)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _choose_pc(self) -> None:
        self.use_pc = True
        self.accept()

    def filename(self) -> str:
        return self.name.text().strip()
