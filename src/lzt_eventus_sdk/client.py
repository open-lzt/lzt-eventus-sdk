"""`ManagementClient` — async client for the lzt-eventus `event_engine` management API.

Zero coupling to the server package — a consumer only needs `base_url` +
`api_key`. Every non-2xx response becomes a typed `ManagementApiError` (never
a bare `httpx` exception); a connection failure becomes
`ManagementApiConnectionError`.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Any, Self

import httpx

from lzt_eventus_sdk.enums import EventType, SubscriptionTransport
from lzt_eventus_sdk.errors import ManagementApiConnectionError, ManagementApiError, build_error
from lzt_eventus_sdk.models import (
    AccountScope,
    CategoryScope,
    NoScope,
    PendingBatch,
    PendingEvent,
    PollingCtx,
    SseCtx,
    SubscriptionCreated,
    SubscriptionCtx,
    SubscriptionInfo,
    SubscriptionPage,
    SubscriptionScope,
    WebhookCtx,
    WebSocketCtx,
)

_DEFAULT_TIMEOUT = 10.0

_CTX_BY_KIND: dict[str, type[WebhookCtx | WebSocketCtx | SseCtx | PollingCtx]] = {
    "webhook": WebhookCtx,
    "websocket": WebSocketCtx,
    "sse": SseCtx,
    "polling": PollingCtx,
}
_SCOPE_BY_KIND: dict[str, type[NoScope | CategoryScope | AccountScope]] = {
    "none": NoScope,
    "category": CategoryScope,
    "account": AccountScope,
}


def _parse_ctx(data: dict[str, Any]) -> SubscriptionCtx:
    kind = data.get("kind")
    cls = _CTX_BY_KIND.get(kind) if isinstance(kind, str) else None
    if cls is None:
        raise ValueError(f"unknown subscription ctx kind: {kind!r}")
    return cls(**data)


def _parse_scope(data: dict[str, Any]) -> SubscriptionScope:
    kind = data.get("kind")
    cls = _SCOPE_BY_KIND.get(kind) if isinstance(kind, str) else None
    if cls is None:
        raise ValueError(f"unknown subscription scope kind: {kind!r}")
    return cls(**data)


def _subscription_info(data: dict[str, Any]) -> SubscriptionInfo:
    return SubscriptionInfo(
        subscription_id=data["subscription_id"],
        transport=data["transport"],
        endpoint=data["endpoint"],
        event_types=list(data["event_types"]),
        scope=_parse_scope(data["scope"]),
        ctx=_parse_ctx(data["ctx"]),
        active=data["active"],
        created_at=datetime.fromisoformat(data["created_at"]),
    )


def _subscription_created(data: dict[str, Any]) -> SubscriptionCreated:
    info = _subscription_info(data)
    return SubscriptionCreated(
        subscription_id=info.subscription_id,
        transport=info.transport,
        endpoint=info.endpoint,
        event_types=info.event_types,
        scope=info.scope,
        ctx=info.ctx,
        active=info.active,
        created_at=info.created_at,
        secret=data.get("secret"),
        stream_token=data.get("stream_token"),
    )


class ManagementClient:
    """Async context manager over one `httpx.AsyncClient`.

    ```python
    async with ManagementClient("https://engine.example", api_key="...") as mgmt:
        sub = await mgmt.create_subscription(
            transport=SubscriptionTransport.WEBHOOK, endpoint="https://you.example/hook",
            event_types=[EventType.NEW_LOT], scope=CategoryScope(category=MarketCategory.STEAM),
        )
    ```
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._http.request(method, path, json=json_body, params=params)
        except httpx.HTTPError as exc:
            raise ManagementApiConnectionError(reason=str(exc)) from exc

        if response.status_code >= 400:
            body: dict[str, Any] = {}
            with contextlib.suppress(ValueError):
                body = response.json()
            raise build_error(
                status=response.status_code,
                code=body.get("error", "unknown_error"),
                detail=body.get("detail") or {},
                request_id=body.get("request_id"),
            )
        result: dict[str, Any] = response.json()
        return result


    async def create_subscription(
        self,
        *,
        transport: SubscriptionTransport | str,
        endpoint: str,
        event_types: Sequence[EventType | str],
        scope: SubscriptionScope | None = None,
        ctx: SubscriptionCtx | None = None,
        backfill: bool = False,
    ) -> SubscriptionCreated:
        json_body: dict[str, Any] = {
            "transport": transport,
            "endpoint": endpoint,
            "event_types": list(event_types),
            "backfill": backfill,
        }
        if scope is not None:
            json_body["scope"] = dataclasses.asdict(scope)
        if ctx is not None:
            json_body["ctx"] = dataclasses.asdict(ctx)
        body = await self._request("POST", "/subscriptions/create", json_body=json_body)
        return _subscription_created(body["data"])

    async def list_subscriptions(
        self, *, limit: int = 50, offset: int = 0, active_only: bool = False
    ) -> SubscriptionPage:
        body = await self._request(
            "GET",
            "/subscriptions/list",
            params={"limit": limit, "offset": offset, "active_only": active_only},
        )
        return SubscriptionPage(
            items=[_subscription_info(item) for item in body["items"]],
            total=body["total"],
            limit=body["limit"],
            offset=body["offset"],
        )

    async def get_subscription(self, subscription_id: str) -> SubscriptionInfo:
        body = await self._request(
            "GET", "/subscriptions/get", params={"subscription_id": subscription_id}
        )
        return _subscription_info(body["data"])

    async def update_subscription(
        self,
        subscription_id: str,
        *,
        event_types: Sequence[EventType | str] | None = None,
        scope: SubscriptionScope | None = None,
        active: bool | None = None,
    ) -> SubscriptionInfo:
        payload: dict[str, Any] = {"subscription_id": subscription_id}
        if event_types is not None:
            payload["event_types"] = list(event_types)
        if scope is not None:
            payload["scope"] = dataclasses.asdict(scope)
        if active is not None:
            payload["active"] = active
        body = await self._request("POST", "/subscriptions/update", json_body=payload)
        return _subscription_info(body["data"])

    async def deactivate_subscription(self, subscription_id: str) -> None:
        await self._request(
            "POST", "/subscriptions/deactivate", json_body={"subscription_id": subscription_id}
        )


    async def poll_pending(
        self,
        subscription_id: str,
        *,
        event_type: Sequence[EventType | str] | None = None,
        limit: int = 100,
        read_all: bool = False,
    ) -> PendingBatch:
        params: dict[str, Any] = {
            "subscription_id": subscription_id,
            "limit": limit,
            "read_all": read_all,
        }
        if event_type:
            params["event_type"] = list(event_type)
        body = await self._request("GET", "/events/pending", params=params)
        return PendingBatch(
            subscription_id=body["subscription_id"],
            items=[
                PendingEvent(seq=i["seq"], event_type=i["event_type"], data=i["data"])
                for i in body["items"]
            ],
            next_seq=body["next_seq"],
            last_read_seq=body["last_read_seq"],
            drained=body["drained"],
            committed=body["committed"],
        )

    async def confirm_read(self, subscription_id: str, up_to_seq: int) -> int:
        """Mark events up to (and including) `up_to_seq` as processed. Returns the
        confirmed `last_seq` — idempotent, replaying an older/equal seq is a no-op."""
        body = await self._request(
            "POST",
            "/events/read_events",
            json_body={"subscription_id": subscription_id, "up_to_seq": up_to_seq},
        )
        return int(body["last_seq"])


    async def list_event_types(self) -> list[str]:
        body = await self._request("GET", "/event-types")
        return list(body["data"])

    async def health(self) -> bool:
        try:
            await self._request("GET", "/healthz")
        except ManagementApiError:
            return False
        return True
