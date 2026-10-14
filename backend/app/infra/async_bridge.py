"""Run coroutines from synchronous code on one long-lived background event loop.

The planner and the routes are synchronous (FastAPI runs them in its worker threadpool). The RailRadar client is
async (httpx.AsyncClient, concurrent fan-out with gather). Every call into it goes through this single loop, so
the AsyncClient's connection pool is always used from the same loop and no thread pool is created per request."""

import asyncio
import concurrent.futures
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from app.providers.errors import ProviderError, ProviderErrorKind

T = TypeVar("T")


class LoopThread:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or self._loop.is_closed():
                loop = asyncio.new_event_loop()
                ready = threading.Event()

                def runner() -> None:
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()

                threading.Thread(target=runner, name="railsaathi-async-bridge", daemon=True).start()
                ready.wait()
                self._loop = loop
            return self._loop

    def run(self, coro: Coroutine[Any, Any, T], timeout: float | None = 90.0) -> T:
        """Block the calling (non-loop) thread until `coro` finishes on the bridge loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure())
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()  # stop the coroutine on the loop instead of leaving it running
            raise ProviderError(ProviderErrorKind.TIMEOUT, "The live data request took too long") from exc


_bridge = LoopThread()


def run_sync(coro: Coroutine[Any, Any, T], timeout: float | None = 90.0) -> T:
    return _bridge.run(coro, timeout)
