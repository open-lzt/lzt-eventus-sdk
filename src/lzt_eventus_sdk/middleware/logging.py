from __future__ import annotations

import logging
from typing import Any

from lzt_eventus_sdk.events.event import ClientEvent
from lzt_eventus_sdk.middleware.base import BaseMiddleware, Handler

_logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Outer middleware — sees every event, even ones no handler matches. No
    PII/secrets logged, only routing metadata.
    """

    async def __call__(self, handler: Handler, event: ClientEvent, data: dict[str, Any]) -> Any:
        _logger.info(
            "dispatching event",
            extra={
                "subscription_id": data.get("subscription_id"),
                "event_type": event.event_type,
                "seq": event.seq,
                "transport": event.transport,
                "event_id": event.event_id,
            },
        )
        return await handler(event, data)
