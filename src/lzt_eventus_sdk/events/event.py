from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lzt_eventus_sdk.models import PendingEvent


class TransportKind(StrEnum):
    """Provenance of a `ClientEvent` — which source produced it."""

    WEBHOOK = "webhook"
    SSE = "sse"
    WS = "ws"
    POLLING = "polling"


@dataclass(frozen=True, slots=True)
class ClientEvent:
    """The single value object every transport normalises its wire frame into.

    Account/subscription identity is deliberately not carried here — it rides
    the injected `AccountContext` so the same event is account-agnostic.
    """

    seq: int
    event_type: str
    data: dict[str, object]
    transport: TransportKind
    received_at: datetime
    event_id: str | None = None
    idempotency_key: str | None = None

    @classmethod
    def from_pending(cls, item: PendingEvent, *, transport: TransportKind) -> ClientEvent:
        return cls(
            seq=item.seq,
            event_type=item.event_type,
            data=item.data,
            transport=transport,
            received_at=datetime.now(UTC),
        )
