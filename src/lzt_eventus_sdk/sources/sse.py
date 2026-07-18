from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.result import DispatchOutcome
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.sources.base import BaseSource
from lzt_eventus_sdk.storage.cursor import CursorStore

_STREAM_TOKEN_HEADER = "X-Stream-Token"
_LAST_EVENT_ID_HEADER = "Last-Event-ID"
_JITTER_FRACTION = 0.25

_logger = logging.getLogger(__name__)


class SSEProtocolError(Exception):
    """A `data:` frame's JSON body was malformed or missing a required field."""


@dataclass(frozen=True, slots=True)
class SSEConfig:
    path: str = "/streams/sse"
    min_backoff: float = 1.0
    max_backoff: float = 30.0


def _decode_sse_frame(raw: str) -> ClientEvent:
    """The wire body is the uniform `{seq, event_type, data}` envelope (same
    shape as `PendingEvent`); the SSE `id:`/`event:` lines are protocol-level
    framing only, not the source of truth for those fields.
    """
    try:
        payload = json.loads(raw)
        return ClientEvent(
            seq=int(payload["seq"]),
            event_type=str(payload["event_type"]),
            data=dict(payload["data"]),
            transport=TransportKind.SSE,
            received_at=datetime.now(UTC),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SSEProtocolError(str(exc)) from exc


async def _parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[ClientEvent]:
    data_lines: list[str] = []
    async for raw_line in lines:
        line = raw_line.rstrip("\n")
        if line == "":
            if data_lines:
                yield _decode_sse_frame("\n".join(data_lines))
            data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())


class SSESource(BaseSource):
    """`GET /streams/sse`, httpx streaming — no new dependency (build step 7).
    Resumes via `Last-Event-ID: <CursorStore.get(...)>`; auth via
    `X-Stream-Token` (the SSE-header alias of `Authorization: Bearer`).
    """

    def __init__(
        self,
        account: AccountContext,
        *,
        cursor_store: CursorStore,
        base_url: str,
        config: SSEConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(account)
        self._cursor_store = cursor_store
        self._config = config or SSEConfig()
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport)
        self._closed = False

    async def _stream_once(self) -> AsyncIterator[ClientEvent]:
        last_seq = await self._cursor_store.get(self.account.subscription_id, TransportKind.SSE)
        headers = {_STREAM_TOKEN_HEADER: self.account.stream_token or ""}
        if last_seq:
            headers[_LAST_EVENT_ID_HEADER] = str(last_seq)
        params = {"subscription_id": self.account.subscription_id}
        async with self._http.stream(
            "GET", self._config.path, headers=headers, params=params
        ) as response:
            response.raise_for_status()
            async for event in _parse_sse(response.aiter_lines()):
                yield event

    async def stream(self) -> AsyncGenerator[ClientEvent, None]:
        backoff = self._config.min_backoff
        while not self._closed:
            try:
                async for event in self._stream_once():
                    backoff = self._config.min_backoff
                    yield event
            except (httpx.HTTPError, SSEProtocolError):
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
                    "SSE event errored, cursor not advanced (will redeliver on reconnect)",
                    extra={"subscription_id": self.account.subscription_id, "seq": event.seq},
                )
                continue
            await self._cursor_store.advance(
                self.account.subscription_id, TransportKind.SSE, event.seq
            )

    async def aclose(self) -> None:
        self._closed = True
        await self._http.aclose()
