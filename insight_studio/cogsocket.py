"""CogSocket client on top of QWebSocket.

CogSocket is Cognex's request/response protocol carried as JSON text frames over a WebSocket
(see "In-Sight HMI Developers Guide", Appendix A). Every message is an object with a ``$type``
of ``get``, ``put``, ``post``, ``listen``, ``unlisten``, ``event`` or ``resp``.
"""

from __future__ import annotations

import json
import logging
import platform
import socket
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from .qtasync import Future

log = logging.getLogger(__name__)

_NO_BODY = object()

# Sent back when the peer uses binary encoding, which CogSocket clients do not support.
_BINARY_NOT_SUPPORTED = bytes([0, 0, 0xE0, 0x80])


class CogSocketError(Exception):
    """An error response from the device (``resp`` with a non-zero ``error``)."""

    def __init__(self, message: str, code: int = -1, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.path = path

    def __str__(self) -> str:
        base = super().__str__()
        where = f" [{self.path}]" if self.path else ""
        return f"{base} (error {self.code}){where}"


class CogSocketClosed(CogSocketError):
    def __init__(self, message: str = "Connection closed") -> None:
        super().__init__(message, -1)


EventHandler = Callable[..., None]


class CogSocket(QObject):
    """A CogSocket client endpoint.

    Signals:
        opened: the WebSocket connected.
        closed: the WebSocket disconnected (expected or not).
        traffic(direction, text): every frame sent ("send") or received ("recv"), for logging.
    """

    opened = Signal()
    closed = Signal()
    traffic = Signal(str, str)

    def __init__(self, parent: Optional[QObject] = None, request_timeout_ms: int = 30000) -> None:
        super().__init__(parent)
        self._ws = QWebSocket()
        self._ws.connected.connect(self._on_connected)
        self._ws.disconnected.connect(self._on_disconnected)
        self._ws.textMessageReceived.connect(self._on_text)
        self._ws.binaryMessageReceived.connect(self._on_binary)
        self._ws.errorOccurred.connect(self._on_error)
        self._timeout_ms = request_timeout_ms
        self._next_id = 0
        self._pending: dict[int, tuple[Future, str, QTimer]] = {}
        self._listeners: dict[str, list[EventHandler]] = {}
        self._open_future: Optional[Future] = None
        self._is_open = False

    # ------------------------------------------------------------------ connection
    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self, url: str) -> Future:
        """Opens the WebSocket (e.g. ``ws://192.168.0.10/ws``)."""
        fut = Future()
        self._open_future = fut
        self._ws.open(QUrl(url))
        return fut

    def close(self) -> None:
        if self._ws.state() != QAbstractSocket.SocketState.UnconnectedState:
            self._ws.close()
        self._fail_all(CogSocketClosed())

    def _on_connected(self) -> None:
        self._is_open = True
        if self._open_future is not None:
            self._open_future.set_result(None)
            self._open_future = None
        self.opened.emit()

    def _on_disconnected(self) -> None:
        was_open = self._is_open
        self._is_open = False
        if self._open_future is not None:
            self._open_future.set_exception(
                CogSocketClosed(f"Unable to connect: {self._ws.errorString()}")
            )
            self._open_future = None
        self._fail_all(CogSocketClosed())
        if was_open:
            self.closed.emit()

    def _on_error(self, _error) -> None:
        if self._open_future is not None:
            self._open_future.set_exception(
                CogSocketClosed(f"Unable to connect: {self._ws.errorString()}")
            )
            self._open_future = None

    def _fail_all(self, exc: Exception) -> None:
        pending, self._pending = self._pending, {}
        for fut, _path, timer in pending.values():
            timer.stop()
            fut.set_exception(exc)

    # ------------------------------------------------------------------ requests
    def get(self, path: str) -> Future:
        return self._request("get", path)

    def put(self, path: str, value: Any) -> Future:
        return self._request("put", path, value)

    def post(self, path: str, args: Optional[list] = None) -> Future:
        """Calls a method. ``args`` is the positional argument list (sent as a JSON array)."""
        if args is None or len(args) == 0:
            return self._request("post", path)
        return self._request("post", path, list(args))

    @staticmethod
    def _key(path: str) -> str:
        # Devices echo the listened path; match with or without a leading slash.
        return path.lstrip("/")

    def add_listener(self, path: str, handler: EventHandler) -> Future:
        handlers = self._listeners.get(self._key(path))
        if handlers is not None:
            handlers.append(handler)
            fut = Future()
            fut.set_result(None)
            return fut
        self._listeners[self._key(path)] = [handler]
        return self._request("listen", path)

    def remove_listener(self, path: str, handler: Optional[EventHandler] = None) -> Future:
        handlers = self._listeners.get(self._key(path))
        if handlers and handler is not None and handler in handlers:
            handlers.remove(handler)
        if handlers is not None and (handler is None or not handlers):
            del self._listeners[self._key(path)]
            return self._request("unlisten", path)
        fut = Future()
        fut.set_result(None)
        return fut

    def _request(self, kind: str, path: str, body: Any = _NO_BODY) -> Future:
        fut = Future()
        if not self._is_open:
            fut.set_exception(CogSocketClosed("Not connected"))
            return fut
        self._next_id += 1
        if self._next_id > 0x7FFFFFFF:
            self._next_id = 1
        rid = self._next_id
        message: dict[str, Any] = {"$type": kind, "id": rid, "path": path}
        if body is not _NO_BODY:
            message["body"] = body

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._on_timeout(rid))
        timer.start(self._timeout_ms)
        self._pending[rid] = (fut, path, timer)
        self._send(message)
        return fut

    def _on_timeout(self, rid: int) -> None:
        entry = self._pending.pop(rid, None)
        if entry:
            fut, path, _timer = entry
            fut.set_exception(CogSocketError("Request timed out", -1, path))

    def _send(self, message: dict) -> None:
        text = json.dumps(message, separators=(",", ":"))
        self.traffic.emit("send", text)
        self._ws.sendTextMessage(text)

    # ------------------------------------------------------------------ incoming
    def _on_binary(self, _data) -> None:
        self._ws.sendBinaryMessage(_BINARY_NOT_SUPPORTED)

    def _on_text(self, text: str) -> None:
        self.traffic.emit("recv", text)
        try:
            message = json.loads(text)
        except ValueError:
            log.warning("Ignoring malformed CogSocket frame: %.200s", text)
            return
        kind = message.get("$type")
        if kind == "resp":
            self._handle_response(message)
        elif kind == "event":
            self._handle_event(message)
        elif kind in ("get", "put", "post", "listen", "unlisten"):
            self._handle_incoming_request(message)
        else:
            log.warning("Unknown CogSocket message type: %r", kind)

    def _handle_response(self, message: dict) -> None:
        rid = message.get("id")
        entry = self._pending.pop(rid, None)
        if entry is None:
            log.debug("Response %s with no pending request", rid)
            return
        fut, path, timer = entry
        timer.stop()
        error = message.get("error")
        body = message.get("body")
        if error:
            if isinstance(body, dict):
                text = body.get("message") or json.dumps(body)
            elif body is None:
                text = f"Error {error}"
            else:
                text = str(body)
            fut.set_exception(CogSocketError(text, int(error), path))
        else:
            fut.set_result(body)

    def _handle_event(self, message: dict) -> None:
        path = message.get("path", "")
        body = message.get("body", _NO_BODY)
        if body is _NO_BODY or body is None:
            args: list = []
        elif isinstance(body, list):
            args = body
        else:
            args = [body]
        for handler in list(self._listeners.get(self._key(path), [])):
            try:
                handler(*args)
            except Exception:
                log.exception("Event handler for %s failed", path)
        rid = message.get("id")
        if rid:
            self._send({"$type": "resp", "id": rid})

    def _handle_incoming_request(self, message: dict) -> None:
        """The device may call the client (e.g. ``@/hello``). Answer what we can."""
        rid = message.get("id")
        path = message.get("path", "")
        if message.get("$type") == "post" and path.rstrip("/") == "@/hello":
            body = {"name": socket.gethostname(), "model": platform.system()}
            if rid:
                self._send({"$type": "resp", "id": rid, "body": body})
            return
        if rid:
            self._send(
                {"$type": "resp", "id": rid, "error": -2147477839, "body": "Member not found"}
            )
