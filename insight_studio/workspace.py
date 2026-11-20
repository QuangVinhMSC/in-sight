"""The ISVS editor area: spreadsheet grid overlaid on the image (or split), plus the pixel-value strip."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from .image_view import ImageView
from .sheet import SheetView

# Cell opacity per transparency level; level 1 matches the ISVS default look (image faintly visible).
CELL_ALPHA_LEVELS = (255, 230, 200, 170, 140, 110, 80, 50)
DEFAULT_TRANSPARENCY = 1


class ImageSheetArea(QWidget):
    """Hosts the image display and the grid in *overlay* (grid drawn over the image) or *split* view."""

    viewChanged = Signal()  # overlay/split, grid visibility or transparency changed

    def __init__(self, image: ImageView, sheet: SheetView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.image = image
        self.sheet = sheet
        self._overlay = True
        self._show_grid = True
        self._grid_suppressed = False  # e.g. while a graphic is edited on the image
        self._selecting = False  # cell selection mode: grid shown opaque, without the image
        self._transparency = DEFAULT_TRANSPARENCY
        self._message = ""
        self._pixel_text = ""

        self._stack = QStackedWidget()
        self._overlay_page = QWidget()
        self._overlay_layout = QGridLayout(self._overlay_page)
        self._overlay_layout.setContentsMargins(0, 0, 0, 0)
        self._split = QSplitter(Qt.Orientation.Vertical)
        self._split.setChildrenCollapsible(False)
        self._stack.addWidget(self._overlay_page)
        self._stack.addWidget(self._split)
        self._split_sizes: list[int] = [520, 340]

        self.pixel_strip = QLabel()
        self.pixel_strip.setObjectName("pixelStrip")
        self.pixel_strip.setFixedHeight(20)
        self.image.pixelHovered.connect(self._on_pixel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stack, 1)
        layout.addWidget(self.pixel_strip)
        self._place()

    # ------------------------------------------------------------------ state
    @property
    def overlay(self) -> bool:
        return self._overlay

    @property
    def show_grid(self) -> bool:
        return self._show_grid

    @property
    def transparency(self) -> int:
        return self._transparency

    def grid_visible(self) -> bool:
        return self.sheet.isVisibleTo(self)

    def set_overlay(self, overlay: bool) -> None:
        """Change Split: grid over the image (True) or image above the grid (False)."""
        overlay = bool(overlay)
        if overlay == self._overlay:
            return
        if not self._overlay:
            self._split_sizes = self._split.sizes()
        self._overlay = overlay
        self._place()

    def toggle_split(self) -> None:
        self.set_overlay(not self._overlay)

    def set_show_grid(self, show: bool) -> None:
        """Show Grid: hides the grid in overlay view (Show Pixel Values mode)."""
        self._show_grid = bool(show)
        self._update_visibility()

    def set_grid_suppressed(self, suppressed: bool) -> None:
        """Temporarily hides the overlaid grid so the image can be used (interactive graphics)."""
        self._grid_suppressed = bool(suppressed)
        self._update_visibility()

    def set_selection_mode(self, on: bool) -> None:
        """Cell selection mode: "the display temporarily switches to a Spreadsheet view where the
        image is not visible underneath" (ISVS help)."""
        self._selecting = bool(on)
        self._apply_alpha()
        self._update_visibility()

    def set_transparency(self, level: int) -> None:
        self._transparency = max(0, min(len(CELL_ALPHA_LEVELS) - 1, int(level)))
        self._apply_alpha()
        self.viewChanged.emit()

    def increase_transparency(self) -> None:
        self.set_transparency(self._transparency + 1)

    def decrease_transparency(self) -> None:
        self.set_transparency(self._transparency - 1)

    def can_increase_transparency(self) -> bool:
        return self._overlay and self._transparency < len(CELL_ALPHA_LEVELS) - 1

    def can_decrease_transparency(self) -> bool:
        return self._overlay and self._transparency > 0

    def set_message(self, text: str) -> None:
        """A message shown in the strip under the image instead of pixel values (e.g. editing hints)."""
        self._message = text
        self._refresh_strip()

    # ------------------------------------------------------------------ layout
    def _place(self) -> None:
        for w in (self.image, self.sheet):
            self._overlay_layout.removeWidget(w)
        if self._overlay:
            self._overlay_layout.addWidget(self.image, 0, 0)
            self._overlay_layout.addWidget(self.sheet, 0, 0)
            self.sheet.raise_()
            self._stack.setCurrentWidget(self._overlay_page)
        else:
            self._split.insertWidget(0, self.image)
            self._split.insertWidget(1, self.sheet)
            self._split.setStretchFactor(0, 3)
            self._split.setStretchFactor(1, 2)
            self._split.setSizes(self._split_sizes)
            self._stack.setCurrentWidget(self._split)
        self._apply_alpha()
        self._update_visibility()

    def _apply_alpha(self) -> None:
        opaque = not self._overlay or self._selecting
        self.sheet.set_cell_alpha(255 if opaque else CELL_ALPHA_LEVELS[self._transparency])

    def _update_visibility(self) -> None:
        visible = not self._overlay or self._selecting or (self._show_grid and not self._grid_suppressed)
        self.sheet.setVisible(visible)
        self.image.setVisible(not (self._overlay and self._selecting))
        self._refresh_strip()
        self.viewChanged.emit()

    def _on_pixel(self, text: str) -> None:
        self._pixel_text = text
        self._refresh_strip()

    def _refresh_strip(self) -> None:
        image_usable = not self._overlay or not self.sheet.isVisibleTo(self)
        self.pixel_strip.setText(self._message or (self._pixel_text if image_usable else ""))

    # ------------------------------------------------------------------ persistence
    def save_state(self) -> dict:
        sizes = self._split.sizes() if not self._overlay else self._split_sizes
        return {"overlay": self._overlay, "show_grid": self._show_grid, "transparency": self._transparency,
                "split": sizes}

    def restore_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return
        sizes = state.get("split")
        if isinstance(sizes, list) and len(sizes) == 2:
            self._split_sizes = [int(v) for v in sizes]
        self._transparency = int(state.get("transparency", self._transparency))
        self._show_grid = bool(state.get("show_grid", True))
        self._overlay = not bool(state.get("overlay", True))  # force a re-place
        self.set_overlay(bool(state.get("overlay", True)))
