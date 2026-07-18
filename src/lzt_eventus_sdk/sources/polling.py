from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import StrEnum

from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.result import DispatchOutcome
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.models import PendingBatch
from lzt_eventus_sdk.sources.base import BaseSource


class ConfirmMode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class PollingConfig:
    interval: float = 5.0
    empty_backoff_max: float = 60.0
    limit: int = 100
    confirm: ConfirmMode = ConfirmMode.AUTO
    event_type: list[str] | None = None


class PollingSource(BaseSource):
    """Wraps the existing `poll_pending`/`confirm_read` REST calls — zero new
    I/O surface (build step 5). `stream()` yields raw events without
    confirming (the escape-hatch consumer owns ack); `run()` groups by batch
    so auto-confirm can use the batch's `next_seq` after all items dispatch
    cleanly.
    """

    def __init__(self, account: AccountContext, *, config: PollingConfig | None = None) -> None:
        super().__init__(account)
        self._config = config or PollingConfig()

    async def _fetch_batch(self) -> PendingBatch:
        return await self.account.client.poll_pending(
            self.account.subscription_id,
            event_type=self._config.event_type,
            limit=self._config.limit,
        )

    def _next_sleep(self, current: float, batch: PendingBatch) -> float:
        if batch.items:
            return self._config.interval
        return min(current * 2, self._config.empty_backoff_max)

    async def stream(self) -> AsyncGenerator[ClientEvent, None]:
        sleep_for = self._config.interval
        while True:
            batch = await self._fetch_batch()
            for item in batch.items:
                yield ClientEvent.from_pending(item, transport=TransportKind.POLLING)
            sleep_for = self._next_sleep(sleep_for, batch)
            if batch.drained:
                await asyncio.sleep(sleep_for)

    async def run(self, dispatcher: Dispatcher) -> None:
        sleep_for = self._config.interval
        while True:
            batch = await self._fetch_batch()
            all_ok = True
            for item in batch.items:
                event = ClientEvent.from_pending(item, transport=TransportKind.POLLING)
                result = await dispatcher.feed(event, self.account)
                if result.outcome is DispatchOutcome.ERRORED:
                    all_ok = False

            if self._config.confirm is ConfirmMode.AUTO and batch.items and all_ok:
                await self.account.client.confirm_read(
                    self.account.subscription_id, up_to_seq=batch.next_seq
                )

            sleep_for = self._next_sleep(sleep_for, batch)
            if batch.drained:
                await asyncio.sleep(sleep_for)
