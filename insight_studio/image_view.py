"""Image display with result graphics overlay and an interactive graphic editor."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QGraphicsScene,
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


class ImageView(QGraphicsView):
    mouseMovedImage = Signal(float, float)  # native coordinates under the mouse

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(48, 48, 48))
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

    # ------------------------------------------------------------------ image
    def set_coordinate_mode(self, uses_xy: bool) -> None:
        self._xy = uses_xy
        self._overlay.setTransform(QTransform() if uses_xy else graphics.SWAP_AXES)

    def set_image(self, image: QImage) -> None:
        if image.isNull():
            return
        self._pixmap.setPixmap(QPixmap.fromImage(image))
        size = (image.width(), image.height())
        self.scene().setSceneRect(QRectF(0, 0, image.width(), image.height()))
        if self._fit_pending or size != self._image_size:
            self._image_size = size
            self._fit_pending = False
            self.fit()

    def clear(self) -> None:
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

    def fit(self) -> None:
        rect = self.scene().sceneRect()
        if rect.width() > 0 and rect.height() > 0:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor: float) -> None:
        self.scale(factor, factor)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.zoom(factor)

    def mouseMoveEvent(self, event) -> None:
        p = self._overlay.mapFromScene(self.mapToScene(event.position().toPoint()))
        self.mouseMovedImage.emit(p.x(), p.y())
        super().mouseMoveEvent(event)

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

    # ------------------------------------------------------------------ editing
    def begin_edit(self, graphic: dict) -> GraphicEditor:
        self.end_edit()
        self.editor = GraphicEditor(graphic, self._overlay)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        return self.editor

    def end_edit(self) -> None:
        if self.editor is not None:
            self.editor.remove()
            self.editor = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
