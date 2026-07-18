from __future__ import annotations

from abc import ABC, abstractmethod


class BaseStorage[K, V](ABC):
    """Generic K/V storage seam. `MemoryStorage` is the mandatory default; a
    future `RedisStorage` (named `[redis]` extra, deferred) serves the same
    ABC so `IdempotencyStore`/`CursorStore` need no changes to swap backends.
    """

    @abstractmethod
    async def get(self, key: K) -> V | None: ...

    @abstractmethod
    async def set(self, key: K, value: V, *, ttl: float | None = None) -> None: ...

    @abstractmethod
    async def set_if_not_exists(self, key: K, value: V, *, ttl: float | None = None) -> bool:
        """Atomic compare-and-set. Returns `True` if this call wrote the value,
        `False` if the key was already present and unexpired (value unchanged).
        """
        ...

    @abstractmethod
    async def delete(self, key: K) -> None: ...
