from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from lzt_eventus_sdk.events.event import ClientEvent

# `Any` is the deliberate seam here: a middleware may short-circuit with a
# `DispatchResult` (outer phase) or pass through a handler's return value
# (inner phase) — this ABC is shared across both phases (and, per the plan,
# reusable on the HTTP client side later), so it can't be pinned to one type.
Handler = Callable[[ClientEvent, dict[str, Any]], Awaitable[Any]]


class BaseMiddleware(ABC):
    """Chain-of-Responsibility, aiogram signature. Outer middleware runs once
    per event before filter evaluation (dedup, logging); inner middleware
    wraps only the matched handler (error boundary).
    """

    @abstractmethod
    async def __call__(self, handler: Handler, event: ClientEvent, data: dict[str, Any]) -> Any: ...
