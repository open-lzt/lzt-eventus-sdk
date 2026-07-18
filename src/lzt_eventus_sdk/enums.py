"""Wire-value enums for the management API — mirrors the server's own enums so a
caller gets autocomplete and a typo caught at import time instead of a raw string
that only fails at request time. Values are copied, not imported, to keep this
package's only runtime dependency `httpx` (no coupling to the server package or
to `pylzt`, the separate market-API SDK `MarketCategory` mirrors).
"""

from __future__ import annotations

from enum import StrEnum


class SubscriptionTransport(StrEnum):
    """`transport` on `create_subscription` / the subscription wire shape.

    NOT the same enum as `lzt_eventus_sdk.events.TransportKind` — that one tags
    which transport an already-received `ClientEvent` came in on (its `WS` member
    is the *local* tag `"ws"`); this one is the value the server's wire contract
    expects, matching `lzt_eventus.delivery.subscription.TransportKind` exactly.
    """

    WEBHOOK = "webhook"
    WEBSOCKET = "websocket"
    SSE = "sse"
    POLLING = "polling"


class EventType(StrEnum):
    """The full subscribable event catalog — mirrors `lzt_eventus.events.base.EventType`.
    Call `ManagementClient.list_event_types()` for the server's live catalog if
    this ever drifts (see the cross-repo wire-contract-sync rule in lzt-eventus's
    AGENTS.md — this list ships together with server-side additions)."""

    NEW_LOT = "new_lot"
    PRICE_DROPPED = "price_dropped"
    LOT_UPDATED = "lot_updated"
    LOT_DISAPPEARED = "lot_disappeared"
    SNAPSHOT_INITIALIZED = "snapshot_initialized"
    INCOME_RECEIVED = "income_received"
    EXPENSE_RECORDED = "expense_recorded"
    BALANCE_REFILLED = "balance_refilled"
    BALANCE_WITHDRAWN = "balance_withdrawn"
    ITEM_PURCHASED = "item_purchased"
    ITEM_SOLD = "item_sold"
    MONEY_TRANSFERRED = "money_transferred"
    MONEY_RECEIVED = "money_received"
    INTERNAL_PURCHASE = "internal_purchase"
    HOLD_CLAIMED = "hold_claimed"
    PAYOUT_REQUESTED = "payout_requested"
    AUTO_PAYMENT_TRIGGERED = "auto_payment_triggered"
    BALANCE_EXCHANGED = "balance_exchanged"
    TRANSFER_HELD = "transfer_held"
    TRANSFER_CANCELLED = "transfer_cancelled"
    INVOICE_CREATED = "invoice_created"
    INVOICE_PAID = "invoice_paid"
    INVOICE_EXPIRED = "invoice_expired"
    GUARANTEE_EXPIRING = "guarantee_expiring"
    ACCOUNT_INVALID = "account_invalid"
    DISPUTE_OPENED = "dispute_opened"
    CLAIM_FILED = "claim_filed"
    LOT_RESERVED = "lot_reserved"
    RESERVE_EXPIRED = "reserve_expired"
    PURCHASE_CONFIRMED = "purchase_confirmed"
    PURCHASE_CANCELLED = "purchase_cancelled"
    DEAL_DETECTED = "deal_detected"
    PRICE_VS_AI_CHANGED = "price_vs_ai_changed"
    INVENTORY_REVALUED = "inventory_revalued"
    DISCOUNT_REQUESTED = "discount_requested"
    DISCOUNT_APPROVED = "discount_approved"
    DISCOUNT_DECLINED = "discount_declined"
    NEW_CONVERSATION = "new_conversation"
    NEW_MESSAGE = "new_message"
    RATING_CHANGED = "rating_changed"
    MARKET_NOTIFICATION_RECEIVED = "market_notification_received"
    FORUM_NOTIFICATION_RECEIVED = "forum_notification_received"


class MarketCategory(StrEnum):
    """`category` on `CategoryScope` — mirrors `pylzt.types.Category` without
    depending on that package."""

    STEAM = "steam"
    DISCORD = "discord"
    FORTNITE = "fortnite"
    TELEGRAM = "telegram"
    RIOT = "riot"
    ROBLOX = "roblox"
    EPICGAMES = "epicgames"
    BATTLENET = "battlenet"
    EA = "ea"
    ESCAPEFROMTARKOV = "escapefromtarkov"
    GIFTS = "gifts"
    INSTAGRAM = "instagram"
    MINECRAFT = "minecraft"
    MIHOYO = "mihoyo"
    SOCIALCLUB = "socialclub"
    SUPERCELL = "supercell"
    TIKTOK = "tiktok"
    UPLAY = "uplay"
    VPN = "vpn"
    WARFACE = "warface"
    WOT = "wot"
    WOTBLITZ = "wotblitz"
    HYTALE = "hytale"
    LLM = "llm"
    VK = "vkontakte"
    OTHER = "other"
