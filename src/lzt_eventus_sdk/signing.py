"""Webhook HMAC-SHA256 verification — standalone, matches `event_engine`'s own
signing scheme exactly (same header names, same `sha256=<hex>` format) without
depending on the (private) server package at all.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "X-LZT-Signature"
EVENT_ID_HEADER = "X-LZT-Event-Id"
EVENT_TYPE_HEADER = "X-LZT-Event-Type"
IDEMPOTENCY_HEADER = "Idempotency-Key"


def sign_webhook(secret: str, body: bytes) -> str:
    """Hex HMAC-SHA256 of `body` under `secret` (the value, sans scheme prefix)."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def signature_header(secret: str, body: bytes) -> str:
    """The full `X-LZT-Signature` value, e.g. `sha256=<hex>`."""
    return f"sha256={sign_webhook(secret, body)}"


def verify_webhook(secret: str, body: bytes, presented: str | None) -> bool:
    """`presented` is the raw `X-LZT-Signature` header value (`sha256=<hex>`)."""
    if not presented or not presented.startswith("sha256="):
        return False
    expected = sign_webhook(secret, body)
    return hmac.compare_digest(expected, presented[len("sha256=") :])
