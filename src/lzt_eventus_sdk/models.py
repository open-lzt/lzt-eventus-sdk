"""Response DTOs for `ManagementClient` — a stable wire-level contract, decoupled
from the server's own pydantic schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class WebhookCtx:
    kind: str = "webhook"


@dataclass(frozen=True, slots=True)
class WebSocketCtx:
    kind: str = "websocket"


@dataclass(frozen=True, slots=True)
class SseCtx:
    kind: str = "sse"


@dataclass(frozen=True, slots=True)
class PollingCtx:
    """`poll_delay_seconds` is the min wait the server holds an empty
    `/events/pending` batch before returning (long-poll emulation)."""

    kind: str = "polling"
    poll_delay_seconds: float = 0.0


SubscriptionCtx = WebhookCtx | WebSocketCtx | SseCtx | PollingCtx


@dataclass(frozen=True, slots=True)
class NoScope:
    kind: str = "none"


@dataclass(frozen=True, slots=True)
class CategoryScope:
    kind: str = "category"
    category: str = ""


@dataclass(frozen=True, slots=True)
class AccountScope:
    kind: str = "account"
    account_alias: str = ""


SubscriptionScope = NoScope | CategoryScope | AccountScope


@dataclass(frozen=True, slots=True)
class SubscriptionInfo:
    subscription_id: str
    transport: str
    endpoint: str
    event_types: list[str]
    scope: SubscriptionScope
    ctx: SubscriptionCtx
    active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SubscriptionCreated(SubscriptionInfo):
    """Same fields as `SubscriptionInfo`, plus the one-time plaintext secrets."""

    secret: str | None = None
    stream_token: str | None = None


@dataclass(frozen=True, slots=True)
class SubscriptionPage:
    items: list[SubscriptionInfo]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class PendingEvent:
    seq: int
    event_type: str
    data: dict[str, object]


@dataclass(frozen=True, slots=True)
class PendingBatch:
    subscription_id: str
    items: list[PendingEvent]
    next_seq: int
    last_read_seq: int
    drained: bool
    committed: bool
