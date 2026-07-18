from __future__ import annotations

import time
from dataclasses import dataclass

from lzt_eventus_sdk.storage.base import BaseStorage


@dataclass(slots=True)
class _Entry[V]:
    value: V
    expires_at: float | None


_SWEEP_INTERVAL = 500


class MemoryStorage[K, V](BaseStorage[K, V]):
    """In-process dict-backed `BaseStorage`. TTL is enforced lazily (checked on
    `get`) plus an active sweep every `_SWEEP_INTERVAL` writes (triggered from
    `set`/`set_if_not_exists`) so entries written once and never re-queried
    don't grow the dict unbounded. Monotonic-clock based so wall-clock changes
    never expire entries early.
    """

    def __init__(self) -> None:
        self._data: dict[K, _Entry[V]] = {}
        self._writes = 0

    async def get(self, key: K) -> V | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at is not None and entry.expires_at < time.monotonic():
            del self._data[key]
            return None
        return entry.value

    async def set(self, key: K, value: V, *, ttl: float | None = None) -> None:
        expires_at = time.monotonic() + ttl if ttl is not None else None
        self._data[key] = _Entry(value=value, expires_at=expires_at)
        self._maybe_sweep()

    async def set_if_not_exists(self, key: K, value: V, *, ttl: float | None = None) -> bool:
        # No `await` between the check and the write — atomic under the
        # single-threaded event loop, which is the whole fix for the
        # idempotency check-then-act race.
        entry = self._data.get(key)
        if entry is not None and (
            entry.expires_at is None or entry.expires_at >= time.monotonic()
        ):
            return False
        expires_at = time.monotonic() + ttl if ttl is not None else None
        self._data[key] = _Entry(value=value, expires_at=expires_at)
        self._maybe_sweep()
        return True

    async def delete(self, key: K) -> None:
        self._data.pop(key, None)

    def _maybe_sweep(self) -> None:
        self._writes += 1
        if self._writes % _SWEEP_INTERVAL != 0:
            return
        now = time.monotonic()
        expired = [
            k for k, e in self._data.items() if e.expires_at is not None and e.expires_at < now
        ]
        for key in expired:
            del self._data[key]
