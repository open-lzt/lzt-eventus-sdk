from __future__ import annotations

from lzt_eventus_sdk.sources.base import BaseSource, SourceSupervisor
from lzt_eventus_sdk.sources.polling import ConfirmMode, PollingConfig, PollingSource
from lzt_eventus_sdk.sources.sse import SSEConfig, SSEProtocolError, SSESource

# `WSSource` is intentionally NOT re-exported here — it requires the `[ws]`
# extra (`websockets`). Import it explicitly from `lzt_eventus_sdk.sources.ws`
# so a core (httpx-only) install never fails on this package import.

__all__ = [
    "BaseSource",
    "ConfirmMode",
    "PollingConfig",
    "PollingSource",
    "SSEConfig",
    "SSEProtocolError",
    "SSESource",
    "SourceSupervisor",
]
