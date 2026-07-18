"""Unit tests for `WebhookReceiver` — pure-ASGI, tested via `httpx.ASGITransport`
(already an httpx dependency, no new test dep) driving the app exactly like a
real ASGI server would."""

from __future__ import annotations

import json

import httpx

from lzt_eventus_sdk.client import ManagementClient
from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.router import Router
from lzt_eventus_sdk.events.event import ClientEvent
from lzt_eventus_sdk.server.receiver import WebhookReceiver
from lzt_eventus_sdk.signing import (
    EVENT_ID_HEADER,
    EVENT_TYPE_HEADER,
    IDEMPOTENCY_HEADER,
    signature_header,
)

_SECRET = "webhook-secret"
_SUBSCRIPTION_ID = "sub-1"


def _account() -> AccountContext:
    client = ManagementClient(
        "https://engine.example",
        api_key="k",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    return AccountContext(
        client=client, subscription_id=_SUBSCRIPTION_ID, label="t", secret=_SECRET
    )


async def _secret_resolver(subscription_id: str) -> str | None:
    return _SECRET if subscription_id == _SUBSCRIPTION_ID else None


async def _account_resolver(subscription_id: str) -> AccountContext | None:
    return _account() if subscription_id == _SUBSCRIPTION_ID else None


def _body(seq: int = 1, event_type: str = "new_lot") -> bytes:
    payload = {"seq": seq, "event_type": event_type, "data": {"category": "steam"}}
    return json.dumps(payload).encode()


def _headers(
    body: bytes, *, event_type: str = "new_lot", idempotency_key: str = "idem-1"
) -> dict[str, str]:
    return {
        "X-LZT-Signature": signature_header(_SECRET, body),
        EVENT_ID_HEADER: "evt-1",
        EVENT_TYPE_HEADER: event_type,
        IDEMPOTENCY_HEADER: idempotency_key,
        "Content-Type": "application/json",
    }


async def _post(receiver: WebhookReceiver, body: bytes, headers: dict[str, str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=receiver)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/hook/{_SUBSCRIPTION_ID}", content=body, headers=headers)


def _receiver(router: Router) -> WebhookReceiver:
    dispatcher = Dispatcher(router)
    return WebhookReceiver(
        dispatcher, secret_resolver=_secret_resolver, account_resolver=_account_resolver
    )


async def test_valid_signature_handled_event_returns_200() -> None:
    router = Router()
    seen: list[int] = []

    @router.on("new_lot")
    async def handle(event: ClientEvent) -> None:
        seen.append(event.seq)

    body = _body()
    response = await _post(_receiver(router), body, _headers(body))

    assert response.status_code == 200
    assert seen == [1]


async def test_invalid_signature_returns_401() -> None:
    router = Router()
    body = _body()
    headers = _headers(body)
    headers["X-LZT-Signature"] = "sha256=" + "0" * 64

    response = await _post(_receiver(router), body, headers)

    assert response.status_code == 401


async def test_unknown_subscription_returns_401() -> None:
    router = Router()
    dispatcher = Dispatcher(router)
    receiver = WebhookReceiver(
        dispatcher, secret_resolver=_secret_resolver, account_resolver=_account_resolver
    )
    body = _body()
    transport = httpx.ASGITransport(app=receiver)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/hook/does-not-exist", content=body, headers=_headers(body))

    assert response.status_code == 401


async def test_malformed_json_returns_400() -> None:
    router = Router()
    body = b"{not valid json"
    headers = {
        "X-LZT-Signature": signature_header(_SECRET, body),
        IDEMPOTENCY_HEADER: "idem-1",
    }

    response = await _post(_receiver(router), body, headers)

    assert response.status_code == 400


async def test_handler_exception_returns_503_for_server_retry() -> None:
    router = Router()

    @router.on("new_lot")
    async def handle() -> None:
        raise RuntimeError("boom")

    body = _body()
    response = await _post(_receiver(router), body, _headers(body))

    assert response.status_code == 503


async def test_duplicate_delivery_via_idempotency_key_dedups_to_200() -> None:
    from lzt_eventus_sdk.middleware.idempotency import IdempotencyMiddleware
    from lzt_eventus_sdk.storage.idempotency import IdempotencyStore
    from lzt_eventus_sdk.storage.memory import MemoryStorage

    router = Router()
    seen: list[int] = []

    @router.on("new_lot")
    async def handle(event: ClientEvent) -> None:
        seen.append(event.seq)

    store = IdempotencyStore(MemoryStorage())
    dispatcher = Dispatcher(router, outer_middleware=[IdempotencyMiddleware(store)])
    receiver = WebhookReceiver(
        dispatcher, secret_resolver=_secret_resolver, account_resolver=_account_resolver
    )

    body = _body()
    headers = _headers(body, idempotency_key="idem-replay")

    first = await _post(receiver, body, headers)
    second = await _post(receiver, body, headers)  # simulated at-least-once redelivery

    assert first.status_code == 200
    assert second.status_code == 200
    assert seen == [1]  # handler ran exactly once


async def test_filter_exception_returns_503_not_unhandled() -> None:
    """A filter raising is NOT caught inside `Dispatcher._walk_and_handle` (only
    handler-body exceptions are) — it must still map to the documented
    retry-safe 503, not propagate to the ASGI boundary as a raw exception."""
    from typing import Any

    from lzt_eventus_sdk.dispatch.filters import Filter

    class _BoomFilter(Filter):
        async def __call__(self, event: ClientEvent, data: dict[str, Any]) -> bool:
            raise RuntimeError("filter boom")

    router = Router()

    @router.on(_BoomFilter())
    async def handle(event: ClientEvent) -> None:
        pass

    body = _body()
    response = await _post(_receiver(router), body, _headers(body))

    assert response.status_code == 503


async def test_outer_middleware_exception_returns_503_not_unhandled() -> None:
    """An outer middleware (e.g. a storage backend error surfacing through
    `IdempotencyMiddleware`) raising is not caught anywhere inside `Dispatcher`
    — it propagates straight out of `feed()`. The receiver's boundary guard
    must still turn it into the documented 503, not a bare 500/traceback."""
    from lzt_eventus_sdk.middleware.base import BaseMiddleware, Handler

    class _BoomMiddleware(BaseMiddleware):
        async def __call__(
            self, handler: Handler, event: ClientEvent, data: dict[str, object]
        ) -> object:
            raise RuntimeError("middleware boom")

    router = Router()

    @router.on("new_lot")
    async def handle(event: ClientEvent) -> None:
        pass

    dispatcher = Dispatcher(router, outer_middleware=[_BoomMiddleware()])
    receiver = WebhookReceiver(
        dispatcher, secret_resolver=_secret_resolver, account_resolver=_account_resolver
    )
    body = _body()
    response = await _post(receiver, body, _headers(body))

    assert response.status_code == 503


async def test_oversize_body_returns_413() -> None:
    router = Router()
    dispatcher = Dispatcher(router)
    receiver = WebhookReceiver(
        dispatcher,
        secret_resolver=_secret_resolver,
        account_resolver=_account_resolver,
        max_body_bytes=8,
    )
    body = _body()  # well over 8 bytes
    response = await _post(receiver, body, _headers(body))

    assert response.status_code == 413
