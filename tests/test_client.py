"""`ManagementClient` against golden fixtures captured from the real API
(`tests/fixtures/api_captures.json`) — every assertion here is checked against a
response the real server actually produced, not a hand-written guess.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from lzt_eventus_sdk import (
    CategoryScope,
    EventType,
    InvalidLimit,
    ManagementClient,
    MarketCategory,
    SubscriptionNotFound,
    SubscriptionTransport,
    Unauthorized,
)


def _client(capture: dict[str, Any]) -> ManagementClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(capture["status"], json=capture["body"])

    return ManagementClient(
        "https://engine.example", api_key="k", transport=httpx.MockTransport(handler)
    )


async def test_create_subscription(captures: dict[str, Any]) -> None:
    async with _client(captures["create_subscription"]) as mgmt:
        sub = await mgmt.create_subscription(
            transport=SubscriptionTransport.POLLING,
            endpoint="my-poller",
            event_types=[EventType.NEW_LOT, EventType.PRICE_DROPPED],
            scope=CategoryScope(category=MarketCategory.STEAM),
            backfill=True,
        )

    assert sub.subscription_id == "de4e557c7e604364a978b4cf9412e922"
    assert sub.transport == SubscriptionTransport.POLLING
    assert sub.event_types == ["new_lot", "price_dropped"]
    assert sub.scope == CategoryScope(category="steam")
    assert sub.active is True
    assert sub.secret is None  # polling transport mints no secret


async def test_list_subscriptions(captures: dict[str, Any]) -> None:
    async with _client(captures["list_subscriptions"]) as mgmt:
        page = await mgmt.list_subscriptions()

    assert page.total == 1
    assert page.limit == 50
    assert page.offset == 0
    assert len(page.items) == 1
    assert page.items[0].subscription_id == "de4e557c7e604364a978b4cf9412e922"


async def test_get_subscription(captures: dict[str, Any]) -> None:
    async with _client(captures["get_subscription"]) as mgmt:
        sub = await mgmt.get_subscription("de4e557c7e604364a978b4cf9412e922")

    assert sub.endpoint == "my-poller"
    assert sub.scope == CategoryScope(category="steam")


async def test_update_subscription(captures: dict[str, Any]) -> None:
    async with _client(captures["update_subscription"]) as mgmt:
        sub = await mgmt.update_subscription("de4e557c7e604364a978b4cf9412e922", active=True)

    assert sub.active is True


async def test_poll_pending(captures: dict[str, Any]) -> None:
    async with _client(captures["poll_pending"]) as mgmt:
        batch = await mgmt.poll_pending("de4e557c7e604364a978b4cf9412e922", limit=10)

    assert batch.subscription_id == "de4e557c7e604364a978b4cf9412e922"
    assert len(batch.items) >= 1
    first = batch.items[0]
    assert first.seq == 1
    assert first.event_type == "new_lot"
    assert first.data["category"] == "steam"
    assert batch.committed is False


async def test_confirm_read(captures: dict[str, Any]) -> None:
    async with _client(captures["read_events"]) as mgmt:
        last_seq = await mgmt.confirm_read("de4e557c7e604364a978b4cf9412e922", up_to_seq=2)

    assert last_seq == captures["read_events"]["body"]["last_seq"]


async def test_list_event_types(captures: dict[str, Any]) -> None:
    async with _client(captures["event_types"]) as mgmt:
        types = await mgmt.list_event_types()

    assert "new_lot" in types
    assert "price_dropped" in types
    assert types == sorted(types)  # server sorts them; a drift here means a contract change


async def test_health(captures: dict[str, Any]) -> None:
    async with _client(captures["healthz"]) as mgmt:
        assert await mgmt.health() is True


async def test_deactivate_subscription_no_raise(captures: dict[str, Any]) -> None:
    async with _client(captures["deactivate_subscription"]) as mgmt:
        await mgmt.deactivate_subscription("de4e557c7e604364a978b4cf9412e922")  # must not raise


async def test_subscription_not_found_raises_typed_error(captures: dict[str, Any]) -> None:
    async with _client(captures["error_subscription_not_found"]) as mgmt:
        with pytest.raises(SubscriptionNotFound) as exc_info:
            await mgmt.get_subscription("does-not-exist")

    assert exc_info.value.status == 404
    assert exc_info.value.code == "subscription_not_found"
    assert exc_info.value.detail["subscription_id"] == "does-not-exist"


async def test_invalid_limit_raises_typed_error(captures: dict[str, Any]) -> None:
    async with _client(captures["error_invalid_limit"]) as mgmt:
        with pytest.raises(InvalidLimit) as exc_info:
            await mgmt.poll_pending("x", limit=0)

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_limit"


async def test_unauthorized_raises_typed_error(captures: dict[str, Any]) -> None:
    async with _client(captures["error_unauthorized"]) as mgmt:
        with pytest.raises(Unauthorized) as exc_info:
            await mgmt.list_subscriptions()

    assert exc_info.value.status == 401
    assert exc_info.value.code == "unauthorized"


async def test_connection_error_is_typed() -> None:
    from lzt_eventus_sdk import ManagementApiConnectionError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with ManagementClient(
        "https://engine.example", api_key="k", transport=httpx.MockTransport(handler)
    ) as mgmt:
        with pytest.raises(ManagementApiConnectionError):
            await mgmt.list_subscriptions()
