"""Unit tests for `dispatch/` — router/dispatcher/filters/context fed synthetic
events, no transport involved (build step 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from lzt_eventus_sdk.client import ManagementClient
from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.filters import EventTypeFilter, F
from lzt_eventus_sdk.dispatch.result import DispatchOutcome
from lzt_eventus_sdk.dispatch.router import Router, SkipHandler
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.middleware.base import BaseMiddleware, Handler


def _client() -> ManagementClient:
    return ManagementClient(
        "https://engine.example",
        api_key="k",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )


def _ctx(subscription_id: str = "sub-1") -> AccountContext:
    return AccountContext(client=_client(), subscription_id=subscription_id, label="test")


def _event(
    event_type: str = "new_lot", seq: int = 1, data: dict[str, object] | None = None
) -> ClientEvent:
    return ClientEvent(
        seq=seq,
        event_type=event_type,
        data=data or {},
        transport=TransportKind.POLLING,
        received_at=datetime.now(UTC),
    )


async def test_feed_routes_to_matching_handler() -> None:
    router = Router()
    calls: list[str] = []

    @router.on("new_lot")
    async def handle_new_lot(event: ClientEvent) -> None:
        calls.append(event.event_type)

    dispatcher = Dispatcher(router)
    result = await dispatcher.feed(_event("new_lot"), _ctx())

    assert result.outcome is DispatchOutcome.HANDLED
    assert calls == ["new_lot"]


async def test_unmatched_event_type_is_skipped_not_error() -> None:
    router = Router()

    @router.on("new_lot")
    async def handle_new_lot() -> None:
        raise AssertionError("should never run")

    dispatcher = Dispatcher(router)
    result = await dispatcher.feed(_event("price_dropped"), _ctx())

    assert result.outcome is DispatchOutcome.SKIPPED


async def test_first_match_wins_registration_order() -> None:
    router = Router()
    calls: list[str] = []

    @router.on("new_lot")
    async def first(event: ClientEvent) -> None:
        calls.append("first")

    @router.on("new_lot")
    async def second(event: ClientEvent) -> None:
        calls.append("second")

    dispatcher = Dispatcher(router)
    await dispatcher.feed(_event("new_lot"), _ctx())

    assert calls == ["first"]


async def test_skip_handler_falls_through_to_next() -> None:
    router = Router()
    calls: list[str] = []

    @router.on("new_lot")
    async def first(event: ClientEvent) -> None:
        calls.append("first")
        raise SkipHandler

    @router.on("new_lot")
    async def second(event: ClientEvent) -> None:
        calls.append("second")

    dispatcher = Dispatcher(router)
    result = await dispatcher.feed(_event("new_lot"), _ctx())

    assert calls == ["first", "second"]
    assert result.outcome is DispatchOutcome.HANDLED


async def test_included_child_router_is_walked() -> None:
    parent = Router()
    child = Router()
    parent.include_router(child)
    calls: list[str] = []

    @child.on("new_lot")
    async def handle(event: ClientEvent) -> None:
        calls.append("child")

    dispatcher = Dispatcher(parent)
    await dispatcher.feed(_event("new_lot"), _ctx())

    assert calls == ["child"]


async def test_handler_gets_injected_context_and_client() -> None:
    router = Router()
    seen: dict[str, object] = {}

    @router.on("new_lot")
    async def handle(subscription_id: str, client: ManagementClient, ctx: AccountContext) -> None:
        seen["subscription_id"] = subscription_id
        seen["client"] = client
        seen["ctx"] = ctx

    ctx = _ctx("sub-42")
    dispatcher = Dispatcher(router)
    await dispatcher.feed(_event("new_lot"), ctx)

    assert seen["subscription_id"] == "sub-42"
    assert seen["client"] is ctx.client
    assert seen["ctx"] is ctx


async def test_handler_exception_yields_errored_result() -> None:
    router = Router()

    @router.on("new_lot")
    async def handle(event: ClientEvent) -> None:
        raise RuntimeError("boom")

    dispatcher = Dispatcher(router)
    result = await dispatcher.feed(_event("new_lot"), _ctx())

    assert result.outcome is DispatchOutcome.ERRORED
    assert isinstance(result.error, RuntimeError)


async def test_magic_filter_field_access_and_comparison() -> None:
    router = Router()
    calls: list[str] = []

    @router.on("new_lot", F.data["category"] == "steam")
    async def handle() -> None:
        calls.append("matched")

    dispatcher = Dispatcher(router)
    await dispatcher.feed(_event("new_lot", data={"category": "steam"}), _ctx())
    await dispatcher.feed(_event("new_lot", data={"category": "csgo"}), _ctx())

    assert calls == ["matched"]


async def test_magic_filter_missing_field_fails_closed_not_raises() -> None:
    router = Router()
    calls: list[str] = []

    @router.on("new_lot", F.data["category"] == "steam")
    async def handle() -> None:
        calls.append("matched")

    dispatcher = Dispatcher(router)
    result = await dispatcher.feed(_event("new_lot", data={}), _ctx())

    assert calls == []
    assert result.outcome is DispatchOutcome.SKIPPED


async def test_event_type_filter_multiple_types() -> None:
    filt = EventTypeFilter("a", "b")
    assert await filt(_event("a"), {}) is True
    assert await filt(_event("b"), {}) is True
    assert await filt(_event("c"), {}) is False


async def test_middleware_chain_ordering() -> None:
    order: list[str] = []

    class Outer(BaseMiddleware):
        async def __call__(self, handler: Handler, event: ClientEvent, data: dict[str, Any]) -> Any:
            order.append("outer-before")
            result = await handler(event, data)
            order.append("outer-after")
            return result

    class Inner(BaseMiddleware):
        async def __call__(self, handler: Handler, event: ClientEvent, data: dict[str, Any]) -> Any:
            order.append("inner-before")
            result = await handler(event, data)
            order.append("inner-after")
            return result

    router = Router()

    @router.on("new_lot")
    async def handle() -> None:
        order.append("handler")

    dispatcher = Dispatcher(router, outer_middleware=[Outer()], inner_middleware=[Inner()])
    await dispatcher.feed(_event("new_lot"), _ctx())

    assert order == ["outer-before", "inner-before", "handler", "inner-after", "outer-after"]


async def test_outer_middleware_can_short_circuit() -> None:
    from lzt_eventus_sdk.dispatch.result import DispatchResult

    class ShortCircuit(BaseMiddleware):
        async def __call__(self, handler: Handler, event: ClientEvent, data: dict[str, Any]) -> Any:
            return DispatchResult(outcome=DispatchOutcome.DUPLICATE, event=event)

    router = Router()
    calls: list[str] = []

    @router.on("new_lot")
    async def handle() -> None:
        calls.append("should-not-run")

    dispatcher = Dispatcher(router, outer_middleware=[ShortCircuit()])
    result = await dispatcher.feed(_event("new_lot"), _ctx())

    assert calls == []
    assert result.outcome is DispatchOutcome.DUPLICATE
