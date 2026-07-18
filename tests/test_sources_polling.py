"""Unit tests for `PollingSource` — wraps the existing REST client, zero new
I/O surface, tested with `httpx.MockTransport` (existing golden-fixture
pattern)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from lzt_eventus_sdk.client import ManagementClient
from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.router import Router
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.sources.polling import ConfirmMode, PollingConfig, PollingSource

_RUN_TIMEOUT = 0.2


def _batch_body(
    items: list[dict[str, object]], *, next_seq: int, drained: bool
) -> dict[str, object]:
    return {
        "subscription_id": "sub-1",
        "items": items,
        "next_seq": next_seq,
        "last_read_seq": next_seq - 1,
        "drained": drained,
        "committed": False,
    }


def _client_with_responses(responses: list[httpx.Response]) -> ManagementClient:
    calls = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            return next(calls)
        except StopIteration:
            return httpx.Response(200, json=_batch_body([], next_seq=1, drained=True))

    return ManagementClient(
        "https://engine.example", api_key="k", transport=httpx.MockTransport(handler)
    )


async def test_stream_yields_events_without_confirming() -> None:
    client = _client_with_responses(
        [
            httpx.Response(
                200,
                json=_batch_body(
                    [{"seq": 1, "event_type": "new_lot", "data": {"category": "steam"}}],
                    next_seq=2,
                    drained=True,
                ),
            )
        ]
    )
    account = AccountContext(client=client, subscription_id="sub-1", label="t")
    source = PollingSource(account, config=PollingConfig(interval=0.01, empty_backoff_max=0.02))

    events: list[ClientEvent] = []
    stream = source.stream()
    events.append(await stream.__anext__())

    assert events[0].seq == 1
    assert events[0].event_type == "new_lot"
    assert events[0].transport is TransportKind.POLLING
    await stream.aclose()


async def test_run_auto_confirms_after_clean_batch() -> None:
    confirmed: list[int] = []
    call_count = {"polls": 0}

    def route(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/events/read_events":
            payload = json.loads(request.content)
            confirmed.append(payload["up_to_seq"])
            return httpx.Response(200, json={"last_seq": payload["up_to_seq"]})
        call_count["polls"] += 1
        if call_count["polls"] == 1:
            return httpx.Response(
                200,
                json=_batch_body(
                    [{"seq": 1, "event_type": "new_lot", "data": {}}], next_seq=2, drained=True
                ),
            )
        return httpx.Response(200, json=_batch_body([], next_seq=2, drained=True))

    client = ManagementClient(
        "https://engine.example", api_key="k", transport=httpx.MockTransport(route)
    )
    account = AccountContext(client=client, subscription_id="sub-1", label="t")
    source = PollingSource(account, config=PollingConfig(interval=0.01, empty_backoff_max=0.02))

    router = Router()
    seen: list[int] = []

    @router.on("new_lot")
    async def handle(event: ClientEvent) -> None:
        seen.append(event.seq)

    dispatcher = Dispatcher(router)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(source.run(dispatcher), timeout=_RUN_TIMEOUT)

    assert seen == [1]
    assert confirmed == [2]


async def test_run_manual_confirm_mode_never_auto_confirms() -> None:
    confirmed: list[int] = []

    def route(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/events/read_events":
            confirmed.append(1)
            return httpx.Response(200, json={"last_seq": 1})
        return httpx.Response(
            200,
            json=_batch_body(
                [{"seq": 1, "event_type": "new_lot", "data": {}}], next_seq=2, drained=True
            ),
        )

    client = ManagementClient(
        "https://engine.example", api_key="k", transport=httpx.MockTransport(route)
    )
    account = AccountContext(client=client, subscription_id="sub-1", label="t")
    source = PollingSource(
        account,
        config=PollingConfig(interval=0.01, empty_backoff_max=0.02, confirm=ConfirmMode.MANUAL),
    )

    router = Router()

    @router.on("new_lot")
    async def handle() -> None:
        pass

    dispatcher = Dispatcher(router)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(source.run(dispatcher), timeout=_RUN_TIMEOUT)

    assert confirmed == []
