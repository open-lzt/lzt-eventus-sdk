<p align="right"><b>English</b> · <a href="index.md">Русский</a></p>

# AI-agent docs — module map

Condensed pointer set for an agent working in this repo. Full narrative docs for humans live in
[`../../README.en.md`](../../README.en.md); this page exists so an agent doesn't have to
reverse-engineer the package from scratch.

## Public surface

Everything importable from the top level is in `src/lzt_eventus_sdk/__init__.py`'s `__all__` —
that is the stable contract; anything else is free to churn.

- [`client.py`](../../src/lzt_eventus_sdk/client.py) — `ManagementClient`, the async context-manager
  facade over the server's HTTP wire contract (`create_subscription`, `poll_pending`,
  `confirm_read`, `list_event_types`, `health`, ...).
- [`models.py`](../../src/lzt_eventus_sdk/models.py) — `NoScope` / `CategoryScope` / `AccountScope`
  (subscription filters), `PollingCtx` / `WebhookCtx` / `WebSocketCtx` / `SseCtx` (per-transport
  knobs), `PendingBatch`, `Subscription`.
- [`enums.py`](../../src/lzt_eventus_sdk/enums.py) — `SubscriptionTransport`, `EventType`,
  `MarketCategory` — `StrEnum`s mirroring the server's own enums by value.
- [`errors.py`](../../src/lzt_eventus_sdk/errors.py) — `ManagementApiError` root, typed subclasses
  per server error code (`SubscriptionNotFound`, `SubscriptionScopeMismatch`,
  `SubscriptionCtxMismatch`, ...), plus `ManagementApiConnectionError` for transport failures.
- [`signing.py`](../../src/lzt_eventus_sdk/signing.py) — `verify_webhook`, `SIGNATURE_HEADER` — HMAC
  verification for inbound webhook deliveries.
- `dispatch/` — `Dispatcher`, `Router`, `AccountContext`; `sources/` — `PollingSource`, `SseSource`,
  `WsSource` (behind the `[ws]` extra), `WebhookSource` — four transports normalized into one
  `ClientEvent` shape, routed through a shared dispatcher.
- `middleware/` — cross-cutting handler wrappers (idempotency, logging, error handling), same
  registration pattern as the transport middleware.
- `storage/` — `BaseCursorStore` / `BaseIdempotencyStore` ABCs + in-memory defaults, for a poller
  that needs to remember where it left off between runs.

## Wire-contract coupling — read before touching anything here

This SDK mirrors [`lzt-eventus`](https://github.com/open-lzt/lzt-eventus)'s management API
1:1 — `SubscriptionTransport`, `EventType`, `MarketCategory`, `scope`/`ctx` shapes. Any route/DTO
change on the server side needs a matching update here in the same change window — see the
server repo's `AGENTS.md` for the cross-repo sync rule. `tests/fixtures/api_captures.json` holds
real captured responses from a running server `TestClient`; re-capture it after any server-side
API change (see `CONTRIBUTING.md`).

## Architecture & scope

- [`../../README.en.md`](../../README.en.md) — quickstart, subscriptions, transports, examples.
- [`../architecture.en.md`](../architecture.en.md) — the event model, `Dispatcher`/`Router`/`sources`
  split, multi-account context injection, and the source-aware ack/retry policy.
