"""Entry point: python -m insight_studio [--connect HOST] [--user USER] [--password PW]"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="insight-studio", description="Spreadsheet job editor for In-Sight")
    parser.add_argument("--connect", metavar="HOST", help="connect to HOST[:port] on start")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    ns = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if ns.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setOrganizationName("InsightStudio")
    app.setApplicationName("Insight Studio")
    win = MainWindow()
    win.show()
    if ns.connect:
        win.log(f"Connecting to {ns.connect}…")
        win.run(win.device.connect_to(ns.connect, ns.user, ns.password), f"Connecting to {ns.connect}")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
