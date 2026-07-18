from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import UTC, datetime
from typing import Any

from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.dispatcher import Dispatcher
from lzt_eventus_sdk.dispatch.result import DispatchOutcome
from lzt_eventus_sdk.events.event import ClientEvent, TransportKind
from lzt_eventus_sdk.signing import (
    EVENT_ID_HEADER,
    EVENT_TYPE_HEADER,
    IDEMPOTENCY_HEADER,
    SIGNATURE_HEADER,
    verify_webhook,
)

# ASGI's protocol types are inherently untyped mappings (no ASGI typing lib
# dependency here) — this `Any` is the unavoidable boundary with the ASGI spec.
# `MutableMapping`, not `dict`, matches the ASGI callable signature every real
# server (uvicorn, httpx.ASGITransport) actually types against.
Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

SecretResolver = Callable[[str], Awaitable[str | None]]
AccountResolver = Callable[[str], Awaitable[AccountContext | None]]

_DEFAULT_MAX_BODY_BYTES = 1_048_576
_SUBSCRIPTION_ID_PATTERN = re.compile(r"/(?P<subscription_id>[^/]+)/?$")

_HANDLED_OUTCOMES = frozenset(
    {DispatchOutcome.HANDLED, DispatchOutcome.SKIPPED, DispatchOutcome.DUPLICATE}
)

_logger = logging.getLogger(__name__)


def _header_map(raw_headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in raw_headers}


def _json_body(code: str, detail: str) -> bytes:
    return json.dumps({"error": code, "detail": detail}).encode()


async def _read_body(receive: Receive, max_bytes: int) -> tuple[bytes, bool]:
    """Returns `(body, oversize)`. Reads with a hard cap so an unbounded body
    can never be buffered into memory (the OOM vector D4/plan flags)."""
    chunks: list[bytes] = []
    total = 0
    more_body = True
    while more_body:
        message = await receive()
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > max_bytes:
            return b"", True
        chunks.append(chunk)
        more_body = message.get("more_body", False)
    return b"".join(chunks), False


class WebhookReceiver:
    """Pure-ASGI inbound app (D4) — zero web-framework dependency. Mount under
    `/hook/{subscription_id}`: the trailing path segment resolves which
    secret/account to use, since the signed headers never carry a
    subscription id (verified-by-code against the real server, Q1).

    Status mapping (D6, mirrors the server's own retry contract —
    5xx/408/429 retry, other 4xx terminal):
    handled/skipped/duplicate -> 200, bad signature -> 401,
    malformed/oversize -> 400/413, handler raised -> 503 (redeliver).
    """

    def __init__(
        self,
        dispatcher: Dispatcher,
        *,
        secret_resolver: SecretResolver,
        account_resolver: AccountResolver,
        max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._dispatcher = dispatcher
        self._secret_resolver = secret_resolver
        self._account_resolver = account_resolver
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            raise ValueError(
                f"WebhookReceiver only handles ASGI 'http' scope, got {scope['type']!r}"
            )

        status, body = await self._handle(scope, receive)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _handle(self, scope: Scope, receive: Receive) -> tuple[int, bytes]:
        path = str(scope.get("path", ""))
        match = _SUBSCRIPTION_ID_PATTERN.search(path)
        if match is None:
            return 400, _json_body("bad_request", "no subscription id in path")
        subscription_id = match.group("subscription_id")

        raw_body, oversize = await _read_body(receive, self._max_body_bytes)
        if oversize:
            return 413, _json_body("payload_too_large", "request body exceeds max_body_bytes")

        secret = await self._secret_resolver(subscription_id)
        if secret is None:
            return 401, _json_body("unauthorized", "unknown subscription")

        headers = _header_map(scope.get("headers", []))
        presented = headers.get(SIGNATURE_HEADER.lower())
        if not verify_webhook(secret, raw_body, presented):
            return 401, _json_body("unauthorized", "signature verification failed")

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return 400, _json_body("bad_request", "malformed JSON body")

        account = await self._account_resolver(subscription_id)
        if account is None:
            return 401, _json_body("unauthorized", "unknown subscription")

        try:
            event = ClientEvent(
                seq=int(body["seq"]),
                event_type=headers.get(EVENT_TYPE_HEADER.lower()) or str(body["event_type"]),
                data=dict(body.get("data", {})),
                transport=TransportKind.WEBHOOK,
                received_at=datetime.now(UTC),
                event_id=headers.get(EVENT_ID_HEADER.lower()),
                idempotency_key=headers.get(IDEMPOTENCY_HEADER.lower()),
            )
        except (KeyError, TypeError, ValueError):
            return 400, _json_body("bad_request", "malformed event body")

        try:
            # Filter/outer-middleware exceptions must map to the same retry-safe
            # 503 as a handler-body error, not leak a raw traceback to the ASGI
            # boundary (handler-body errors are already caught inside dispatch
            # and turned into ERRORED; this is the outer-boundary guard for
            # everything dispatch itself doesn't catch).
            result = await self._dispatcher.feed(event, account)
        except Exception:
            _logger.exception(
                "unhandled exception in dispatcher.feed",
                extra={"subscription_id": subscription_id},
            )
            return 503, _json_body("handler_error", "handler raised; retry")

        if result.outcome in _HANDLED_OUTCOMES:
            return 200, b'{"ok":true}'
        return 503, _json_body("handler_error", "handler raised; retry")

    def as_starlette_route(self, path: str = "/hook/{subscription_id}") -> Any:
        """Optional adapter for Starlette-based hosts. Soft-imports starlette —
        no `[server]` extra exists (D4); pin starlette in your own app if you
        use this helper."""
        try:
            from starlette.routing import Mount  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "as_starlette_route() requires starlette to be installed in your "
                "app (lzt-eventus-sdk itself has no such dependency)"
            ) from exc
        return Mount(path, app=self)
