from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lzt_eventus_sdk.events.event import ClientEvent


class DispatchOutcome(StrEnum):
    HANDLED = "handled"
    SKIPPED = "skipped"
    DUPLICATE = "duplicate"
    ERRORED = "errored"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """What `feed()` did with one event — a source maps this to its own
    ack/cursor policy (D6): webhook -> HTTP status; SSE/WS/polling -> whether
    to advance the local cursor.

    Lives in its own module (not `dispatcher.py`) so `middleware/idempotency.py`
    can depend on this type without importing `Dispatcher` itself and creating
    a `dispatch <-> middleware` import cycle (middleware/base.py is imported by
    dispatcher.py; middleware/__init__.py eagerly imports idempotency.py).
    """

    outcome: DispatchOutcome
    event: ClientEvent
    error: BaseException | None = None
