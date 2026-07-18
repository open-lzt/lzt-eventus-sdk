from __future__ import annotations

from lzt_eventus_sdk.storage.base import BaseStorage

_SEEN = True


class IdempotencyStore:
    """Thin façade over `BaseStorage[str, bool]` — dedup keys for at-least-once
    delivery. Key priority (caller's responsibility to pick): `Idempotency-Key`
    header -> `event_id` -> `(subscription_id, seq)`.
    """

    def __init__(self, storage: BaseStorage[str, bool]) -> None:
        self._storage = storage

    async def seen(self, key: str) -> bool:
        return await self._storage.get(key) is not None

    async def mark(self, key: str, *, ttl: float | None = None) -> None:
        await self._storage.set(key, _SEEN, ttl=ttl)

    async def mark_if_new(self, key: str, *, ttl: float | None = None) -> bool:
        """Atomic seen-check + mark. Returns `True` if this call marked the key
        (i.e. it was not seen before); `False` if another caller already marked
        it. Use this instead of `seen()`+`mark()` to avoid a check-then-act race
        between two concurrent redeliveries of the same key.
        """
        return await self._storage.set_if_not_exists(key, _SEEN, ttl=ttl)
