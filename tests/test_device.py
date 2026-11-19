"""End-to-end tests of the CogSocket client and device layer against the fake device."""

import pytest

from insight_studio.cogsocket import CogSocketError
from insight_studio.device import InSightDevice
from insight_studio.devtools.fake_insight import FAKE_JOB_MAGIC, FakeInSight
from insight_studio.qtasync import spawn, wait


@pytest.fixture
def fake(qapp):
    f = FakeInSight(0)
    yield f
    f.tcp.close()


@pytest.fixture
def device(qapp, fake):
    dev = InSightDevice()
    wait(dev.connect_to(fake.host, "admin", ""))
    yield dev
    wait(spawn(dev.disconnect_from()))


def run(coro, timeout=5000):
    return wait(spawn(coro, report_errors=False), timeout)


def test_connect_sequence(device, fake):
    assert device.connected
    assert device.root == "/cam0/hmi/"
    assert device.session == "cam0/hmi/hs/~f00d0001/"
    assert device.access_level == "full"
    assert device.info.uses_xy
    paths = [m.get("path") for m in fake.received if m.get("$type") != "http"]
    # order matters: root query, info, ..., openSession, listeners, login, ...
    assert paths[0] == "/system/paths/hmi"
    assert paths.index("/cam0/hmi/openSession") < paths.index("cam0/hmi/hs/~f00d0001/login")
    login = next(m for m in fake.received if str(m.get("path", "")).endswith("/login"))
    assert login["body"] == ["admin", "", False, False]
    assert device.expressions["A0"]["expr"] == "AcquireImage()"
    assert device.cell_names == {"A0": "Image"}


def test_bad_login_raises(qapp, fake):
    dev = InSightDevice()
    with pytest.raises(CogSocketError):
        wait(dev.connect_to(fake.host, "admin", "wrong"))
    assert not dev.connected


def test_results_arrive_after_ready(device, qapp):
    got = []
    device.resultChanged.connect(got.append)
    run(device.trigger())
    wait_until(lambda: got, qapp)
    assert got[-1]["$type"] == "HmiResult"
    assert device.cell_results()["A0"]["data"] == "❒Image"


def test_set_expression_value_and_name(device, fake):
    run(device.set_cell_expression("B2", "EditInt(0,100)"))
    assert fake.expressions["B2"] == "EditInt(0,100)"
    assert device.expressions["B2"]["expr"] == "EditInt(0,100)"
    run(device.set_cell_value("B2", 42))
    assert device.cell_results()["B2"]["data"] == 42
    run(device.set_cell_name("B2", "Threshold"))
    assert device.cell_names["B2"] == "Threshold"
    run(device.set_cell_expression("C2", "Threshold*2"))
    assert device.cell_results()["C2"]["data"] == 84.0


def test_clear_cell(device, fake):
    run(device.set_cell_expression("D4", "5"))
    run(device.set_cell_expression("D4", ""))
    assert "D4" not in fake.expressions
    assert "D4" not in device.expressions


def test_error_response_is_raised(device):
    with pytest.raises(CogSocketError) as e:
        run(device.set_cell_name("Q9", "Empty"))
    assert "must contain a value" in str(e.value)


def test_job_download_upload_roundtrip(device, fake):
    run(device.set_cell_expression("A5", "'hello"))
    data = run(device.download_job("test.jobx"))
    assert FAKE_JOB_MAGIC.encode() in data
    run(device.create_new_job())
    assert "A5" not in fake.expressions
    run(device.upload_job("test.jobx", data))
    assert fake.expressions["A5"] == "'hello"
    assert fake.job_name == "test.jobx"


def test_save_and_load_on_device(device, fake):
    run(device.set_cell_expression("A7", "1+2"))
    run(device.save_job("onboard.jobx"))
    files = run(device.list_files())
    assert [f["name"] for f in files] == ["onboard.jobx"]
    run(device.create_new_job())
    run(device.load_job("onboard.jobx"))
    assert fake.expressions["A7"] == "1+2"


def test_image_fetch_over_http(device, qapp):
    run(device.trigger())
    url = device.result["acqImageView"]["layers"][0]["url"]
    data = run(device.http_get(url))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_online_offline_events(device, qapp):
    states = []
    device.stateChanged.connect(states.append)
    run(device.set_soft_online(True))
    wait_until(lambda: states and states[-1].get("online"), qapp)
    assert device.online
    run(device.set_soft_online(False))
    wait_until(lambda: not device.online, qapp)


def test_job_load_then_disconnect_has_no_stray_errors(qapp, fake):
    """Seen on an IS8902CX: jobChanged refreshes outliving the connection raised errors."""
    from insight_studio import qtasync

    errors = []
    qtasync.set_unhandled_error_hook(errors.append)
    try:
        dev = InSightDevice()
        wait(dev.connect_to(fake.host, "admin", ""))
        data = run(dev.download_job("x.jobx"))
        run(dev.upload_job("x.jobx", data))  # emits jobLoading/jobChanged events
        run(dev.disconnect_from())
        from PySide6.QtCore import QDeadlineTimer

        deadline = QDeadlineTimer(500)
        while not deadline.hasExpired():
            qapp.processEvents()
        assert errors == []
    finally:
        qtasync.set_unhandled_error_hook(None)


def wait_until(cond, qapp, timeout_ms=3000):
    from PySide6.QtCore import QDeadlineTimer

    deadline = QDeadlineTimer(timeout_ms)
    while not cond():
        if deadline.hasExpired():
            raise TimeoutError("condition not met")
        qapp.processEvents()
