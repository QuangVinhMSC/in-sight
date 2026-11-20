"""High-level In-Sight device client built on the documented HMI API.

The connect sequence follows the Web SDK's reference client (CvsInSight.cs):
open ws://host/ws -> GET /system/paths/hmi -> info/job/settings/state -> openSession ->
listeners -> login -> ready. A keep-alive is posted every 10 s.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import cells
from .cogsocket import CogSocket, CogSocketError
from .qtasync import Future, completed, spawn

log = logging.getLogger(__name__)

KEEP_ALIVE_MS = 10000


class DeviceError(Exception):
    pass


@dataclass
class CameraInfo:
    raw: dict = field(default_factory=dict)

    @property
    def model(self) -> str:
        return str(self.raw.get("model", ""))

    @property
    def name(self) -> str:
        return str(self.raw.get("name", ""))

    @property
    def firmware(self) -> str:
        return str(self.raw.get("firmwareVersion", ""))

    @property
    def api_version(self) -> str:
        return str(self.raw.get("hmiProtocolVersion", ""))

    @property
    def capabilities(self) -> list[str]:
        caps = self.raw.get("capabilities")
        return [str(c) for c in caps] if isinstance(caps, list) else []

    @property
    def uses_xy(self) -> bool:
        return "xyCoordinates" in self.capabilities or bool(self.raw.get("xyCoordinates"))

    @property
    def http_root(self) -> str:
        root = self.raw.get("httpRequestRoot")
        return f"/{str(root).strip('/')}/" if root else "/"


class InSightDevice(QObject):
    """One connection (CogSocket + HmiSession) to an In-Sight vision system."""

    connectedChanged = Signal(bool)
    stateChanged = Signal(dict)
    liveModeChanged = Signal(bool)
    jobInfoChanged = Signal(dict)
    jobLoadingChanged = Signal(bool)
    jobLoadFailed = Signal(str)
    editorAttachedChanged = Signal(bool)
    sessionDisposed = Signal()
    resultChanged = Signal(dict)
    expressionsChanged = Signal(dict)  # {location: {"expr": str, "dataId": int?}}
    cellNamesChanged = Signal(dict)  # {location: name}
    sheetFormatChanged = Signal(dict)
    traffic = Signal(str, str)
    message = Signal(str)  # human readable status messages

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.sock: Optional[CogSocket] = None
        self.net = QNetworkAccessManager(self)
        self.host = ""
        self.username = ""
        self.root = "/cam0/hmi/"
        self.session = ""  # e.g. "hs/~1234/" (always ends with "/")
        self.info = CameraInfo()
        self.job: dict = {}
        self.settings: dict = {}
        self.state: dict = {}
        self.access_level = ""
        self.editor_attached = False
        self.job_loading = False
        self.connected = False
        self.result: dict = {}
        self.expressions: dict[str, dict] = {}
        self.cell_names: dict[str, str] = {}
        self.sheet_format: dict = {}
        self.conditions_supported = True  # get/setCellCondition (firmware 23.1.1+)
        self._keep_alive = QTimer(self)
        self._keep_alive.setInterval(KEEP_ALIVE_MS)
        self._keep_alive.timeout.connect(self._send_keep_alive)
        self._skip_keep_alive = False
        self._ready_pending = False
        self.auto_ready = True
        self._job_refresh = QTimer(self)
        self._job_refresh.setSingleShot(True)
        self._job_refresh.setInterval(150)
        self._job_refresh.timeout.connect(self._refresh_job)

    # ------------------------------------------------------------------ helpers
    @property
    def base_url(self) -> str:
        return f"http://{self.host}"

    @property
    def online(self) -> bool:
        return bool(self.state.get("online"))

    @property
    def soft_online(self) -> bool:
        return bool(self.state.get("softOnline"))

    @property
    def live_mode(self) -> bool:
        return bool(self.state.get("liveMode"))

    @property
    def read_only(self) -> bool:
        """The HMI should not write while ISVS/ISE/VisionView is attached."""
        return self.editor_attached

    def has_capability(self, name: str) -> bool:
        return name in self.info.capabilities

    def _s(self, member: str) -> str:
        return self.session + member

    def _r(self, member: str) -> str:
        return self.root + member

    def _require(self) -> CogSocket:
        if not self.sock or not self.connected:
            raise DeviceError("Not connected to a device")
        return self.sock

    # ------------------------------------------------------------------ connect
    def connect_to(self, host: str, username: str, password: str) -> Future:
        return spawn(self._connect(host.strip(), username, password), report_errors=False)

    async def _connect(self, host: str, username: str, password: str) -> None:
        if self.sock is not None:
            await self.disconnect_from()
        if not host:
            raise DeviceError("No host given")
        self.host = host
        self.username = username
        self.conditions_supported = True
        sock = CogSocket(self)
        sock.traffic.connect(self.traffic)
        sock.closed.connect(self._on_socket_closed)
        self.sock = sock
        try:
            await sock.open(f"ws://{host}/ws")

            try:
                root = await sock.get("/system/paths/hmi")
            except CogSocketError:
                root = "cam0/hmi"
            self.root = "/" + str(root or "cam0/hmi").strip("/") + "/"

            self.info = CameraInfo(await sock.get(self._r("info")) or {})
            self.job = await self._safe_get(self._r("job"), {})
            self.settings = await self._safe_get(self._r("settings"), {})
            self.editor_attached = bool(await self._safe_get(self._r("editorAttached"), False))
            self.state = await self._safe_get(self._r("state"), {}) or {}
            self.job_loading = False

            session_info = {
                "$type": "HmiSessionInfo",
                "cellNames": [cells.FULL_RANGE],
                "includeCustomView": False,
            }
            try:
                sid = await sock.post(self._r("openSession"), [session_info])
            except CogSocketError as e:
                raise DeviceError(f"Unable to open an HMI session: {e}") from e
            if not sid:
                raise DeviceError("No more HMI sessions are available on the device")
            self.session = str(sid).rstrip("/") + "/"

            root_events = {
                "stateChanged": self._on_state_changed,
                "liveModeChanged": self._on_live_mode_changed,
                "jobChanged": self._on_job_changed,
                "settingsChanged": self._on_settings_changed,
                "jobLoadingChanged": self._on_job_loading_changed,
                "jobLoadFailed": self._on_job_load_failed,
                "editorAttachedChanged": self._on_editor_attached_changed,
                "sessionDisposed": self._on_session_disposed,
            }
            for name, handler in root_events.items():
                try:
                    await sock.add_listener(self._r(name), handler)
                except CogSocketError as e:  # older firmware lacks some events
                    log.info("Event %s not available: %s", name, e)
            await sock.add_listener(self._s("resultChanged"), self._on_result_changed)

            level = await sock.post(self._s("login"), [username, password, False, False])
            if isinstance(level, dict):
                level = level.get("accessLevel") or level.get("level") or "user"
            if not level:
                raise DeviceError("Login failed")
            self.access_level = str(level)

            self.connected = True
            self._keep_alive.start()
            self.connectedChanged.emit(True)
            self.message.emit(
                f"Connected to {self.info.name or host} ({self.info.model}, firmware "
                f"{self.info.firmware}, HMI API {self.info.api_version}) as {username} "
                f"[{self.access_level}]"
            )
            self.stateChanged.emit(dict(self.state))
            self.jobInfoChanged.emit(dict(self.job or {}))
            self.editorAttachedChanged.emit(self.editor_attached)

            await self.refresh_sheet()
            await self.ready()
        except BaseException:
            await self._teardown(emit=False)
            raise

    async def _safe_get(self, path: str, default: Any) -> Any:
        try:
            value = await self.sock.get(path)  # type: ignore[union-attr]
            return default if value is None else value
        except CogSocketError as e:
            log.info("GET %s failed: %s", path, e)
            return default

    async def disconnect_from(self) -> None:
        if self.sock is None:
            return
        if self.connected:
            try:
                await self.sock.post(self._s("dispose"))
            except CogSocketError:
                pass
        await self._teardown(emit=True)

    async def _teardown(self, emit: bool) -> None:
        self._keep_alive.stop()
        self._job_refresh.stop()
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.closed.disconnect(self._on_socket_closed)
            except (RuntimeError, TypeError):
                pass
            sock.close()
            sock.deleteLater()
        was_connected = self.connected
        self.connected = False
        self.session = ""
        self.result = {}
        self._ready_pending = False
        if emit and was_connected:
            self.connectedChanged.emit(False)

    def _on_socket_closed(self) -> None:
        self.message.emit("Connection to the device was closed")
        spawn(self._teardown(emit=True))

    # ------------------------------------------------------------------ results
    def ready(self) -> Future:
        """Accepts the next result (raises resultChanged when one is available)."""
        sock = self._require()
        if self._ready_pending:
            return completed(0)  # a ready is already outstanding
        self._skip_keep_alive = True
        self._ready_pending = True
        return sock.post(self._s("ready"))

    def _send_keep_alive(self) -> None:
        if not self.connected or self.sock is None:
            return
        if self._skip_keep_alive:
            self._skip_keep_alive = False
            return
        fut = self.sock.post(self._s("keepAlive"))
        fut.add_done_callback(lambda f: f.exception() and log.warning("keepAlive: %s", f.exception()))

    def _on_result_changed(self, result: Any = None, *_rest) -> None:
        self._ready_pending = False
        if isinstance(result, dict):
            self._set_result(result)
        # The device sends one result per 'ready'. With auto_ready the next one is requested
        # at once; a UI sets auto_ready = False and calls ready() after it has drawn a result.
        if self.connected and self.auto_ready:
            fut = self.ready()
            fut.add_done_callback(lambda f: None)

    def _set_result(self, result: dict) -> None:
        self.result = result
        self.resultChanged.emit(result)

    async def latest_result(self) -> dict:
        result = await self._require().post(self._s("getLatestResult"))
        if isinstance(result, dict):
            self._set_result(result)
        return result or {}

    def cell_results(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for c in self.result.get("cells") or []:
            loc = c.get("location")
            if loc:
                out[str(loc).upper()] = c
        return out

    # ------------------------------------------------------------------ sheet content
    async def refresh_sheet(self) -> None:
        """Reloads expressions, names and formats for the whole sheet."""
        await self.refresh_expressions()
        await self.refresh_cell_names()
        await self.refresh_sheet_format()

    async def refresh_expressions(self, cell_range: str = cells.FULL_RANGE) -> dict:
        sock = self._require()
        exprs: dict[str, dict] = {}
        try:
            body = await sock.post(self._s("getCellExpressions"), [cell_range, True])
            exprs = _normalise_expressions(body)
        except CogSocketError as e:
            self.message.emit(f"Cannot read cell expressions ({e}). Is the user logged in with edit rights?")
        if cell_range == cells.FULL_RANGE:
            self.expressions = exprs
        else:
            for loc in cells.iter_range(cell_range):
                self.expressions.pop(loc, None)
            self.expressions.update(exprs)
        self.expressionsChanged.emit(dict(self.expressions))
        return exprs

    async def refresh_cell_names(self) -> dict:
        try:
            body = await self._require().post(self._s("getAllCellNames"))
        except CogSocketError as e:
            log.info("getAllCellNames failed: %s", e)
            body = {}
        names = {str(k).upper(): str(v) for k, v in (body or {}).items()} if isinstance(body, dict) else {}
        self.cell_names = names
        self.cellNamesChanged.emit(dict(names))
        return names

    async def refresh_sheet_format(self) -> dict:
        try:
            fmt = await self._require().post(self._r("job/getSheetFormat"), [[cells.FULL_RANGE]])
        except CogSocketError as e:
            log.info("getSheetFormat failed: %s", e)
            fmt = {}
        self.sheet_format = fmt if isinstance(fmt, dict) else {}
        self.sheetFormatChanged.emit(dict(self.sheet_format))
        return self.sheet_format

    async def set_cell_expression(self, location: str, expression: str) -> None:
        sock = self._require()
        await sock.post(self._s("setCellExpression"), [location, expression])
        await self.refresh_expressions()
        await self.refresh_cell_names()
        await self.latest_result()

    async def set_cell_expressions(self, items: dict[str, str]) -> None:
        """Writes several cells (e.g. a paste), then refreshes once."""
        sock = self._require()
        errors = []
        for loc, expr in items.items():
            try:
                await sock.post(self._s("setCellExpression"), [loc, expr])
            except CogSocketError as e:
                errors.append(f"{loc}: {e}")
        await self.refresh_expressions()
        await self.refresh_cell_names()
        await self.latest_result()
        if errors:
            raise DeviceError("Some cells could not be written:\n" + "\n".join(errors))

    async def get_cell_expression(self, location: str) -> str:
        return str(await self._require().post(self._s("getCellExpression"), [location]) or "")

    async def set_cell_value(self, location: str, value: Any) -> None:
        await self._require().post(self._s("setCellValue"), [location, value])
        await self.latest_result()

    async def set_cell_name(self, location: str, name: str) -> None:
        await self._require().post(self._s("setCellName"), [location, name])
        await self.refresh_cell_names()

    async def query_cells(self, cell_range: str) -> list:
        body = await self._require().post(self._s("queryCellResults"), [[cell_range]])
        return body if isinstance(body, list) else []

    async def get_cell_condition(self, location: str) -> Any:
        return await self._require().post(self._s("getCellCondition"), [location])

    async def set_cell_condition(self, location: str, condition: str) -> None:
        await self._require().post(self._s("setCellCondition"), [location, condition])

    async def get_cell_conditions(self, locations) -> dict[str, str]:
        """Cell states of the given cells ("" enabled, "0" disabled, a reference = conditional).

        Returns {} on devices without get/setCellCondition (firmware before 23.1.1).
        """
        if not self.conditions_supported:
            return {}
        sock = self._require()
        out: dict[str, str] = {}
        for loc in locations:
            try:
                out[loc] = str(await sock.post(self._s("getCellCondition"), [loc]) or "")
            except CogSocketError as e:
                if not out:
                    log.info("getCellCondition not available: %s", e)
                    self.conditions_supported = False
                    return {}
                raise
        return out

    async def write_cells(self, targets: dict, current: dict) -> None:
        """Writes target :class:`~insight_studio.sheet_ops.CellState` s, then refreshes once.

        ``current`` holds the states of the same cells now (names/conditions may be None = unknown).
        Order matters on the device: names that move are released first (a name in use gets a
        ``_1`` suffix), expressions next (a name or cell state needs a non-empty cell, clearing a
        cell drops both), then cell states, names and control values.
        """
        from .sheet_ops import EMPTY

        sock = self._require()
        errors: list[str] = []

        async def call(member: str, loc: str, *args) -> bool:
            try:
                await sock.post(self._s(member), [loc, *args])
                return True
            except CogSocketError as e:
                errors.append(f"{loc}: {e}")
                return False

        released = set()
        for loc, t in targets.items():
            cur = current.get(loc, EMPTY)
            if t.expr and cur.expr and cur.name and t.name is not None and t.name != cur.name:
                if await call("setCellName", loc, ""):
                    released.add(loc)
        for loc, t in targets.items():
            if t.expr != current.get(loc, EMPTY).expr:
                await call("setCellExpression", loc, t.expr)
        for loc, t in targets.items():
            cur = current.get(loc, EMPTY)
            if not t.expr:
                continue
            fresh = not cur.expr
            if t.condition is not None and self.conditions_supported:
                now = "" if fresh else cur.condition
                if t.condition != now:
                    await call("setCellCondition", loc, t.condition)
            if t.name:
                now = "" if fresh or loc in released else (cur.name or "")
                if t.name != now:
                    await call("setCellName", loc, t.name)
            if t.value is not None:
                await call("setCellValue", loc, t.value)
        await self.refresh_expressions()
        await self.refresh_cell_names()
        await self.latest_result()
        if errors:
            raise DeviceError("Some cells could not be written:\n" + "\n".join(errors))

    # ------------------------------------------------------------------ graphic editing
    async def begin_edit(self, location: str) -> Any:
        return await self._require().post(self._s("beginEdit"), [location])

    async def end_edit(self) -> None:
        await self._require().post(self._s("endEdit"))

    # ------------------------------------------------------------------ state
    async def set_soft_online(self, value: bool) -> None:
        await self._require().put(self._s("softOnline"), bool(value))

    async def set_live_mode(self, value: bool) -> None:
        await self._require().put(self._s("liveMode"), bool(value))

    async def trigger(self) -> None:
        await self._require().post(self._s("manualTrigger"))

    # ------------------------------------------------------------------ jobs
    async def create_new_job(self) -> None:
        await self._require().post(self._s("createNewJob"))

    async def load_job(self, filename: str) -> None:
        await self._require().post(self._s("loadJob"), [filename])

    async def save_job(self, filename: str) -> None:
        await self._require().post(self._s("saveJob"), [filename])

    async def list_files(self, directory: Optional[str] = None) -> list[dict]:
        args = [directory] if directory else None
        body = await self._require().post(self._s("listFiles"), args)
        return body if isinstance(body, list) else []

    async def download_job(self, filename: str) -> bytes:
        """Returns the active job serialised as a job file (.jobx) by the device."""
        body = await self._require().post(self._s("saveJobData"), [filename])
        return _decode_bytes(body)

    async def upload_job(self, filename: str, data: bytes) -> None:
        """Loads job file bytes from the PC as the active job (HTTP POST loadJobData)."""
        payload = {
            "$type": "HmiNamedContent",
            "name": filename,
            "content": base64.b64encode(data).decode("ascii"),
        }
        await self.http_post(self._http_session_url("loadJobData"),
                             json.dumps(payload).encode("utf-8"), "application/json",
                             timeout_ms=120000)

    async def load_image(self, data: bytes, content_type: str, name: str = "") -> None:
        """Loads a BMP/JPEG image as the current image (HTTP POST loadImage)."""
        url = self._http_session_url("loadImage")
        await self.http_post(url, data, content_type, timeout_ms=60000)

    def _http_session_url(self, member: str) -> str:
        root = self.info.http_root.strip("/")
        session = self.session.strip("/")
        if root and not session.startswith(root + "/"):
            path = f"/{root}/{session}/{member}"
        else:
            path = f"/{session}/{member}"
        return self.base_url + path

    # ------------------------------------------------------------------ job settings
    async def set_easy_view(self, items: list[dict]) -> None:
        await self._require().post(self._s("setEasyView"), [items])

    async def set_custom_views(self, views: list[dict]) -> None:
        await self._require().post(self._s("setCustomViewList"), [views])

    # ------------------------------------------------------------------ HTTP
    def http_get(self, path_or_url: str, timeout_ms: int = 30000) -> Future:
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        req = QNetworkRequest(QUrl(url))
        req.setTransferTimeout(timeout_ms)
        return self._reply_future(self.net.get(req))

    def http_post(self, url: str, data: bytes, content_type: str, timeout_ms: int = 30000) -> Future:
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, content_type)
        req.setTransferTimeout(timeout_ms)
        return self._reply_future(self.net.post(req, QByteArray(data)))

    @staticmethod
    def _reply_future(reply: QNetworkReply) -> Future:
        fut = Future()

        def finished() -> None:
            data = bytes(reply.readAll().data())
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error() != QNetworkReply.NetworkError.NoError:
                fut.set_exception(DeviceError(f"HTTP {status or ''} {reply.errorString()}".strip()))
            else:
                fut.set_result(data)
            reply.deleteLater()

        reply.finished.connect(finished)
        return fut

    # ------------------------------------------------------------------ events
    def _on_state_changed(self, *args) -> None:
        keys = ["online", "softOnline", "nativeOnline", "discreteOnline", "ffpOnline"]
        if len(args) == 1 and isinstance(args[0], dict):
            self.state.update(args[0])
        else:
            for k, v in zip(keys, args):
                self.state[k] = bool(v)
        self.stateChanged.emit(dict(self.state))

    def _on_live_mode_changed(self, value: Any = False, *_rest) -> None:
        self.state["liveMode"] = bool(value)
        self.liveModeChanged.emit(bool(value))
        self.stateChanged.emit(dict(self.state))

    def _on_job_changed(self, *_args) -> None:
        # A job load raises several jobChanged events; coalesce them into one refresh.
        if self.connected:
            self._job_refresh.start()

    def _refresh_job(self) -> None:
        async def refresh() -> None:
            try:
                self.job = await self._safe_get(self._r("job"), {})
                self.jobInfoChanged.emit(dict(self.job or {}))
                await self.refresh_sheet()
            except (DeviceError, CogSocketError):
                if self.connected:
                    raise  # otherwise the connection closed meanwhile; nothing to refresh

        if self.connected:
            spawn(refresh())

    def _on_settings_changed(self, *_args) -> None:
        async def refresh() -> None:
            self.settings = await self._safe_get(self._r("settings"), {})

        if self.connected:
            spawn(refresh())

    def _on_job_loading_changed(self, value: Any = None, *_rest) -> None:
        self.job_loading = bool(value) if value is not None else not self.job_loading
        self.jobLoadingChanged.emit(self.job_loading)
        if not self.job_loading and self.connected:
            self._on_job_changed()

    def _on_job_load_failed(self, error: Any = None, *_rest) -> None:
        if isinstance(error, dict):
            text = error.get("message") or json.dumps(error)
        else:
            text = str(error or "Job load failed")
        self.jobLoadFailed.emit(text)
        self.message.emit(f"Job load failed: {text}")

    def _on_editor_attached_changed(self, value: Any = False, *_rest) -> None:
        self.editor_attached = bool(value)
        self.editorAttachedChanged.emit(self.editor_attached)

    def _on_session_disposed(self, session_id: Any = None, *_rest) -> None:
        sid = str(session_id or "").rstrip("/")
        if sid and self.session and not self.session.rstrip("/").endswith(sid.split("/")[-1]):
            return  # another client's session
        self.message.emit("The device disposed this HMI session")
        self.sessionDisposed.emit()
        spawn(self._teardown(emit=True))


def _normalise_expressions(body: Any) -> dict[str, dict]:
    """getCellExpressions returns {loc: {expr, dataId}} (possibly wrapped in a list or JSON)."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return {}
    if isinstance(body, list):
        merged: dict = {}
        for item in body:
            if isinstance(item, dict):
                merged.update(item)
        body = merged
    out: dict[str, dict] = {}
    if isinstance(body, dict):
        for loc, value in body.items():
            if str(loc).startswith("$"):
                continue
            if isinstance(value, dict):
                out[str(loc).upper()] = {k: v for k, v in value.items() if k != "$type"}
            elif value is not None:
                out[str(loc).upper()] = {"expr": str(value)}
    return out


def _decode_bytes(body: Any) -> bytes:
    """Decodes a Byte[] payload ({"$type":"Byte[]","base64":...}) or a base64 string."""
    if isinstance(body, dict):
        b64 = body.get("base64") or body.get("content") or ""
        return base64.b64decode(b64)
    if isinstance(body, str):
        return base64.b64decode(body)
    if isinstance(body, list):
        return bytes(int(x) & 0xFF for x in body)
    raise DeviceError("Unexpected job data returned by the device")
