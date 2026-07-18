from __future__ import annotations

from lzt_eventus_sdk.events.event import TransportKind
from lzt_eventus_sdk.storage.base import BaseStorage


class CursorStore:
    """Client-local `last_seq` per `(subscription_id, transport)`, mirroring the
    server's own per-consumer cursor shape. Push transports (SSE/WS/webhook)
    have no server-side ack — this cursor is purely a local resume aid, advanced
    only after successful dispatch, and only ever sent back as a resume hint
    (`Last-Event-ID` / WS auth-frame `last_seq`), never as a server ack.
    """

    def __init__(self, storage: BaseStorage[str, int]) -> None:
        self._storage = storage

    @staticmethod
    def _key(subscription_id: str, transport: TransportKind) -> str:
        return f"{subscription_id}:{transport.value}"

    async def get(self, subscription_id: str, transport: TransportKind) -> int:
        value = await self._storage.get(self._key(subscription_id, transport))
        return value if value is not None else 0

    async def advance(self, subscription_id: str, transport: TransportKind, seq: int) -> None:
        current = await self.get(subscription_id, transport)
        if seq > current:
            await self._storage.set(self._key(subscription_id, transport), seq)
