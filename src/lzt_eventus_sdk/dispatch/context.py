from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lzt_eventus_sdk.client import ManagementClient


@dataclass(frozen=True, slots=True)
class AccountContext:
    """Per-account state injected into every handler's `data` dict. One
    `Dispatcher`/`Router`/middleware chain is shared across accounts (D3);
    this is the only thing that varies per account.
    """

    client: ManagementClient
    subscription_id: str
    label: str
    secret: str | None = None
    stream_token: str | None = None
