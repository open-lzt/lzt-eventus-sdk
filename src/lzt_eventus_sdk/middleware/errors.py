from __future__ import annotations

import logging
from typing import Any

from lzt_eventus_sdk.events.event import ClientEvent
from lzt_eventus_sdk.middleware.base import BaseMiddleware, Handler

_logger = logging.getLogger(__name__)


class HandlerError(Exception):
    """Wraps a handler's raised exception with routing context, chained onto
    the original. Caught by `Dispatcher._run_handler`'s base safety net and
    turned into `DispatchResult(outcome=ERRORED)`.
    """

    def __init__(self, *, event_type: str, seq: int) -> None:
        self.event_type = event_type
        self.seq = seq
        super().__init__(f"handler raised for event_type={event_type!r} seq={seq}")


class ErrorBoundaryMiddleware(BaseMiddleware):
    """Innermost wrapper — catches only handler code, never framework code.
    Logs, chains, and re-raises so `Dispatcher` still records
    `DispatchResult(outcome=ERRORED)`; the source-aware ack policy (D6:
    webhook -> 503, SSE/WS/polling -> don't advance cursor) lives at the
    transport, not here.
    """

    async def __call__(self, handler: Handler, event: ClientEvent, data: dict[str, Any]) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:
            _logger.exception(
                "handler raised",
                extra={
                    "event_type": event.event_type,
                    "seq": event.seq,
                    "transport": event.transport,
                },
            )
            raise HandlerError(event_type=event.event_type, seq=event.seq) from exc
