"""A fake In-Sight device for tests and UI development.

It speaks the same transport as a real device (CogSocket over a WebSocket at ``/ws`` plus
plain HTTP on the same port) and implements the subset of the HMI API that Insight Studio
uses. It does NOT run vision tools: expressions are stored, and only literals, simple
arithmetic, a few HMI controls (EditInt, EditFloat, EditString, CheckBox, EditRegion,
EditCircle) and AcquireImage() produce results. Job files it produces are a private test
format, not real .jobx files.

Run standalone:  python -m insight_studio.devtools.fake_insight --port 8080
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from typing import Any, Optional

from PySide6.QtCore import QBuffer, QIODevice, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket
from PySide6.QtWebSockets import QWebSocket, QWebSocketServer

from .. import cells

ROOT = "cam0/hmi"
SESSION = "cam0/hmi/hs/~f00d0001"
IMG_W, IMG_H = 640, 480
FAKE_JOB_MAGIC = "insight-studio-fake-job"


class FakeInSight(QObject):
    def __init__(self, port: int = 0, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.tcp = QTcpServer(self)
        self.wss = QWebSocketServer("FakeInSight", QWebSocketServer.SslMode.NonSecureMode, self)
        self.wss.newConnection.connect(self._on_ws_connection)
        self.tcp.newConnection.connect(self._on_tcp_connection)
        if not self.tcp.listen(QHostAddress.SpecialAddress.LocalHost, port):
            raise RuntimeError(f"Cannot listen on port {port}: {self.tcp.errorString()}")
        self.port = self.tcp.serverPort()
        self.clients: list[QWebSocket] = []
        self.received: list[dict] = []  # every request received (for tests)
        self.listeners: set[str] = set()
        self.expressions: dict[str, str] = {}
        self.values: dict[str, Any] = {}  # values set via setCellValue
        self.button_presses: list[str] = []  # Button cells pressed via setCellValue
        self.names: dict[str, str] = {}
        self.conditions: dict[str, str] = {}  # cell states ("0" disabled, a reference = conditional)
        self.files: dict[str, bytes] = {}
        self.state = {"online": False, "softOnline": False, "nativeOnline": True,
                      "discreteOnline": True, "ffpOnline": True, "liveMode": False}
        self.editor_attached = False
        self.job_name = "untitled.jobx"
        self.image_counter = 1
        self.result_id = 0
        self.ready_pending = False
        self.logged_in = False
        self.loaded_images: dict[int, bytes] = {}
        self.reset_job()

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def reset_job(self) -> None:
        self.expressions = {"A0": "AcquireImage()"}
        self.values = {}
        self.names = {"A0": "Image"}
        self.conditions = {}

    # ------------------------------------------------------------------ transport
    def _on_tcp_connection(self) -> None:
        while self.tcp.hasPendingConnections():
            sock = self.tcp.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._on_tcp_ready(s))

    def _on_tcp_ready(self, sock: QTcpSocket) -> None:
        if sock.property("handled"):
            return
        head = bytes(sock.peek(65536).data())
        end = head.find(b"\r\n\r\n")
        if end < 0:
            return
        headers_text = head[:end].decode("latin-1")
        if re.search(r"^upgrade:\s*websocket", headers_text, re.I | re.M):
            sock.setProperty("handled", True)
            sock.readyRead.disconnect()
            self.wss.handleConnection(sock)
            return
        lines = headers_text.split("\r\n")
        method, path, _ = (lines[0].split(" ") + ["", "", ""])[:3]
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        length = int(headers.get("content-length", "0") or 0)
        if len(head) < end + 4 + length:
            if sock.bytesAvailable() < end + 4 + length:
                return  # wait for the body
        raw = bytes(sock.read(end + 4 + length).data())
        body = raw[end + 4:]
        sock.setProperty("handled", True)
        status, ctype, payload = self._http(method, path, headers, body)
        reason = {200: "OK", 404: "Not Found", 400: "Bad Request"}.get(status, "OK")
        response = (f"HTTP/1.1 {status} {reason}\r\nContent-Type: {ctype}\r\n"
                    f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n").encode()
        sock.write(response + payload)
        sock.flush()
        sock.disconnectFromHost()

    def _http(self, method: str, path: str, headers: dict, body: bytes) -> tuple[int, str, bytes]:
        path = path.split("?")[0]
        self.received.append({"$type": "http", "method": method, "path": path})
        m = re.match(r"^/cam0/img/(\d+)$", path)
        if method == "GET" and m:
            return 200, "image/png", self._render_image(int(m.group(1)))
        if method == "POST" and path.endswith("/loadJobData") and self.editor_attached:
            return 404, "text/plain", b"not found"  # like the IS8902CX while ISVS is attached
        if method == "POST" and path.endswith("/loadJobData"):
            try:
                content = json.loads(body.decode("utf-8"))
                data = base64.b64decode(content["content"])
                self._load_job_bytes(data, content.get("name") or "uploaded.jobx")
            except Exception as e:  # noqa: BLE001
                return 400, "text/plain", str(e).encode()
            return 200, "application/json", b"0"
        if method == "POST" and path.endswith("/loadImage"):
            self.image_counter += 1
            self.loaded_images[self.image_counter] = body
            self._new_result()
            return 200, "application/json", b"0"
        return 404, "text/plain", b"not found"

    def _on_ws_connection(self) -> None:
        while self.wss.hasPendingConnections():
            ws = self.wss.nextPendingConnection()
            self.clients.append(ws)
            ws.textMessageReceived.connect(lambda text, w=ws: self._on_message(w, text))
            ws.disconnected.connect(lambda w=ws: self.clients.remove(w) if w in self.clients else None)

    def _send(self, ws: QWebSocket, message: dict) -> None:
        ws.sendTextMessage(json.dumps(message))

    def _emit(self, path: str, body: Any = None) -> None:
        # Like the device, echo the path exactly as the client listened to it.
        for listened in [p for p in self.listeners if p.lstrip("/") == path]:
            msg: dict[str, Any] = {"$type": "event", "path": listened}
            if body is not None:
                msg["body"] = body
            for ws in list(self.clients):
                self._send(ws, msg)

    # ------------------------------------------------------------------ dispatch
    def _on_message(self, ws: QWebSocket, text: str) -> None:
        msg = json.loads(text)
        self.received.append(msg)
        raw_path = str(msg.get("path", ""))
        kind, rid, path = msg.get("$type"), msg.get("id"), raw_path.lstrip("/")
        body = msg.get("body")
        try:
            if kind == "listen":
                self.listeners.add(raw_path)
                result = None
            elif kind == "unlisten":
                self.listeners.discard(raw_path)
                result = None
            elif kind == "get":
                result = self._get(path)
            elif kind == "put":
                result = self._put(path, body)
            elif kind == "post":
                args = body if isinstance(body, list) else ([] if body is None else [body])
                result = self._post(path, args)
            else:
                raise KeyError(kind)
        except KeyError:
            if rid:
                self._send(ws, {"$type": "resp", "id": rid, "error": -2147477839,
                                "body": "Member not found"})
            return
        except PermissionError as e:
            if rid:
                self._send(ws, {"$type": "resp", "id": rid, "error": -1610311888, "body": str(e)})
            return
        except SyntaxError as e:  # setCellExpression refused by the parser
            if rid:
                self._send(ws, {"$type": "resp", "id": rid, "error": -1610357770, "body": str(e)})
            return
        if rid:
            resp: dict[str, Any] = {"$type": "resp", "id": rid}
            if result is not None:
                resp["body"] = result
            self._send(ws, resp)

    def _get(self, path: str) -> Any:
        if path == "system/paths/hmi":
            return ROOT
        if path == f"{ROOT}/info":
            return {
                "$type": "CameraInfo", "model": "FAKE-IS2800", "name": "fake-insight",
                "firmwareVersion": "26.1.0 (fake)", "hmiProtocolVersion": "3.0",
                "ipAddress": "127.0.0.1", "serial": "0", "macID": "00-00-00-00-00-00",
                "capabilities": ["xyCoordinates", "getCellExpressions", "customView", "resultsQueue"],
                "acq": {"$type": "CameraAcqInfo", "isColor": False,
                        "nativeWidth": IMG_W, "nativeHeight": IMG_H},
            }
        if path == f"{ROOT}/job":
            return {"name": self.job_name, "easyView": None, "pages": None,
                    "customViewSettingsList": [], "jobImageOrientation": None}
        if path == f"{ROOT}/job/name":
            return self.job_name
        if path == f"{ROOT}/settings":
            return {}
        if path == f"{ROOT}/editorAttached":
            return self.editor_attached
        if path == f"{ROOT}/state":
            return dict(self.state)
        if path == f"{SESSION}/result":
            return self._result()
        raise KeyError(path)

    def _put(self, path: str, value: Any) -> Any:
        if path == f"{SESSION}/softOnline":
            self.state["softOnline"] = bool(value)
            self.state["online"] = bool(value)
            if value:
                self.state["liveMode"] = False
            self._emit(f"{ROOT}/stateChanged", [self.state["online"], self.state["softOnline"],
                                                 True, True, True])
            return None
        if path == f"{SESSION}/liveMode":
            self.state["liveMode"] = bool(value)
            self._emit(f"{ROOT}/liveModeChanged", bool(value))
            return None
        raise KeyError(path)

    def _require_login(self) -> None:
        if not self.logged_in:
            raise PermissionError("Access denied")

    def _post(self, path: str, args: list) -> Any:
        if path == f"{ROOT}/openSession":
            return SESSION
        if path == f"{ROOT}/job/getSheetFormat":
            widths = [0] * cells.NUM_COLS
            widths[0] = 110
            return {"$type": "SheetFormat", "columnWidths": widths, "rowHeights": [],
                    "cellFormats": [{"location": "A0", "bold": True}]}
        if not path.startswith(SESSION + "/"):
            raise KeyError(path)
        member = path[len(SESSION) + 1:]
        if member == "login":
            user, password = (args + ["", ""])[:2]
            if user != "admin" or password not in ("", None):
                raise PermissionError("Login failed")
            self.logged_in = True
            return "full"
        if member in ("keepAlive", "dispose", "endEdit"):
            return 0 if member == "endEdit" else None
        self._require_login()
        if member == "ready":
            self.ready_pending = True
            QTimer.singleShot(5, self._deliver_result)
            return 0
        if member == "getLatestResult":
            return self._result()
        if member == "manualTrigger":
            self.image_counter += 1
            self._new_result()
            return None
        if member == "getCellExpressions":
            rng = args[0] if args else cells.FULL_RANGE
            wanted = set(cells.iter_range(rng))
            return [{loc: {"expr": e} for loc, e in self.expressions.items() if loc in wanted}]
        if member == "getCellExpression":
            loc = self._resolve(args[0])
            return self.expressions.get(loc, "")
        if member == "setCellExpression":
            loc, expr = self._resolve(args[0]), str(args[1])
            # like the device: a rewrite keeps the name, cell state and value; clearing drops them
            if expr.strip() == "":
                self.expressions.pop(loc, None)
                self.names.pop(loc, None)
                self.conditions.pop(loc, None)
                self.values.pop(loc, None)
            elif not _arity_ok(expr):
                # like the IS8902CX: refused, but the text stays in the cell as a string
                self.expressions[loc] = "'#" + expr.strip()
                self._new_result()
                raise SyntaxError("Error occurred")
            else:
                self.expressions[loc] = expr
            self._new_result()
            return None
        if member == "setCellValue":
            loc = self._resolve(args[0])
            if cells.function_name(self.expressions.get(loc, "")) == "Button":
                self.button_presses.append(loc)
                self._new_result()
                return None
            self.values[loc] = args[1]
            self._new_result()
            return None
        if member == "getAllCellNames":
            return dict(self.names)
        if member == "setCellName":
            loc, name = self._resolve(args[0]), str(args[1])
            if loc not in self.expressions:
                raise PermissionError("The cell must contain a value")
            if not name:
                self.names.pop(loc, None)
                return None
            base, n = name, 0
            while any(v == name and k != loc for k, v in self.names.items()):
                n += 1
                name = f"{base}_{n}"
            self.names[loc] = name
            return None
        if member == "getCellCondition":
            return self.conditions.get(self._resolve(args[0]), "")
        if member == "setCellCondition":
            loc, cond = self._resolve(args[0]), str(args[1]).strip()
            if loc in self.expressions and cond not in ("", "1"):
                self.conditions[loc] = cond
            else:
                self.conditions.pop(loc, None)
            self._new_result()
            return None
        if member == "queryCellResults":
            rng = args[0][0] if args and isinstance(args[0], list) else cells.FULL_RANGE
            wanted = set(cells.iter_range(rng))
            return [c for c in self._cells() if c["location"] in wanted]
        if member == "beginEdit":
            # Like 26.x firmware: an Editing<Type> object carrying the graphic.
            loc = self._resolve(args[0]) if args else ""
            cell = next((c for c in self._cells() if c["location"] == loc), {})
            data = cell.get("data")
            if not isinstance(data, dict):
                return self._result()["acqImageView"]
            return _editing_object(self.expressions.get(loc, ""), data, cell.get("caption", ""))
        if member == "createNewJob":
            self.reset_job()
            self.job_name = "untitled.jobx"
            self._emit(f"{ROOT}/jobChanged")
            self._new_result()
            return None
        if member == "saveJob":
            self.files[str(args[0])] = self._job_bytes()
            self.job_name = str(args[0])
            return 0
        if member == "loadJob":
            name = str(args[0])
            if name not in self.files:
                raise PermissionError(f"File not found: {name}")
            self._load_job_bytes(self.files[name], name)
            return 0
        if member == "saveJobData":
            return {"$type": "Byte[]", "base64": base64.b64encode(self._job_bytes()).decode()}
        if member == "listFiles":
            return [{"$type": "FileListItem", "attributes": 1, "name": n, "size": len(b)}
                    for n, b in sorted(self.files.items())]
        raise KeyError(path)

    def _resolve(self, name_or_loc: str) -> str:
        text = str(name_or_loc)
        for loc, name in self.names.items():
            if name == text:
                return loc
        if cells.parse_address(text):
            return text.replace("$", "").upper()
        raise PermissionError(f"Unknown cell {text}")

    # ------------------------------------------------------------------ jobs
    def _job_bytes(self) -> bytes:
        return json.dumps({"format": FAKE_JOB_MAGIC, "cells": self.expressions,
                           "names": self.names, "values": self.values,
                           "conditions": self.conditions}).encode()

    def _load_job_bytes(self, data: bytes, name: str) -> None:
        doc = json.loads(data.decode("utf-8"))
        if doc.get("format") != FAKE_JOB_MAGIC:
            raise ValueError("Not a fake job file")
        self._emit(f"{ROOT}/jobLoadingChanged", True)
        self.expressions = dict(doc.get("cells") or {})
        self.names = dict(doc.get("names") or {})
        self.values = dict(doc.get("values") or {})
        self.conditions = dict(doc.get("conditions") or {})
        self.job_name = name
        self._emit(f"{ROOT}/jobLoadingChanged", False)
        self._emit(f"{ROOT}/jobChanged")
        self._new_result()

    # ------------------------------------------------------------------ results
    def _new_result(self) -> None:
        self.result_id += 1
        self._deliver_result()

    def _deliver_result(self) -> None:
        if not self.ready_pending:
            return
        path = f"{SESSION}/resultChanged"
        if any(p.lstrip("/") == path for p in self.listeners):
            self.ready_pending = False
            self._emit(path, self._result())

    def _result(self) -> dict:
        cell_results = self._cells()
        graphics = []
        for c in cell_results:
            data = c.get("data")
            if isinstance(data, dict) and data.get("$type") in ("Region", "Circle"):
                g = dict(data)
                g["source"] = c["location"]
                graphics.append(g)
        graphics.append({"$type": "Text", "color": -16744448, "source": "A0",
                         "text": f"Image {self.image_counter}", "x": 10, "y": 10})
        return {
            "$type": "HmiResult",
            "id": self.result_id,
            "jobStatus": 1,
            "cells": cell_results,
            "acqImageView": {
                "$type": "ViewRecord",
                "layers": [
                    {"$type": "ImageLayer", "url": f"/cam0/img/{self.image_counter}",
                     "width": IMG_W, "height": IMG_H,
                     "image": {"$type": "Image", "width": IMG_W, "height": IMG_H,
                               "url": f"/cam0/img/{self.image_counter}"}},
                    {"$type": "GraphicsLayer", "graphics": graphics},
                ],
                "viewport": {"$type": "Viewport", "width": IMG_W, "height": IMG_H},
            },
        }

    def _cells(self) -> list[dict]:
        values: dict[str, Any] = {}
        out = []
        for loc in sorted(self.expressions, key=lambda a: (cells.parse_address(a) or (0, 0))):
            cond = self.conditions.get(loc, "")
            ref = cells.parse_address(cond) if cond and cond != "0" else None
            if cond == "0" or (ref and not values.get(cells.address(*ref))):
                c = {"$type": "HmiFloatResult", "data": values.get(loc, 0.0), "disabled": True}
            else:
                c = self._eval(loc, self.expressions[loc], values)
            c["location"] = loc
            c["name"] = self.names.get(loc, loc)
            out.append(c)
        return out

    def _eval(self, loc: str, expr: str, values: dict) -> dict:
        e = expr.strip()
        stored = self.values.get(loc)
        if e.startswith("'"):
            values[loc] = e[1:]
            return {"$type": "HmiStringResult", "data": e[1:]}
        fn = cells.function_name(e)
        args = _split_args(e[e.find("(") + 1:e.rfind(")")]) if fn else []
        if fn == "AcquireImage":
            return {"$type": "HmiStringResult", "data": "❒Image"}
        if fn in ("EditInt", "EditFloat"):
            lo, hi = (float(args[0]) if args else 0), (float(args[1]) if len(args) > 1 else 255)
            v = float(stored) if stored is not None else lo
            v = min(max(v, lo), hi)
            values[loc] = v
            if fn == "EditInt":
                return {"$type": "HmiEditIntResult", "data": int(v), "min": int(lo), "max": int(hi),
                        "editable": True}
            return {"$type": "HmiEditFloatResult", "data": v, "min": lo, "max": hi, "editable": True}
        if fn == "EditString":
            v = "" if stored is None else str(stored)
            values[loc] = v
            return {"$type": "HmiEditStringResult", "data": v, "maxLength": 64, "editable": True}
        if fn == "CheckBox":
            caption = args[0].strip('"') if args else ""
            v = int(stored if stored is not None else (args[1] if len(args) > 1 else 0))
            values[loc] = v
            return {"$type": "HmiCheckBoxResult", "data": v, "caption": caption, "editable": True}
        if fn == "Button":
            return {"$type": "HmiButtonResult", "data": 0, "caption": args[0].strip('"') if args else "",
                    "editable": True}
        if fn == "ListBox":
            options = [a.strip('"') for a in args]
            v = int(stored) if stored is not None else 0
            values[loc] = v
            return {"$type": "HmiListBoxResult", "data": v, "options": options, "editable": True}
        if fn in _EDIT_GRAPHICS:
            data = dict(stored) if isinstance(stored, dict) else json.loads(json.dumps(_EDIT_GRAPHICS[fn]))
            data.setdefault("color", -16711936)
            # the caption is the Name argument (second to last); results carry no function name
            caption = args[-2].strip('"') if len(args) >= 2 else fn
            return {"$type": "HmiButtonResult", "data": data, "caption": caption, "editable": True}
        # arithmetic over numbers, cell references and cell names
        def ref(m: re.Match) -> str:
            a = m.group(0).replace("$", "")
            v = values.get(a)
            return repr(float(v)) if isinstance(v, (int, float)) else "None"
        for name_loc, name in sorted(self.names.items(), key=lambda kv: -len(kv[1])):
            e = re.sub(rf"(?<![A-Za-z0-9_.]){re.escape(name)}(?![A-Za-z0-9_(])", name_loc, e)
        expr_py = re.sub(r"\$?[A-Z]\$?\d{1,3}", ref, e)
        if re.fullmatch(r"[0-9eE.+\-*/() ]+", expr_py):
            try:
                v = float(eval(expr_py, {"__builtins__": {}}, {}))  # noqa: S307 - digits only
                values[loc] = v
                return {"$type": "HmiFloatResult", "data": v}
            except Exception:  # noqa: BLE001
                pass
        if fn:
            return {"$type": "HmiStringResult", "data": f"❒{fn}"}
        return {"$type": "HmiErrorCellResult", "error": True}

    def _render_image(self, n: int) -> bytes:
        if n in self.loaded_images:
            img = QImage.fromData(self.loaded_images[n])
        else:
            img = QImage(IMG_W, IMG_H, QImage.Format.Format_RGB32)
            p = QPainter(img)
            g = QLinearGradient(QPointF(0, 0), QPointF(IMG_W, IMG_H))
            g.setColorAt(0, QColor(40, 40, 40))
            g.setColorAt(1, QColor(160, 160, 160))
            p.fillRect(QRectF(0, 0, IMG_W, IMG_H), g)
            p.setPen(QColor(230, 230, 230))
            p.setFont(QFont("Sans", 28))
            p.drawText(QRectF(0, 0, IMG_W, IMG_H), Qt.AlignmentFlag.AlignCenter, f"FAKE IMAGE {n}")
            p.drawEllipse(QPointF(320 + (n % 5) * 10, 240), 60, 60)
            p.end()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data().data())


_REGION = {"$type": "Region", "x": 100.0, "y": 80.0, "w": 240.0, "h": 160.0, "angle": 0.0, "curve": 0.0}
# Default graphics of the Edit* controls (HMI API appendix A: an EditMaskedRegion reports a
# CompositeRegion whose first subregion is the region and the others the masks).
_EDIT_GRAPHICS = {
    "EditRegion": _REGION,
    "EditCircle": {"$type": "Circle", "x": 320.0, "y": 240.0, "radius": 80.0},
    "EditAnnulus": {"$type": "Annulus", "x": 320.0, "y": 240.0, "innerRadius": 40.0, "outerRadius": 80.0},
    "EditPolygon": {"$type": "Polygon", "points": [300.0, 150.0, 400.0, 300.0, 200.0, 300.0], "length": 3},
    "EditCompositeRegion": {"$type": "CompositeRegion", "subregions": [
        {"$type": "SubRegion", "add": True, "shape": _REGION}]},
    "EditMaskedRegion": {"$type": "CompositeRegion", "subregions": [  # the device's default: ROI + one mask
        {"$type": "SubRegion", "add": True, "shape": dict(_REGION, y=135.0, h=50.0)},
        {"$type": "SubRegion", "add": False, "shape": dict(_REGION, x=110.0, y=135.0, w=10.0, h=50.0)}]},
    "EditPolylinePath": {"$type": "CompositeRegion", "subregions": [
        {"$type": "SubRegion", "add": True, "shape": dict(_REGION, h=50.0)},
        {"$type": "SubRegion", "add": True, "shape": dict(_REGION, x=340.0, h=50.0, angle=30.0)}]},
}

# Argument counts the IS8902CX accepts (2026-11-20); EditMaskedRegion needs the fixture's Theta although
# the help's syntax line leaves it out.
_ARITY = {"EditRegion": 10, "EditCircle": 8, "EditAnnulus": 8, "EditPolygon": 12, "EditCompositeRegion": 11,
          "EditMaskedRegion": 13, "EditPolylinePath": 12}

# beginEdit's Editing object per function: its $type and the flag names, in argument order after the
# fixture (Image, X, Y, Theta, flags…, Name, Show).
_EDITING = {
    "EditRegion": ("EditingRegion", ("move", "resize", "rotate", "bend")),
    "EditCircle": ("EditingCircle", ("move", "resize")),
    "EditAnnulus": ("EditingAnnulus", ("move", "resize")),
    "EditPolygon": ("EditingPolygon", ("addPoints", "removePoints", "movePoints", "move", "scale", "rotate")),
    "EditPolylinePath": ("EditingPolyline", ("addPoints", "removePoints", "movePoints", "move", "scale", "rotate")),
    "EditCompositeRegion": ("EditingCompositeRegion", ("addRegions", "removeRegions", "editRegions", "move", "rotate")),
    "EditMaskedRegion": ("EditingMaskedRegion", ("addRegion", "removeRegion", "editRegion", "move", "resize",
                                                 "rotate", "bend")),
}


def _arity_ok(expr: str) -> bool:
    fn = cells.function_name(expr.strip())
    if fn not in _ARITY:
        return True
    e = expr.strip()
    return len(_split_args(e[e.find("(") + 1:e.rfind(")")])) == _ARITY[fn]


def _editing_object(expr: str, data: dict, caption: str) -> dict:
    fn = cells.function_name(expr.strip()) or ""
    type_name, flags = _EDITING.get(fn, (f"Editing{data['$type']}", ()))
    e = expr.strip()
    args = _split_args(e[e.find("(") + 1:e.rfind(")")]) if fn else []
    out = {"$type": type_name, "url": "/cam0/app/editing/1", "data": data, "title": caption,
           "bounds": {"$type": "Rectangle", "x": 0.0, "y": 0.0, "w": float(IMG_W), "h": float(IMG_H)},
           "fixture": {"$type": "Fixture", "x": 0.0, "y": 0.0, "angle": 0.0}}
    for name, arg in zip(flags, args[4:]):
        out[name] = arg.strip() not in ("0", "")
    return out


def _split_args(text: str) -> list[str]:
    out, depth, cur, in_str = [], 0, [], False
    for ch in text:
        if ch == '"':
            in_str = not in_str
        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append("".join(cur).strip())
                cur = []
                continue
        cur.append(ch)
    if cur or out:
        out.append("".join(cur).strip())
    return [a for a in out if a != ""] if out != [""] else []


def main() -> int:
    from PySide6.QtWidgets import QApplication

    parser = argparse.ArgumentParser(description="Fake In-Sight device (for development only)")
    parser.add_argument("--port", type=int, default=8080)
    ns = parser.parse_args()
    app = QApplication(sys.argv)  # QImage text rendering needs a GUI application
    fake = FakeInSight(ns.port)
    print(f"Fake In-Sight listening on {fake.host}  (user 'admin', empty password)")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
