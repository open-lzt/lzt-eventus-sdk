"""Unit tests for the shipped middlewares — needs storage (build step 4)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from lzt_eventus_sdk.client import ManagementClient
from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.result import DispatchOutcome
from lzt_eventus_sdk.dispatch.router import Router
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.middleware.errors import ErrorBoundaryMiddleware, HandlerError
from lzt_eventus_sdk.middleware.idempotency import IdempotencyMiddleware
from lzt_eventus_sdk.storage.idempotency import IdempotencyStore
from lzt_eventus_sdk.storage.memory import MemoryStorage


def _ctx(subscription_id: str = "sub-1") -> AccountContext:
    client = ManagementClient(
        "https://engine.example",
        api_key="k",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    return AccountContext(client=client, subscription_id=subscription_id, label="test")


def _event(
    seq: int = 1, event_id: str | None = None, idempotency_key: str | None = None
) -> ClientEvent:
    return ClientEvent(
        seq=seq,
        event_type="new_lot",
        data={},
        transport=TransportKind.WEBHOOK,
        received_at=datetime.now(UTC),
        event_id=event_id,
        idempotency_key=idempotency_key,
    )


async def test_idempotency_middleware_dedups_by_idempotency_key() -> None:
    store = IdempotencyStore(MemoryStorage())
    router = Router()
    calls: list[int] = []

    @router.on("new_lot")
    async def handle(event: ClientEvent) -> None:
        calls.append(event.seq)

    dispatcher = Dispatcher(router, outer_middleware=[IdempotencyMiddleware(store)])
    ctx = _ctx()

    first = await dispatcher.feed(_event(seq=1, idempotency_key="idem-1"), ctx)
    second = await dispatcher.feed(_event(seq=1, idempotency_key="idem-1"), ctx)

    assert first.outcome is DispatchOutcome.HANDLED
    assert second.outcome is DispatchOutcome.DUPLICATE
    assert calls == [1]  # handler ran exactly once despite the redelivery


async def test_idempotency_middleware_falls_back_to_subscription_and_seq() -> None:
    store = IdempotencyStore(MemoryStorage())
    router = Router()
    calls: list[int] = []

    @router.on("new_lot")
    async def handle(event: ClientEvent) -> None:
        calls.append(event.seq)

    dispatcher = Dispatcher(router, outer_middleware=[IdempotencyMiddleware(store)])
    ctx = _ctx("sub-9")

    await dispatcher.feed(_event(seq=5), ctx)
    result = await dispatcher.feed(_event(seq=5), ctx)

    assert result.outcome is DispatchOutcome.DUPLICATE
    assert calls == [5]


async def test_error_boundary_middleware_chains_and_still_errors() -> None:
    router = Router()

    @router.on("new_lot")
    async def handle() -> None:
        raise ValueError("handler bug")

    dispatcher = Dispatcher(router, inner_middleware=[ErrorBoundaryMiddleware()])
    result = await dispatcher.feed(_event(), _ctx())

    assert result.outcome is DispatchOutcome.ERRORED
    assert isinstance(result.error, HandlerError)
    assert isinstance(result.error.__cause__, ValueError)


async def test_error_boundary_does_not_swallow_healthy_handlers() -> None:
    router = Router()
    calls: list[str] = []

    @router.on("new_lot")
    async def handle() -> None:
        calls.append("ok")

    dispatcher = Dispatcher(router, inner_middleware=[ErrorBoundaryMiddleware()])
    result = await dispatcher.feed(_event(), _ctx())

    assert result.outcome is DispatchOutcome.HANDLED
    assert calls == ["ok"]
