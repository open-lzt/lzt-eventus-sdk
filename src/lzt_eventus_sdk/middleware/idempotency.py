from __future__ import annotations

from typing import Any

from lzt_eventus_sdk.dispatch.result import DispatchOutcome, DispatchResult
from lzt_eventus_sdk.events.event import ClientEvent
from lzt_eventus_sdk.middleware.base import BaseMiddleware, Handler
from lzt_eventus_sdk.storage.idempotency import IdempotencyStore

_DEFAULT_TTL = 86_400.0  # 24h — covers any realistic at-least-once redelivery window


class IdempotencyMiddleware(BaseMiddleware):
    """Outer middleware — dedups at-least-once redelivery before any handler
    runs. Dedup key priority: `Idempotency-Key` header -> `event_id` ->
    `(subscription_id, seq)` (webhook always has the first; SSE/WS/polling
    fall back to seq-based keys).
    """

    def __init__(self, store: IdempotencyStore, *, ttl: float = _DEFAULT_TTL) -> None:
        self._store = store
        self._ttl = ttl

    async def __call__(self, handler: Handler, event: ClientEvent, data: dict[str, Any]) -> Any:
        sub_id = data.get("subscription_id")
        key = event.idempotency_key or event.event_id or f"{sub_id}:{event.seq}"
        if not await self._store.mark_if_new(key, ttl=self._ttl):
            return DispatchResult(outcome=DispatchOutcome.DUPLICATE, event=event)
        return await handler(event, data)
