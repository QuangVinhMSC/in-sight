import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def pump_until(qapp, cond, timeout_ms=4000):
    from PySide6.QtCore import QDeadlineTimer

    deadline = QDeadlineTimer(timeout_ms)
    while not cond():
        if deadline.hasExpired():
            raise TimeoutError("condition not met")
        qapp.processEvents()


@pytest.fixture
def window(qapp, tmp_path):
    """Main window connected to a fake In-Sight device: (window, fake, errors)."""
    from PySide6.QtCore import QSettings

    from insight_studio.devtools.fake_insight import FakeInSight
    from insight_studio.main_window import MainWindow
    from insight_studio.qtasync import wait

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
