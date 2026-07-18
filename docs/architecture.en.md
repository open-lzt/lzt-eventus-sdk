<p align="right"><b>English</b> · <a href="architecture.md">Русский</a></p>

# Architecture

`lzt_eventus_sdk` grows from "REST client + webhook-signature verifier" into a small
aiogram-style event-consumer framework: one `Dispatcher` fed by four pluggable transports
(polling, webhook, SSE, WS), a nestable `Router` tree, an outer/inner middleware chain, and
generic K/V storage for dedup + resumable cursors — without depending on or vendoring the
private `evented`/`wsflow` libraries. Same shape, sized to this SDK.

```
management API (lzt-eventus)
        │
        ▼
   ┌─────────┐   normalize wire frame    ┌────────────┐    feed(event, ctx)   ┌──────────────┐
   │ sources/ │ ─────────────────────▶  │ ClientEvent │ ──────────────────▶  │  Dispatcher   │
   │ polling  │                          └────────────┘                       │  + Router     │
   │ webhook  │                                                                │  + middleware │
   │ sse / ws │                                                                └───────┬───────┘
   └─────────┘                                                                          │
                                                                                          ▼
                                                                                     your handlers
```

## 1. Event model — generic event, opt-in typed registry

The server's `EventType` catalog is open and growing. A closed client-side subclass-per-type
hierarchy would crash on any event type the server adds before the SDK catches up. Instead:
dispatch keys on the `event_type` **string** (aiogram keys on update type the same way); a
`ClientEvent` base carries `seq`/`event_type`/`data`/metadata; consumers who want typing
register a payload model against `PayloadRegistry` (`events.register("new_lot")`), resolved
lazily. An unknown type falls back to the base `ClientEvent`, never an error — forward
compatibility wins over exhaustive typing.

## 2. One `Dispatcher.feed()` entrypoint — transports are dumb sources

Every transport normalizes its wire frame to a `ClientEvent` and calls the *same*
`Dispatcher.feed(event, ctx)`. There is no per-transport dispatch path — a handler registered
once receives events regardless of which transport delivered them. Transports differ only in
acquisition and ack semantics (§4).

## 3. Multi-account — shared Dispatcher, per-account context injected

One `Router` tree and one middleware chain are shared across every account. Each source is
bound to an `AccountContext` (`ManagementClient` + `subscription_id` + label + stream
credential). On `feed`, that context is injected into the middleware `data` dict, so a handler
reads `data["client"]` (the right account's client — e.g. to call `confirm_read`) and
`data["subscription_id"]`. This is aiogram's `bot`-injection pattern.

## 4. Transports (`sources/`)

| Source | Needs | Ack / resume |
|---|---|---|
| `PollingSource` | `httpx` only, reuses the existing REST client | `confirm_read(up_to_seq)` after successful dispatch |
| `SSESource` | `httpx` streaming | `Last-Event-ID` resume via `CursorStore` |
| `WSSource` (`[ws]` extra) | `websockets` | Auth frame `{subscription_id, token, last_seq}`, resume from `last_seq` |
| `WebhookReceiver` (`server/`) | pure ASGI, no framework dep | Server-side retry contract (below) |

All four run under a `SourceSupervisor` — backoff-restart on failure, so one flaky transport
doesn't take the process down.

**Webhook receiver is pure ASGI on purpose.** Pulling in FastAPI/Starlette would drag a web
framework into a client library. A pure-ASGI callable is a few dozen lines, adds no
dependency, keeps `pip install lzt-eventus-sdk` httpx-only, and still mounts natively into any
FastAPI/Starlette app via `app.mount(...)`.

**Error/ack policy is source-aware, wired to the server's retry contract.** Server webhook
delivery treats 5xx/408/429 as retryable and other 4xx as terminal. So `ErrorBoundaryMiddleware`
maps a handler exception on the **webhook** source to `503` (server redelivers; idempotency
dedup guards double-processing); on **SSE/WS/polling** it logs and does not advance the cursor
past the failed `seq` (redelivered on reconnect/next poll). A bad signature is `401`
(terminal — never self-heals); a malformed body is `400` (terminal); a dedup hit is `200`.

## 5. Storage — two façades over one `BaseStorage[K, V]`

Dedup keys and resumable `last_seq` cursors are both K/V. `IdempotencyStore` and `CursorStore`
are thin façades over one `BaseStorage[K, V]` ABC (`MemoryStorage` ships as the default), so a
single future backend serves both. The cursor shape mirrors the server's own cursor store
(`last_seq` per consumer) but stays client-local — a restart resumes SSE/WS/polling from where
it left off.

## 6. Middleware (`middleware/`)

An outer/inner chain, same shape as the transport middleware on the server side:
`LoggingMiddleware`, `ErrorBoundaryMiddleware` (§4's ack policy), `IdempotencyMiddleware`
(dedup via `IdempotencyStore` before a handler ever runs).

## 7. Escape hatch — bypass the Dispatcher entirely

Every `BaseSource` exposes `stream()` — a raw `async for event in source.stream()` iterator
that skips routing entirely. A consumer who distrusts the framework can drive events manually
while still reusing the reconnect/cursor machinery; `Dispatcher.feed()` is just the default
consumer of `stream()`.

## Package / dependency structure (extras)

| Install | Adds dep | Enables |
|---|---|---|
| `lzt-eventus-sdk` (core) | `httpx` only | REST client, signing, events, dispatch, middleware, memory storage, polling source, SSE source (httpx streaming), webhook receiver (pure ASGI) |
| `lzt-eventus-sdk[ws]` | `websockets>=12` | `WSSource` (httpx has no WS client) |

SSE and the webhook receiver need no new dependency (httpx streams; pure-ASGI mounts into the
consumer's own server) — WebSockets is the only transport that forces one, so it's the only
mandatory extra.

## Pattern names

Router-tree + Observer (dispatch) · Chain-of-Responsibility (middleware) · Adapter (each source
normalizes its wire shape) · Supervisor + retry-with-backoff (`SourceSupervisor`) ·
Idempotency-Key dedup · Resumable-Cursor (checkpoint) · Strategy (source-aware ack policy).
