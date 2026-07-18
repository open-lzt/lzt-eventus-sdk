"""Unit tests for `WSSource`.

`tests/fixtures/ws_frames.json` is HAND-CONSTRUCTED from the verified WS wire
contract (first client frame `{subscription_id, token, last_seq}`, server
frames `{seq, event_type, data}`) confirmed directly against the lzt-eventus
server source — not a live-captured golden fixture. Documented exception to
the repo's golden-capture convention (no live server session was available).

Requires the `[ws]` extra (`websockets`); skipped entirely if absent.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

websockets = pytest.importorskip("websockets")

from lzt_eventus_sdk.client import ManagementClient  # noqa: E402
from lzt_eventus_sdk.dispatch.context import AccountContext  # noqa: E402
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher  # noqa: E402
from lzt_eventus_sdk.dispatch.filters import EventTypeFilter  # noqa: E402
from lzt_eventus_sdk.dispatch.router import Router  # noqa: E402
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind  # noqa: E402
from lzt_eventus_sdk.sources.ws import WSConfig, WSProtocolError, _decode_ws_frame  # noqa: E402
from lzt_eventus_sdk.storage.cursor import CursorStore  # noqa: E402
from lzt_eventus_sdk.storage.memory import MemoryStorage  # noqa: E402

_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ws_frames.json").read_text())


def test_decode_ws_frame_matches_fixture() -> None:
    for raw in _FIXTURE["frames"]:
        event = _decode_ws_frame(json.dumps(raw))
        assert event.seq == raw["seq"]
        assert event.event_type == raw["event_type"]
        assert event.data == raw["data"]
        assert event.transport is TransportKind.WS


def test_decode_ws_frame_malformed_raises_protocol_error() -> None:
    with pytest.raises(WSProtocolError):
        _decode_ws_frame("{not valid json")

    with pytest.raises(WSProtocolError):
        _decode_ws_frame(json.dumps({"seq": 1}))  # missing event_type/data


async def test_ws_source_sends_auth_frame_then_parses_events() -> None:
    received_auth: dict[str, object] = {}

    async def server_handler(socket: object) -> None:
        raw_auth = await socket.recv()  # type: ignore[attr-defined]
        received_auth.update(json.loads(raw_auth))
        for frame in _FIXTURE["frames"]:
            await socket.send(json.dumps(frame))  # type: ignore[attr-defined]
        await asyncio.sleep(1)  # keep the connection open past the test's read window

    async with websockets.serve(server_handler, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        base_url = f"ws://localhost:{port}"

        client = ManagementClient(
            "https://engine.example",
            api_key="k",
            transport=None,
        )
        cursor_store = CursorStore(MemoryStorage())
        await cursor_store.advance("sub-1", TransportKind.WS, 4)

        from lzt_eventus_sdk.sources.ws import WSSource

        account = AccountContext(
            client=client, subscription_id="sub-1", label="t", stream_token="tok-xyz"
        )
        source = WSSource(
            account,
            cursor_store=cursor_store,
            base_url=base_url,
            config=WSConfig(min_backoff=0.01, max_backoff=0.02),
        )

        events: list[ClientEvent] = []
        stream = source.stream()
        events.append(await stream.__anext__())
        events.append(await stream.__anext__())
        await stream.aclose()
        await source.aclose()
        await client.aclose()

    assert received_auth == {"subscription_id": "sub-1", "token": "tok-xyz", "last_seq": 4}
    assert [e.seq for e in events] == [1, 2]


async def test_ws_source_advances_cursor_after_dispatch() -> None:
    """`run()`'s cursor-advance-after-dispatch wiring is a pure consumer of
    `stream()` (D2 — sources are dumb, `Dispatcher.feed` does the routing), so
    this stubs `stream()` instead of a real socket: the auth-frame/parsing
    round trip over a live server is already covered by
    `test_ws_source_sends_auth_frame_then_parses_events` above, and a real
    `websockets.serve()` test server is flaky under Windows' asyncio Proactor
    loop when many tests run in the same session.
    """
    client = ManagementClient("https://engine.example", api_key="k", transport=None)
    cursor_store = CursorStore(MemoryStorage())

    from lzt_eventus_sdk.sources.ws import WSSource

    account = AccountContext(
        client=client, subscription_id="sub-1", label="t", stream_token="tok-xyz"
    )
    source = WSSource(account, cursor_store=cursor_store, base_url="ws://localhost:1")

    async def fake_stream() -> AsyncIterator[ClientEvent]:
        for raw in _FIXTURE["frames"]:
            yield _decode_ws_frame(json.dumps(raw))

    source.stream = fake_stream  # type: ignore[method-assign, assignment]

    router = Router()
    seen: list[int] = []

    @router.on(EventTypeFilter("new_lot", "price_dropped"))
    async def handle(event: ClientEvent) -> None:
        seen.append(event.seq)

    dispatcher = Dispatcher(router)
    await source.run(dispatcher)
    await client.aclose()

    assert seen == [1, 2]
    assert await cursor_store.get("sub-1", TransportKind.WS) == 2


async def test_ws_source_does_not_advance_cursor_when_dispatch_errors() -> None:
    """A handler exception becomes `DispatchOutcome.ERRORED` (not re-raised) —
    the cursor must not advance past it, or a reconnect would never redeliver
    the failed event."""
    client = ManagementClient("https://engine.example", api_key="k", transport=None)
    cursor_store = CursorStore(MemoryStorage())

    from lzt_eventus_sdk.sources.ws import WSSource

    account = AccountContext(
        client=client, subscription_id="sub-1", label="t", stream_token="tok-xyz"
    )
    source = WSSource(account, cursor_store=cursor_store, base_url="ws://localhost:1")

    async def fake_stream() -> AsyncIterator[ClientEvent]:
        yield _decode_ws_frame(json.dumps(_FIXTURE["frames"][0]))  # only the errored event

    source.stream = fake_stream  # type: ignore[method-assign, assignment]

    router = Router()

    @router.on(EventTypeFilter("new_lot", "price_dropped"))
    async def handle(event: ClientEvent) -> None:
        raise RuntimeError("boom")

    dispatcher = Dispatcher(router)
    await source.run(dispatcher)
    await client.aclose()

    # the single event errored, so the cursor must stay put (never advance
    # past a failed dispatch, or a reconnect would never redeliver it).
    assert await cursor_store.get("sub-1", TransportKind.WS) == 0
