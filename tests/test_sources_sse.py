"""Unit tests for `SSESource`.

`tests/fixtures/sse_stream.txt` is HAND-CONSTRUCTED from the verified wire
contract confirmed directly against the lzt-eventus server source (frame grammar
`id:`/`event:`/`data:` + blank-line dispatch, `data:` JSON body carries the
uniform `{seq, event_type, data}` envelope) — it is not a live-captured golden
fixture, unlike `tests/fixtures/api_captures.json`. This is a deliberate,
documented exception to the repo's golden-capture convention (no live server
session was available to capture from).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.filters import EventTypeFilter
from lzt_eventus_sdk.dispatch.router import Router
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.sources.sse import SSEConfig, SSEProtocolError, SSESource, _parse_sse
from lzt_eventus_sdk.storage.cursor import CursorStore
from lzt_eventus_sdk.storage.memory import MemoryStorage

_STREAM = (Path(__file__).parent / "fixtures" / "sse_stream.txt").read_text()


async def _lines(text: str) -> AsyncIterator[str]:
    for line in text.splitlines(keepends=True):
        yield line


async def test_parse_sse_frames_from_fixture() -> None:
    events: list[ClientEvent] = []
    async for event in _parse_sse(_lines(_STREAM)):
        events.append(event)

    assert len(events) == 2
    assert events[0].seq == 1
    assert events[0].event_type == "new_lot"
    assert events[0].data == {"category": "steam"}
    assert events[0].transport is TransportKind.SSE
    assert events[1].seq == 2
    assert events[1].event_type == "price_dropped"


async def test_parse_sse_malformed_json_raises_protocol_error() -> None:
    bad = "data: {not valid json\n\n"
    with pytest.raises(SSEProtocolError):
        async for _ in _parse_sse(_lines(bad)):
            pass


def _account(client_transport: httpx.MockTransport) -> AccountContext:
    from lzt_eventus_sdk.client import ManagementClient

    client = ManagementClient("https://engine.example", api_key="k", transport=client_transport)
    return AccountContext(client=client, subscription_id="sub-1", label="t", stream_token="tok-abc")


async def test_sse_source_streams_events_over_mock_transport() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, content=_STREAM.encode())

    account = _account(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    source = SSESource(
        account,
        cursor_store=CursorStore(MemoryStorage()),
        base_url="https://stream.example",
        config=SSEConfig(min_backoff=0.01, max_backoff=0.02),
        transport=httpx.MockTransport(handler),
    )

    stream = source.stream()
    first = await stream.__anext__()
    second = await stream.__anext__()
    await stream.aclose()
    await source.aclose()

    assert first.seq == 1
    assert second.seq == 2
    assert seen_headers.get("x-stream-token") == "tok-abc"
    assert "last-event-id" not in seen_headers  # no cursor yet on first connect


async def test_sse_source_resumes_with_last_event_id_header() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, content=b"")

    cursor_store = CursorStore(MemoryStorage())
    await cursor_store.advance("sub-1", TransportKind.SSE, 7)

    account = _account(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    source = SSESource(
        account,
        cursor_store=cursor_store,
        base_url="https://stream.example",
        config=SSEConfig(min_backoff=0.01, max_backoff=0.02),
        transport=httpx.MockTransport(handler),
    )

    stream = source.stream()
    with pytest.raises(TimeoutError):
        # empty body -> no frames -> the source keeps reconnecting; bound the wait
        await asyncio.wait_for(stream.__anext__(), timeout=0.05)
    await source.aclose()

    assert seen_headers.get("last-event-id") == "7"


async def test_sse_source_advances_cursor_after_dispatch() -> None:
    # First connection streams the fixture; every reconnect after that gets an
    # empty body, so a single dispatch pass is observable before the bounded
    # timeout below.
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        content = _STREAM.encode() if call_count["n"] == 1 else b""
        return httpx.Response(200, content=content)

    cursor_store = CursorStore(MemoryStorage())
    account = _account(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    source = SSESource(
        account,
        cursor_store=cursor_store,
        base_url="https://stream.example",
        config=SSEConfig(min_backoff=0.01, max_backoff=0.02),
        transport=httpx.MockTransport(handler),
    )

    router = Router()
    seen: list[int] = []
    both_seen = asyncio.Event()

    @router.on(EventTypeFilter("new_lot", "price_dropped"))
    async def handle(event: ClientEvent) -> None:
        seen.append(event.seq)
        if len(seen) == 2:
            both_seen.set()

    dispatcher = Dispatcher(router)
    run_task = asyncio.ensure_future(source.run(dispatcher))
    try:
        await asyncio.wait_for(both_seen.wait(), timeout=2.0)
    finally:
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task
        await source.aclose()

    assert seen == [1, 2]
    assert await cursor_store.get("sub-1", TransportKind.SSE) == 2


async def test_sse_source_does_not_advance_cursor_when_dispatch_errors() -> None:
    """A handler exception becomes `DispatchOutcome.ERRORED` (not re-raised) —
    the cursor must not advance past it, or a reconnect would never redeliver
    the failed event. Stubs `stream()` for a deterministic single-event feed,
    same rationale `test_ws_source_advances_cursor_after_dispatch` gives for WS:
    `run()`'s cursor wiring is a pure consumer of `stream()`.
    """
    account = _account(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    cursor_store = CursorStore(MemoryStorage())
    source = SSESource(
        account,
        cursor_store=cursor_store,
        base_url="https://stream.example",
        config=SSEConfig(min_backoff=0.01, max_backoff=0.02),
    )

    async def fake_stream() -> AsyncIterator[ClientEvent]:
        async for event in _parse_sse(_lines(_STREAM)):
            yield event
            return  # only the first event

    source.stream = fake_stream  # type: ignore[method-assign, assignment]

    router = Router()

    @router.on(EventTypeFilter("new_lot", "price_dropped"))
    async def handle(event: ClientEvent) -> None:
        raise RuntimeError("boom")

    dispatcher = Dispatcher(router)
    await source.run(dispatcher)
    await source.aclose()

    assert await cursor_store.get("sub-1", TransportKind.SSE) == 0
