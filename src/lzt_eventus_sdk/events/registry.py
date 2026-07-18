from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PayloadRegistry:
    """`event_type` string -> opt-in typed payload model.

    Routing keys on the raw `event_type` string (D1 — the server's catalog is
    open and growing); typed payloads are an ergonomic layer on top, never the
    routing mechanism. Unregistered or unparseable payloads resolve to `None`
    — the handler still gets the raw `event.data`, never an error.
    """

    def __init__(self) -> None:
        self._models: dict[str, type[Any]] = {}

    def register(self, event_type: str) -> Callable[[type[Any]], type[Any]]:
        def decorator(model: type[Any]) -> type[Any]:
            self._models[event_type] = model
            return model

        return decorator

    def resolve(self, event_type: str) -> type[Any] | None:
        return self._models.get(event_type)

    def parse(self, event_type: str, data: dict[str, object]) -> Any | None:
        model = self.resolve(event_type)
        if model is None:
            return None
        try:
            model_validate = getattr(model, "model_validate", None)
            if model_validate is not None:
                return model_validate(data)
            return model(**data)
        except (TypeError, ValueError):
            # Parsing failure is not routable data loss — payload stays absent,
            # the handler falls back to `event.data` (forward-compat, D1).
            return None


events = PayloadRegistry()
