"""Interactive editors for editable graphics (EditRegion, EditCircle, ...).

The editor works on a copy of the graphic dict in native device coordinates and emits
``changed`` while the user drags handles. The caller writes the final dict back with
``setCellValue``.
"""

from __future__ import annotations

import copy
import math
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem

from . import graphics

EDIT_COLOR = QColor(0, 200, 255)
HANDLE_PX = 9
EDITABLE_TYPES = {"Region", "Circle", "Annulus", "Line", "Point", "Polygon"}


class Handle(QGraphicsEllipseItem):
    """A small draggable square that reports its new parent-space position."""

    def __init__(self, parent: QGraphicsItem, on_move: Callable[[QPointF], None],
                 shape: str = "square", tooltip: str = "") -> None:
        r = HANDLE_PX / 2
        super().__init__(-r, -r, 2 * r, 2 * r, parent)
        self._on_move = on_move
        self._shape = shape
        self.setBrush(QBrush(QColor(255, 255, 255)))
        pen = QPen(EDIT_COLOR, 1.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(10)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        if tooltip:
            self.setToolTip(tooltip)

    def paint(self, painter, option, widget=None):  # noqa: D401 - Qt override
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        if self._shape == "round":
            painter.drawEllipse(self.rect())
        else:
            painter.drawRect(self.rect())

    def mousePressEvent(self, event):
        event.accept()

    def mouseMoveEvent(self, event):
        self._on_move(self.parentItem().mapFromScene(event.scenePos()))
        event.accept()


class BodyItem(QGraphicsPathItem):
    """The outline of the graphic; dragging it moves the whole graphic."""

    def __init__(self, parent: QGraphicsItem, on_drag: Callable[[QPointF], None]) -> None:
        super().__init__(parent)
        self._on_drag = on_drag
        self._last: Optional[QPointF] = None
        pen = QPen(EDIT_COLOR, 2)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(0, 200, 255, 40)))
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        self._last = self.parentItem().mapFromScene(event.scenePos())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._last is None:
            return
        pos = self.parentItem().mapFromScene(event.scenePos())
        delta = pos - self._last
        self._last = pos
        self._on_drag(delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._last = None
        event.accept()


class GraphicEditor(QObject):
    """Owns the editing items placed under ``parent`` (the overlay group)."""

    changed = Signal(dict)

    def __init__(self, graphic: dict, parent: QGraphicsItem) -> None:
        super().__init__()
        if graphic.get("$type") not in EDITABLE_TYPES:
            raise ValueError(f"Editing {graphic.get('$type')} graphics is not supported yet")
        self.g = copy.deepcopy(graphic)
        self.root = QGraphicsPathItem(parent)  # container
        self.root.setZValue(5)
        self.body = BodyItem(self.root, self._move_by)
        self.handles: list[Handle] = []
        self._build_handles()
        self._sync()

    def remove(self) -> None:
        scene = self.root.scene()
        if scene is not None:
            scene.removeItem(self.root)

    @property
    def value(self) -> dict:
        return copy.deepcopy(self.g)

    # ------------------------------------------------------------------ geometry
    def _num(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.g.get(key, default))
        except (TypeError, ValueError):
            return default

    def _build_handles(self) -> None:
        t = self.g["$type"]
        if t == "Region":
            self.handles = [
                Handle(self.root, self._region_size, tooltip="Size"),
                Handle(self.root, self._region_rotate, "round", tooltip="Rotate"),
            ]
        elif t == "Circle":
            self.handles = [Handle(self.root, lambda p: self._radius("radius", p), "round")]
        elif t == "Annulus":
            self.handles = [
                Handle(self.root, lambda p: self._radius("innerRadius", p), "round", "Inner radius"),
                Handle(self.root, lambda p: self._radius("outerRadius", p), "round", "Outer radius"),
            ]
        elif t == "Line":
            self.handles = [
                Handle(self.root, lambda p: self._line_end(0, p)),
                Handle(self.root, lambda p: self._line_end(1, p)),
            ]
        elif t == "Point":
            self.handles = [Handle(self.root, self._point)]
        elif t == "Polygon":
            pts = self.g.get("points") or []
            self.handles = [
                Handle(self.root, (lambda i: (lambda p: self._vertex(i, p)))(i))
                for i in range(len(pts) // 2)
            ]

    def _sync(self) -> None:
        t = self.g["$type"]
        path = graphics.shape_path(self.g) if t != "Point" else None
        if t == "Point":
            path = QPainterPath()
            path.addEllipse(QPointF(self._num("x"), self._num("y")), 3, 3)
        self.body.setPath(path or QPainterPath())
        if t == "Region":
            tr = graphics.region_transform(self.g)
            w, h = self._num("w"), self._num("h")
            self.handles[0].setPos(tr.map(QPointF(w, h)))
            self.handles[1].setPos(tr.map(QPointF(w + max(20.0, 0.15 * w), 0)))
        elif t == "Circle":
            self.handles[0].setPos(QPointF(self._num("x") + self._num("radius"), self._num("y")))
        elif t == "Annulus":
            cx, cy = self._num("x"), self._num("y")
            self.handles[0].setPos(QPointF(cx + self._num("innerRadius"), cy))
            self.handles[1].setPos(QPointF(cx + self._num("outerRadius"), cy))
        elif t == "Line":
            self.handles[0].setPos(QPointF(self._num("x0"), self._num("y0")))
            self.handles[1].setPos(QPointF(self._num("x1"), self._num("y1")))
        elif t == "Point":
            self.handles[0].setPos(QPointF(self._num("x"), self._num("y")))
        elif t == "Polygon":
            pts = self.g.get("points") or []
            for i, hnd in enumerate(self.handles):
                hnd.setPos(QPointF(float(pts[2 * i]), float(pts[2 * i + 1])))
        self.changed.emit(self.value)

    # ------------------------------------------------------------------ edits
    def _move_by(self, d: QPointF) -> None:
        t = self.g["$type"]
        if t == "Line":
            for k in ("x0", "x1"):
                self.g[k] = self._num(k) + d.x()
            for k in ("y0", "y1"):
                self.g[k] = self._num(k) + d.y()
        elif t == "Polygon":
            pts = [float(v) for v in self.g.get("points") or []]
            for i in range(0, len(pts) - 1, 2):
                pts[i] += d.x()
                pts[i + 1] += d.y()
            self.g["points"] = pts
        else:
            self.g["x"] = self._num("x") + d.x()
            self.g["y"] = self._num("y") + d.y()
        self._sync()

    def _region_size(self, p: QPointF) -> None:
        inv, ok = graphics.region_transform(self.g).inverted()
        local = inv.map(p)
        self.g["w"] = max(1.0, local.x())
        self.g["h"] = max(1.0, local.y())
        self._sync()

    def _region_rotate(self, p: QPointF) -> None:
        angle = math.degrees(math.atan2(p.y() - self._num("y"), p.x() - self._num("x")))
        self.g["angle"] = round(angle, 2)
        self._sync()

    def _radius(self, key: str, p: QPointF) -> None:
        r = max(1.0, math.hypot(p.x() - self._num("x"), p.y() - self._num("y")))
        self.g[key] = r
        if self.g["$type"] == "Annulus":
            inner, outer = self._num("innerRadius"), self._num("outerRadius")
            if inner > outer:
                self.g["innerRadius"], self.g["outerRadius"] = outer, inner
                # keep dragging the same visual handle
                self.handles.reverse()
        self._sync()

    def _line_end(self, idx: int, p: QPointF) -> None:
        self.g[f"x{idx}"] = p.x()
        self.g[f"y{idx}"] = p.y()
        self._sync()

    def _point(self, p: QPointF) -> None:
        self.g["x"], self.g["y"] = p.x(), p.y()
        self._sync()

    def _vertex(self, i: int, p: QPointF) -> None:
        pts = [float(v) for v in self.g.get("points") or []]
        pts[2 * i], pts[2 * i + 1] = p.x(), p.y()
        self.g["points"] = pts
        self._sync()


def round_graphic(g: dict, decimals: int = 3) -> dict:
    """Rounds float geometry so values written back to the sheet are tidy."""
    out = {}
    for k, v in g.items():
        if isinstance(v, float):
            out[k] = round(v, decimals)
        elif isinstance(v, list):
            out[k] = [round(x, decimals) if isinstance(x, float) else x for x in v]
        else:
            out[k] = v
    return out
