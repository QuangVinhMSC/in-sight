"""Interactive Graphics Mode: editors for editable graphics (EditRegion, EditCircle, …, the
literal regions of a tool's property sheet).

Drawn like ISVS 26.1 (help "Rectangle Regions Interactive Graphics Mode", live screenshot
``live/20``): the graphic in red, magenta handles — four resizable corners, the two scan
direction arrows labelled X and Y, the rotation handle in the middle of the bottom edge and
the bend handle in the middle of the right edge. Dragging inside a shape moves it, dragging
one of its sides resizes it. Polygons: click an edge to add a point, Shift+Alt+click a point
to remove it. Composite regions have a right-click menu (Add Subregion ▸, Remove Subregion,
Subregion Operation ▸); masked regions one with Add Mask / Delete Mask.

The editor works on a copy of the graphic dict in the coordinates of the item it is placed
under (native device coordinates, or a tool's fixture coordinates when a fixture transform is
given) and emits ``changed`` while the user edits. The caller writes the final dict back
(``setCellValue``) or puts the numbers into the property sheet.
"""

from __future__ import annotations

import copy
import math
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QMenu

from . import graphics

EDIT_COLOR = QColor(255, 0, 0)  # ISVS draws the edited graphic in red
HANDLE_COLOR = QColor(255, 0, 255)  # and its handles in magenta
MASK_COLOR = QColor(60, 70, 170)  # hatching of masks / subtracted subregions
SCAN_LINE_COLOR = QColor(255, 220, 0)
HANDLE_PX = 7  # handle size on screen
EDGE_PX = 4  # how close (on screen) the mouse must be to a side to resize it

SHAPE_TYPES = ("Annulus", "Circle", "Polygon", "Region")  # composite subregions (menu order)
COMPOSITE_TYPES = {"CompositeRegion", "MaskedRegion", "PolylinePath"}
EDITABLE_TYPES = {"Region", "Circle", "Annulus", "Line", "Point", "Polygon"} | COMPOSITE_TYPES
MAX_SUBREGIONS = 32  # EditCompositeRegion
MAX_MASKS = 99  # EditMaskedRegion
MIN_SIZE = 1.0
MAX_CURVE = 150.0

# Edit flags as sent by the device (EditingRegion / Edit*Result): absent means allowed.
FLAG_KEYS = ("move", "resize", "rotate", "bend", "addRegion", "removeRegion", "editRegion")


def edit_flags(*sources: Optional[dict]) -> dict:
    """The edit flags found in the given dicts (beginEdit's Editing object, the cell result)."""
    out: dict = {}
    for src in sources:
        if isinstance(src, dict):
            for k in FLAG_KEYS:
                if k in src and k not in out:
                    out[k] = bool(src[k])
            if "size" in src and "resize" not in out and isinstance(src["size"], bool):
                out["resize"] = src["size"]
    return out


def _detach(item: QGraphicsItem) -> None:
    if item.scene() is not None:
        item.scene().removeItem(item)
    else:
        item.setParentItem(None)


def _num(g: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(g.get(key, default))
    except (TypeError, ValueError):
        return default


def _cosmetic(color: QColor, width: float = 2.0, style=Qt.PenStyle.SolidLine) -> QPen:
    pen = QPen(color, width)
    pen.setCosmetic(True)
    pen.setStyle(style)
    return pen


def device_scale(item: QGraphicsItem) -> float:
    """Screen pixels per unit of ``item``'s coordinates (1 when not shown in a view)."""
    scene = item.scene()
    if scene is None or not scene.views():
        return 1.0
    t = item.deviceTransform(scene.views()[0].viewportTransform())
    return math.sqrt(abs(t.determinant())) or 1.0


def device_vector(item: QGraphicsItem, at: QPointF, v: QPointF) -> QPointF:
    """Unit vector on screen for the direction ``v`` at ``at`` (both in ``item`` coordinates)."""
    scene = item.scene()
    if scene is not None and scene.views():
        t = item.deviceTransform(scene.views()[0].viewportTransform())
    else:
        t = item.sceneTransform()
    d = t.map(at + v) - t.map(at)
    n = math.hypot(d.x(), d.y()) or 1.0
    return QPointF(d.x() / n, d.y() / n)


# ============================================================================ items
class Handle(QGraphicsItem):
    """A small magenta handle of fixed screen size that reports drags in its parent's
    coordinates. ``kind``: square (corner/vertex), rotate, bend or round."""

    def __init__(self, parent: QGraphicsItem, on_move: Callable[[QPointF], None], kind: str = "square",
                 tooltip: str = "", cursor: Qt.CursorShape = Qt.CursorShape.SizeAllCursor,
                 on_press: Optional[Callable[[object], bool]] = None) -> None:
        super().__init__(parent)
        self._on_move = on_move
        self._on_press = on_press
        self.kind = kind
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setCursor(cursor)
        self.setZValue(10)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        if tooltip:
            self.setToolTip(tooltip)

    def boundingRect(self) -> QRectF:
        r = HANDLE_PX / 2 + 3
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: D401 - Qt override
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(HANDLE_COLOR, 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        r = HANDLE_PX / 2
        if self.kind == "round":
            painter.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
        elif self.kind == "rotate":  # circular arrow
            rect = QRectF(-r, -r, 2 * r, 2 * r)
            painter.drawArc(rect, 60 * 16, 290 * 16)
            painter.setBrush(HANDLE_COLOR)
            painter.drawPolygon(QPolygonF([QPointF(r * 0.5, -r - 1.5), QPointF(r * 0.5 + 3.5, -r + 1),
                                           QPointF(r * 0.5 - 0.5, -r + 2.5)]))
        elif self.kind == "bend":  # curved arrow
            path = QPainterPath(QPointF(-r, r * 0.6))
            path.quadTo(QPointF(0, -r * 0.6), QPointF(r, r * 0.1))
            painter.drawPath(path)
            painter.drawRect(QRectF(-r - 1, r * 0.6 - 1.5, 3, 3))
            painter.setBrush(HANDLE_COLOR)
            painter.drawPolygon(QPolygonF([QPointF(r + 1.5, r * 0.1), QPointF(r - 2.5, -r * 0.5),
                                           QPointF(r - 2.5, r * 0.7)]))
        else:
            painter.drawRect(QRectF(-r + 1, -r + 1, 2 * r - 2, 2 * r - 2))

    def mousePressEvent(self, event) -> None:
        if self._on_press is not None and self._on_press(event):
            event.accept()
            return
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self._on_move(self.parentItem().mapFromScene(event.scenePos()))
        event.accept()


class ScanArrow(QGraphicsItem):
    """Scan direction indicator: a filled red triangle pointing along an axis of the region,
    labelled X or Y on the outside (fixed screen size)."""

    def __init__(self, parent: QGraphicsItem, label: str) -> None:
        super().__init__(parent)
        self.label = label
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(9)
        self._dir = QPointF(1, 0)
        self._out = QPointF(0, -1)

    def set_vectors(self, direction: QPointF, outside: QPointF) -> None:
        self.prepareGeometryChange()
        self._dir, self._out = direction, outside
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-22, -22, 44, 44)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        d, o = self._dir, self._out
        n = QPointF(-d.y(), d.x())
        tip, base = d * 6, d * -3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(EDIT_COLOR)
        painter.drawPolygon(QPolygonF([tip, base + n * 5, base - n * 5]))
        f = QFont(painter.font())
        f.setPointSizeF(9)
        painter.setFont(f)
        painter.setPen(EDIT_COLOR)
        c = o * 13
        painter.drawText(QRectF(c.x() - 8, c.y() - 8, 16, 16), Qt.AlignmentFlag.AlignCenter, self.label)


class BodyItem(QGraphicsPathItem):
    """The outline/area of a shape: dragging inside moves it, near a side resizes it (the shape
    editor decides), right-click opens the editor's menu."""

    def __init__(self, shape: "ShapeEditor") -> None:
        super().__init__(shape.root)
        self.shape_editor = shape
        self._drag: Optional[Callable[[QPointF], None]] = None
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def shape(self) -> QPainterPath:  # the clickable area: inside plus a band along the outline
        path = self.path()
        stroker = QPainterPathStroker()
        stroker.setWidth(2 * EDGE_PX / device_scale(self))
        out = stroker.createStroke(path)
        out.addPath(path)
        out.setFillRule(Qt.FillRule.WindingFill)
        return out

    def hoverMoveEvent(self, event) -> None:
        self.setCursor(self.shape_editor.cursor_at(event.pos(), event.modifiers()))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self.shape_editor.owner.activate(self.shape_editor)
        self._drag = self.shape_editor.press(event.pos(), event.modifiers())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            self._drag(event.pos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        event.accept()

    def contextMenuEvent(self, event) -> None:
        self.shape_editor.owner.context_menu(self.shape_editor, event.screenPos(), event.pos())
        event.accept()


# ============================================================================ shapes
class ShapeEditor:
    """Editing items for one shape dict ``g`` (edited in place) under ``parent``."""

    def __init__(self, owner: "GraphicEditor", g: dict, parent: QGraphicsItem, subtract: bool = False) -> None:
        self.owner = owner
        self.g = g
        self.subtract = subtract
        self.root = QGraphicsPathItem(parent)  # container in the shape's coordinates
        self.body = BodyItem(self)
        self.handles: list[Handle] = []
        self.build()
        self.sync()

    # ------------------------------------------------------------------ helpers
    def flag(self, key: str) -> bool:
        return self.owner.allowed(key)

    def num(self, key: str, default: float = 0.0) -> float:
        return _num(self.g, key, default)

    def tolerance(self) -> float:
        return EDGE_PX / device_scale(self.root)

    def handle(self, on_move, kind="square", tooltip="", cursor=Qt.CursorShape.SizeAllCursor, on_press=None) -> Handle:
        h = Handle(self.root, on_move, kind, tooltip, cursor, on_press)
        self.handles.append(h)
        return h

    def changed(self) -> None:
        self.sync()
        self.owner.shape_changed(self)

    def remove(self) -> None:
        _detach(self.root)

    # ------------------------------------------------------------------ to override
    def build(self) -> None:
        pass

    def path(self) -> QPainterPath:
        return graphics.shape_path(self.g) or QPainterPath()

    def sync(self) -> None:
        self.body.setPath(self.path())
        pen = _cosmetic(EDIT_COLOR, 2, Qt.PenStyle.DashLine if self.subtract else Qt.PenStyle.SolidLine)
        self.body.setPen(pen)
        self.body.setBrush(QBrush(MASK_COLOR, Qt.BrushStyle.BDiagPattern) if self.subtract
                           else QBrush(QColor(255, 0, 0, 1)))  # (almost) invisible fill: clickable inside
        self.place_handles()

    def place_handles(self) -> None:
        pass

    def move_by(self, d: QPointF) -> None:
        self.g["x"] = self.num("x") + d.x()
        self.g["y"] = self.num("y") + d.y()

    def cursor_at(self, p: QPointF, modifiers) -> Qt.CursorShape:
        return Qt.CursorShape.SizeAllCursor if self.flag("move") else Qt.CursorShape.ArrowCursor

    def press(self, p: QPointF, modifiers) -> Optional[Callable[[QPointF], None]]:
        """Mouse pressed on the body at ``p``: returns the drag handler (or None)."""
        return self._mover(p)

    def _mover(self, p: QPointF) -> Optional[Callable[[QPointF], None]]:
        if not self.flag("move"):
            return None
        last = [p]

        def drag(q: QPointF) -> None:
            d = q - last[0]
            last[0] = q
            self.owner.move_shape(self, d)

        return drag


class RegionShape(ShapeEditor):
    """Rectangle region (with curve): four corners, sides, rotation and bend handles, scan arrows."""

    CORNERS = ((0, 0), (1, 0), (1, 1), (0, 1))

    def build(self) -> None:
        self.corners = []
        for fx, fy in self.CORNERS:
            cursor = Qt.CursorShape.SizeFDiagCursor if fx == fy else Qt.CursorShape.SizeBDiagCursor
            self.corners.append(self.handle((lambda fx, fy: lambda p: self._corner(fx, fy, p))(fx, fy),
                                            tooltip="Resize", cursor=cursor))
        self.rotator = self.handle(self._rotate, "rotate", "Rotate", Qt.CursorShape.CrossCursor)
        self.bender = self.handle(self._bend, "bend", "Bend", Qt.CursorShape.CrossCursor)
        self.arrow_x = ScanArrow(self.root, "X")
        self.arrow_y = ScanArrow(self.root, "Y")
        self.scan_line = QGraphicsPathItem(self.root)
        self.scan_line.setPen(_cosmetic(SCAN_LINE_COLOR, 1, Qt.PenStyle.DotLine))
        self.scan_line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def transform(self) -> QTransform:
        return graphics.region_transform(self.g)

    def sag(self) -> float:
        w, curve = self.num("w"), max(-MAX_CURVE, min(MAX_CURVE, self.num("curve")))
        return math.tan(math.radians(curve) / 2) * w / 2

    def place_handles(self) -> None:
        t = self.transform()
        w, h, s = self.num("w"), self.num("h"), self.sag()
        for hnd, (fx, fy) in zip(self.corners, self.CORNERS):
            hnd.setPos(t.map(QPointF(fx * w, fy * h)))
            hnd.setVisible(self.flag("resize"))
        self.rotator.setPos(t.map(QPointF(w / 2, h - s)))
        self.rotator.setVisible(self.flag("rotate"))
        k = max(-1.0, min(1.0, self.num("curve") / 90.0))
        self.bender.setPos(t.map(QPointF(w, h / 2 - k * h / 2)))
        self.bender.setVisible(self.flag("bend"))
        show_axes = self.g.get("showXArrow", True) is not False and not self.subtract
        top, left = t.map(QPointF(w / 2, -s)), t.map(QPointF(0, h / 2))
        self.arrow_x.setPos(top)
        self.arrow_x.set_vectors(device_vector(self.root, top, t.map(QPointF(w / 2 + 1, -s)) - top),
                                 device_vector(self.root, top, t.map(QPointF(w / 2, -s - 1)) - top))
        self.arrow_y.setPos(left)
        self.arrow_y.set_vectors(device_vector(self.root, left, t.map(QPointF(0, h / 2 + 1)) - left),
                                 device_vector(self.root, left, t.map(QPointF(-1, h / 2)) - left))
        self.arrow_x.setVisible(show_axes)
        self.arrow_y.setVisible(show_axes and self.g.get("showYArrow", True) is not False)
        line = QPainterPath()
        if self.g.get("showScanLine") or self.owner.masked:
            line.moveTo(t.map(QPointF(0, h / 2)))
            line.lineTo(t.map(QPointF(w, h / 2)))
        self.scan_line.setPath(line)

    # ------------------------------------------------------------------ edits
    def _set_rect(self, left: float, top: float, right: float, bottom: float) -> None:
        origin = self.transform().map(QPointF(left, top))
        self.g["x"], self.g["y"] = origin.x(), origin.y()
        self.g["w"], self.g["h"] = right - left, bottom - top

    def _corner(self, fx: int, fy: int, p: QPointF) -> None:
        if not self.flag("resize"):
            return
        local = self.transform().inverted()[0].map(p)
        w, h = self.num("w"), self.num("h")
        left, right = (0.0, max(MIN_SIZE, local.x())) if fx else (min(w - MIN_SIZE, local.x()), w)
        top, bottom = (0.0, max(MIN_SIZE, local.y())) if fy else (min(h - MIN_SIZE, local.y()), h)
        self.owner.resize_shape(self, lambda: self._set_rect(left, top, right, bottom))

    def _side(self, side: str, p: QPointF) -> None:
        local = self.transform().inverted()[0].map(p)
        w, h = self.num("w"), self.num("h")
        left, top, right, bottom = 0.0, 0.0, w, h
        if side == "left":
            left = min(w - MIN_SIZE, local.x())
        elif side == "right":
            right = max(MIN_SIZE, local.x())
        elif side == "top":
            top = min(h - MIN_SIZE, local.y())
        else:
            bottom = max(MIN_SIZE, local.y())
        self.owner.resize_shape(self, lambda: self._set_rect(left, top, right, bottom))

    def _rotate(self, p: QPointF) -> None:
        if not self.flag("rotate"):
            return
        w, h = self.num("w"), self.num("h")
        c = self.transform().map(QPointF(w / 2, h / 2))
        angle = math.degrees(math.atan2(p.y() - c.y(), p.x() - c.x())) - 90.0
        angle = (angle + 180.0) % 360.0 - 180.0
        self.owner.rotate_shape(self, c, angle - self.num("angle"))

    def rotate_about(self, c: QPointF, delta: float) -> None:
        t = QTransform().translate(c.x(), c.y()).rotate(delta).translate(-c.x(), -c.y())
        origin = t.map(QPointF(self.num("x"), self.num("y")))
        self.g["x"], self.g["y"] = origin.x(), origin.y()
        self.g["angle"] = round((self.num("angle") + delta + 180.0) % 360.0 - 180.0, 3)

    def _bend(self, p: QPointF) -> None:
        if not self.flag("bend"):
            return
        local = self.transform().inverted()[0].map(p)
        h = self.num("h") or 1.0
        k = max(-1.0, min(1.0, (h / 2 - local.y()) / (h / 2)))
        self.g["curve"] = round(k * 90.0, 1)
        self.changed()

    def side_at(self, p: QPointF) -> Optional[str]:
        local = self.transform().inverted()[0].map(p)
        w, h, tol = self.num("w"), self.num("h"), self.tolerance()
        if not (-tol <= local.x() <= w + tol and -tol - abs(self.sag()) <= local.y() <= h + tol):
            return None
        for side, dist in (("left", abs(local.x())), ("right", abs(local.x() - w)),
                           ("top", abs(local.y())), ("bottom", abs(local.y() - h))):
            if dist <= tol and abs(self.num("curve")) < 1e-6:
                return side
        return None

    def cursor_at(self, p: QPointF, modifiers) -> Qt.CursorShape:
        side = self.side_at(p) if self.flag("resize") else None
        if side is None:
            return super().cursor_at(p, modifiers)
        horizontal = side in ("left", "right")
        a = self.num("angle") % 180
        if 45 <= a < 135:
            horizontal = not horizontal
        return Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor

    def press(self, p: QPointF, modifiers):
        side = self.side_at(p) if self.flag("resize") else None
        if side is not None:
            return lambda q, side=side: self._side(side, q)
        return self._mover(p)


class CircleShape(ShapeEditor):
    def build(self) -> None:
        self.radius_handles = [self.handle(lambda p: self._radius("radius", p), tooltip="Radius") for _ in range(4)]

    def place_handles(self) -> None:
        cx, cy, r = self.num("x"), self.num("y"), self.num("radius")
        for hnd, (dx, dy) in zip(self.radius_handles, ((1, 0), (0, 1), (-1, 0), (0, -1))):
            hnd.setPos(QPointF(cx + dx * r, cy + dy * r))
            hnd.setVisible(self.flag("resize"))

    def _radius(self, key: str, p: QPointF) -> None:
        if not self.flag("resize"):
            return
        self.g[key] = max(MIN_SIZE, math.hypot(p.x() - self.num("x"), p.y() - self.num("y")))
        self.changed()


class AnnulusShape(CircleShape):
    def build(self) -> None:
        self.inner = self.handle(lambda p: self._annulus("innerRadius", p), "square", "Inner radius")
        self.outer = self.handle(lambda p: self._annulus("outerRadius", p), "square", "Outer radius")

    def place_handles(self) -> None:
        cx, cy = self.num("x"), self.num("y")
        self.inner.setPos(QPointF(cx + self.num("innerRadius"), cy))
        self.outer.setPos(QPointF(cx, cy + self.num("outerRadius")))
        for hnd in (self.inner, self.outer):
            hnd.setVisible(self.flag("resize"))

    def _annulus(self, key: str, p: QPointF) -> None:
        if not self.flag("resize"):
            return
        r = max(MIN_SIZE, math.hypot(p.x() - self.num("x"), p.y() - self.num("y")))
        if key == "innerRadius":
            r = min(r, self.num("outerRadius") - MIN_SIZE)
        else:
            r = max(r, self.num("innerRadius") + MIN_SIZE)
        self.g[key] = max(MIN_SIZE if key == "outerRadius" else 0.0, r)
        self.changed()


class LineShape(ShapeEditor):
    def build(self) -> None:
        self.ends = [self.handle((lambda i: lambda p: self._end(i, p))(i), tooltip=f"Point {i}") for i in (0, 1)]

    def place_handles(self) -> None:
        for i, hnd in enumerate(self.ends):
            hnd.setPos(QPointF(self.num(f"x{i}"), self.num(f"y{i}")))

    def _end(self, i: int, p: QPointF) -> None:
        self.g[f"x{i}"], self.g[f"y{i}"] = p.x(), p.y()
        self.changed()

    def move_by(self, d: QPointF) -> None:
        for i in (0, 1):
            self.g[f"x{i}"] = self.num(f"x{i}") + d.x()
            self.g[f"y{i}"] = self.num(f"y{i}") + d.y()


class PointShape(ShapeEditor):
    def build(self) -> None:
        self.point = self.handle(self._point, tooltip="Point")

    def path(self) -> QPainterPath:
        p = QPainterPath()
        r = 4 / device_scale(self.root)
        p.addEllipse(QPointF(self.num("x"), self.num("y")), r, r)
        return p

    def place_handles(self) -> None:
        self.point.setPos(QPointF(self.num("x"), self.num("y")))

    def _point(self, p: QPointF) -> None:
        if self.flag("move"):
            self.g["x"], self.g["y"] = p.x(), p.y()
            self.changed()


class PolygonShape(ShapeEditor):
    """Vertices can be dragged; clicking an edge adds a point there, Shift+Alt+click on a point
    removes it (at least three points stay)."""

    def __init__(self, *args, **kwargs) -> None:
        self._retired: list[Handle] = []
        super().__init__(*args, **kwargs)

    def points(self) -> list[QPointF]:
        vals = [float(v) for v in self.g.get("points") or []]
        return [QPointF(vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]

    def set_points(self, pts: list[QPointF]) -> None:
        self.g["points"] = [c for p in pts for c in (p.x(), p.y())]
        if "length" in self.g:
            self.g["length"] = len(pts)

    def build(self) -> None:
        for h in self.handles:
            _detach(h)
            self._retired.append(h)  # may be the handle whose mouse press removed a point
        self.handles = []
        for i in range(len(self.points())):
            self.handle((lambda i: lambda p: self._vertex(i, p))(i), tooltip="Shift+Alt+click removes the point",
                        on_press=(lambda i: lambda e: self._press_vertex(i, e))(i))

    def place_handles(self) -> None:
        pts = self.points()
        if len(pts) != len(self.handles):
            self.build()
        for hnd, p in zip(self.handles, pts):
            hnd.setPos(p)

    def _vertex(self, i: int, p: QPointF) -> None:
        pts = self.points()
        if i < len(pts) and self.flag("resize"):
            pts[i] = p
            self.set_points(pts)
            self.changed()

    def _press_vertex(self, i: int, event) -> bool:
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier and mods & Qt.KeyboardModifier.AltModifier:
            pts = self.points()
            if len(pts) > 3 and self.flag("resize"):
                del pts[i]
                self.set_points(pts)
                self.changed()
            return True
        return False

    def move_by(self, d: QPointF) -> None:
        self.set_points([p + d for p in self.points()])

    def edge_at(self, p: QPointF) -> Optional[int]:
        pts, tol = self.points(), self.tolerance()
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            ab = b - a
            L2 = ab.x() ** 2 + ab.y() ** 2
            if L2 <= 0:
                continue
            u = max(0.0, min(1.0, ((p - a).x() * ab.x() + (p - a).y() * ab.y()) / L2))
            q = a + ab * u
            if math.hypot(p.x() - q.x(), p.y() - q.y()) <= tol:
                return i
        return None

    def cursor_at(self, p: QPointF, modifiers) -> Qt.CursorShape:
        if self.edge_at(p) is not None and self.flag("resize"):
            return Qt.CursorShape.CrossCursor  # "an arrow with +": add a point
        return super().cursor_at(p, modifiers)

    def press(self, p: QPointF, modifiers):
        i = self.edge_at(p) if self.flag("resize") else None
        if i is None:
            return self._mover(p)
        pts = self.points()
        pts.insert(i + 1, p)
        self.set_points(pts)
        self.changed()
        k = i + 1
        return lambda q: self._vertex(k, q)


SHAPES: dict[str, type[ShapeEditor]] = {
    "Region": RegionShape, "Circle": CircleShape, "Annulus": AnnulusShape, "Line": LineShape,
    "Point": PointShape, "Polygon": PolygonShape,
}


# ============================================================================ masks
class MaskItem(QGraphicsPathItem):
    """A mask of an EditMaskedRegion: a hatched band across the ROI (main region coordinates)
    that can be dragged along the ROI and resized by its sides."""

    def __init__(self, owner: "GraphicEditor", index: int, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.owner, self.index = owner, index
        self._drag: Optional[Callable[[QPointF], None]] = None
        self.setAcceptHoverEvents(True)
        self.setZValue(3)
        self.setPen(_cosmetic(EDIT_COLOR, 1.5))
        self.setBrush(QBrush(MASK_COLOR, Qt.BrushStyle.BDiagPattern))

    def _side(self, p: QPointF) -> Optional[str]:
        u0, wm = self.owner.masks[self.index]
        tol = EDGE_PX / device_scale(self)
        if abs(p.x() - u0) <= tol:
            return "left"
        if abs(p.x() - (u0 + wm)) <= tol:
            return "right"
        return None

    def hoverMoveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.SizeHorCursor if self._side(event.pos()) else Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.owner.flags.get("editRegion", True):
            event.ignore()
            return
        side, last = self._side(event.pos()), [event.pos()]

        def drag(q: QPointF) -> None:
            if side is None:
                self.owner.move_mask(self.index, q.x() - last[0].x())
                last[0] = q
            else:
                self.owner.resize_mask(self.index, side, q.x())

        self._drag = drag
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            self._drag(event.pos())

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None

    def contextMenuEvent(self, event) -> None:
        main = self.owner.shapes[0] if self.owner.shapes else None
        self.owner.context_menu(main, event.screenPos(), self.owner.from_mask_layer(event.pos()), mask=self.index)
        event.accept()


# ============================================================================ editor
class GraphicEditor(QObject):
    """Interactive Graphics Mode for one graphic, placed under ``parent`` (the overlay group).

    ``transform`` maps the graphic's coordinates to ``parent`` (a tool's fixture), ``flags``
    are the device's edit flags, ``function`` the function that made the graphic (an
    EditMaskedRegion reports a CompositeRegion)."""

    changed = Signal(dict)

    def __init__(self, graphic: dict, parent: QGraphicsItem, transform: Optional[QTransform] = None,
                 flags: Optional[dict] = None, function: Optional[str] = None) -> None:
        super().__init__()
        t = graphic.get("$type")
        if t not in EDITABLE_TYPES:
            raise ValueError(f"Editing {t} graphics is not supported")
        self.g = copy.deepcopy(graphic)
        self.flags = dict(flags or {})
        self.masked = t == "MaskedRegion" or (function or "").lower() == "editmaskedregion"
        self.polyline = t == "PolylinePath" or (function or "").lower() == "editpolylinepath"
        self.composite = t in COMPOSITE_TYPES
        self.root = QGraphicsPathItem(parent)
        self.root.setZValue(5)
        if transform is not None:
            self.root.setTransform(transform)
        self.shapes: list[ShapeEditor] = []
        self.active: Optional[ShapeEditor] = None
        self.masks: list[tuple[float, float]] = []  # masked region: (offset along the ROI, width)
        self.mask_items: list[MaskItem] = []
        self.mask_layer: Optional[QGraphicsPathItem] = None
        self._retired: list = []  # removed items stay referenced: a menu/mouse handler may still run on them
        self._build()

    # ------------------------------------------------------------------ construction
    def _subregions(self) -> list[dict]:
        subs = self.g.get("subregions")
        if not isinstance(subs, list):
            subs = self.g["subregions"] = []
        return subs

    def _build(self) -> None:
        for s in self.shapes:
            s.remove()
        self._retired += self.shapes + self.mask_items
        self.shapes, self.mask_items = [], []
        if not self.composite:
            self.shapes.append(SHAPES[self.g["$type"]](self, self.g, self.root))
        elif self.masked:
            subs = self._subregions()
            main = subs[0]["shape"] if subs and isinstance(subs[0].get("shape"), dict) else None
            if main is None or main.get("$type") != "Region":
                raise ValueError("The masked region has no region")
            shape = RegionShape(self, main, self.root)
            self.shapes.append(shape)
            self.mask_layer = QGraphicsPathItem(shape.root)
            inv = shape.transform().inverted()[0]
            self.masks = []
            for sub in subs[1:]:
                m = sub.get("shape") or {}
                start = inv.map(QPointF(_num(m, "x"), _num(m, "y"))).x()
                self.masks.append((start, _num(m, "w")))
            self._sync_masks()
        else:
            for sub in self._subregions():
                shape = sub.get("shape")
                if isinstance(shape, dict) and shape.get("$type") in SHAPE_TYPES:
                    self.shapes.append(SHAPES[shape["$type"]](self, shape, self.root,
                                                              subtract=not sub.get("add", True)))
        self.active = self.shapes[0] if self.shapes else None

    def remove(self) -> None:
        _detach(self.root)

    def allowed(self, key: str) -> bool:
        """Edit flags: a composite region's subregions are changed with "editRegion", the whole
        composite moved with "move"."""
        if self.composite and not self.masked:
            if key == "move":
                return self.flags.get("editRegion", True) or self.flags.get("move", True)
            return self.flags.get("editRegion", True)
        return self.flags.get(key, True)

    @property
    def value(self) -> dict:
        return copy.deepcopy(self.g)

    def set_value(self, graphic: dict) -> None:
        """Replaces the edited graphic (e.g. typed into the property sheet) without emitting."""
        self.g = copy.deepcopy(graphic)
        self._build()

    def refresh(self) -> None:
        """Re-places the screen-sized decorations (after zooming or rotating the view)."""
        for s in self.shapes:
            s.sync()

    def set_transform(self, transform: Optional[QTransform]) -> None:
        self.root.setTransform(transform or QTransform())
        self.refresh()

    # ------------------------------------------------------------------ edits from the shapes
    def activate(self, shape: ShapeEditor) -> None:
        self.active = shape

    def shape_changed(self, shape: Optional[ShapeEditor] = None) -> None:
        if self.masked:
            self._sync_masks()
        self.changed.emit(self.value)

    def move_shape(self, shape: ShapeEditor, d: QPointF) -> None:
        if self.composite and not self.masked and not self.flags.get("editRegion", True):
            for s in self.shapes:  # subregions are fixed: the whole composite moves
                s.move_by(d)
                s.sync()
            self.shape_changed()
            return
        shape.move_by(d)
        shape.changed()

    def resize_shape(self, shape: ShapeEditor, apply: Callable[[], None]) -> None:
        apply()
        if self.masked:
            w = shape.num("w")
            self.masks = [(max(0.0, min(u, w - min(wm, w))), min(wm, w)) for u, wm in self.masks]
        shape.changed()

    def rotate_shape(self, shape: ShapeEditor, centre: QPointF, delta: float) -> None:
        if isinstance(shape, RegionShape):
            shape.rotate_about(centre, delta)
            shape.changed()

    # ------------------------------------------------------------------ masks
    def from_mask_layer(self, p: QPointF) -> QPointF:
        return self.shapes[0].transform().map(p) if self.shapes else p

    def _sync_masks(self) -> None:
        main = self.shapes[0]
        self.mask_layer.setTransform(main.transform())
        h = main.num("h")
        while len(self.mask_items) > len(self.masks):
            item = self.mask_items.pop()
            if item.scene() is not None:
                item.scene().removeItem(item)
        while len(self.mask_items) < len(self.masks):
            self.mask_items.append(MaskItem(self, len(self.mask_items), self.mask_layer))
        subs = self._subregions()
        template = {k: v for k, v in subs[0].items() if k not in ("shape", "add")}
        shape_tpl = {k: v for k, v in main.g.items() if k not in ("x", "y", "w", "h", "angle", "curve")}
        out = [subs[0]]
        t = main.transform()
        for item, (u, wm) in zip(self.mask_items, self.masks):
            p = QPainterPath()
            p.addRect(QRectF(u, 0, wm, h))
            item.setPath(p)
            o = t.map(QPointF(u, 0))
            out.append({**template, "$type": "SubRegion", "add": False,
                        "shape": {**shape_tpl, "$type": "Region", "x": o.x(), "y": o.y(), "w": wm, "h": h,
                                  "angle": main.num("angle"), "curve": 0.0}})
        subs[:] = out

    def move_mask(self, i: int, du: float) -> None:
        w = self.shapes[0].num("w")
        u, wm = self.masks[i]
        self.masks[i] = (max(0.0, min(w - wm, u + du)), wm)
        self.shape_changed()

    def resize_mask(self, i: int, side: str, x: float) -> None:
        w = self.shapes[0].num("w")
        u, wm = self.masks[i]
        if side == "left":
            nu = max(0.0, min(u + wm - MIN_SIZE, x))
            self.masks[i] = (nu, u + wm - nu)
        else:
            self.masks[i] = (u, max(MIN_SIZE, min(w - u, x - u)))
        self.shape_changed()

    def add_mask(self, at_local_x: float) -> None:
        main = self.shapes[0]
        w = main.num("w")
        wm = max(MIN_SIZE, min(w, round(max(10.0, w * 0.05), 3)))
        u = max(0.0, min(w - wm, at_local_x - wm / 2))
        self.masks.append((u, wm))
        self.shape_changed()

    def delete_mask(self, i: int) -> None:
        if 0 <= i < len(self.masks):
            del self.masks[i]
            self.shape_changed()

    # ------------------------------------------------------------------ composite subregions
    def add_subregion(self, kind: str, at: QPointF) -> None:
        if kind not in SHAPE_TYPES:
            return
        x, y = at.x(), at.y()
        shapes = {
            "Region": {"$type": "Region", "x": x - 50, "y": y - 40, "w": 100.0, "h": 80.0, "angle": 0.0, "curve": 0.0},
            "Circle": {"$type": "Circle", "x": x, "y": y, "radius": 50.0},
            "Annulus": {"$type": "Annulus", "x": x, "y": y, "innerRadius": 30.0, "outerRadius": 60.0},
            "Polygon": {"$type": "Polygon", "points": [x, y - 40, x + 40, y + 30, x - 40, y + 30], "length": 3},
        }
        color = self.g.get("color")
        shape = dict(shapes[kind])
        if color is not None:
            shape["color"] = color
        sub = {"$type": "SubRegion", "add": True, "shape": shape}
        if color is not None:
            sub["color"] = color
        self._subregions().append(sub)
        self._build()
        self.active = self.shapes[-1] if self.shapes else None
        self.shape_changed()

    def _sub_index(self, shape: ShapeEditor) -> Optional[int]:
        for i, sub in enumerate(self._subregions()):
            if sub.get("shape") is shape.g:
                return i
        return None

    def remove_subregion(self, shape: ShapeEditor) -> None:
        i = self._sub_index(shape)
        if i is None or len(self._subregions()) <= 1:
            return
        del self._subregions()[i]
        self._build()
        self.shape_changed()

    def set_operation(self, shape: ShapeEditor, add: bool) -> None:
        i = self._sub_index(shape)
        if i is None:
            return
        self._subregions()[i]["add"] = add
        self._build()
        self.shape_changed()

    # ------------------------------------------------------------------ right-click menu
    def build_menu(self, shape: Optional[ShapeEditor], p: QPointF, mask: Optional[int] = None) -> Optional[QMenu]:
        """The Interactive Graphics Mode right-click menu (``p`` in graphic coordinates)."""
        if self.masked:
            menu = QMenu()
            local = self.shapes[0].transform().inverted()[0].map(p)
            inside = 0 <= local.x() <= self.shapes[0].num("w") and 0 <= local.y() <= self.shapes[0].num("h")
            a = menu.addAction("Add Mask", lambda: self.add_mask(local.x()))
            a.setEnabled(inside and len(self.masks) < MAX_MASKS and self.flags.get("addRegion", True))
            if mask is None:
                mask = next((i for i, (u, wm) in enumerate(self.masks) if u <= local.x() <= u + wm), None)
            a = menu.addAction("Delete Mask", lambda: self.delete_mask(mask))
            a.setEnabled(mask is not None and self.flags.get("removeRegion", True))
            return menu
        if not self.composite or self.polyline:
            return None
        menu = QMenu()
        add = menu.addMenu("Add Subregion")
        for kind in SHAPE_TYPES:
            add.addAction(kind, (lambda k: lambda: self.add_subregion(k, p))(kind))
        add.setEnabled(self.flags.get("addRegion", True) and len(self._subregions()) < MAX_SUBREGIONS)
        a = menu.addAction("Remove Subregion", lambda: self.remove_subregion(shape))
        a.setEnabled(shape is not None and self.flags.get("removeRegion", True) and len(self._subregions()) > 1)
        op = menu.addMenu("Subregion Operation")
        for label, value in (("Add", True), ("Subtract", False)):
            act = op.addAction(label, (lambda v: lambda: self.set_operation(shape, v))(value))
            act.setCheckable(True)
            act.setChecked(shape is not None and (not shape.subtract) == value)
        op.setEnabled(shape is not None and self.flags.get("editRegion", True))
        return menu

    def context_menu(self, shape: Optional[ShapeEditor], screen_pos, p: QPointF, mask: Optional[int] = None) -> None:
        menu = self.build_menu(shape, p, mask)
        if menu is not None:
            menu.exec(screen_pos)


def round_graphic(g, decimals: int = 3):
    """Rounds float geometry (also inside subregions) so values written back are tidy."""
    if isinstance(g, dict):
        return {k: round_graphic(v, decimals) for k, v in g.items()}
    if isinstance(g, list):
        return [round_graphic(v, decimals) for v in g]
    if isinstance(g, float):
        return round(g, decimals)
    return g
