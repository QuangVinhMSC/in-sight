"""Interactive Graphics Mode: editors for editable graphics (EditRegion, EditCircle, …, the
literal regions of a tool's property sheet).

Drawn like ISVS 26.1 (help "Rectangle Regions Interactive Graphics Mode", live screenshots
``live/20``, ``live/28…39``, ``live/98…112``): the graphic in red, magenta handles — four resizable
corners, the two scan direction arrows labelled X and Y, the rotation handle in the middle of the
bottom edge and the bend handle in the middle of the right edge. Dragging inside a shape moves it,
dragging one of its sides resizes it. Rotating turns a region about its centre (angles shown
0…360, clockwise); bending keeps the region's centre and the direction of its chord (Angle +
Curve/2 stays the same) and stops when the inner edge reaches a radius of 1 px. Polygons: a
dashed bounding box with a rotation handle below it, right-click an edge or a point for Add Point /
Remove Point, Shift+Alt+click a point to remove it. Composite regions have a right-click menu
(Add Subregion ▸, Remove Subregion, Subregion Operation ▸; a new subregion is the first one at
80 % and subtracts); masked regions one with Add Mask / Delete Mask (new masks are placed at the
left end of the ROI). ``status_text`` is ISVS's status line under the image
(``Location=306,78 Size=440×320 Rotation=39.0° Curve=-49.3°``; while dragging only what changes).

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
MAX_CURVE = 360.0  # beyond the inner-radius limit (max_curve) — a full turn


def max_curve(w: float, h: float) -> float:
    """ISVS stops bending when the inner edge reaches a radius of 1 px: |curve| ≤ W/(H/2 + 1) rad
    (±156.6° for 440×320, survey 2026-11-20)."""
    if w <= 0:
        return 0.0
    return min(MAX_CURVE, math.degrees(w / (max(h, 0.0) / 2 + 1)))


def norm_angle(a: float) -> float:
    """ISVS shows angles as 0…360 (342.253 for −17.747)."""
    a = round(a % 360.0, 6)
    return 0.0 if a >= 360.0 else a + 0.0

# Edit flags of beginEdit's Editing object, as the IS8902CX sends them (2026-11-20); absent means allowed.
#   EditingRegion: move resize rotate bend          EditingCircle / EditingAnnulus: move resize
#   EditingPolygon / EditingPolyline: move movePoints addPoints removePoints scale rotate
#   EditingCompositeRegion: move rotate addRegions removeRegions editRegions
#   EditingMaskedRegion: move resize rotate bend addRegion removeRegion editRegion
# They are normalised to the keys below (the plural composite names to the singular ones).
FLAG_KEYS = ("move", "resize", "rotate", "bend", "scale", "addRegion", "removeRegion", "editRegion",
             "addPoints", "removePoints", "movePoints")
FLAG_ALIASES = {"size": "resize", "addRegions": "addRegion", "removeRegions": "removeRegion",
                "editRegions": "editRegion"}
# Editing object type -> the Edit* function that made it (masked and polyline data are CompositeRegions)
EDITING_FUNCTIONS = {"EditingMaskedRegion": "EditMaskedRegion", "EditingPolyline": "EditPolylinePath",
                     "EditingCompositeRegion": "EditCompositeRegion"}


def edit_flags(*sources: Optional[dict]) -> dict:
    """The edit flags found in the given dicts (beginEdit's Editing object first)."""
    out: dict = {}
    for src in sources:
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            key = FLAG_ALIASES.get(k, k)
            if key in FLAG_KEYS and isinstance(v, bool) and key not in out:
                out[key] = v
    return out


def editing_function(editing: Optional[dict]) -> Optional[str]:
    """The Edit* function named by an Editing object's ``$type`` (None when it does not tell)."""
    if isinstance(editing, dict):
        t = str(editing.get("$type") or "")
        return EDITING_FUNCTIONS.get(t) or ("Edit" + t[len("Editing"):] if t.startswith("Editing") else None)
    return None


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
        if self.label == "+":  # centre cross-hair
            painter.setPen(_cosmetic(EDIT_COLOR, 1))
            painter.drawLine(QPointF(-7, 0), QPointF(7, 0))
            painter.drawLine(QPointF(0, -7), QPointF(0, 7))
            return
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
        if self.owner.preview:
            for h in self.handles + [getattr(self, n) for n in ("rotator", "bender") if hasattr(self, n)]:
                h.setVisible(False)
            self.body.setCursor(Qt.CursorShape.ArrowCursor)

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
        # ISVS shows a cross-hair at the centre while the region is only shown (live/25), not in IGM
        self.crosshair = ScanArrow(self.root, "+")
        self.crosshair.setVisible(False)

    def transform(self) -> QTransform:
        """Region coordinates -> parent, ignoring the curve (see :meth:`pt` / :meth:`local`)."""
        return graphics.region_transform(self.g)

    def pt(self, s: float, t: float) -> QPointF:
        """The region point (s along X, t along Y) in parent coordinates, curve included."""
        return graphics.region_point(self.g, s, t)

    def local(self, p: QPointF) -> QPointF:
        """Inverse of :meth:`pt`."""
        return graphics.region_local(self.g, p)

    def place_handles(self) -> None:
        w, h = self.num("w"), self.num("h")
        for hnd, (fx, fy) in zip(self.corners, self.CORNERS):
            hnd.setPos(self.pt(fx * w, fy * h))
            hnd.setVisible(self.flag("resize"))
        self.rotator.setPos(self.pt(w / 2, h))  # middle of the bottom edge
        self.rotator.setVisible(self.flag("rotate"))
        self.bender.setPos(self.pt(w, h / 2))  # middle of the right edge
        self.bender.setVisible(self.flag("bend"))
        show_axes = self.g.get("showXArrow", True) is not False and not self.subtract
        top, left = self.pt(w / 2, 0), self.pt(0, h / 2)
        self.arrow_x.setPos(top)
        self.arrow_x.set_vectors(device_vector(self.root, top, self.pt(w / 2 + 1, 0) - top),
                                 device_vector(self.root, top, self.pt(w / 2, -1) - top))
        self.arrow_y.setPos(left)
        self.arrow_y.set_vectors(device_vector(self.root, left, self.pt(0, h / 2 + 1) - left),
                                 device_vector(self.root, left, self.pt(-1, h / 2) - left))
        self.crosshair.setPos(self.pt(w / 2, h / 2))
        self.crosshair.setVisible(self.owner.preview and not self.subtract)
        self.arrow_x.setVisible(show_axes)
        self.arrow_y.setVisible(show_axes and self.g.get("showYArrow", True) is not False)
        line = QPainterPath()
        if self.g.get("showScanLine") or self.owner.masked:  # the device draws it along the centre line
            steps = max(1, int(abs(self.num("curve")) / 3))
            line.moveTo(self.pt(0, h / 2))
            for i in range(1, steps + 1):
                line.lineTo(self.pt(w * i / steps, h / 2))
        self.scan_line.setPath(line)

    # ------------------------------------------------------------------ edits
    def _set_rect(self, left: float, top: float, right: float, bottom: float) -> None:
        """Crops/extends the region to [left, right] × [top, bottom] in region coordinates. A
        curved region keeps its centre of curvature: the new origin is the curved point
        (left, top), the angle turns with it and the curve shrinks with the span."""
        w, h, curve = self.num("w"), self.num("h"), self.num("curve")
        origin = self.pt(left, top)
        theta = math.radians(curve)
        if abs(theta) > 1e-9 and w > 0:
            span = (right - left) / w
            c = h / 2 + w / theta
            self.g["w"] = theta * span * (c - (top + bottom) / 2)
            self.g["curve"] = curve * span
            self.g["angle"] = self.num("angle") + math.degrees(left * theta / w)
        else:
            self.g["w"] = right - left
        self.g["x"], self.g["y"] = origin.x(), origin.y()
        self.g["h"] = bottom - top

    def _corner(self, fx: int, fy: int, p: QPointF) -> None:
        if not self.flag("resize"):
            return
        local = self.local(p)
        w, h = self.num("w"), self.num("h")
        left, right = (0.0, max(MIN_SIZE, local.x())) if fx else (min(w - MIN_SIZE, local.x()), w)
        top, bottom = (0.0, max(MIN_SIZE, local.y())) if fy else (min(h - MIN_SIZE, local.y()), h)
        self.owner.resize_shape(self, lambda: self._set_rect(left, top, right, bottom))

    def _side(self, side: str, p: QPointF) -> None:
        local = self.local(p)
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
        """The rotation handle follows the mouse around the region's centre."""
        if not self.flag("rotate"):
            return
        w, h = self.num("w"), self.num("h")
        c, hnd = self.pt(w / 2, h / 2), self.pt(w / 2, h)
        delta = math.degrees(math.atan2(p.y() - c.y(), p.x() - c.x())
                             - math.atan2(hnd.y() - c.y(), hnd.x() - c.x()))
        delta = (delta + 180.0) % 360.0 - 180.0
        if abs(delta) > 1e-9:
            self.owner.rotate_shape(self, c, delta)

    def rotate_about(self, c: QPointF, delta: float) -> None:
        t = QTransform().translate(c.x(), c.y()).rotate(delta).translate(-c.x(), -c.y())
        origin = t.map(QPointF(self.num("x"), self.num("y")))
        self.g["x"], self.g["y"] = origin.x(), origin.y()
        self.g["angle"] = round(norm_angle(self.num("angle") + delta), 3)

    def _bend(self, p: QPointF) -> None:
        """As ISVS: the region bends about its centre (the middle of the centre line stays put)
        and its chord keeps its direction, so Angle + Curve/2 is constant; the curve is twice the
        angle of the pointer seen from the centre against the chord (down = positive), limited
        by :func:`max_curve`."""
        if not self.flag("bend"):
            return
        w, h = self.num("w"), self.num("h")
        centre = self.pt(w / 2, h / 2)
        chord = self.num("angle") + self.num("curve") / 2
        v = QTransform().rotate(-chord).map(p - centre)
        limit = max_curve(w, h)
        curve = round(max(-limit, min(limit, 2 * math.degrees(math.atan2(v.y(), v.x())))), 3)
        self.owner.op = "bend"
        self.set_curve(curve)
        self.changed()

    def set_curve(self, curve: float) -> None:
        """Changes the curve keeping the region's centre and chord direction (ISVS)."""
        w, h = self.num("w"), self.num("h")
        centre = self.pt(w / 2, h / 2)
        chord = self.num("angle") + self.num("curve") / 2
        self.g["curve"] = curve
        self.g["angle"] = round(norm_angle(chord - curve / 2), 3)
        self.g["x"], self.g["y"] = 0.0, 0.0
        off = self.pt(w / 2, h / 2)
        self.g["x"], self.g["y"] = centre.x() - off.x(), centre.y() - off.y()

    def side_at(self, p: QPointF) -> Optional[str]:
        local = self.local(p)
        w, h, tol = self.num("w"), self.num("h"), self.tolerance()
        if not (-tol <= local.x() <= w + tol and -tol <= local.y() <= h + tol):
            return None
        for side, dist in (("left", abs(local.x())), ("right", abs(local.x() - w)),
                           ("top", abs(local.y())), ("bottom", abs(local.y() - h))):
            if dist <= tol:
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
    """Vertices can be dragged; right-click an edge or a point for Add Point / Remove Point,
    Shift+Alt+click on a point removes it (at least three points stay). As in ISVS a plain click
    on an edge does not add a point. A dashed bounding box with a rotation handle below its
    middle turns the polygon about the box centre; there are no scale handles (live/108…112)."""

    ROTATE_GAP_PX = 14  # the rotation handle sits this far below the box

    def __init__(self, *args, **kwargs) -> None:
        self._retired: list[Handle] = []
        self._turn: Optional[tuple[QPointF, QPointF, list[QPointF]]] = None  # centre, start, points
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
        if not hasattr(self, "box"):
            self.box = QGraphicsPathItem(self.root)
            self.box.setPen(_cosmetic(EDIT_COLOR, 1, Qt.PenStyle.DashLine))
            self.box.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.rotator = Handle(self.root, self._rotate, "rotate", "Rotate", Qt.CursorShape.CrossCursor,
                              on_press=self._press_rotate)

    def bounds(self) -> QRectF:
        pts = self.points()
        if not pts:
            return QRectF()
        xs, ys = [p.x() for p in pts], [p.y() for p in pts]
        return QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))

    def place_handles(self) -> None:
        pts = self.points()
        if len(pts) != len(self.handles):
            self._retired.append(self.rotator)
            _detach(self.rotator)
            self.build()
        for hnd, p in zip(self.handles, pts):
            hnd.setPos(p)
            hnd.setVisible(self.flag("movePoints") or self.flag("removePoints"))
        r = self.bounds()
        box = QPainterPath()
        if not self.owner.composite:  # a polygon of its own (EditPolygon), not a subregion
            box.addRect(r)
        self.box.setPath(box)
        self.rotator.setPos(QPointF(r.center().x(), r.bottom() + self.ROTATE_GAP_PX / device_scale(self.root)))
        self.rotator.setVisible(self.flag("rotate") and not self.owner.composite)

    def _press_rotate(self, event) -> bool:
        c = self.bounds().center()
        self._turn = (c, self.root.mapFromScene(event.scenePos()), self.points())
        return False

    def _rotate(self, p: QPointF) -> None:
        if not self.flag("rotate") or self._turn is None:
            return
        c, start, pts = self._turn
        delta = math.degrees(math.atan2(p.y() - c.y(), p.x() - c.x()) - math.atan2(start.y() - c.y(), start.x() - c.x()))
        t = QTransform().translate(c.x(), c.y()).rotate(delta).translate(-c.x(), -c.y())
        self.owner.op = "rotate"
        self.set_points([t.map(q) for q in pts])
        self.changed()

    def _vertex(self, i: int, p: QPointF) -> None:
        pts = self.points()
        if i < len(pts) and self.flag("movePoints"):
            self.owner.op = "points"
            pts[i] = p
            self.set_points(pts)
            self.changed()

    def _press_vertex(self, i: int, event) -> bool:
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier and mods & Qt.KeyboardModifier.AltModifier:
            pts = self.points()
            if len(pts) > 3 and self.flag("removePoints"):
                del pts[i]
                self.set_points(pts)
                self.changed()
            return True
        return False

    def move_by(self, d: QPointF) -> None:
        self.set_points([p + d for p in self.points()])

    def vertex_at(self, p: QPointF) -> Optional[int]:
        tol = 2 * self.tolerance()
        for i, q in enumerate(self.points()):
            if math.hypot(p.x() - q.x(), p.y() - q.y()) <= tol:
                return i
        return None

    def add_point(self, p: QPointF) -> None:
        """Add Point: on an edge at the clicked spot; on a point, in the middle of its next edge."""
        pts = self.points()
        v = self.vertex_at(p)
        if v is not None:
            a, b = pts[v], pts[(v + 1) % len(pts)]
            pts.insert(v + 1, (a + b) / 2)
        else:
            i = self.edge_at(p)
            if i is None:
                return
            pts.insert(i + 1, p)
        self.set_points(pts)
        self.changed()

    def remove_point(self, i: int) -> None:
        pts = self.points()
        if len(pts) > 3 and 0 <= i < len(pts):
            del pts[i]
            self.set_points(pts)
            self.changed()

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

    def press(self, p: QPointF, modifiers):
        return self._mover(p)


SHAPES: dict[str, type[ShapeEditor]] = {
    "Region": RegionShape, "Circle": CircleShape, "Annulus": AnnulusShape, "Line": LineShape,
    "Point": PointShape, "Polygon": PolygonShape,
}


# ============================================================================ masks
class MaskItem(QGraphicsPathItem):
    """A mask of an EditMaskedRegion: a hatched rectangle in the ROI (main region coordinates),
    normally across its whole height, that can be dragged along the ROI and resized by its sides."""

    def __init__(self, owner: "GraphicEditor", index: int, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.owner, self.index = owner, index
        self._drag: Optional[Callable[[QPointF], None]] = None
        self.setAcceptHoverEvents(True)
        self.setZValue(3)
        self.setPen(_cosmetic(EDIT_COLOR, 1.5))
        self.setBrush(QBrush(MASK_COLOR, Qt.BrushStyle.BDiagPattern))

    def _side(self, p: QPointF) -> Optional[str]:
        u0, wm = self.owner.masks[self.index][:2]
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
    statusChanged = Signal()  # status_text() changed (also when a drag ends)

    def __init__(self, graphic: dict, parent: QGraphicsItem, transform: Optional[QTransform] = None,
                 flags: Optional[dict] = None, function: Optional[str] = None, preview: bool = False) -> None:
        super().__init__()
        self.op: Optional[str] = None  # what the current drag changes: move, resize, rotate, bend, points
        self.preview = preview  # only shown (property sheet row selected, before F9): no handles
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
        # masked region: (x offset, width, y offset, height) of each mask in ROI coordinates. The device
        # keeps whatever is written (also masks offset in y); new masks span the ROI's height.
        self.masks: list[tuple[float, float, float, float]] = []
        self.mask_items: list[MaskItem] = []
        self.mask_layer: Optional[QGraphicsPathItem] = None
        self._retired: list = []  # removed items stay referenced: a menu/mouse handler may still run on them
        if preview:
            self.flags = {k: False for k in FLAG_KEYS}
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
                start = inv.map(QPointF(_num(m, "x"), _num(m, "y")))
                self.masks.append((start.x(), _num(m, "w"), start.y(), _num(m, "h")))
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
        self.statusChanged.emit()

    def end_drag(self) -> None:
        if self.op is not None:
            self.op = None
            self.statusChanged.emit()

    def status_text(self) -> str:
        """ISVS's status line under the image in Interactive Graphics Mode: ``Location=306,78
        Size=440×320 Rotation=39.0° Curve=-49.3°`` for a region (rounded; angles 1 decimal), the
        bounding box for other graphics; while dragging only what the drag changes."""
        main = self.shapes[0] if self.shapes and (self.masked or not self.composite) else None
        if isinstance(main, RegionShape):
            g = main.g
            loc = f"Location={round(_num(g, 'x'))},{round(_num(g, 'y'))}"
            size = f"Size={round(_num(g, 'w'))}×{round(_num(g, 'h'))}"
            rot = f"Rotation={_num(g, 'angle'):.1f}°"
            curve = f"Curve={_num(g, 'curve'):.1f}°"
            parts = {"move": [loc], "rotate": [rot], "bend": [curve],
                     "resize": [size, curve] if abs(_num(g, "curve")) > 1e-9 else [size]}.get(self.op)
            return " ".join(parts or [loc, size, rot, curve])
        rect = QRectF()
        for s in self.shapes:
            if not s.subtract or not self.composite:
                rect = rect.united(s.path().boundingRect())
        if isinstance(main, PolygonShape):  # ISVS counts pixels: 180…620 is 441 wide
            return (f"Location={math.floor(rect.left())},{math.floor(rect.top())} "
                    f"Size={math.floor(rect.right()) - math.floor(rect.left()) + 1}×"
                    f"{math.floor(rect.bottom()) - math.floor(rect.top()) + 1}")
        if isinstance(main, (CircleShape, AnnulusShape)) and not self.composite:
            g = main.g
            radii = (f"Radius={_num(g, 'radius'):.1f}" if g.get("$type") == "Circle" else
                     f"Inner Radius={_num(g, 'innerRadius'):.1f} Outer Radius={_num(g, 'outerRadius'):.1f}")
            return f"Location={round(_num(g, 'x'))},{round(_num(g, 'y'))} {radii}"
        if rect.isNull():
            return ""
        return f"Location={round(rect.left())},{round(rect.top())} Size={round(rect.width())}×{round(rect.height())}"

    def move_shape(self, shape: ShapeEditor, d: QPointF) -> None:
        self.op = "move"
        if self.composite and not self.masked and not self.flags.get("editRegion", True):
            for s in self.shapes:  # subregions are fixed: the whole composite moves
                s.move_by(d)
                s.sync()
            self.shape_changed()
            return
        shape.move_by(d)
        shape.changed()

    def resize_shape(self, shape: ShapeEditor, apply: Callable[[], None]) -> None:
        self.op = "resize"
        old_h = shape.num("h")
        apply()
        if self.masked:
            w, h = shape.num("w"), shape.num("h")
            masks = []
            for u, wm, v, hm in self.masks:
                wm = min(wm, w)
                if abs(v) < 1e-6 and abs(hm - old_h) < 1e-6:
                    v, hm = 0.0, h  # a mask across the ROI stays across it
                else:
                    hm = min(hm, h)
                    v = max(0.0, min(v, h - hm))
                masks.append((max(0.0, min(u, w - wm)), wm, v, hm))
            self.masks = masks
        shape.changed()

    def rotate_shape(self, shape: ShapeEditor, centre: QPointF, delta: float) -> None:
        self.op = "rotate"
        if isinstance(shape, RegionShape):
            shape.rotate_about(centre, delta)
            shape.changed()

    # ------------------------------------------------------------------ masks
    def from_mask_layer(self, p: QPointF) -> QPointF:
        return self.shapes[0].transform().map(p) if self.shapes else p

    def _sync_masks(self) -> None:
        main = self.shapes[0]
        self.mask_layer.setTransform(main.transform())
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
        for item, (u, wm, v, hm) in zip(self.mask_items, self.masks):
            p = QPainterPath()
            p.addRect(QRectF(u, v, wm, hm))
            item.setPath(p)
            o = t.map(QPointF(u, v))
            out.append({**template, "$type": "SubRegion", "add": False,
                        "shape": {**shape_tpl, "$type": "Region", "x": o.x(), "y": o.y(), "w": wm, "h": hm,
                                  "angle": main.num("angle"), "curve": 0.0}})
        subs[:] = out

    def move_mask(self, i: int, du: float) -> None:
        w = self.shapes[0].num("w")
        u, wm, v, hm = self.masks[i]
        self.masks[i] = (max(0.0, min(w - wm, u + du)), wm, v, hm)
        self.shape_changed()

    def resize_mask(self, i: int, side: str, x: float) -> None:
        w = self.shapes[0].num("w")
        u, wm, v, hm = self.masks[i]
        if side == "left":
            nu = max(0.0, min(u + wm - MIN_SIZE, x))
            self.masks[i] = (nu, u + wm - nu, v, hm)
        else:
            self.masks[i] = (u, max(MIN_SIZE, min(w - u, x - u)), v, hm)
        self.shape_changed()

    def add_mask(self, at_local_x: float = 0.0) -> None:
        """ISVS puts a new mask at the left end of the ROI, next to the masks already there — not
        at the click (live/99). ``at_local_x`` is kept for callers; it is not used."""
        main = self.shapes[0]
        w = main.num("w")
        wm = max(MIN_SIZE, min(w, round(max(10.0, w * 0.05), 3)))
        u = 0.0
        for mu, mw, _v, _h in sorted(self.masks):
            if mu < u + wm and u < mu + mw:  # overlaps: try right after this mask
                u = mu + mw
        u = min(u, max(0.0, w - wm))
        self.masks.append((u, wm, 0.0, main.num("h")))
        self.shape_changed()

    def delete_mask(self, i: int) -> None:
        if 0 <= i < len(self.masks):
            del self.masks[i]
            self.shape_changed()

    # ------------------------------------------------------------------ composite subregions
    def _new_subregion(self, kind: str, at: QPointF) -> dict:
        """ISVS (live/103): a new subregion is the first one at 80 % of its size, centred on it
        (a Region keeps the first region's angle); without a first subregion, around ``at``."""
        first = self.shapes[0] if self.shapes else None
        if first is not None:
            r = first.path().boundingRect()
            c, w, h = r.center(), r.width() * 0.8, r.height() * 0.8
        else:
            c, w, h = at, 100.0, 80.0
        if kind == "Region" and isinstance(first, RegionShape):
            fw, fh = first.num("w") * 0.8, first.num("h") * 0.8
            centre = first.pt(first.num("w") / 2, first.num("h") / 2)
            g = {"$type": "Region", "x": 0.0, "y": 0.0, "w": fw, "h": fh, "angle": first.num("angle"), "curve": 0.0}
            off = graphics.region_point(g, fw / 2, fh / 2)
            g["x"], g["y"] = centre.x() - off.x(), centre.y() - off.y()
            return g
        x, y, r = c.x(), c.y(), min(w, h) / 2
        return {
            "Region": {"$type": "Region", "x": x - w / 2, "y": y - h / 2, "w": w, "h": h, "angle": 0.0, "curve": 0.0},
            "Circle": {"$type": "Circle", "x": x, "y": y, "radius": r},
            "Annulus": {"$type": "Annulus", "x": x, "y": y, "innerRadius": r / 2, "outerRadius": r},
            "Polygon": {"$type": "Polygon", "points": [x, y - h / 2, x + w / 2, y + h / 2, x - w / 2, y + h / 2],
                        "length": 3},
        }[kind]

    def add_subregion(self, kind: str, at: QPointF, add: Optional[bool] = None) -> None:
        """Add Subregion ▸ kind. From the Interactive Graphics Mode menu the new subregion
        subtracts (ISVS live/104); the first one of an empty composite adds."""
        if kind not in SHAPE_TYPES:
            return
        color = self.g.get("color")
        shape = self._new_subregion(kind, at)
        if color is not None:
            shape["color"] = color
        if add is None:
            add = not self._subregions()
        sub = {"$type": "SubRegion", "add": add, "shape": shape}
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
                mask = next((i for i, (u, wm, v, hm) in enumerate(self.masks)
                             if u <= local.x() <= u + wm and v <= local.y() <= v + hm), None)
            a = menu.addAction("Delete Mask", lambda: self.delete_mask(mask))
            a.setEnabled(mask is not None and self.flags.get("removeRegion", True))
            return menu
        if isinstance(shape, PolygonShape) and not self.composite:
            menu = QMenu()
            vertex = shape.vertex_at(p)
            on_edge = vertex is not None or shape.edge_at(p) is not None
            a = menu.addAction("Add Point", lambda: shape.add_point(p))
            a.setEnabled(on_edge and self.allowed("addPoints"))
            a = menu.addAction("Remove Point", lambda: shape.remove_point(vertex))
            a.setEnabled(vertex is not None and len(shape.points()) > 3 and self.allowed("removePoints"))
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
        # ISVS greys the operation of the first subregion (live/102)
        op.setEnabled(shape is not None and self.flags.get("editRegion", True) and bool(self._sub_index(shape)))
        return menu

    def context_menu(self, shape: Optional[ShapeEditor], screen_pos, p: QPointF, mask: Optional[int] = None) -> None:
        if self.preview:
            return
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
