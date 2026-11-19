"""A tiny awaitable/coroutine runner that lives on the Qt event loop.

Network replies from Qt arrive as signals on the GUI thread. Instead of nesting callbacks,
request methods return a :class:`Future` and higher-level code is written as ``async def``
coroutines that are driven by :func:`spawn`. No asyncio loop and no extra threads are needed.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable, Coroutine, Optional

from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEventLoop, QTimer

log = logging.getLogger(__name__)

_unhandled_error_hook: Optional[Callable[[BaseException], None]] = None


def set_unhandled_error_hook(hook: Optional[Callable[[BaseException], None]]) -> None:
    """Installs a function that is called with exceptions that escape spawned tasks."""
    global _unhandled_error_hook
    _unhandled_error_hook = hook


class Future:
    """A minimal single-threaded future that can be awaited from a coroutine."""

    __slots__ = ("_done", "_result", "_exc", "_callbacks")

    def __init__(self) -> None:
        self._done = False
        self._result: Any = None
        self._exc: Optional[BaseException] = None
        self._callbacks: list[Callable[["Future"], None]] = []

    def done(self) -> bool:
        return self._done

    def set_result(self, value: Any = None) -> None:
        if self._done:
            return
        self._done = True
        self._result = value
        self._fire()

    def set_exception(self, exc: BaseException) -> None:
        if self._done:
            return
        self._done = True
        self._exc = exc
        self._fire()

    def exception(self) -> Optional[BaseException]:
        return self._exc

    def result(self) -> Any:
        if not self._done:
            raise RuntimeError("Future is not done yet")
        if self._exc is not None:
            raise self._exc
        return self._result

    def add_done_callback(self, callback: Callable[["Future"], None]) -> None:
        if self._done:
            callback(self)
        else:
            self._callbacks.append(callback)

    def _fire(self) -> None:
        callbacks, self._callbacks = self._callbacks, []
        for cb in callbacks:
            try:
                cb(self)
            except Exception:  # pragma: no cover - defensive
                log.exception("Future callback failed")

    def __await__(self):
        if not self._done:
            yield self
        return self.result()


def completed(value: Any = None) -> Future:
    fut = Future()
    fut.set_result(value)
    return fut


def failed(exc: BaseException) -> Future:
    fut = Future()
    fut.set_exception(exc)
    return fut


def sleep(ms: int) -> Future:
    fut = Future()
    QTimer.singleShot(int(ms), lambda: fut.set_result(None))
    return fut


def spawn(coro: Coroutine, *, report_errors: bool = True) -> Future:
    """Runs a coroutine on the Qt event loop and returns a Future for its result.

    Exceptions that escape the coroutine are passed to the unhandled error hook when
    ``report_errors`` is true and nobody else consumes them. A Future is returned unchanged.
    """
    if isinstance(coro, Future):
        return coro
    task = Future()

    def step(value: Any = None, exc: Optional[BaseException] = None) -> None:
        try:
            if exc is not None:
                awaited = coro.throw(exc)
            else:
                awaited = coro.send(value)
        except StopIteration as stop:
            task.set_result(stop.value)
            return
        except BaseException as e:  # noqa: BLE001 - propagate into the task
            task.set_exception(e)
            if report_errors:
                _report(e)
            return

        if not isinstance(awaited, Future):
            step(None, TypeError(f"Can only await qtasync.Future objects, got {awaited!r}"))
            return

        def resume(f: Future) -> None:
            # Resume on a fresh stack frame so long chains of immediately-completed
            # futures do not recurse.
            QTimer.singleShot(0, lambda: step(f._result, f._exc))

        awaited.add_done_callback(resume)

    step()
    return task


def _report(exc: BaseException) -> None:
    if _unhandled_error_hook is not None:
        try:
            _unhandled_error_hook(exc)
            return
        except Exception:  # pragma: no cover - defensive
            pass
    log.error("Unhandled error in task:\n%s", "".join(traceback.format_exception(exc)))


def wait(fut: Future, timeout_ms: int = 10000) -> Any:
    """Blocks (while processing Qt events) until the future completes. Intended for tests/CLI."""
    if QCoreApplication.instance() is None:
        raise RuntimeError("A QCoreApplication is required")
    deadline = QDeadlineTimer(timeout_ms)
    loop = QEventLoop()
    while not fut.done():
        if deadline.hasExpired():
            raise TimeoutError("Timed out waiting for future")
        loop.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
    return fut.result()
