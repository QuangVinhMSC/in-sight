"""Toolbar icons drawn with QPainter (own artwork, in the spirit of the ISVS toolbar).

Each icon is drawn on a 16x16 grid. ``icon(name)`` returns a cached QIcon with a normal and a
greyed-out disabled version.
"""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

COLORS = {
    "fg": "#e8e8e8", "dark": "#202020", "paper": "#ffffff", "grey": "#9a9a9a", "blue": "#1f5fbf",
    "lblue": "#7fb2ff", "yellow": "#f0c040", "folder": "#e8b860", "red": "#e02020", "green": "#3cb043",
    "orange": "#f0a020", "navy": "#2040a0", "cell": "#d8d8d8",
}


class _Colors:
    def __init__(self, disabled: bool) -> None:
        self.disabled = disabled

    def __call__(self, name: str, alpha: int = 255) -> QColor:
        c = QColor(COLORS.get(name, name))
        if self.disabled:
            g = int(0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue())
            g = 70 + g * 60 // 255  # flat grey, low contrast on the dark toolbar
            c = QColor(g, g, g)
        c.setAlpha(alpha)
        return c


Draw = Callable[[QPainter, _Colors], None]
_ICONS: dict[str, Draw] = {}
_CACHE: dict[str, QIcon] = {}


def _icon(name: str):
    def deco(fn: Draw) -> Draw:
        _ICONS[name] = fn
        return fn
    return deco


def _pen(p: QPainter, color: QColor, width: float = 1.0) -> None:
    pen = QPen(color, width)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(pen)


def _rect(p: QPainter, x, y, w, h, fill: QColor | None, line: QColor | None, width: float = 1.0) -> None:
    p.setBrush(QBrush(fill) if fill is not None else Qt.BrushStyle.NoBrush)
    if line is None:
        p.setPen(Qt.PenStyle.NoPen)
    else:
        _pen(p, line, width)
    p.drawRect(QRectF(x, y, w, h))


def _poly(p: QPainter, pts, fill: QColor | None, line: QColor | None, width: float = 1.0, close=True) -> None:
    poly = QPolygonF([QPointF(x, y) for x, y in pts])
    p.setBrush(QBrush(fill) if fill is not None else Qt.BrushStyle.NoBrush)
    if line is None:
        p.setPen(Qt.PenStyle.NoPen)
    else:
        _pen(p, line, width)
    p.drawPolygon(poly) if close else p.drawPolyline(poly)


def _text(p: QPainter, rect, text: str, color: QColor, size: float, bold=False, italic=False,
          family="DejaVu Sans") -> None:
    f = QFont(family)
    f.setPixelSize(max(1, int(size)))
    f.setBold(bold)
    f.setItalic(italic)
    p.setFont(f)
    p.setPen(color)
    p.drawText(QRectF(*rect), Qt.AlignmentFlag.AlignCenter, text)


def _page(p, c, x=3.5, y=1.5, w=9, h=13) -> None:
    _poly(p, [(x, y), (x + w - 3, y), (x + w, y + 3), (x + w, y + h), (x, y + h)], c("paper"), c("dark"))
    _poly(p, [(x + w - 3, y), (x + w - 3, y + 3), (x + w, y + 3)], None, c("dark"), close=False)


def _folder(p, c, x=1.5, y=3.5, w=13, h=10) -> None:
    _poly(p, [(x, y), (x + 4, y), (x + 5, y + 1.5), (x + w, y + 1.5), (x + w, y + h), (x, y + h)],
          c("folder"), c("dark"))
    _poly(p, [(x, y + 4), (x + w, y + 4)], None, c("#b08030"), close=False)


def _floppy(p, c, x=2.5, y=2.5, s=11) -> None:
    _rect(p, x, y, s, s, c("blue"), c("dark"))
    _rect(p, x + 2.5, y, s - 5, 4, c("paper"), None)
    _rect(p, x + 2, y + s - 4, s - 4, 4, c("lblue"), None)


def _picture(p, c, x=4.5, y=4.5, w=10, h=9, back="paper") -> None:
    _rect(p, x, y, w, h, c(back), c("dark"))
    _poly(p, [(x + 1, y + h - 1), (x + 4, y + h - 5), (x + 6, y + h - 3), (x + 7.5, y + h - 4.5),
              (x + w - 1, y + h - 1)], c("dark"), None)


def _magnifier(p, c, cx=6.5, cy=6.5, r=4.5) -> None:
    _pen(p, c("fg"), 1.6)
    p.setBrush(QBrush(c("#3a5a8a")))
    p.drawEllipse(QPointF(cx, cy), r, r)
    _pen(p, c("fg"), 2.6)
    p.drawLine(QPointF(cx + r * 0.7, cy + r * 0.7), QPointF(14.5, 14.5))


def _grid(p, c, x=2.5, y=2.5, w=11, h=11, fill="cell") -> None:
    _rect(p, x, y, w, h, c(fill), c("dark"))
    _pen(p, c("dark"), 1)
    for i in range(1, 3):
        p.drawLine(QPointF(x + w * i / 3, y), QPointF(x + w * i / 3, y + h))
        p.drawLine(QPointF(x, y + h * i / 3), QPointF(x + w, y + h * i / 3))


def _arrow(p, c, color, x1, y1, x2, y2, head=3.0, width=1.6) -> None:
    _pen(p, c(color), width)
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    a = math.atan2(y2 - y1, x2 - x1)
    pts = [(x2, y2), (x2 - head * math.cos(a - 0.5), y2 - head * math.sin(a - 0.5)),
           (x2 - head * math.cos(a + 0.5), y2 - head * math.sin(a + 0.5))]
    _poly(p, pts, c(color), None)


def _curve_arrow(p, c, flip: bool) -> None:
    path = QPainterPath()
    if not flip:
        path.moveTo(4, 7)
        path.cubicTo(6, 3, 13, 3, 13, 8)
        path.cubicTo(13, 12, 9, 14, 6, 13)
        tip, wing = (2.5, 8.5), [(2.5, 3.5), (7, 7)]
    else:
        path.moveTo(12, 7)
        path.cubicTo(10, 3, 3, 3, 3, 8)
        path.cubicTo(3, 12, 7, 14, 10, 13)
        tip, wing = (13.5, 8.5), [(13.5, 3.5), (9, 7)]
    _pen(p, c("lblue"), 2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    _poly(p, [tip] + wing, c("lblue"), None)


# ------------------------------------------------------------------ file / sensor
@_icon("new_job")
def _(p, c):
    _page(p, c)


@_icon("open_job")
def _(p, c):
    _folder(p, c)


@_icon("save_job")
def _(p, c):
    _floppy(p, c)


@_icon("trigger")
def _(p, c):
    _poly(p, [(2, 1.5), (2, 12), (4.5, 9.5), (6.5, 14), (8, 13.3), (6, 9), (9.5, 9)], c("paper"), c("dark"))
    _text(p, (8, 7, 8, 9), "1", c("fg"), 9, bold=True)


@_icon("repeat_trigger")
def _(p, c):
    _pen(p, c("fg"), 1.6)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(2.5, 2.5, 11, 11), 30 * 16, 260 * 16)
    _poly(p, [(12.5, 1.5), (13.8, 6.2), (9.2, 5.2)], c("fg"), None)
    _text(p, (4, 4, 8, 8), "1", c("fg"), 7, bold=True)


@_icon("live_video")
def _(p, c):
    _rect(p, 1.5, 5.5, 9, 7, c("paper"), c("dark"))
    _poly(p, [(10.5, 7.5), (14.5, 5.5), (14.5, 12.5), (10.5, 10.5)], c("paper"), c("dark"))
    _arrow(p, c, "green", 5, 9, 9, 3, head=3, width=1.4)


@_icon("online")
def _(p, c):
    _poly(p, [(4, 2), (13, 8), (4, 14)], c("green"), c("#1d7a2a"))


@_icon("offline")
def _(p, c):
    _rect(p, 3.5, 3.5, 9, 9, c("red"), c("#801010"))


@_icon("home")
def _(p, c):
    _poly(p, [(1.5, 8), (8, 2), (14.5, 8), (12.5, 8), (12.5, 14), (9.5, 14), (9.5, 10), (6.5, 10), (6.5, 14),
              (3.5, 14), (3.5, 8)], c("paper"), None)


@_icon("app")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, c("yellow"), c("dark"))
    _pen(p, c("dark"), 1.6)
    p.setBrush(QBrush(c("dark")))
    p.drawEllipse(QPointF(8, 8), 3.6, 3.6)
    p.setBrush(QBrush(c("yellow")))
    p.drawEllipse(QPointF(8, 8), 1.4, 1.4)


# ------------------------------------------------------------------ control
@_icon("open_image")
def _(p, c):
    _folder(p, c, 1, 6, 9, 8)
    _picture(p, c, 6.5, 2.5, 8, 7)


@_icon("save_image")
def _(p, c):
    _floppy(p, c, 1.5, 6.5, 8)
    _picture(p, c, 6.5, 2.5, 8, 7)


@_icon("cut")
def _(p, c):
    _pen(p, c("fg"), 1.4)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(4.5, 12), 2.3, 2.3)
    p.drawEllipse(QPointF(11.5, 12), 2.3, 2.3)
    p.drawLine(QPointF(6, 10.3), QPointF(11, 1.5))
    p.drawLine(QPointF(10, 10.3), QPointF(5, 1.5))


@_icon("copy")
def _(p, c):
    _rect(p, 2.5, 1.5, 8, 10, c("paper"), c("dark"))
    _rect(p, 5.5, 4.5, 8, 10, c("paper"), c("dark"))


@_icon("paste")
def _(p, c):
    _rect(p, 2.5, 3.5, 11, 11, c("folder"), c("dark"))
    _rect(p, 5.5, 2, 5, 3, c("grey"), c("dark"))
    _rect(p, 6.5, 7.5, 6, 6, c("paper"), c("dark"))


@_icon("undo")
def _(p, c):
    _curve_arrow(p, c, False)


@_icon("redo")
def _(p, c):
    _curve_arrow(p, c, True)


@_icon("find")
def _(p, c):
    _pen(p, c("fg"), 1.6)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(9.5, 6.5), 4, 4)
    _pen(p, c("fg"), 2.4)
    p.drawLine(QPointF(6.5, 9.5), QPointF(1.8, 14.2))


# ------------------------------------------------------------------ image display
@_icon("zoom_in")
def _(p, c):
    _magnifier(p, c)
    _pen(p, c("paper"), 1.4)
    p.drawLine(QPointF(4.3, 6.5), QPointF(8.7, 6.5))
    p.drawLine(QPointF(6.5, 4.3), QPointF(6.5, 8.7))


@_icon("zoom_out")
def _(p, c):
    _magnifier(p, c)
    _pen(p, c("paper"), 1.4)
    p.drawLine(QPointF(4.3, 6.5), QPointF(8.7, 6.5))


@_icon("zoom_1to1")
def _(p, c):
    _magnifier(p, c)
    _text(p, (3, 3, 7, 7), "1", c("paper"), 6, bold=True)


@_icon("zoom_fill")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, c("cell"), c("dark"))
    _magnifier(p, c, 7, 7, 3.5)


@_icon("zoom_fit")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, None, c("fg"))
    _rect(p, 4.5, 4.5, 7, 7, c("cell"), c("dark"))
    _pen(p, c("lblue"), 1.4)
    for x1, y1, x2, y2 in ((2.5, 2.5, 4.5, 4.5), (13.5, 2.5, 11.5, 4.5), (2.5, 13.5, 4.5, 11.5),
                           (13.5, 13.5, 11.5, 11.5)):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


@_icon("rotate")
def _(p, c):
    _picture(p, c, 1.5, 5.5, 10, 9)
    _pen(p, c("lblue"), 1.6)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(6, 1, 9, 9), 0, 150 * 16)
    _poly(p, [(15.5, 4.5), (13.5, 7.5), (12, 4.5)], c("lblue"), None)


@_icon("saturation")
def _(p, c):
    _rect(p, 1.5, 2.5, 13, 11, c("orange"), c("dark"))
    _poly(p, [(2.5, 12.5), (6, 7), (8.5, 10), (10.5, 8), (13.5, 12.5)], c("dark"), None)
    _rect(p, 10, 4, 2.5, 2.5, c("paper"), None)


@_icon("change_split")
def _(p, c):
    _grid(p, c, 1.5, 1.5, 13, 13, "paper")
    _pen(p, c("red"), 2)
    p.drawLine(QPointF(2, 2), QPointF(14, 14))
    p.drawLine(QPointF(14, 2), QPointF(2, 14))


@_icon("transparency_up")
def _(p, c):
    _grid(p, c, 1.5, 3.5, 9, 11, "cell")
    _rect(p, 10.5, 3.5, 4, 11, c("paper"), c("dark"))
    _arrow(p, c, "red", 12.5, 13, 12.5, 2, head=3.5, width=2)


@_icon("transparency_down")
def _(p, c):
    _grid(p, c, 1.5, 1.5, 9, 11, "grey")
    _rect(p, 10.5, 1.5, 4, 11, c("paper"), c("dark"))
    _arrow(p, c, "red", 12.5, 3, 12.5, 14.5, head=3.5, width=2)


@_icon("show_grid")
def _(p, c):
    _grid(p, c, 1.5, 2.5, 13, 11, "paper")


@_icon("show_graphics")
def _(p, c):
    _picture(p, c, 1.5, 3.5, 13, 11)
    _pen(p, c("red"), 1.4)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(8, 7.5), 3.2, 3.2)
    p.drawLine(QPointF(8, 3), QPointF(8, 12))
    p.drawLine(QPointF(3.5, 7.5), QPointF(12.5, 7.5))


@_icon("text_scale")
def _(p, c):
    _picture(p, c, 1.5, 4.5, 9, 10, "orange")
    _rect(p, 7.5, 1.5, 7, 7, c("paper"), c("dark"))
    _text(p, (7.5, 1.5, 7, 7), "T", c("dark"), 7, bold=True)


# ------------------------------------------------------------------ cell formatting
@_icon("bold")
def _(p, c):
    _text(p, (1, 0, 14, 16), "B", c("fg"), 14, bold=True)


@_icon("italic")
def _(p, c):
    _text(p, (1, 0, 14, 16), "I", c("fg"), 14, italic=True, family="DejaVu Serif")


def _align(p, c, mode: str) -> None:
    _pen(p, c("fg"), 1.6)
    for i, w in enumerate((12, 8, 12, 8)):
        y = 3 + i * 3.3
        x = {"left": 2, "center": 2 + (12 - w) / 2, "right": 14 - w}[mode]
        p.drawLine(QPointF(x, y), QPointF(x + w, y))


@_icon("align_left")
def _(p, c):
    _align(p, c, "left")


@_icon("align_center")
def _(p, c):
    _align(p, c, "center")


@_icon("align_right")
def _(p, c):
    _align(p, c, "right")


@_icon("decimal_more")
def _(p, c):
    _text(p, (5, 0, 11, 16), ".00", c("fg"), 7, bold=True)
    _arrow(p, c, "green", 6, 4, 1, 4, head=3, width=1.4)


@_icon("decimal_less")
def _(p, c):
    _text(p, (5, 0, 11, 16), ".0", c("fg"), 7, bold=True)
    _arrow(p, c, "green", 1, 12, 6, 12, head=3, width=1.4)


@_icon("back_color")
def _(p, c):
    _poly(p, [(3, 7), (8, 2), (13, 7), (8, 12)], c("paper"), c("dark"))
    _rect(p, 1.5, 13, 13, 2.5, c("yellow"), None)


@_icon("fore_color")
def _(p, c):
    _text(p, (1, -1, 14, 14), "A", c("lblue"), 12, bold=True)
    _rect(p, 1.5, 13, 13, 2.5, c("navy"), None)


# ------------------------------------------------------------------ cell dependency
def _boxes(p, c, color="fg") -> None:
    _rect(p, 1.5, 1.5, 5, 4, c("paper"), c("dark"))
    _rect(p, 9.5, 6, 5, 4, c("paper"), c("dark"))
    _rect(p, 1.5, 10.5, 5, 4, c("paper"), c("dark"))
    _pen(p, c(color), 1.2)
    p.drawLine(QPointF(6.5, 3.5), QPointF(9.5, 8))
    p.drawLine(QPointF(6.5, 12.5), QPointF(9.5, 8))


@_icon("dep_more")
def _(p, c):
    _boxes(p, c, "red")
    _arrow(p, c, "red", 4, 6, 4, 10, head=2.5, width=1.2)


@_icon("dep_less")
def _(p, c):
    _boxes(p, c, "grey")


@_icon("dep_reset")
def _(p, c):
    _boxes(p, c, "grey")
    _pen(p, c("red"), 1.4)
    p.drawLine(QPointF(9, 11), QPointF(15, 15))


@_icon("dep_errors")
def _(p, c):
    _poly(p, [(8, 1.5), (15, 14.5), (1, 14.5)], c("#a04040"), c("dark"))
    _text(p, (4, 4, 8, 11), "!", c("paper"), 9, bold=True)


@_icon("dep_first_error")
def _(p, c):
    _grid(p, c, 1.5, 1.5, 11, 13, "paper")
    _rect(p, 4.5, 3, 2, 7, c("red"), None)
    _rect(p, 4.5, 11, 2, 2, c("red"), None)
    _arrow(p, c, "green", 15.5, 9, 10, 9, head=3, width=1.6)


# ------------------------------------------------------------------ cell editing
@_icon("abs_ref")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, c("grey"), c("dark"))
    _rect(p, 4.5, 3.5, 7, 9, c("paper"), c("dark"))
    _text(p, (4.5, 3.5, 7, 9), "$", c("dark"), 8, bold=True)


@_icon("rel_ref")
def _(p, c):
    _grid(p, c, 1.5, 1.5, 13, 13, "grey")


@_icon("insert_function")
def _(p, c):
    _text(p, (0, 0, 16, 15), "fx", c("fg"), 11, bold=True, italic=True, family="DejaVu Serif")


@_icon("edit_graphic")
def _(p, c):
    _rect(p, 1.5, 1.5, 10, 9, None, c("fg"), 1.4)
    _poly(p, [(8, 7), (8, 15), (10, 13), (11.5, 15.5), (12.8, 14.8), (11.4, 12.4), (14, 12.4)], c("paper"),
          c("dark"))


@_icon("maximize_region")
def _(p, c):
    _rect(p, 4.5, 4.5, 7, 7, None, c("fg"), 1.2)
    _pen(p, c("fg"), 1.4)
    for x, y, dx, dy in ((1.5, 1.5, 1, 1), (14.5, 1.5, -1, 1), (1.5, 14.5, 1, -1), (14.5, 14.5, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + 3.5 * dx, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + 3.5 * dy))


@_icon("help")
def _(p, c):
    p.setBrush(Qt.BrushStyle.NoBrush)
    _pen(p, c("fg"), 1.4)
    p.drawEllipse(QRectF(1.5, 1.5, 13, 13))
    _text(p, (1.5, 1.5, 13, 13), "?", c("fg"), 9, bold=True)


@_icon("cell_state")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, c("orange"), c("dark"))
    _poly(p, [(3, 13), (13, 3), (13, 13)], c("paper"), None)
    _text(p, (2, 1, 8, 9), "/", c("dark"), 9, bold=True)


@_icon("comment")
def _(p, c):
    _poly(p, [(1.5, 2.5), (14.5, 2.5), (14.5, 10.5), (7, 10.5), (4, 14), (4, 10.5), (1.5, 10.5)], c("paper"),
          c("dark"))


@_icon("cell_name")
def _(p, c):
    _rect(p, 1.5, 3.5, 13, 9, c("paper"), c("dark"))
    _text(p, (1.5, 3.5, 13, 9), "<>", c("dark"), 7, bold=True)


@_icon("accept")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, c("grey"), c("dark"))
    _poly(p, [(4, 8), (7, 11), (12.5, 4.5)], None, c("green"), 2.2, close=False)


@_icon("cancel")
def _(p, c):
    _grid(p, c, 1.5, 1.5, 13, 13, "grey")
    _pen(p, c("red"), 2)
    p.drawLine(QPointF(6, 7), QPointF(13.5, 14.5))
    p.drawLine(QPointF(13.5, 7), QPointF(6, 14.5))


def _render(fn: Draw, size: int, disabled: bool) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(size / 16.0, size / 16.0)
    fn(p, _Colors(disabled))
    p.end()
    return pm


def icon(name: str) -> QIcon:
    """The named toolbar icon (empty icon for unknown names)."""
    if name in _CACHE:
        return _CACHE[name]
    fn = _ICONS.get(name)
    ic = QIcon()
    if fn is not None:
        for size in (16, 24, 32, 48):
            ic.addPixmap(_render(fn, size, False), QIcon.Mode.Normal)
            ic.addPixmap(_render(fn, size, True), QIcon.Mode.Disabled)
    _CACHE[name] = ic
    return ic


def names() -> list[str]:
    return sorted(_ICONS)


# ------------------------------------------------------------------ toolbox categories
# Own artwork for the Functions panel / Insert Function dialog, one per toolbox category (the
# Vision Tools subcategories have their own, as in ISVS); a function shows its category's icon.
def _wrench(p, c, color="grey") -> None:
    _pen(p, c(color), 2.4)
    p.drawLine(QPointF(4, 12), QPointF(10, 6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    _pen(p, c(color), 2)
    p.drawArc(QRectF(8.5, 2, 6, 6), -60 * 16, 270 * 16)


def _hammer(p, c) -> None:
    _pen(p, c("#c08040"), 2)
    p.drawLine(QPointF(3, 13), QPointF(10, 6))
    _poly(p, [(7, 3), (11, 2), (14, 5), (12, 7), (9, 5)], c("grey"), c("dark"))


@_icon("cat:All")
@_icon("cat:Vision Tools")
@_icon("cat:Vision Tools/Bead")
def _(p, c):
    _hammer(p, c)
    _pen(p, c("red"), 2)
    p.drawLine(QPointF(4, 4), QPointF(12, 12))


@_icon("cat:Edge AI")
def _(p, c):
    _pen(p, c("lblue"), 1.4)
    p.setBrush(QBrush(c("#506080")))
    p.drawEllipse(QRectF(2, 3, 12, 10))
    _pen(p, c("fg"), 1)
    for x1, y1, x2, y2 in ((5, 6, 8, 9), (8, 9, 11, 6), (8, 9, 8, 12), (5, 6, 5, 10)):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


@_icon("cat:Vision Tools/Blob")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, c("dark"), None)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(c("green")))
    p.drawEllipse(QRectF(3, 3, 6, 5))
    p.setBrush(QBrush(c("red")))
    p.drawEllipse(QRectF(8, 8, 5, 5))


@_icon("cat:Vision Tools/Color")
def _(p, c):
    for i, col in enumerate(("red", "green", "blue", "red", "green", "blue")):
        _rect(p, 2 + i * 2, 2, 1.6, 12, c(col), None)


@_icon("cat:Vision Tools/Edge")
def _(p, c):
    _poly(p, [(1.5, 14.5), (14.5, 1.5), (14.5, 14.5)], c("#505050"), None)
    _pen(p, c("#c08060"), 1.6)
    p.drawLine(QPointF(1.5, 14.5), QPointF(14.5, 1.5))


@_icon("cat:Vision Tools/Histogram")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, c("paper"), c("dark"))
    for i, hgt in enumerate((4, 9, 6, 11, 7)):
        _rect(p, 3 + i * 2.2, 13 - hgt, 1.6, hgt, c("navy"), None)


@_icon("cat:Vision Tools/ID")
def _(p, c):
    _rect(p, 1.5, 1.5, 13, 13, c("paper"), c("dark"))
    for x, y in ((3, 3), (9, 3), (3, 9), (7, 7), (11, 11), (11, 7), (7, 11)):
        _rect(p, x, y, 2.5 if (x, y) in ((7, 7), (11, 11), (11, 7), (7, 11)) else 4, 2.5 if (x, y) in (
            (7, 7), (11, 11), (11, 7), (7, 11)) else 4, c("dark"), None)


@_icon("cat:Vision Tools/Image")
def _(p, c):
    _grid(p, c, 1.5, 1.5, 13, 13, "grey")


@_icon("cat:Vision Tools/InspectEdge")
def _(p, c):
    _magnifier(p, c, 6.5, 6.5, 4.5)


@_icon("cat:Vision Tools/OCV/OCR")
def _(p, c):
    _rect(p, 1.5, 3.5, 13, 9, c("#404040"), c("grey"))
    _text(p, (1.5, 3.5, 13, 9), "OCR", c("fg"), 5.5, bold=True)


@_icon("cat:Vision Tools/Pattern Match")
def _(p, c):
    _pen(p, c("fg"), 1.4)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(8, 8), 4, 4)
    p.drawLine(QPointF(8, 1.5), QPointF(8, 14.5))
    p.drawLine(QPointF(1.5, 8), QPointF(14.5, 8))


@_icon("cat:Geometry")
def _(p, c):
    _poly(p, [(2, 14), (2, 2), (14, 14)], c("#c06030"), c("dark"))
    _poly(p, [(4.5, 12), (4.5, 7.5), (9, 12)], c("#404040"), None)


@_icon("cat:Graphics")
def _(p, c):
    _pen(p, c("#c08040"), 2)
    p.drawLine(QPointF(4, 12), QPointF(13, 3))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(c("orange")))
    p.drawEllipse(QRectF(1.5, 10, 4.5, 4.5))


@_icon("cat:Mathematics")
def _(p, c):
    for i, col in enumerate(("green", "yellow", "red")):
        _pen(p, c(col), 1.4)
        p.drawLine(QPointF(1.5 + i * 2, 14.5), QPointF(12.5 + i, 1.5 + i * 2))


@_icon("cat:Robotics String Functions")
def _(p, c):
    _pen(p, c("grey"), 2.2)
    p.drawLine(QPointF(3, 14), QPointF(5, 7))
    p.drawLine(QPointF(5, 7), QPointF(11, 4))
    _pen(p, c("fg"), 1.4)
    p.drawLine(QPointF(11, 4), QPointF(13, 7))
    p.drawLine(QPointF(11, 4), QPointF(14, 3))
    _rect(p, 1.5, 13, 5, 2, c("grey"), None)


@_icon("cat:Text")
def _(p, c):
    _text(p, (0, 4, 8, 12), "a", c("fg"), 10, bold=True)
    _rect(p, 8, 3.5, 6.5, 11, c("orange"), c("dark"))
    _text(p, (8, 3.5, 6.5, 11), "b", c("paper"), 8, bold=True)


@_icon("cat:Coordinate Transforms")
def _(p, c):
    _rect(p, 1.5, 2.5, 13, 11, c("#4070c0"), c("lblue"))
    _pen(p, c("paper"), 1)
    p.drawLine(QPointF(3, 12), QPointF(13, 4))


@_icon("cat:Input/Output")
def _(p, c):
    _rect(p, 3.5, 1.5, 9, 13, c("#303030"), c("grey"))
    for y in (4, 8, 12):
        _rect(p, 1.5, y - 1, 2, 2, c("yellow"), None)
        _rect(p, 12.5, y - 1, 2, 2, c("lblue"), None)


@_icon("cat:Clocked Data Storage")
def _(p, c):
    _rect(p, 2.5, 4.5, 11, 10, c("#4070c0"), c("dark"))
    p.setBrush(QBrush(c("paper")))
    _pen(p, c("dark"), 1)
    p.drawEllipse(QRectF(8, 1.5, 6.5, 6.5))
    p.drawLine(QPointF(11.25, 4.75), QPointF(11.25, 2.8))
    p.drawLine(QPointF(11.25, 4.75), QPointF(12.8, 4.75))


@_icon("cat:Vision Data Access")
def _(p, c):
    _rect(p, 1.5, 2.5, 13, 11, c("yellow"), c("dark"))
    _poly(p, [(3, 11), (6, 6), (9, 9), (13, 4)], None, c("navy"), 1.4, close=False)


@_icon("cat:White Balance")
def _(p, c):
    _hammer(p, c)
    _pen(p, c("paper"), 2)
    p.drawLine(QPointF(4, 4), QPointF(12, 12))


@_icon("cat:Structures")
def _(p, c):
    p.setBrush(Qt.BrushStyle.NoBrush)
    _pen(p, c("fg"), 2.2)
    p.drawArc(QRectF(2.5, 2.5, 11, 11), 30 * 16, 300 * 16)
    _rect(p, 8, 7.5, 5, 2, c("fg"), None)


@_icon("cat:Scripting")
def _(p, c):
    _page(p, c, 2.5, 1.5, 11, 13)
    _pen(p, c("orange"), 1)
    for y in (6, 8.5, 11):
        p.drawLine(QPointF(4.5, y), QPointF(11.5, y))


@_icon("cat:Arrays and Objects")
def _(p, c):
    _text(p, (0, 0, 16, 16), "[··]", c("yellow"), 9, bold=True)


@_icon("cat:Advanced AI")
@_icon("cat:Focus")
def _(p, c):
    _pen(p, c("lblue"), 1.4)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(8, 8), 5.5, 5.5)
    p.drawEllipse(QPointF(8, 8), 2, 2)


def category_icon(path) -> QIcon:
    """Icon of a toolbox category path (the Vision Tools subcategories have their own)."""
    path = tuple(path or ())
    if not path:
        return icon("cat:All")
    full = "cat:" + "/".join(path[:2])
    return icon(full if full in _ICONS else "cat:" + path[0])
