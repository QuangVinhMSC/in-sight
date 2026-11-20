"""Converts In-Sight graphic objects (HMI API section 3.4.3) into Qt graphics items.

Items are built in the device's "native" coordinates with ``QTransform.rotate(angle)``. On
devices that report the ``xyCoordinates`` capability this is image X/Y with clockwise angles.
On older devices (x = row, y = column, counter-clockwise angles) the caller places the overlay
group under an axis-swap transform, which maps both positions and rotation direction.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsSimpleTextItem,
)

from .cells import argb_to_rgba

DEFAULT_COLOR = QColor(0, 255, 0)
SELECTED_COLOR = QColor(255, 200, 0)
SWAP_AXES = QTransform(0, 1, 1, 0, 0, 0)


def qcolor(value, fallback: QColor = DEFAULT_COLOR) -> QColor:
    rgba = argb_to_rgba(value)
    if rgba is None:
        return QColor(fallback)
    r, g, b, a = rgba
    return QColor(r, g, b, a if a else 255)


def _f(g: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(g.get(key, default))
    except (TypeError, ValueError):
        return default


def _points(flat: Iterable, stride: int = 2) -> list[QPointF]:
    vals = [float(v) for v in (flat or [])]
    return [QPointF(vals[i], vals[i + 1]) for i in range(0, len(vals) - stride + 1, stride)]


def region_transform(g: dict) -> QTransform:
    t = QTransform()
    t.translate(_f(g, "x"), _f(g, "y"))
    t.rotate(_f(g, "angle"))
    return t


def shape_path(g: dict) -> Optional[QPainterPath]:
    """Outline path for a geometric graphic in native coordinates, or None."""
    t = g.get("$type")
    path = QPainterPath()
    if t in ("Region", "FilledBox", "Rectangle"):
        w, h = _f(g, "w"), _f(g, "h")
        rect = QPainterPath()
        curve = _f(g, "curve")
        if t == "Region" and abs(curve) > 1e-3 and w > 0:
            # Curved region: an annular sector (see curve_point).
            rect = _curved_region(w, h, curve)
        else:
            rect.addRect(QRectF(0, 0, w, h))
        return region_transform(g).map(rect)
    if t == "Circle":
        r = _f(g, "radius")
        path.addEllipse(QPointF(_f(g, "x"), _f(g, "y")), r, r)
        return path
    if t == "Annulus":
        c = QPointF(_f(g, "x"), _f(g, "y"))
        for r in (_f(g, "innerRadius"), _f(g, "outerRadius")):
            path.addEllipse(c, r, r)
        return path
    if t == "Arc":
        r = _f(g, "radius")
        rect = QRectF(_f(g, "x") - r, _f(g, "y") - r, 2 * r, 2 * r)
        a0, a1 = _f(g, "angle0"), _f(g, "angle1")
        sweep = a1 - a0
        if g.get("rotateClockwise"):
            sweep = -sweep
        path.arcMoveTo(rect, -a0)
        path.arcTo(rect, -a0, -sweep)
        return path
    if t == "Line":
        path.moveTo(_f(g, "x0"), _f(g, "y0"))
        path.lineTo(_f(g, "x1"), _f(g, "y1"))
        for idx, (ax, ay, bx, by) in enumerate(
            [(_f(g, "x0"), _f(g, "y0"), _f(g, "x1"), _f(g, "y1")),
             (_f(g, "x1"), _f(g, "y1"), _f(g, "x0"), _f(g, "y0"))]
        ):
            if int(g.get(f"adornment{idx}", 0) or 0) == 1:
                _arrow_head(path, QPointF(ax, ay), QPointF(bx, by))
        return path
    if t in ("LineList",):
        vals = [float(v) for v in (g.get("lines") or g.get("points") or [])]
        for i in range(0, len(vals) - 3, 4):
            path.moveTo(vals[i], vals[i + 1])
            path.lineTo(vals[i + 2], vals[i + 3])
        return path
    if t in ("Polygon", "BlobChain", "Polyline", "BeadPath"):
        stride = int(g.get("pointSize", 2) or 2) if t == "BeadPath" else 2
        pts = _points(g.get("points"), stride)
        if not pts:
            return None
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        if t in ("Polygon", "BlobChain") or (t == "BeadPath" and g.get("closed")):
            path.closeSubpath()
        return path
    if t == "4Side":
        pts = [QPointF(_f(g, f"x{i}"), _f(g, f"y{i}")) for i in range(4)]
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        path.closeSubpath()
        return path
    if t == "ColorMatch":
        vals = [float(v) for v in (g.get("segments") or [])]
        for i in range(0, len(vals) - 3, 4):
            path.moveTo(vals[i], vals[i + 1])
            path.lineTo(vals[i + 2], vals[i + 3])
        return path
    if t == "Cross":
        w, h = _f(g, "w", 20), _f(g, "h", 20)
        local = QPainterPath()
        local.moveTo(-w / 2, 0)
        local.lineTo(w / 2, 0)
        local.moveTo(0, -h / 2)
        local.lineTo(0, h / 2)
        return region_transform(g).map(local)
    return None


def curve_point(w: float, h: float, curve: float, s: float, t: float) -> QPointF:
    """Region coordinates (``s`` along X, ``t`` along Y, before ``region_transform``) of a point of
    a curved region, as the IS8902CX draws it (SVG layer, 2026-11-20): an annular sector whose
    left edge (the Y axis) stays straight, whose centre line keeps the length ``w`` and whose right
    edge is turned by ``curve`` degrees; a positive curve bends towards +Y. Its centre is at
    (0, h/2 + w/θ), so the X-axis edge has radius h/2 + w/θ and the opposite edge w/θ − h/2."""
    theta = math.radians(curve)
    if abs(theta) < 1e-9 or w <= 0:
        return QPointF(s, t)
    c = h / 2 + w / theta
    phi = s * theta / w
    rho = c - t
    return QPointF(rho * math.sin(phi), c - rho * math.cos(phi))


def curve_local(w: float, h: float, curve: float, p: QPointF) -> QPointF:
    """Inverse of :func:`curve_point`: (s, t) of the region point ``p`` (region coordinates)."""
    theta = math.radians(curve)
    if abs(theta) < 1e-9 or w <= 0:
        return QPointF(p)
    c = h / 2 + w / theta
    vx, vy = p.x(), p.y() - c
    r = math.hypot(vx, vy)
    if theta > 0:
        phi, rho = math.atan2(vx, -vy), r
    else:
        phi, rho = math.atan2(-vx, vy), -r
    return QPointF(phi * w / theta, c - rho)


def region_point(g: dict, s: float, t: float) -> QPointF:
    """Image (native) coordinates of the region point (s, t), curve included."""
    p = curve_point(_f(g, "w"), _f(g, "h"), _f(g, "curve"), s, t)
    return region_transform(g).map(p)


def region_local(g: dict, p: QPointF) -> QPointF:
    """Region coordinates (s, t) of the image (native) point ``p``, curve included."""
    q = region_transform(g).inverted()[0].map(p)
    return curve_local(_f(g, "w"), _f(g, "h"), _f(g, "curve"), q)


def _curved_region(w: float, h: float, curve: float) -> QPainterPath:
    path = QPainterPath()
    steps = max(8, int(abs(curve) / 3) + 1)

    def edge(t: float, forward: bool) -> list[QPointF]:
        rng = range(steps + 1) if forward else range(steps, -1, -1)
        return [curve_point(w, h, curve, w * i / steps, t) for i in rng]

    top, bottom = edge(0.0, True), edge(h, False)
    path.moveTo(top[0])
    for p in top[1:] + bottom:  # top arc, right (radial) edge, bottom arc back
        path.lineTo(p)
    path.closeSubpath()  # left edge: straight, along the Y axis
    return path


def _arrow_head(path: QPainterPath, tip: QPointF, tail: QPointF, size: float = 10) -> None:
    dx, dy = tip.x() - tail.x(), tip.y() - tail.y()
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    for sign in (1, -1):
        bx = tip.x() - size * ux + sign * size * 0.5 * -uy
        by = tip.y() - size * uy + sign * size * 0.5 * ux
        path.moveTo(tip)
        path.lineTo(bx, by)


class MarkerItem(QGraphicsPathItem):
    """A fixed-size marker (Point, Fixture) that does not scale with zoom."""

    def __init__(self, kind: str, angle: float, color: QColor, parent: Optional[QGraphicsItem] = None):
        super().__init__(parent)
        path = QPainterPath()
        if kind == "Fixture":
            path.moveTo(0, 0)
            path.lineTo(30, 0)
            _arrow_head(path, QPointF(30, 0), QPointF(0, 0), 8)
            path.moveTo(0, 0)
            path.lineTo(0, 20)
            t = QTransform()
            t.rotate(angle)
            path = t.map(path)
        else:
            path.moveTo(-6, -6)
            path.lineTo(6, 6)
            path.moveTo(-6, 6)
            path.lineTo(6, -6)
        self.setPath(path)
        pen = QPen(color, 1.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)


def make_items(g: dict, parent: QGraphicsItem, highlight: bool = False) -> list[QGraphicsItem]:
    """Creates child items of ``parent`` for one graphic. Returns the items created."""
    t = g.get("$type")
    color = SELECTED_COLOR if highlight else qcolor(g.get("color"))
    width = max(1.0, _f(g, "lineThickness", 1.0)) + (1.0 if highlight else 0.0)
    items: list[QGraphicsItem] = []

    if t in ("CompositeRegion", "MaskedRegion", "PolylinePath"):
        for sub in g.get("subregions") or []:
            shape = dict(sub.get("shape") or {})
            if not shape:
                continue
            shape.setdefault("color", g.get("color"))
            created = make_items(shape, parent, highlight)
            if not sub.get("add", True):
                for it in created:
                    if isinstance(it, QGraphicsPathItem):
                        it.setBrush(QBrush(color, Qt.BrushStyle.BDiagPattern))
                        pen = it.pen()
                        pen.setStyle(Qt.PenStyle.DashLine)
                        it.setPen(pen)
            items.extend(created)
        return items
    if t == "MultiGraphics":
        for child in g.get("graphics") or []:
            items.extend(make_items(child, parent, highlight))
        return items
    if t == "SubRegion":
        return make_items(g.get("shape") or {}, parent, highlight)
    if t == "Text":
        item = QGraphicsSimpleTextItem(str(g.get("text", "")), parent)
        font = QFont(str(g.get("font") or "Sans"))
        font.setPointSizeF(max(6.0, _f(g, "fontSize", 10)))
        item.setFont(font)
        item.setBrush(QBrush(color))
        item.setPos(QPointF(_f(g, "x"), _f(g, "y")))
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        bg = g.get("bgColor")
        rgba = argb_to_rgba(bg)
        if rgba and rgba[3] > 0:
            back = QGraphicsPathItem(item)
            p = QPainterPath()
            p.addRect(item.boundingRect())
            back.setPath(p)
            back.setBrush(QBrush(QColor(*rgba)))
            back.setPen(Qt.PenStyle.NoPen)
            back.setZValue(-1)
            back.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent, True)
        items.append(item)
        return items
    if t in ("Point", "Fixture"):
        item = MarkerItem(t, _f(g, "angle"), color, parent)
        item.setPos(QPointF(_f(g, "x"), _f(g, "y")))
        items.append(item)
        return items

    path = shape_path(g)
    if path is None:
        return items
    item = QGraphicsPathItem(path, parent)
    pen = QPen(color, width)
    pen.setCosmetic(True)
    if t == "4Side":
        pen.setStyle(Qt.PenStyle.DashLine)
    item.setPen(pen)
    if t == "FilledBox":
        item.setBrush(QBrush(color))
    if t == "ColorMatch":
        # Multi-coloured segments: draw each with its own colour.
        item.setPen(Qt.PenStyle.NoPen)
        vals = [float(v) for v in (g.get("segments") or [])]
        colors = g.get("colors") or []
        for i in range(0, len(vals) - 3, 4):
            seg = QPainterPath()
            seg.moveTo(vals[i], vals[i + 1])
            seg.lineTo(vals[i + 2], vals[i + 3])
            s = QGraphicsPathItem(seg, item)
            c = qcolor(colors[i // 4], color) if i // 4 < len(colors) else color
            p = QPen(c, width)
            p.setCosmetic(True)
            s.setPen(p)
    items.append(item)
    return items
