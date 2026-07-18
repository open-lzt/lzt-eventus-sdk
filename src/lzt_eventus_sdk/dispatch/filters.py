from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from lzt_eventus_sdk.events.event import ClientEvent


class Filter(ABC):
    """A predicate over `(event, data)`. Returning a `dict` means "passed, and
    merge these keys into `data`" (aiogram magic-filter behaviour); any other
    truthy/falsy value is a plain pass/fail.
    """

    @abstractmethod
    async def __call__(self, event: ClientEvent, data: dict[str, Any]) -> bool | dict[str, Any]: ...


class EventTypeFilter(Filter):
    """The common case — auto-prepended by `@router.on("new_lot")`."""

    def __init__(self, *event_types: str) -> None:
        self._event_types = frozenset(event_types)

    async def __call__(self, event: ClientEvent, data: dict[str, Any]) -> bool:
        return event.event_type in self._event_types


class MagicFilter(Filter):
    """Minimal field-access + comparison + boolean-combinator expression
    builder — `F.data["category"] == "steam"`, `F.seq > 1000`, `~F.data["x"]`.
    Not the full `evented` magic-filter surface, just enough for local routing
    (00 § Scope — client-side filters are a local demultiplexer, not a
    re-implementation of the server's subscribe-time `filters={...}`).
    """

    def __init__(self, resolver: Callable[[ClientEvent], Any]) -> None:
        self._resolver = resolver

    def __getattr__(self, name: str) -> MagicFilter:
        if name.startswith("_"):
            raise AttributeError(name)
        resolver = self._resolver
        return MagicFilter(lambda event: getattr(resolver(event), name))

    def __getitem__(self, key: object) -> MagicFilter:
        resolver = self._resolver
        return MagicFilter(lambda event: resolver(event)[key])

    # Magic-filter DSL: __eq__/__ne__ build a predicate, not a bool — the same
    # deliberate Liskov break aiogram's own magic filter makes.
    def __eq__(self, other: object) -> MagicFilter:  # type: ignore[override]
        resolver = self._resolver
        return MagicFilter(lambda event: resolver(event) == other)

    def __ne__(self, other: object) -> MagicFilter:  # type: ignore[override]
        resolver = self._resolver
        return MagicFilter(lambda event: resolver(event) != other)

    def __gt__(self, other: object) -> MagicFilter:
        resolver = self._resolver
        return MagicFilter(lambda event: resolver(event) > other)

    def __ge__(self, other: object) -> MagicFilter:
        resolver = self._resolver
        return MagicFilter(lambda event: resolver(event) >= other)

    def __lt__(self, other: object) -> MagicFilter:
        resolver = self._resolver
        return MagicFilter(lambda event: resolver(event) < other)

    def __le__(self, other: object) -> MagicFilter:
        resolver = self._resolver
        return MagicFilter(lambda event: resolver(event) <= other)

    def __and__(self, other: MagicFilter) -> MagicFilter:
        resolver, other_resolver = self._resolver, other._resolver
        return MagicFilter(lambda event: bool(resolver(event)) and bool(other_resolver(event)))

    def __or__(self, other: MagicFilter) -> MagicFilter:
        resolver, other_resolver = self._resolver, other._resolver
        return MagicFilter(lambda event: bool(resolver(event)) or bool(other_resolver(event)))

    def __invert__(self) -> MagicFilter:
        resolver = self._resolver
        return MagicFilter(lambda event: not resolver(event))

    async def __call__(self, event: ClientEvent, data: dict[str, Any]) -> bool:
        try:
            return bool(self._resolver(event))
        except (AttributeError, KeyError, TypeError):
            # A field that doesn't exist on this event just fails the filter —
            # never crashes routing (forward-compat with the open event catalog).
            return False


F = MagicFilter(lambda event: event)
