"""Unit tests for `events/` — pure data, no I/O (build step 1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.events.registry import PayloadRegistry
from lzt_eventus_sdk.models import PendingEvent


def test_client_event_from_pending() -> None:
    item = PendingEvent(seq=7, event_type="new_lot", data={"category": "steam"})

    event = ClientEvent.from_pending(item, transport=TransportKind.POLLING)

    assert event.seq == 7
    assert event.event_type == "new_lot"
    assert event.data == {"category": "steam"}
    assert event.transport is TransportKind.POLLING
    assert event.event_id is None
    assert event.idempotency_key is None
    assert event.received_at.tzinfo is not None


def test_registry_resolves_registered_type() -> None:
    registry = PayloadRegistry()

    @dataclass
    class NewLotPayload:
        category: str

    registry.register("new_lot")(NewLotPayload)

    parsed = registry.parse("new_lot", {"category": "steam"})
    assert isinstance(parsed, NewLotPayload)
    assert parsed.category == "steam"


def test_registry_unknown_type_returns_none_never_raises() -> None:
    registry = PayloadRegistry()

    assert registry.parse("some_future_event_type", {"anything": 1}) is None


def test_registry_parse_failure_returns_none_not_raises() -> None:
    registry = PayloadRegistry()

    @dataclass
    class StrictPayload:
        required_field: int

    registry.register("strict")(StrictPayload)

    # Missing required field -> TypeError inside the dataclass constructor,
    # caught and turned into None (handler still gets raw event.data).
    assert registry.parse("strict", {"unrelated": "x"}) is None


def test_client_event_frozen_and_slotted() -> None:
    event = ClientEvent(
        seq=1,
        event_type="t",
        data={},
        transport=TransportKind.WEBHOOK,
        received_at=datetime.now(UTC),
    )
    assert not hasattr(event, "__dict__")  # slots=True
