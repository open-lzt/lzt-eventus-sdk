"""Unit tests for `storage/` — pure, no I/O (build step 3)."""

from __future__ import annotations

import asyncio

from lzt_eventus_sdk.events.event import TransportKind
from lzt_eventus_sdk.storage.cursor import CursorStore
from lzt_eventus_sdk.storage.idempotency import IdempotencyStore
from lzt_eventus_sdk.storage.memory import MemoryStorage


async def test_memory_storage_get_set_delete() -> None:
    storage: MemoryStorage[str, int] = MemoryStorage()
    assert await storage.get("k") is None

    await storage.set("k", 42)
    assert await storage.get("k") == 42

    await storage.delete("k")
    assert await storage.get("k") is None


async def test_memory_storage_ttl_expiry() -> None:
    storage: MemoryStorage[str, int] = MemoryStorage()
    await storage.set("k", 1, ttl=0.01)
    assert await storage.get("k") == 1

    await asyncio.sleep(0.05)
    assert await storage.get("k") is None


async def test_idempotency_store_dedup() -> None:
    store = IdempotencyStore(MemoryStorage())

    assert await store.seen("evt-1") is False
    await store.mark("evt-1")
    assert await store.seen("evt-1") is True
    # a different key is unaffected
    assert await store.seen("evt-2") is False


async def test_cursor_store_advance_only_moves_forward() -> None:
    store = CursorStore(MemoryStorage())

    assert await store.get("sub-1", TransportKind.SSE) == 0

    await store.advance("sub-1", TransportKind.SSE, 5)
    assert await store.get("sub-1", TransportKind.SSE) == 5

    await store.advance("sub-1", TransportKind.SSE, 3)
    assert await store.get("sub-1", TransportKind.SSE) == 5  # never regresses

    await store.advance("sub-1", TransportKind.SSE, 9)
    assert await store.get("sub-1", TransportKind.SSE) == 9


async def test_cursor_store_keys_are_per_transport() -> None:
    store = CursorStore(MemoryStorage())

    await store.advance("sub-1", TransportKind.WS, 10)
    assert await store.get("sub-1", TransportKind.WS) == 10
    assert await store.get("sub-1", TransportKind.SSE) == 0
    assert await store.get("sub-1", TransportKind.POLLING) == 0


async def test_memory_storage_set_if_not_exists_is_atomic_under_concurrency() -> None:
    storage: MemoryStorage[str, bool] = MemoryStorage()

    results = await asyncio.gather(*(storage.set_if_not_exists("k", True) for _ in range(20)))

    assert results.count(True) == 1
    assert results.count(False) == 19


async def test_memory_storage_set_if_not_exists_respects_expiry() -> None:
    storage: MemoryStorage[str, int] = MemoryStorage()

    assert await storage.set_if_not_exists("k", 1, ttl=0.01) is True
    assert await storage.set_if_not_exists("k", 2) is False  # still unexpired

    await asyncio.sleep(0.05)
    assert await storage.set_if_not_exists("k", 3) is True  # expired, so a fresh write wins


async def test_memory_storage_sweeps_expired_entries_after_write_threshold() -> None:
    storage: MemoryStorage[str, int] = MemoryStorage()

    for i in range(500):
        await storage.set(f"expired-{i}", i, ttl=0.001)
    await asyncio.sleep(0.05)  # let the batch above actually expire

    for i in range(500):
        # No ttl. The 500th write here is the 1000th write overall, which
        # crosses the next `_SWEEP_INTERVAL` boundary and actively sweeps the
        # now-expired "expired-*" entries out of `_data`.
        await storage.set(f"fresh-{i}", i)

    assert "expired-0" not in storage._data
    assert "expired-499" not in storage._data
    assert len(storage._data) == 500  # only the unexpired "fresh-*" entries remain


async def test_idempotency_store_mark_if_new_is_exclusive_under_concurrency() -> None:
    store = IdempotencyStore(MemoryStorage())

    results = await asyncio.gather(*(store.mark_if_new("evt-1") for _ in range(10)))

    assert results.count(True) == 1
    assert results.count(False) == 9
