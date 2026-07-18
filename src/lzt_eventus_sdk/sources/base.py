from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.events.event import ClientEvent

_DEFAULT_MIN_BACKOFF = 1.0
_DEFAULT_MAX_BACKOFF = 60.0
_JITTER_FRACTION = 0.25

_logger = logging.getLogger(__name__)


class BaseSource(ABC):
    """Common contract for the four transports. `stream()` is the escape hatch
    (00 § Toggle+fallback) — raw frames, bypassing the `Dispatcher` entirely,
    for a consumer that wants to drive events manually while reusing the
    reconnect/cursor machinery. `run()` is the default driver.
    """

    def __init__(self, account: AccountContext) -> None:
        self.account = account

    @abstractmethod
    def stream(self) -> AsyncIterator[ClientEvent]: ...

    async def run(self, dispatcher: Dispatcher) -> None:
        async for event in self.stream():
            await dispatcher.feed(event, self.account)

    async def aclose(self) -> None:
        return None


class SourceSupervisor:
    """Runs N sources concurrently against one `Dispatcher` (multi-account,
    D3). A source task that exits/raises is restarted with exp backoff +
    jitter (capped) — one crashing source never takes down its siblings.
    """

    def __init__(
        self,
        dispatcher: Dispatcher,
        *,
        min_backoff: float = _DEFAULT_MIN_BACKOFF,
        max_backoff: float = _DEFAULT_MAX_BACKOFF,
    ) -> None:
        self._dispatcher = dispatcher
        self._sources: list[BaseSource] = []
        self._min_backoff = min_backoff
        self._max_backoff = max_backoff
        self._stopping = False

    def add(self, source: BaseSource) -> SourceSupervisor:
        self._sources.append(source)
        return self

    async def run(self) -> None:
        self._stopping = False
        async with asyncio.TaskGroup() as tg:
            for source in self._sources:
                tg.create_task(self._supervise(source))

    async def _supervise(self, source: BaseSource) -> None:
        backoff = self._min_backoff
        while not self._stopping:
            try:
                await source.run(self._dispatcher)
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.exception(
                    "source crashed, restarting", extra={"source": type(source).__name__}
                )
                await asyncio.sleep(backoff + random.uniform(0, backoff * _JITTER_FRACTION))
                backoff = min(backoff * 2, self._max_backoff)
            else:
                if self._stopping:
                    return
                backoff = self._min_backoff

    async def stop(self) -> None:
        self._stopping = True
        for source in self._sources:
            await source.aclose()
