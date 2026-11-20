"""Image display with result graphics overlay and an interactive graphic editor."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from . import graphics
from .editors import GraphicEditor

try:  # QtSvgWidgets is optional at runtime
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtSvgWidgets import QGraphicsSvgItem
except ImportError:  # pragma: no cover
    QSvgRenderer = None
    QGraphicsSvgItem = None


# ISVS "Show Image Saturation": grey (or RGB) level <= 5 is undersaturated (blue), >= 240 oversaturated (red).
LOW_SATURATION = 5
HIGH_SATURATION = 240

TEXT_FIXED, TEXT_SCALE, TEXT_SHRINK = "fixed", "scale", "shrink"
TEXT_SCALE_MODES = {TEXT_FIXED: "Fixed", TEXT_SCALE: "Scale With Image", TEXT_SHRINK: "Shrink Only"}


def saturation_mask(image: QImage) -> QImage:
    """An overlay image: red where any channel >= HIGH_SATURATION, blue where all channels <= LOW_SATURATION."""
    img = image.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    data = bytes(img.constBits())[: w * h * 4]  # RGB32 rows have no padding
    high = bytes(1 if v >= HIGH_SATURATION else 0 for v in range(256))
    low = bytes(1 if v <= LOW_SATURATION else 0 for v in range(256))
    over = under = None
    for ch in (0, 1, 2):  # B, G, R (little-endian RGB32)
        plane = data[ch::4]
        o = int.from_bytes(plane.translate(high), "little")
        u = int.from_bytes(plane.translate(low), "little")
        over = o if over is None else over | o
        under = u if under is None else under & u
    n = w * h
    # index 1 = over (red), 2 = under (blue): under pixels can never be over, so a plain sum works
    idx = (over + 2 * under).to_bytes(n, "little")
    mask = QImage(idx, w, h, w, QImage.Format.Format_Indexed8)
    mask.setColorTable([0x00000000, 0xFFFF0000, 0xFF0000FF])
    return mask.copy()  # detach from the Python buffer


class ImageView(QGraphicsView):
    mouseMovedImage = Signal(float, float)  # native coordinates under the mouse
    pixelHovered = Signal(str)  # "Approximate (R,G,B)@(x,y) = r,g,b" or "" outside the image
    zoomModeChanged = Signal(str)  # "fit", "fill", "1:1" or "" (free zoom)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(86, 86, 86))  # ISVS empty image area (#565656)
        self.setMouseTracking(True)
        self._pixmap = QGraphicsPixmapItem()
        self._pixmap.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._pixmap)
        self._extra_layers: list = []
        self._overlay = QGraphicsItemGroup()
        self._overlay.setHandlesChildEvents(False)
        self._overlay.setZValue(1)
        self.scene().addItem(self._overlay)
        self._svg_items: list = []
        self._graphics: list[dict] = []
        self._selected_sources: set[str] = set()
        self._xy = True
        self._fit_pending = True
        self._image_size: Optional[tuple[int, int]] = None
        self.editor: Optional[GraphicEditor] = None
        self.show_graphics = True
        self._image = QImage()
        self._zoom_mode = "fit"
        self._rotation = 0
        self._saturation = QGraphicsPixmapItem()
        self._saturation.setZValue(0.6)
        self._saturation.setVisible(False)
        self.scene().addItem(self._saturation)
        self.show_saturation = False
        self.text_scale_mode = TEXT_FIXED

    # ------------------------------------------------------------------ image
    def set_coordinate_mode(self, uses_xy: bool) -> None:
        self._xy = uses_xy
        self._overlay.setTransform(QTransform() if uses_xy else graphics.SWAP_AXES)

    def set_image(self, image: QImage) -> None:
        if image.isNull():
            return
        self._image = image
        self._pixmap.setPixmap(QPixmap.fromImage(image))
        if self.show_saturation:
            self._update_saturation()
        size = (image.width(), image.height())
        self.scene().setSceneRect(QRectF(0, 0, image.width(), image.height()))
        if self._fit_pending or size != self._image_size:
            self._image_size = size
            self._fit_pending = False
            self._apply_zoom_mode()

    def image(self) -> QImage:
        return self._image

    def clear(self) -> None:
        self._image = QImage()
        self._saturation.setPixmap(QPixmap())
        self._pixmap.setPixmap(QPixmap())
        self.set_graphics([])
        self.set_extra_images([])
        self.set_svg_layers([])
        self._fit_pending = True

    def set_extra_images(self, layers: list[tuple[QImage, float, float]]) -> None:
        """Processed-image layers drawn above the main image at (tx, ty)."""
        for item in self._extra_layers:
            self.scene().removeItem(item)
        self._extra_layers = []
        for img, tx, ty in layers:
            item = QGraphicsPixmapItem(QPixmap.fromImage(img))
            pos = QPointF(tx, ty) if self._xy else QPointF(ty, tx)
            item.setPos(pos)
            item.setZValue(0.5)
            self.scene().addItem(item)
            self._extra_layers.append(item)

    def set_svg_layers(self, svgs: list[bytes]) -> None:
        for item in self._svg_items:
            self.scene().removeItem(item)
        self._svg_items = []
        if QGraphicsSvgItem is None:
            return
        for data in svgs:
            renderer = QSvgRenderer(data)
            if not renderer.isValid():
                continue
            item = QGraphicsSvgItem()
            item.setSharedRenderer(renderer)
            item._renderer = renderer  # keep alive
            item.setZValue(0.8)
            item.setVisible(self.show_graphics)
            self.scene().addItem(item)
            self._svg_items.append(item)

    # ------------------------------------------------------------------ zoom / rotation
    @property
    def zoom_mode(self) -> str:
        return self._zoom_mode

    def _set_zoom_mode(self, mode: str) -> None:
        if mode != self._zoom_mode:
            self._zoom_mode = mode
            self.zoomModeChanged.emit(mode)

    def scale_factor(self) -> float:
        t = self.transform()
        return (t.m11() ** 2 + t.m12() ** 2) ** 0.5

    def _base_transform(self) -> None:
        self.resetTransform()
        if self._rotation:
            self.rotate(self._rotation)

    def _fit_scale(self, fill: bool) -> None:
        rect = self.scene().sceneRect()
        vp = self.viewport().rect()
        if rect.width() <= 0 or rect.height() <= 0 or vp.width() <= 2 or vp.height() <= 2:
            return
        self._base_transform()
        mapped = self.transform().mapRect(rect)
        sx, sy = (vp.width() - 2) / mapped.width(), (vp.height() - 2) / mapped.height()
        s = max(sx, sy) if fill else min(sx, sy)
        self.scale(s, s)
        self.centerOn(rect.center())
        self._update_text_scale()

    def _apply_zoom_mode(self) -> None:
        if self._zoom_mode == "fit":
            self._fit_scale(False)
        elif self._zoom_mode == "fill":
            self._fit_scale(True)
        elif self._zoom_mode == "1:1":
            self._base_transform()
            self._update_text_scale()

    def fit(self) -> None:
        """Zoom to Fit: the whole image is visible (kept when the view is resized)."""
        self._set_zoom_mode("fit")
        self._apply_zoom_mode()

    def fill(self) -> None:
        """Zoom to Fill: the image covers the whole display."""
        self._set_zoom_mode("fill")
        self._apply_zoom_mode()

    def one_to_one(self) -> None:
        """Zoom 1:1: one image pixel per display pixel."""
        self._set_zoom_mode("1:1")
        self._apply_zoom_mode()

    def zoom(self, factor: float) -> None:
        self._set_zoom_mode("")
        self.scale(factor, factor)
        self._update_text_scale()

    def rotate_image(self) -> None:
        """Rotate Image: turns the display 90 degrees clockwise."""
        self._rotation = (self._rotation + 90) % 360
        if self._zoom_mode:
            self._apply_zoom_mode()
        else:
            self.rotate(90)
        if self.editor is not None:
            self.editor.refresh()

    @property
    def rotation(self) -> int:
        return self._rotation

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._zoom_mode in ("fit", "fill"):
            self._apply_zoom_mode()

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.zoom(factor)

    def mouseMoveEvent(self, event) -> None:
        scene_pt = self.mapToScene(event.position().toPoint())
        p = self._overlay.mapFromScene(scene_pt)
        self.mouseMovedImage.emit(p.x(), p.y())
        self.pixelHovered.emit(self.pixel_text(scene_pt.x(), scene_pt.y()))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.pixelHovered.emit("")
        super().leaveEvent(event)

    def pixel_text(self, x: float, y: float) -> str:
        """ISVS Show Pixel Values text for image position (x, y); exact only at zoom 1:1."""
        img = self._image
        ix, iy = int(x), int(y)
        if img.isNull() or x < 0 or y < 0 or ix >= img.width() or iy >= img.height():
            return ""
        c = img.pixelColor(ix, iy)
        prefix = "" if self._zoom_mode == "1:1" else "Approximate "
        if img.isGrayscale():
            return f"{prefix}(Grey)@({ix},{iy}) = {c.red()}"
        return f"{prefix}(R,G,B)@({ix},{iy}) = {c.red()},{c.green()},{c.blue()}"

    # ------------------------------------------------------------------ saturation / text scale
    def set_show_saturation(self, show: bool) -> None:
        self.show_saturation = bool(show)
        if self.show_saturation:
            self._update_saturation()
        self._saturation.setVisible(self.show_saturation)

    def _update_saturation(self) -> None:
        if self._image.isNull():
            self._saturation.setPixmap(QPixmap())
            return
        self._saturation.setPixmap(QPixmap.fromImage(saturation_mask(self._image)))

    def set_text_scale_mode(self, mode: str) -> None:
        self.text_scale_mode = mode
        self._update_text_scale()

    def _update_text_scale(self) -> None:
        """Text Scale Mode for graphic labels: fixed size, scaled with the image, or only shrunk."""
        if self.text_scale_mode == TEXT_FIXED:
            ignore = True
        elif self.text_scale_mode == TEXT_SCALE:
            ignore = False
        else:
            ignore = self.scale_factor() >= 1.0
        if self.editor is not None:
            self.editor.refresh()  # handles and scan arrows keep their screen size
        flag = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
        for item in self._overlay.childItems():
            if isinstance(item, QGraphicsSimpleTextItem) and (self.editor is None or item is not self.editor.root):
                item.setFlag(flag, ignore)

    # ------------------------------------------------------------------ graphics
    def set_graphics(self, items: list[dict]) -> None:
        self._graphics = list(items)
        self._redraw()

    def set_selected_sources(self, sources: set[str]) -> None:
        self._selected_sources = {s.upper() for s in sources}
        self._redraw()

    def set_show_graphics(self, show: bool) -> None:
        self.show_graphics = show
        for item in self._svg_items:
            item.setVisible(show)
        self._redraw()

    def _redraw(self) -> None:
        for child in list(self._overlay.childItems()):
            if self.editor is not None and child is self.editor.root:
                continue
            self.scene().removeItem(child)
        if not self.show_graphics:
            return
        for g in self._graphics:
            source = str(g.get("source") or "").upper()
            hl = bool(source) and source in self._selected_sources
            for item in graphics.make_items(g, self._overlay, highlight=hl):
                item.setZValue(2 if hl else 1)
        self._update_text_scale()

    # ------------------------------------------------------------------ editing
    def begin_edit(self, graphic: dict, transform: Optional[QTransform] = None, flags: Optional[dict] = None,
                   function: Optional[str] = None) -> GraphicEditor:
        """Interactive Graphics Mode for ``graphic`` (native coordinates, or the coordinates of a
        fixture: ``transform`` maps them to native ones)."""
        self.end_edit()
        self.editor = GraphicEditor(graphic, self._overlay, transform, flags, function)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.editor.refresh()
        return self.editor

    def contextMenuEvent(self, event) -> None:
        super().contextMenuEvent(event)
        if not event.isAccepted() and self.editor is not None:  # right-click outside the graphic
            p = self.editor.root.mapFromScene(self.mapToScene(event.pos()))
            self.editor.context_menu(None, event.globalPos(), p)
            event.accept()

    def end_edit(self) -> None:
        if self.editor is not None:
            self.editor.remove()
            self.editor = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
