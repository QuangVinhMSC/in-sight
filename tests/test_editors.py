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
    editing_function,
    max_curve,
    round_graphic,
)
from insight_studio import graphics

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
    # ISVS: the curve is twice the pointer's angle seen from the centre; the centre and the chord
    # direction stay (Angle + Curve/2 constant, angles shown 0…360)
    shape._bend(QPointF(centre.x() + 100, centre.y() + 100 * 0.267949))   # 15° below the chord: +30
    assert close(ed.g["curve"], 30) and close(ed.g["angle"], 345)
    assert seen and close(seen[-1]["curve"], 30)
    c = shape.pt(115, 60)
    assert close(c.x(), centre.x()) and close(c.y(), centre.y())
    shape._bend(QPointF(centre.x() + 100, centre.y() - 50))  # upwards: negative curve, same chord
    assert ed.g["curve"] < 0 and close((ed.g["angle"] + ed.g["curve"] / 2) % 360, 0)
    shape._bend(QPointF(centre.x() - 500, centre.y() + 500))  # far round: stops at the 1 px inner radius
    assert close(ed.g["curve"], round(max_curve(230, 120), 3))


def test_bend_reproduces_isvs():
    """Survey 2026-11-20 (live/30…33): the same 440×320 region bent down and up in ISVS."""
    assert round(max_curve(440, 320), 1) == 156.6
    flat = {"$type": "Region", "x": 226.527, "y": 90.46, "w": 440.0, "h": 320.0, "angle": 14.352, "curve": 0.0}
    for curve, want in ((64.199, (134.191, 154.047, 342.253)), (-49.335, (305.684, 77.652, 39.02))):
        ed = GraphicEditor(dict(flat), QGraphicsPathItem())
        ed.shapes[0].set_curve(curve)
        got = (ed.g["x"], ed.g["y"], ed.g["angle"])
        assert all(abs(a - b) < 0.005 for a, b in zip(got, want)), got


def test_status_line_like_isvs(parent):
    ed, _ = editor(parent, {"$type": "Region", "x": 305.684, "y": 77.652, "w": 440.0, "h": 320.0, "angle": 39.02,
                            "curve": -49.335})
    assert ed.status_text() == "Location=306,78 Size=440×320 Rotation=39.0° Curve=-49.3°"
    ed.shapes[0]._bend(QPointF(900, 300))
    assert ed.status_text().startswith("Curve=")               # while dragging: only what changes
    ed.end_drag()
    assert ed.status_text().startswith("Location=")
    poly = {"$type": "Polygon", "points": [400.0, 140.0, 180.0, 460.0, 620.0, 460.0], "length": 3}
    ed, _ = editor(parent, poly)
    assert ed.status_text() == "Location=180,140 Size=441×321"


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
    drag = shape.press(QPointF(50, 0), Qt.KeyboardModifier.NoModifier)   # ISVS: a click on an edge only moves
    assert ed.g["points"] == [0, 0, 100, 0, 100, 100]
    menu = ed.build_menu(shape, QPointF(50, 0))                           # right-click on the edge
    assert [a.text() for a in menu.actions()] == ["Add Point", "Remove Point"]
    assert menu.actions()[0].isEnabled() and not menu.actions()[1].isEnabled()
    menu.actions()[0].trigger()                                           # Add Point at the clicked spot
    assert ed.g["points"] == [0, 0, 50, 0, 100, 0, 100, 100] and ed.g["length"] == 4
    shape._vertex(1, QPointF(50, -20))                                    # the new point can be dragged
    assert ed.g["points"][2:4] == [50, -20]
    assert len(shape.handles) == 4
    menu = ed.build_menu(shape, QPointF(100, 100))                        # on a point: both enabled
    assert all(a.isEnabled() for a in menu.actions())
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
    assert not menu.actions()[2].menu().isEnabled()                        # nor the first one's operation
    add_menu.actions()[3].trigger()                                        # Add Subregion > Region
    region2 = ed.g["subregions"][1]                                        # ISVS: the first at 80 %, subtracts
    assert region2["add"] is False
    assert [round(region2["shape"][k], 6) for k in ("x", "y", "w", "h")] == [120, 90, 160, 80]
    menu = ed.build_menu(ed.shapes[0], QPointF(10, 10))
    menu.actions()[0].menu().actions()[1].trigger()                        # Add Subregion > Circle
    assert [s["shape"]["$type"] for s in ed.g["subregions"]] == ["Region", "Region", "Circle"]
    circle = ed.shapes[2]
    assert (circle.g["x"], circle.g["y"], circle.g["radius"]) == (200, 130, 40)
    m = ed.build_menu(circle, QPointF(0, 0))
    op = m.actions()[2].menu()
    assert op.isEnabled() and [a.text() for a in op.actions()] == ["Add", "Subtract"] and op.actions()[1].isChecked()
    op.actions()[0].trigger()                                              # Add
    assert ed.g["subregions"][2]["add"] is True and not ed.shapes[2].subtract
    m = ed.build_menu(ed.shapes[0], QPointF(0, 0))
    m.actions()[1].trigger()                                               # Remove Subregion (the region)
    assert [s["shape"]["$type"] for s in ed.g["subregions"]] == ["Region", "Circle"]
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
    assert ed.masked and ed.masks == [(50, 10, 0, 100)]
    assert ed.shapes[0].scan_line.path().elementCount() == 2               # dotted scan line through the middle
    menu = ed.build_menu(ed.shapes[0], QPointF(250, 130))
    assert [a.text() for a in menu.actions()] == ["Add Mask", "Delete Mask"]
    assert not menu.actions()[1].isEnabled()                               # not on a mask
    menu.actions()[0].trigger()
    assert ed.masks[1] == (0, 10, 0, 100)                                  # ISVS: at the left end, full height
    ed.add_mask()
    assert ed.masks[2] == (10, 10, 0, 100)                                 # next to it
    ed.delete_mask(2)
    ed.move_mask(1, -100)                                                  # stays inside the region
    assert ed.masks[1] == (0, 10, 0, 100)
    ed.move_mask(0, 95)
    ed.resize_mask(0, "right", 400)
    assert ed.masks[0] == (145, 55, 0, 100)                                # up to the end of the region
    ed.move_shape(ed.shapes[0], QPointF(5, 5))                             # masks move with the region
    subs = seen[-1]["subregions"]
    assert [(s["shape"]["x"], s["shape"]["y"], s["shape"]["w"]) for s in subs[1:]] == [(250, 85, 55), (105, 85, 10)]
    m = ed.build_menu(ed.shapes[0], QPointF(260, 130))
    m.actions()[1].trigger()                                               # Delete Mask under the mouse
    assert ed.masks == [(0, 10, 0, 100)] and len(ed.g["subregions"]) == 2


def test_set_value_and_round(parent):
    ed, seen = editor(parent, REGION)
    ed.set_value(dict(REGION, x=1.23456))
    assert ed.g["x"] == 1.23456 and not seen
    assert round_graphic({"a": [1.23456, {"b": 2.0004}], "c": "x"}) == {"a": [1.235, {"b": 2.0}], "c": "x"}
    with pytest.raises(ValueError):
        GraphicEditor({"$type": "Text"}, parent)


# Device drawing (IS8902CX SVG layer, 2026-11-20) of EditRegion x=200 y=150 w=300 h=200:
# (curve, angle) -> corners (0,0) (w,0) (w,h) (0,h)
DEVICE_CURVES = {
    (30, 0): [(200, 150), (536.5, 240.2), (436.5, 413.4), (200, 350)],
    (-30, 0): [(200, 150), (436.5, 86.6), (536.5, 259.8), (200, 350)],
    (30, 20): [(200, 150), (485.4, 349.8), (332.1, 478.4), (131.6, 337.9)],
    (90, 0): [(200, 150), (491, 441), (291, 441), (200, 350)],
    (-90, 0): [(200, 150), (291, 59), (491, 59), (200, 350)],
    (120, 0): [(200, 150), (410.7, 514.9), (237.4, 414.9), (200, 350)],
}


@pytest.mark.parametrize("key", sorted(DEVICE_CURVES))
def test_curved_region_like_device(key):
    curve, angle = key
    g = {"$type": "Region", "x": 200.0, "y": 150.0, "w": 300.0, "h": 200.0, "angle": float(angle), "curve": float(curve)}
    corners = [graphics.region_point(g, s, t) for s, t in ((0, 0), (300, 0), (300, 200), (0, 200))]
    for p, (x, y) in zip(corners, DEVICE_CURVES[key]):
        assert abs(p.x() - x) < 0.1 and abs(p.y() - y) < 0.1, (key, p, (x, y))
    path = graphics.shape_path(g)
    for x, y in DEVICE_CURVES[key]:
        assert any(abs(path.elementAt(i).x - x) < 0.1 and abs(path.elementAt(i).y - y) < 0.1
                   for i in range(path.elementCount()))
    for s, t in ((10, 20), (150, 100), (290, 190)):                       # region_local inverts it
        q = graphics.region_local(g, graphics.region_point(g, s, t))
        assert abs(q.x() - s) < 1e-6 and abs(q.y() - t) < 1e-6


def test_curved_region_handles_and_crop(parent):
    g = {"$type": "Region", "x": 200.0, "y": 150.0, "w": 300.0, "h": 200.0, "angle": 0.0, "curve": 30.0}
    ed, _ = editor(parent, g)
    shape = ed.shapes[0]
    assert [(round(c.pos().x(), 1), round(c.pos().y(), 1)) for c in shape.corners] == DEVICE_CURVES[(30, 0)]
    centre = QPointF(200, 150 + 100 + 300 / 0.5235988)                    # centre of curvature
    shape._corner(1, 1, shape.pt(150, 150))                               # crop to half the span, 3/4 height
    assert close(ed.g["curve"], 15) and close(ed.g["h"], 150)
    c = graphics.region_transform(ed.g).map(QPointF(0, ed.g["h"] / 2 + ed.g["w"] / 0.2617994))
    assert abs(c.x() - centre.x()) < 1e-3 and abs(c.y() - centre.y()) < 1e-3  # same circle
    w = ed.g["w"]
    shape._corner(0, 0, shape.pt(20, 0))                                  # moving the left edge turns the origin
    assert close(ed.g["angle"], 15 * 20 / w) and close(ed.g["curve"], 15 * (w - 20) / w)


def test_masks_keep_y_offset_and_height(parent):
    masked = {"$type": "CompositeRegion", "subregions": [
        {"$type": "SubRegion", "add": True, "shape": dict(REGION)},
        {"$type": "SubRegion", "add": False, "shape": {"$type": "Region", "x": 150.0, "y": 110.0, "w": 30.0,
                                                       "h": 20.0, "angle": 0.0, "curve": 0.0}},
        {"$type": "SubRegion", "add": False, "shape": {"$type": "Region", "x": 250.0, "y": 80.0, "w": 10.0,
                                                       "h": 100.0, "angle": 0.0, "curve": 0.0}}]}
    ed, seen = editor(parent, masked, function="EditMaskedRegion")
    assert ed.masks == [(50, 30, 30, 20), (150, 10, 0, 100)]
    ed.move_mask(0, 10)
    assert [(s["shape"]["x"], s["shape"]["y"], s["shape"]["h"]) for s in seen[-1]["subregions"][1:]] == \
        [(160, 110, 20), (250, 80, 100)]
    ed.shapes[0]._side("bottom", QPointF(200, 140))                       # ROI height 100 -> 60
    assert ed.masks[0][2:] == (30, 20) and ed.masks[1][2:] == (0, 60)    # a full-height mask follows


def test_device_editing_objects():
    region = {"$type": "EditingRegion", "bend": True, "move": False, "resize": True, "rotate": False}
    assert edit_flags(region) == {"bend": True, "move": False, "resize": True, "rotate": False}
    comp = {"$type": "EditingCompositeRegion", "addRegions": True, "editRegions": False, "move": True,
            "removeRegions": True, "rotate": True}
    assert edit_flags(comp) == {"addRegion": True, "editRegion": False, "move": True, "removeRegion": True,
                                "rotate": True}
    poly = {"$type": "EditingPolygon", "addPoints": False, "move": True, "movePoints": True,
            "removePoints": True, "rotate": True, "scale": True}
    assert edit_flags(poly)["addPoints"] is False and edit_flags(poly)["scale"] is True
    assert editing_function({"$type": "EditingMaskedRegion"}) == "EditMaskedRegion"
    assert editing_function({"$type": "EditingPolyline"}) == "EditPolylinePath"
    assert editing_function({"$type": "EditingCircle"}) == "EditCircle"
    assert editing_function(None) is None


def test_polygon_point_flags(parent):
    poly = {"$type": "Polygon", "points": [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0], "length": 4}
    ed, seen = editor(parent, poly, flags=edit_flags({"addPoints": False, "removePoints": False}))
    shape = ed.shapes[0]
    shape.press(QPointF(50, 0), Qt.KeyboardModifier.NoModifier)            # no point added on an edge
    both = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier
    shape._press_vertex(0, _Press(both))                                   # nor removed
    shape._vertex(0, QPointF(-10, -10))                                   # but moved (movePoints)
    assert len(ed.g["points"]) == 8 and ed.g["points"][:2] == [-10, -10]
