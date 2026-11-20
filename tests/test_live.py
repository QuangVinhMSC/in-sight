"""Opt-in tests against a real In-Sight device.

    INSIGHT_HOST=192.168.1.102 python -m pytest tests/test_live.py -v

Optional: INSIGHT_USER (default admin), INSIGHT_PASSWORD (default empty).
Safety: the device must be offline. Only scratch cells in rows 590-599 are written and they are
cleared afterwards. Nothing is saved on the device, no job is loaded, the device is not put
online. One manual trigger is issued.
"""

import os

import pytest

from insight_studio import cells
from insight_studio.device import InSightDevice
from insight_studio.qtasync import spawn, wait

HOST = os.environ.get("INSIGHT_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="set INSIGHT_HOST to run tests against a device")

SCRATCH = {
    "Y590": "'Insight Studio live test",
    "Z590": "EditInt(0,100)",
    "Z591": "Z590*2",
    "Z592": 'EditRegion($A$0,0,0,0,1,1,1,1,"Region",2)',
    "Z593": 'CheckBox("Enable")',
    "Z594": 'ListBox("one","two","three")',
    "Z595": "1/0",
}
# written by single tests (and cleared with the rest)
EXTRA = ["X590", "X591", "X592", "X593"]


def run(coro, timeout=20000):
    return wait(spawn(coro, report_errors=False), timeout)


@pytest.fixture(scope="module")
def device(qapp):
    dev = InSightDevice()
    wait(dev.connect_to(HOST, os.environ.get("INSIGHT_USER", "admin"),
                        os.environ.get("INSIGHT_PASSWORD", "")), 20000)
    if dev.online:
        run(dev.disconnect_from())
        pytest.skip("device is online; put it offline to run live tests")
    if dev.read_only:
        run(dev.disconnect_from())
        pytest.skip("an editor (ISVS) is attached")
    occupied = [loc for loc in list(SCRATCH) + EXTRA if loc in dev.expressions]
    if occupied:
        run(dev.disconnect_from())
        pytest.skip(f"scratch cells already in use: {occupied}")
    yield dev
    run(dev.set_cell_expressions({loc: "" for loc in list(SCRATCH) + EXTRA}))
    assert not [loc for loc in list(SCRATCH) + EXTRA if loc in dev.expressions], "scratch cells not cleared"
    run(dev.disconnect_from())


def test_info(device):
    assert device.info.api_version
    assert device.session
    assert device.access_level


def test_expressions_and_results(device):
    run(device.set_cell_expressions(SCRATCH))
    for loc, expr in SCRATCH.items():
        assert device.expressions[loc]["expr"] == expr
    res = device.cell_results()
    assert cells.display_text(res["Y590"]) == "Insight Studio live test"
    assert cells.result_kind(res["Z590"]) == "EditIntResult"
    assert cells.display_text(res["Z595"]) == "#ERR"
    assert cells.editable_graphic(res["Z592"])["$type"] == "Region"


def test_values(device):
    run(device.set_cell_value("Z590", 21))
    assert device.cell_results()["Z591"]["data"] == 42
    run(device.set_cell_value("Z593", 1))
    run(device.set_cell_value("Z594", 2))
    res = device.cell_results()
    assert res["Z593"]["data"] == 1 and cells.display_text(res["Z594"]) == "three"


def test_cell_name(device):
    run(device.set_cell_name("Z590", "LiveTestValue"))
    assert device.cell_names.get("Z590") == "LiveTestValue"


def test_edit_region(device):
    editing = run(device.begin_edit("Z592"))
    graphic = dict(editing.get("data") or cells.editable_graphic(device.cell_results()["Z592"]))
    graphic.update({"x": 50.0, "y": 60.0, "w": 120.0, "h": 80.0, "angle": 10.0})
    run(device.set_cell_value("Z592", graphic))
    run(device.end_edit())
    after = cells.editable_graphic(device.cell_results()["Z592"])
    assert (after["x"], after["y"], after["w"], after["h"], after["angle"]) == (50, 60, 120, 80, 10)


def test_trigger_and_image(device):
    run(device.trigger())
    result = run(device.latest_result())
    url = result["acqImageView"]["layers"][0]["url"]
    data = wait(device.http_get(url), 20000)
    from PySide6.QtGui import QImage

    img = QImage.fromData(data)
    assert not img.isNull() and img.width() > 0


def test_download_job_is_a_jobx(device):
    import io
    import tarfile

    name = device.job.get("name") or "job.jobx"
    data = run(device.download_job(name))
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        assert "Job.json" in tf.getnames()


def test_editing_objects(device):
    """beginEdit's Editing object: $type and flag names per Edit* function (plan §8.10)."""
    from insight_studio.editors import edit_flags, editing_function

    exprs = {"X590": 'EditMaskedRegion($A$0,0,0,0,1,1,1,1,1,1,1,"M",2)',
             "X591": 'EditCompositeRegion($A$0,0,0,0,1,1,0,1,1,"C",2)',
             "X592": 'EditPolygon($A$0,0,0,0,0,1,1,1,1,1,"P",2)'}
    run(device.set_cell_expressions(exprs))
    res = device.cell_results()
    assert res["X590"]["caption"] == "M" and "name" not in res["X590"]
    found = {}
    for loc in exprs:
        editing = run(device.begin_edit(loc))
        run(device.end_edit())
        found[loc] = (editing_function(editing), edit_flags(editing))
    assert found["X590"][0] == "EditMaskedRegion" and found["X590"][1]["addRegion"] is True
    assert found["X591"][0] == "EditCompositeRegion" and found["X591"][1]["editRegion"] is False
    assert found["X592"][0] == "EditPolygon" and found["X592"][1]["addPoints"] is False


def test_refused_expression_stays_as_text(device):
    with pytest.raises(Exception):
        run(device.set_cell_expression("X593", 'EditMaskedRegion($A$0,0,0,0,1,1,1,1,1,1,"M",2)'))
    run(device.refresh_expressions())
    assert device.expressions["X593"]["expr"].startswith("'#EditMaskedRegion(")


def test_curved_region_drawn_like_graphics(device):
    """The device's SVG layer draws a curved region where graphics.region_point puts it."""
    import re

    from insight_studio import graphics

    run(device.set_cell_expressions({"X590": 'EditRegion($A$0,0,0,0,1,1,1,1,"R",2)'}))
    g = dict(cells.editable_graphic(device.cell_results()["X590"]), x=200.0, y=150.0, w=300.0, h=200.0,
             angle=20.0, curve=30.0)
    run(device.set_cell_value("X590", g))
    run(device.trigger())
    layers = run(device.latest_result())["acqImageView"]["layers"]
    svg = bytes(wait(device.http_get(next(L["url"] for L in layers if L["$type"] == "SVGLayer")), 20000)).decode()
    body = re.search(r'<g data-c="X590".*?</g>', svg, re.S).group(0)
    outline = re.search(r'<path d="([^"]*)" stroke="#FF0000"', body).group(1)
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", outline)]
    corner = graphics.region_point(g, 300, 200)  # the path starts at the far corner of the bottom arc
    assert abs(nums[0] - corner.x()) < 0.2 and abs(nums[1] - corner.y()) < 0.2
