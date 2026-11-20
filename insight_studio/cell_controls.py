"""In-cell HMI controls and cell markers drawn by the spreadsheet delegate.

ISVS draws HMI functions as live widgets inside their cells (help: Button, CheckBox, EditInt,
ListBox, MultiStatus pages): a raised push button with the caption, a checkbox with its label,
a white edit box with spin arrows, a drop-down list, coloured status lights. Named cells get a
small blue triangle in the bottom-right corner.

The delegate only paints and hit-tests; :class:`insight_studio.sheet.SheetView` handles the
mouse and asks the main window to write values (``setCellValue``).
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from . import cells
from .catalog import FunctionInfo
from .completion import ExpressionDelegate, ExpressionLineEdit

EXPR_ROLE = Qt.ItemDataRole.UserRole + 1
RESULT_ROLE = Qt.ItemDataRole.UserRole + 2
NAME_ROLE = Qt.ItemDataRole.UserRole + 3
PENDING_ROLE = Qt.ItemDataRole.UserRole + 4

NAME_MARK = QColor(0, 0, 255)
CONTROL_TEXT = QColor(0, 0, 128)  # ISVS default cell foreground (Navy)
DISABLED_TEXT = QColor(150, 150, 150)
FIELD_BACK = QColor(255, 255, 255)
FIELD_BORDER = QColor(127, 157, 185)
BUTTON_FACE = QColor(236, 233, 216)
BUTTON_LIGHT = QColor(255, 255, 255)
BUTTON_SHADOW = QColor(128, 128, 128)
BUTTON_DARK = QColor(64, 64, 64)
CHECK_BORDER = QColor(28, 81, 128)

VALUE_KINDS = {"editint", "editfloat", "editstring"}  # edited in a box over the cell
CLICK_KINDS = {"checkbox", "listbox", "button", "graphic", "editint", "editfloat", "editstring"}


def _alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(min(c.alpha(), alpha))
    return c


def _zoom(index) -> float:
    return float(getattr(index.model(), "zoom", 1.0) or 1.0)


def _cell_alpha(index) -> int:
    return int(getattr(index.model(), "cell_alpha", 255))


def control_parts(kind: str, rect: QRect, zoom: float = 1.0, caption_width: int = 0) -> dict[str, QRect]:
    """Clickable parts of a control drawn in ``rect`` (the cell rectangle).

    ``field``: the edit box / list text; ``up``/``down``: spin arrows; ``drop``: the list arrow;
    ``check``: checkbox and its label; ``button``: the whole push button.
    """
    r = rect.adjusted(0, 0, -1, -1)
    parts: dict[str, QRect] = {}
    if kind in ("button", "graphic"):
        parts["button"] = r
    elif kind == "checkbox":
        s = min(max(7, round(11 * zoom)), max(7, r.height() - 4))
        box = QRect(r.left() + 3, r.center().y() - s // 2, s, s)
        parts["box"] = box
        parts["check"] = QRect(r.left(), r.top(), min(r.width(), s + 8 + caption_width), r.height())
    elif kind == "listbox":
        w = min(r.width() // 2, max(9, round(15 * zoom)))
        parts["drop"] = QRect(r.right() - w + 1, r.top(), w, r.height())
        parts["field"] = QRect(r.left(), r.top(), r.width() - w, r.height())
    elif kind in ("editint", "editfloat"):
        w = min(r.width() // 3, max(7, round(11 * zoom)))
        half = r.height() // 2
        parts["up"] = QRect(r.right() - w + 1, r.top(), w, half)
        parts["down"] = QRect(r.right() - w + 1, r.top() + half, w, r.height() - half)
        parts["field"] = QRect(r.left(), r.top(), r.width() - w, r.height())
    elif kind == "editstring":
        parts["field"] = r
    return parts


class SheetDelegate(ExpressionDelegate):
    """Cell delegate: expression editor with completion, in-cell controls and name markers."""

    editorTextChanged = Signal(str)  # text of the in-cell expression editor while typing

    def __init__(self, source: Callable[[], list[FunctionInfo]],
                 on_inserted: Optional[Callable[..., None]] = None, parent=None) -> None:
        super().__init__(source, on_inserted, parent)
        self.pressed: Optional[tuple[int, int]] = None  # (row, col) of a button held down

    # ------------------------------------------------------------------ expression editor
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, ExpressionLineEdit):
            editor.textChanged.connect(self.editorTextChanged)
        return editor

    # ------------------------------------------------------------------ geometry
    def kind(self, index) -> Optional[str]:
        if index.data(PENDING_ROLE):
            return None
        return cells.control_kind(index.data(RESULT_ROLE))

    def parts(self, index, rect: QRect, font=None) -> dict[str, QRect]:
        kind = self.kind(index)
        if kind is None:
            return {}
        caption_width = 0
        if kind == "checkbox":
            result = index.data(RESULT_ROLE) or {}
            fm = QFontMetrics(font) if font is not None else QApplication.fontMetrics()
            caption_width = fm.horizontalAdvance(str(result.get("caption") or ""))
        return control_parts(kind, rect, _zoom(index), caption_width)

    def hit_part(self, index, rect: QRect, pos, font=None) -> Optional[str]:
        for name, r in self.parts(index, rect, font).items():
            if name != "box" and r.contains(pos):
                return name
        return None

    # ------------------------------------------------------------------ painting
    def paint(self, painter: QPainter, option, index) -> None:
        kind = self.kind(index)
        if kind is None:
            super().paint(painter, option, index)
        else:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            style = opt.widget.style() if opt.widget is not None else QApplication.style()
            style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, opt.widget)
            painter.save()
            painter.setClipRect(option.rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            self._paint_control(painter, opt, index, kind)
            painter.restore()
        if index.data(NAME_ROLE):
            self._paint_name_marker(painter, option.rect, _zoom(index))

    @staticmethod
    def _text_color(index, result: dict) -> QColor:
        if result.get("disabled"):
            return DISABLED_TEXT
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(brush, QBrush):
            return brush.color()
        return CONTROL_TEXT

    def _paint_control(self, p: QPainter, opt, index, kind: str) -> None:
        result = index.data(RESULT_ROLE) or {}
        alpha = _cell_alpha(index)
        zoom = _zoom(index)
        rect = opt.rect
        parts = self.parts(index, rect, opt.font)
        color = self._text_color(index, result)
        disabled = bool(result.get("disabled"))
        p.setFont(opt.font)
        pad = max(2, round(3 * zoom))

        if kind in ("button", "graphic"):
            pressed = self.pressed == (index.row(), index.column())
            r = parts["button"]
            self._paint_button(p, r, pressed, alpha)
            caption = str(result.get("caption") or "")
            if kind == "graphic" and not caption:
                data = result.get("data")
                caption = str(data.get("$type")) if isinstance(data, dict) else "Graphic"
            glyph = max(5, round(9 * zoom))
            g = QRect(r.left() + pad, r.center().y() - glyph // 2 + 1, glyph, max(4, glyph * 2 // 3))
            if pressed:
                g.translate(1, 1)
            p.setPen(QPen(_alpha(color, 255), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if kind == "graphic":
                p.drawRect(g.adjusted(0, -1, 0, 0))
            else:
                p.drawRoundedRect(QRectF(g), 1.5, 1.5)
                p.drawLine(g.bottomLeft() + QPointF(1, 1).toPoint(), g.bottomRight() + QPointF(1, 1).toPoint())
            text_r = r.adjusted(pad + glyph + 3, 0, -pad, 0)
            if pressed:
                text_r.translate(1, 1)
            p.setPen(color)
            p.drawText(text_r, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), caption)
        elif kind == "checkbox":
            box = parts["box"]
            p.fillRect(box, _alpha(FIELD_BACK, alpha))
            p.setPen(QPen(DISABLED_TEXT if disabled else CHECK_BORDER, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(box)
            if result.get("data"):
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                pen = QPen(DISABLED_TEXT if disabled else QColor(33, 161, 33), max(1.5, 2 * zoom))
                p.setPen(pen)
                b = QRectF(box).adjusted(2.5, 2.5, -2, -2)
                path = QPainterPath(QPointF(b.left(), b.center().y()))
                path.lineTo(b.left() + b.width() * 0.4, b.bottom())
                path.lineTo(b.right(), b.top())
                p.drawPath(path)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setPen(color)
            p.drawText(rect.adjusted(box.right() - rect.left() + pad + 1, 0, -pad, 0),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), str(result.get("caption") or ""))
        elif kind == "listbox":
            self._paint_field(p, rect.adjusted(0, 0, -1, -1), alpha, disabled)
            drop = parts["drop"]
            self._paint_button(p, drop.adjusted(1, 1, 0, 0), False, alpha)
            self._paint_arrow(p, drop, down=True, color=DISABLED_TEXT if disabled else BUTTON_DARK)
            p.setPen(color)
            p.drawText(parts["field"].adjusted(pad, 0, -2, 0),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), index.data() or "")
        elif kind in ("editint", "editfloat", "editstring"):
            self._paint_field(p, rect.adjusted(0, 0, -1, -1), alpha, disabled)
            align = Qt.AlignmentFlag.AlignLeft if kind == "editstring" else Qt.AlignmentFlag.AlignRight
            if kind != "editstring":
                for name, down in (("up", False), ("down", True)):
                    self._paint_arrow(p, parts[name], down=down, color=DISABLED_TEXT if disabled else BUTTON_DARK,
                                      small=True)
            p.setPen(color)
            p.drawText(parts["field"].adjusted(pad, 0, -pad, 0), int(align | Qt.AlignmentFlag.AlignVCenter),
                       index.data() or "")
        elif kind == "status":
            d = min(rect.height() - 4, max(6, round(12 * zoom)))
            circle = QRect(rect.left() + pad, rect.center().y() - d // 2, d, d)
            rgba = cells.argb_to_rgba(result.get("color")) or (128, 128, 128, 255)
            self._paint_light(p, circle, QColor(*rgba[:3]))
            p.setPen(color)
            p.drawText(rect.adjusted(pad + d + 4, 0, -pad, 0), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       str(result.get("caption") or ""))
        elif kind == "multistatus":
            n = max(0, int(result.get("numBits") or 0))
            start = int(result.get("startBit") or 0)
            try:
                value = int(result.get("data") or 0) >> start
            except (TypeError, ValueError):
                value = 0
            c0 = QColor(*(cells.argb_to_rgba(result.get("color0")) or (200, 30, 30, 255))[:3])
            c1 = QColor(*(cells.argb_to_rgba(result.get("color1")) or (30, 200, 30, 255))[:3])
            bits = [(value >> i) & 1 for i in range(n)]
            if result.get("reverse"):
                bits.reverse()
            d = min(rect.height() - 3, max(6, round(14 * zoom)))
            x = rect.left() + 2
            for bit in bits:
                if x + d > rect.right() + d:  # clipped beyond the cell anyway
                    break
                self._paint_light(p, QRect(x, rect.center().y() - d // 2, d, d), c1 if bit else c0)
                x += d + 1

    def _paint_field(self, p: QPainter, r: QRect, alpha: int, disabled: bool) -> None:
        p.fillRect(r, _alpha(QColor(240, 240, 240) if disabled else FIELD_BACK, alpha))
        p.setPen(QPen(_alpha(FIELD_BORDER, max(alpha, 160)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)

    def _paint_button(self, p: QPainter, r: QRect, pressed: bool, alpha: int) -> None:
        p.fillRect(r, _alpha(BUTTON_FACE, alpha))
        tl, br = (BUTTON_SHADOW, BUTTON_LIGHT) if pressed else (BUTTON_LIGHT, BUTTON_SHADOW)
        p.setPen(tl)
        p.drawLine(r.topLeft(), r.topRight())
        p.drawLine(r.topLeft(), r.bottomLeft())
        p.setPen(br)
        p.drawLine(r.bottomLeft(), r.bottomRight())
        p.drawLine(r.topRight(), r.bottomRight())

    def _paint_arrow(self, p: QPainter, r: QRect, down: bool, color: QColor, small: bool = False) -> None:
        s = max(2.0, min(r.width(), r.height()) / (3.2 if small else 3.6))
        c = QRectF(r).center()
        if down:
            pts = [QPointF(c.x() - s, c.y() - s / 2), QPointF(c.x() + s, c.y() - s / 2), QPointF(c.x(), c.y() + s / 2)]
        else:
            pts = [QPointF(c.x() - s, c.y() + s / 2), QPointF(c.x() + s, c.y() + s / 2), QPointF(c.x(), c.y() - s / 2)]
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(QPolygonF(pts))
        p.restore()

    def _paint_light(self, p: QPainter, r: QRect, color: QColor) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rf = QRectF(r)
        grad = QRadialGradient(rf.left() + rf.width() * 0.35, rf.top() + rf.height() * 0.3, rf.width() * 0.75)
        grad.setColorAt(0.0, color.lighter(170))
        grad.setColorAt(0.5, color)
        grad.setColorAt(1.0, color.darker(160))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(color.darker(220), 1))
        p.drawEllipse(rf.adjusted(0.5, 0.5, -0.5, -0.5))
        p.restore()

    @staticmethod
    def _paint_name_marker(p: QPainter, rect: QRect, zoom: float) -> None:
        """Named cell: a small blue triangle in the bottom-right corner (ISVS)."""
        s = max(3, round(6 * zoom))
        right, bottom = rect.right(), rect.bottom()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(NAME_MARK)
        p.drawPolygon(QPolygonF([QPointF(right + 1, bottom - s + 1), QPointF(right + 1, bottom + 1),
                                 QPointF(right - s + 1, bottom + 1)]))
        p.restore()
