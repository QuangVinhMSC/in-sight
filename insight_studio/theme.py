"""Dark theme modelled on the In-Sight Vision Suite 26.1 Spreadsheet (colours sampled from screenshots)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

# Window chrome
FRAME = "#666666"  # gaps between panels, splitters
TITLE = "#4a4a4a"  # title/tab strip, dock titles, input boxes
BAR = "#404040"  # menu bar, toolbars, status bar
PANEL = "#565656"  # panel contents (function tree, empty image area)
TEXT = "#e0e0e0"
TEXT_DIM = "#c8c8c8"
TEXT_DISABLED = "#808080"
ACCENT = "#ffd800"  # active session tab text
BANNER = "#fff200"  # job message banner, active header section
SELECT = "#3d6fb0"

# Spreadsheet grid
CELL = QColor(212, 212, 212)  # #d4d4d4
CELL_SELECTED = QColor(218, 228, 244)  # #dae4f4
GRID_LINE = "#b0b0b0"
HEADER = "#f0f0f0"
CELL_TEXT = "#000080"  # ISVS default foreground: Navy

STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BAR}; }}
QMainWindow::separator {{ background: {FRAME}; width: 4px; height: 4px; }}
QToolTip {{ background: {BAR}; color: {TEXT}; border: 1px solid #8a8a8a; padding: 2px; }}

QMenuBar {{ background: {BAR}; color: {TEXT}; }}
QMenuBar::item {{ padding: 3px 8px; background: transparent; }}
QMenuBar::item:selected {{ background: #5a5a5a; }}
QMenu {{ background: #2f2f2f; color: {TEXT}; border: 1px solid #707070; }}
QMenu::item {{ padding: 4px 24px 4px 26px; }}
QMenu::item:selected {{ background: #5a5a5a; }}
QMenu::item:disabled {{ color: {TEXT_DISABLED}; }}
QMenu::separator {{ height: 1px; background: #606060; margin: 3px 6px; }}

QToolBar {{ background: {BAR}; border: 0; spacing: 1px; padding: 1px 2px; }}
QToolBar::separator {{ background: #6a6a6a; width: 2px; margin: 3px 4px; }}
QToolBar::handle {{ image: none; width: 4px; border-left: 2px dotted #8a8a8a; margin: 3px 2px; }}
QToolButton {{ color: {TEXT}; border: 1px solid transparent; border-radius: 0; padding: 2px; }}
QToolButton:hover {{ background: #5a5a5a; border-color: #8a8a8a; }}
QToolButton:pressed {{ background: #6a6a6a; }}
QToolButton:checked {{ background: #556887; border-color: #9fb7dc; }}
QToolButton[popupMode="1"] {{ padding-right: 11px; }}
QToolButton::menu-button {{ border: 0; background: transparent; width: 10px; }}
QToolButton::menu-indicator {{ subcontrol-position: bottom right; width: 0; }}
QToolButton#tabClose {{ background: transparent; color: {TEXT}; border: 0; padding: 0 2px; font-size: 13pt; }}
QToolButton#tabClose:hover {{ color: #ffffff; background: #6a6a6a; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {TITLE}; color: {TEXT}; border: 1px solid #6e6e6e; selection-background-color: {SELECT}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {TEXT_DISABLED}; border-color: #5a5a5a; }}
QComboBox QAbstractItemView {{ background: #2f2f2f; color: {TEXT}; selection-background-color: #5a5a5a; }}

QDockWidget {{ color: {TEXT_DIM}; titlebar-close-icon: none; }}
QDockWidget::title {{ background: {TITLE}; padding: 7px 8px; text-align: left; }}
QDockWidget > QWidget {{ background: {PANEL}; }}

QTabBar::tab {{ background: {PANEL}; color: {TEXT}; padding: 6px 8px; border: 0; }}
QTabBar::tab:selected {{ background: {TITLE}; }}
QTabBar::tab:hover {{ background: #626262; }}

QStatusBar {{ background: {BAR}; color: {TEXT}; }}
QStatusBar::item {{ border: 0; }}

QTreeView, QListView, QTreeWidget, QListWidget {{ background: {PANEL}; color: {TEXT}; border: 0;
    selection-background-color: {SELECT}; }}
QTreeView::item:disabled, QListView::item:disabled {{ color: {TEXT_DISABLED}; }}
QScrollBar:vertical {{ background: {PANEL}; width: 14px; margin: 0; }}
QScrollBar:horizontal {{ background: {PANEL}; height: 14px; margin: 0; }}
QScrollBar::handle {{ background: #6f6f6f; min-height: 20px; min-width: 20px; }}
QScrollBar::handle:hover {{ background: #858585; }}
QScrollBar::add-line, QScrollBar::sub-line {{ background: {PANEL}; width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSplitter::handle {{ background: {FRAME}; }}
QGroupBox {{ color: {TEXT}; }}
QCheckBox, QRadioButton, QLabel {{ color: {TEXT}; }}
QPushButton {{ background: #555555; color: {TEXT}; border: 1px solid #7a7a7a; padding: 4px 14px; }}
QPushButton:hover {{ background: #616161; }}
QPushButton:disabled {{ color: {TEXT_DISABLED}; }}

/* Spreadsheet grid: light cells on a dark frame, yellow active headers */
QTableView#sheet {{ color: {CELL_TEXT}; gridline-color: {GRID_LINE}; border: 0; outline: 0;
    background: transparent; selection-color: {CELL_TEXT}; }}
QTableView#sheet QHeaderView {{ background: {HEADER}; }}
QTableView#sheet QHeaderView::section {{ background: {HEADER}; color: #000000; border: 0;
    border-right: 1px solid {GRID_LINE}; border-bottom: 1px solid {GRID_LINE}; padding: 0 2px; }}
QTableView#sheet QHeaderView::section:checked {{ background: {BANNER}; }}
QTableView#sheet QTableCornerButton::section {{ background: {HEADER}; border: 0; }}

/* Session tab strip */
#sessionBar {{ background: {TITLE}; }}
#sessionBar QLabel#appTitle {{ color: {TEXT}; font-size: 13pt; padding: 0 10px 0 4px; }}
#sessionBar QTabBar::tab {{ background: {TITLE}; color: {TEXT}; padding: 7px 10px; font-size: 12pt; }}
#sessionBar QTabBar::tab:selected {{ background: #3d3d3d; color: {ACCENT}; }}
#sessionBar QToolButton {{ background: #5e5e5e; padding: 5px; }}

#banner {{ background: {BANNER}; color: #000000; padding: 1px 4px; }}
#editorFrame {{ background: {BAR}; border: 1px solid #1e1e1e; }}
#pixelStrip {{ background: {BAR}; color: #999999; padding: 2px 4px; }}
#onlineBox {{ background: #d3d3d3; color: #000000; padding: 0 4px; min-width: 120px; }}
#onlineBox[online="true"] {{ background: #4caf50; color: #ffffff; }}
#placeholder {{ color: {TEXT_DIM}; padding: 12px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 13px; border-left: 1px solid #6e6e6e;
    background: #4a4a4a; }}
QAbstractSpinBox::up-arrow {{ border-left: 3px solid none; border-right: 3px solid none;
    border-bottom: 4px solid {TEXT}; width: 0; height: 0; }}
QAbstractSpinBox::down-arrow {{ border-left: 3px solid none; border-right: 3px solid none;
    border-top: 4px solid {TEXT}; width: 0; height: 0; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{
    border-top-color: {TEXT_DISABLED}; border-bottom-color: {TEXT_DISABLED}; }}
"""


def palette() -> QPalette:
    p = QPalette()
    roles = QPalette.ColorRole
    for role, color in ((roles.Window, BAR), (roles.WindowText, TEXT), (roles.Base, TITLE),
                        (roles.AlternateBase, PANEL), (roles.Button, "#555555"), (roles.ButtonText, TEXT),
                        (roles.Text, TEXT), (roles.BrightText, "#ffffff"), (roles.Highlight, SELECT),
                        (roles.HighlightedText, "#ffffff"), (roles.ToolTipBase, BAR), (roles.ToolTipText, TEXT),
                        (roles.PlaceholderText, "#9a9a9a"), (roles.Link, "#6fa8ff"), (roles.Light, "#6a6a6a"),
                        (roles.Midlight, "#5a5a5a"), (roles.Mid, "#4a4a4a"), (roles.Dark, "#2e2e2e"),
                        (roles.Shadow, "#1e1e1e")):
        p.setColor(role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        p.setColor(disabled, role, QColor(TEXT_DISABLED))
    return p


def apply(app: QApplication) -> None:
    """Applies the ISVS-like dark look to the whole application."""
    style = QStyleFactory.create("Fusion")
    if style is not None:
        app.setStyle(style)
    app.setPalette(palette())
    font = app.font()
    font.setPointSizeF(9.0)  # ISVS uses a 9 pt UI font
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
