from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.result import DispatchOutcome
from lzt_eventus_sdk.errors import MissingDependencyError
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.sources.base import BaseSource
from lzt_eventus_sdk.storage.cursor import CursorStore

try:
    import websockets
    import websockets.exceptions
except ImportError as exc:  # pragma: no cover - exercised only without the [ws] extra
    raise MissingDependencyError(extra="ws", package="websockets") from exc

_JITTER_FRACTION = 0.25

_logger = logging.getLogger(__name__)


class WSProtocolError(Exception):
    """A server event frame was malformed or missing a required field."""


@dataclass(frozen=True, slots=True)
class WSConfig:
    path: str = "/streams/ws"
    min_backoff: float = 1.0
    max_backoff: float = 30.0


def _decode_ws_frame(raw: str | bytes) -> ClientEvent:
    try:
        payload = json.loads(raw)
        return ClientEvent(
            seq=int(payload["seq"]),
            event_type=str(payload["event_type"]),
            data=dict(payload["data"]),
            transport=TransportKind.WS,
            received_at=datetime.now(UTC),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise WSProtocolError(str(exc)) from exc


class WSSource(BaseSource):
    """`GET /streams/ws` (behind the `[ws]` extra — build step 8, the only
    transport needing a new dependency). First frame sent is the auth frame
    `{"subscription_id", "token", "last_seq"}`; subsequent frames are
    `{"seq", "event_type", "data"}`.
    """

    def __init__(
        self,
        account: AccountContext,
        *,
        cursor_store: CursorStore,
        base_url: str,
        config: WSConfig | None = None,
    ) -> None:
        super().__init__(account)
        self._cursor_store = cursor_store
        self._base_url = base_url.rstrip("/")
        self._config = config or WSConfig()
        self._closed = False

    async def _connect_once(self) -> AsyncIterator[ClientEvent]:
        last_seq = await self._cursor_store.get(self.account.subscription_id, TransportKind.WS)
        url = f"{self._base_url}{self._config.path}"
        async with websockets.connect(url) as socket:
            await socket.send(
                json.dumps(
                    {
                        "subscription_id": self.account.subscription_id,
                        "token": self.account.stream_token or "",
                        "last_seq": last_seq,
                    }
                )
            )
            async for raw in socket:
                yield _decode_ws_frame(raw)

    async def stream(self) -> AsyncGenerator[ClientEvent, None]:
        backoff = self._config.min_backoff
        while not self._closed:
            try:
                async for event in self._connect_once():
                    backoff = self._config.min_backoff
                    yield event
            except (websockets.exceptions.WebSocketException, OSError, WSProtocolError):
                pass
            if self._closed:
                return
            await asyncio.sleep(backoff + random.uniform(0, backoff * _JITTER_FRACTION))
            backoff = min(backoff * 2, self._config.max_backoff)

    async def run(self, dispatcher: Dispatcher) -> None:
        async for event in self.stream():
            result = await dispatcher.feed(event, self.account)
            if result.outcome is DispatchOutcome.ERRORED:
                _logger.warning(
                    "WS event errored, cursor not advanced (will redeliver on reconnect)",
                    extra={"subscription_id": self.account.subscription_id, "seq": event.seq},
                )
                continue
            await self._cursor_store.advance(
                self.account.subscription_id, TransportKind.WS, event.seq
            )

    async def aclose(self) -> None:
        self._closed = True
