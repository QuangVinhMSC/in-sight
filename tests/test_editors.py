"""Interactive Graphics Mode editors (no device): regions, polygons, composite and masked regions."""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsScene

from insight_studio.editors import (
    EDIT_COLOR,
    GraphicEditor,
    Handle,
    edit_flags,
    round_graphic,
)

REGION = {"$type": "Region", "x": 100.0, "y": 80.0, "w": 200.0, "h": 100.0, "angle": 0.0, "curve": 0.0}


@pytest.fixture
def parent(qapp):
    scene = QGraphicsScene()
    item = QGraphicsPathItem()
    scene.addItem(item)
    yield item
    scene.clear()


def editor(parent, g, **kw):
    ed = GraphicEditor(g, parent, **kw)
    seen = []
    ed.changed.connect(seen.append)
    return ed, seen


def close(a, b):
    return abs(a - b) < 1e-6


def test_region_handles_like_isvs(parent):
    ed, _ = editor(parent, REGION)
    shape = ed.shapes[0]
    assert shape.body.pen().color() == EDIT_COLOR
    kinds = sorted(h.kind for h in shape.handles)
    assert kinds == ["bend", "rotate", "square", "square", "square", "square"]
    # rotation handle in the middle of the bottom edge, bend handle in the middle of the right edge
    assert shape.rotator.pos() == QPointF(200, 180) and shape.bender.pos() == QPointF(300, 130)
    assert [c.pos() for c in shape.corners] == [QPointF(100, 80), QPointF(300, 80), QPointF(300, 180),
                                                QPointF(100, 180)]
    assert shape.arrow_x.label == "X" and shape.arrow_x.pos() == QPointF(200, 80)
    assert shape.arrow_y.label == "Y" and shape.arrow_y.pos() == QPointF(100, 130)


def test_region_corner_side_rotate_bend(parent):
    ed, seen = editor(parent, REGION)
    shape = ed.shapes[0]
    shape._corner(0, 0, QPointF(120, 60))                  # top-left: bottom-right stays
    assert (ed.g["x"], ed.g["y"], ed.g["w"], ed.g["h"]) == (120, 60, 180, 120)
    shape._side("right", QPointF(350, 999))                 # right side: only the width changes
    assert (ed.g["x"], ed.g["w"], ed.g["h"]) == (120, 230, 120)
    assert shape.side_at(QPointF(350, 100)) == "right" and shape.side_at(QPointF(200, 100)) is None
    centre = QPointF(120 + 115, 60 + 60)
    shape._rotate(QPointF(centre.x() - 50, centre.y()))     # bottom handle dragged to the left: +90°
    assert close(ed.g["angle"], 90)
    t = shape.transform()
    c = t.map(QPointF(115, 60))
    assert close(c.x(), centre.x()) and close(c.y(), centre.y())  # rotates about the centre
    ed.g.update(x=120.0, y=60.0, angle=0.0)
    shape.sync()
    shape._bend(QPointF(350, 60))                           # bend handle to the top-right corner
    assert ed.g["curve"] == 90
    assert seen and seen[-1]["curve"] == 90


def test_region_flags(parent):
    ed, seen = editor(parent, REGION, flags=edit_flags({"resize": False, "bend": False}))
    shape = ed.shapes[0]
    assert not any(c.isVisible() for c in shape.corners) and not shape.bender.isVisible()
    shape._corner(1, 1, QPointF(500, 500))
    shape._bend(QPointF(300, 80))
    assert (ed.g["w"], ed.g["curve"]) == (200, 0) and not seen
    assert shape.press(QPointF(200, 130), Qt.KeyboardModifier.NoModifier) is not None  # moving is allowed


def test_fixture_transform_maps_drags(parent):
    t = QTransform().translate(50, 40).rotate(90)
    ed, _ = editor(parent, REGION, transform=t)
    shape = ed.shapes[0]
    corner = shape.corners[0]
    scene_pos = corner.mapToScene(QPointF(0, 0))
    assert close(scene_pos.x(), 50 - 80) and close(scene_pos.y(), 40 + 100)  # fixture coords -> image
    # a handle reports drags in fixture coordinates
    assert isinstance(corner, Handle) and corner.parentItem().mapFromScene(scene_pos) == QPointF(100, 80)


class _Press:
    def __init__(self, mods):
        self._mods = mods

    def modifiers(self):
        return self._mods


def test_polygon_add_and_remove_points(parent):
    poly = {"$type": "Polygon", "points": [0.0, 0.0, 100.0, 0.0, 100.0, 100.0], "length": 3}
    ed, seen = editor(parent, poly)
    shape = ed.shapes[0]
    assert shape.edge_at(QPointF(50, 1)) == 0
    drag = shape.press(QPointF(50, 0), Qt.KeyboardModifier.NoModifier)   # click on an edge adds a point
    assert ed.g["points"] == [0, 0, 50, 0, 100, 0, 100, 100] and ed.g["length"] == 4
    drag(QPointF(50, -20))                                                # and drags it
    assert ed.g["points"][2:4] == [50, -20]
    assert len(shape.handles) == 4
    both = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier
    assert shape._press_vertex(1, _Press(both))                          # Shift+Alt+click removes it
    assert ed.g["points"] == [0, 0, 100, 0, 100, 100] and len(shape.handles) == 3
    shape._press_vertex(0, _Press(both))                                  # at least three points stay
    assert len(ed.g["points"]) == 6
    assert not shape._press_vertex(0, _Press(Qt.KeyboardModifier.NoModifier))


def test_composite_menu_add_remove_operation(parent):
    comp = {"$type": "CompositeRegion", "color": -16777088,
            "subregions": [{"$type": "SubRegion", "add": True, "shape": dict(REGION)}]}
    ed, seen = editor(parent, comp)
    menu = ed.build_menu(ed.shapes[0], QPointF(10, 10))
    texts = [a.text() for a in menu.actions()]
    assert texts == ["Add Subregion", "Remove Subregion", "Subregion Operation"]
    add_menu = menu.actions()[0].menu()
    assert [a.text() for a in add_menu.actions()] == ["Annulus", "Circle", "Polygon", "Region"]
    assert not menu.actions()[1].isEnabled()                               # the last one cannot be removed
    add_menu.actions()[1].trigger()                                        # Add Subregion > Circle
    assert [s["shape"]["$type"] for s in ed.g["subregions"]] == ["Region", "Circle"]
    circle = ed.shapes[1]
    assert (circle.g["x"], circle.g["y"]) == (10, 10)
    m = ed.build_menu(circle, QPointF(0, 0))
    op = m.actions()[2].menu()
    assert [a.text() for a in op.actions()] == ["Add", "Subtract"] and op.actions()[0].isChecked()
    op.actions()[1].trigger()                                              # Subtract
    assert ed.g["subregions"][1]["add"] is False and ed.shapes[1].subtract
    m = ed.build_menu(ed.shapes[0], QPointF(0, 0))
    m.actions()[1].trigger()                                               # Remove Subregion (the region)
    assert [s["shape"]["$type"] for s in ed.g["subregions"]] == ["Circle"]
    assert seen[-1]["subregions"][0]["add"] is False


def test_composite_without_edit_moves_whole(parent):
    comp = {"$type": "CompositeRegion", "subregions": [
        {"$type": "SubRegion", "add": True, "shape": dict(REGION)},
        {"$type": "SubRegion", "add": False, "shape": {"$type": "Circle", "x": 0.0, "y": 0.0, "radius": 5.0}}]}
    ed, _ = editor(parent, comp, flags={"editRegion": False})
    ed.move_shape(ed.shapes[1], QPointF(10, 0))
    assert ed.g["subregions"][0]["shape"]["x"] == 110 and ed.g["subregions"][1]["shape"]["x"] == 10
    ed.shapes[0]._corner(1, 1, QPointF(900, 900))                         # subregions are not resized
    assert ed.g["subregions"][0]["shape"]["w"] == 200


def test_masked_region_masks(parent):
    masked = {"$type": "CompositeRegion", "subregions": [
        {"$type": "SubRegion", "add": True, "shape": dict(REGION)},
        {"$type": "SubRegion", "add": False, "shape": {"$type": "Region", "x": 150.0, "y": 80.0, "w": 10.0,
                                                       "h": 100.0, "angle": 0.0, "curve": 0.0}}]}
    ed, seen = editor(parent, masked, function="EditMaskedRegion")
    assert ed.masked and ed.masks == [(50, 10)]
    assert ed.shapes[0].scan_line.path().elementCount() == 2               # dotted scan line through the middle
    menu = ed.build_menu(ed.shapes[0], QPointF(250, 130))
    assert [a.text() for a in menu.actions()] == ["Add Mask", "Delete Mask"]
    assert not menu.actions()[1].isEnabled()                               # not on a mask
    menu.actions()[0].trigger()
    assert ed.masks[1] == (145, 10)                                        # centred on the click
    ed.move_mask(0, -100)                                                  # stays inside the region
    assert ed.masks[0] == (0, 10)
    ed.resize_mask(1, "right", 400)
    assert ed.masks[1] == (145, 55)                                        # up to the end of the region
    ed.move_shape(ed.shapes[0], QPointF(5, 5))                             # masks move with the region
    subs = seen[-1]["subregions"]
    assert [(s["shape"]["x"], s["shape"]["y"], s["shape"]["w"]) for s in subs[1:]] == [(105, 85, 10), (250, 85, 55)]
    m = ed.build_menu(ed.shapes[0], QPointF(260, 130))
    m.actions()[1].trigger()                                               # Delete Mask under the mouse
    assert ed.masks == [(0, 10)] and len(ed.g["subregions"]) == 2


def test_set_value_and_round(parent):
    ed, seen = editor(parent, REGION)
    ed.set_value(dict(REGION, x=1.23456))
    assert ed.g["x"] == 1.23456 and not seen
    assert round_graphic({"a": [1.23456, {"b": 2.0004}], "c": "x"}) == {"a": [1.235, {"b": 2.0}], "c": "x"}
    with pytest.raises(ValueError):
        GraphicEditor({"$type": "Text"}, parent)
