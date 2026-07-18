from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from lzt_eventus_sdk.dispatch.filters import EventTypeFilter, Filter

HandlerCallback = Callable[..., Awaitable[object]]


class SkipHandler(Exception):
    """Raise inside a handler to fall through to the next matching handler in
    registration order (aiogram-identical semantics)."""


@dataclass(slots=True)
class HandlerObject:
    callback: HandlerCallback
    filters: tuple[Filter, ...]


class Router:
    """Nestable handler tree. One `EventObserver`-equivalent list per router —
    not one attribute per event type, because the type catalog is open (D1);
    the type match is just the first filter in the chain.
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or f"router-{id(self):x}"
        self.handlers: list[HandlerObject] = []
        self.children: list[Router] = []

    def include_router(self, child: Router) -> Router:
        self.children.append(child)
        return self

    def on(
        self, *filters: str | Filter
    ) -> Callable[[HandlerCallback], HandlerCallback]:
        resolved = tuple(
            EventTypeFilter(f) if isinstance(f, str) else f for f in filters
        )

        def decorator(callback: HandlerCallback) -> HandlerCallback:
            self.handlers.append(HandlerObject(callback=callback, filters=resolved))
            return callback

        return decorator

    def walk(self) -> list[Router]:
        """Depth-first: own handlers first, then children in include order."""
        routers = [self]
        for child in self.children:
            routers.extend(child.walk())
        return routers
