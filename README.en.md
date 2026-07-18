<p align="right"><b>English</b> · <a href="README.md">Русский</a></p>

<h1 align="center">lzt-eventus-sdk</h1>

<p align="center">
  <strong>Async Python client for lzt-eventus's event_engine management API — subscribe, poll, verify.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/lzt-eventus-sdk/"><img src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="License"></a>
</p>

**lzt-eventus-sdk** is the httpx-only client half of [`lzt-eventus`](https://github.com/open-lzt/lzt-eventus)
— a self-hosted event engine over the lzt.market catalog. Install this alone to subscribe, poll,
or verify webhooks from that engine; it pulls in no Postgres, Redis, or FastAPI.

[Architecture](docs/architecture.en.md) · [AI-agent docs](docs/for_ai/index.en.md) ·
[lzt-eventus (server)](https://github.com/open-lzt/lzt-eventus) ·
[Issues](https://github.com/open-lzt/lzt-eventus-sdk/issues/new/choose)

## Why this exists

`event_engine` (the server) is a full event-sourcing daemon — durable append log, cursor
tracking, DLQ, webhook signing, Postgres, the works. A **consumer** of that engine (a webhook
receiver on a different host, a cron poller, an admin panel) needs none of that. Installing the
whole engine just to call `POST /subscriptions/create` would drag in dependencies you'll never
use. This package is the other half: talk to the engine over its HTTP wire contract only.

## Quickstart

```bash
pip install lzt-eventus-sdk
```

```python
import asyncio

from lzt_eventus_sdk import (
    CategoryScope,
    EventType,
    ManagementClient,
    MarketCategory,
    SubscriptionTransport,
)


async def main() -> None:
    async with ManagementClient("https://engine.example", api_key="<LZT_ADMIN_API_KEY>") as mgmt:
        sub = await mgmt.create_subscription(
            transport=SubscriptionTransport.WEBHOOK,
            endpoint="https://you.example/hook",
            event_types=[EventType.NEW_LOT, EventType.PRICE_DROPPED],
            scope=CategoryScope(category=MarketCategory.STEAM),
        )
        print(sub.subscription_id, sub.secret)  # secret is one-time — save it now


asyncio.run(main())
```

Enums everywhere a raw string would otherwise invite a typo the server only catches at request
time: `SubscriptionTransport`, `EventType` (the full subscribable catalog), `MarketCategory`.
They're plain `StrEnum` — pass one where a `str` is expected and it just works, no `.value`
needed. For the full subscription/scope/transport reference, see [below](#subscriptions).

## Examples

Three non-overlapping ways to actually *do something* with an event, not just print it — each
pairs this SDK (receive the event) with [`pylzt`](https://github.com/open-lzt/pylzt) (act on
it). Full runnable scripts.

### Poll-based autobuy — no public endpoint to expose

Take when you'd rather pull than receive a push (behind a firewall, easier to run from cron). No
webhook secret to mint or verify; the subscription tracks its own cursor.

```python
import asyncio
from decimal import Decimal

from pylzt import Client
from pylzt.types import Category, ItemId

from lzt_eventus_sdk import CategoryScope, EventType, ManagementClient, SubscriptionTransport

BUDGET = Decimal("50")
MAX_PURCHASES = 3


async def main() -> None:
    async with (
        Client(tokens=["<lzt-market-token>"]) as market,
        ManagementClient("https://engine.example", api_key="<LZT_ADMIN_API_KEY>") as mgmt,
    ):
        sub = await mgmt.create_subscription(
            transport=SubscriptionTransport.POLLING,
            endpoint="autobuy-worker",
            event_types=[EventType.NEW_LOT],
            scope=CategoryScope(category=Category.TELEGRAM),
        )
        bought = 0
        while bought < MAX_PURCHASES:
            batch = await mgmt.poll_pending(sub.subscription_id, limit=100)
            for event in batch.items:
                lot = event.data["lot"]
                if Decimal(str(lot["price"])) <= BUDGET:
                    await market.market.purchasing_fast_buy(
                        item_id=ItemId(lot["item_id"]), price=lot["price"]
                    )
                    bought += 1
            if batch.items:
                await mgmt.confirm_read(sub.subscription_id, up_to_seq=batch.next_seq)
            else:
                await asyncio.sleep(5.0)


asyncio.run(main())
```

### Webhook receiver — post a chat alert on a price drop

Take when you have a public endpoint to expose and want push delivery (catch-up + retry + DLQ on
the server side, not your responsibility). Verify the signature before trusting the body.

```python
from fastapi import FastAPI, Request, Response
from pylzt import Client

from lzt_eventus_sdk import SIGNATURE_HEADER, verify_webhook

app = FastAPI()
SECRET = "<the secret from create_subscription>"
market = Client(tokens=["<lzt-market-token>"])


@app.post("/hook")
async def hook(request: Request) -> Response:
    body = await request.body()
    if not verify_webhook(secret=SECRET, body=body, presented=request.headers.get(SIGNATURE_HEADER)):
        return Response(status_code=401)
    event = await request.json()
    lot = event["data"]["lot"]
    await market.forum.chatbox_post_message(
        room_id=1, message=f"price drop: {lot['title']} now {lot['price']}"
    )
    return Response(status_code=200)  # 2xx acks; non-2xx is retried -> DLQ
```

### Multi-transport dispatcher — swap webhook/SSE/WS/polling without touching handler code

Take when you want the same handler logic to run under different transports (dev on polling,
prod on webhook) or want several sources feeding one router.

```python
from lzt_eventus_sdk import (
    AccountContext,
    Dispatcher,
    EventType,
    PollingConfig,
    PollingSource,
    Router,
)

router = Router()


@router.on(EventType.NEW_LOT)
async def on_new_lot(event) -> None:
    print(event.event_type, event.data)


dispatcher = Dispatcher(router)
ctx = AccountContext(client=mgmt, subscription_id=sub.subscription_id, label="main")
await PollingSource(ctx, config=PollingConfig()).run(dispatcher)
```

`WSSource` needs the `[ws]` extra (`pip install lzt-eventus-sdk[ws]`) — import it explicitly
from `lzt_eventus_sdk.sources.ws` so a core install never fails on missing `websockets`.

## Subscriptions

`scope` narrows what a subscription actually receives:

| Scope | Matches |
|---|---|
| `NoScope()` *(default)* | Everything requested in `event_types` |
| `CategoryScope(category=MarketCategory.STEAM)` | Catalog events for one category |
| `AccountScope(account_alias="my-alias")` | One account's per-account events (e.g. `RATING_CHANGED`) |

A scope that can never match any of `event_types` — a category scope on `RATING_CHANGED`, say —
is rejected at creation with `SubscriptionScopeMismatch`, not silently accepted into a
subscription that will never fire.

`ctx` carries per-transport knobs, keyed by `transport`:

| Transport | Ctx | Notable field |
|---|---|---|
| `SubscriptionTransport.POLLING` | `PollingCtx` | `poll_delay_seconds` — long-poll wait on an empty `/events/pending` batch |
| `SubscriptionTransport.WEBHOOK` | `WebhookCtx` | — |
| `SubscriptionTransport.WEBSOCKET` | `WebSocketCtx` | — |
| `SubscriptionTransport.SSE` | `SseCtx` | — |

Omit `ctx` for the transport's empty default. A `ctx.kind` that doesn't match `transport` raises
`SubscriptionCtxMismatch`.

```python
await mgmt.create_subscription(
    transport=SubscriptionTransport.POLLING,
    endpoint="my-poller",
    event_types=[EventType.NEW_LOT],
    scope=NoScope(),
    ctx=PollingCtx(poll_delay_seconds=5.0),
    backfill=False,
)
await mgmt.list_subscriptions(limit=50, offset=0, active_only=False)
await mgmt.get_subscription(subscription_id)
await mgmt.update_subscription(subscription_id, event_types=None, scope=None, active=None)
await mgmt.deactivate_subscription(subscription_id)
await mgmt.list_event_types()   # the full subscribable EventType catalog, live from the server
await mgmt.health()             # bool — GET /healthz
```

## Errors

Every non-2xx response raises a typed `ManagementApiError` subclass — never a bare `httpx`
exception — carrying the server's `code` / `detail` / `request_id`:

```python
from lzt_eventus_sdk import SubscriptionNotFound

try:
    await mgmt.get_subscription("does-not-exist")
except SubscriptionNotFound as e:
    print(e.status, e.code, e.detail)  # 404 subscription_not_found {"subscription_id": "..."}
```

A connection failure (timeout, DNS, refused) raises `ManagementApiConnectionError` — also a
`ManagementApiError`, so a broad `except ManagementApiError` catches everything.

## Testing

`tests/fixtures/api_captures.json` holds real responses captured from a running `event_engine`
`TestClient` — not hand-written guesses. Re-capture after any server-side API change (see
`CONTRIBUTING.md`).

## Versioning & compatibility

This SDK tracks `lzt-eventus`'s management API wire contract 1:1 — `SubscriptionTransport`,
`EventType`, `MarketCategory`, and the `scope`/`ctx` shapes mirror the server's own enums and
DTOs by value. If you change a route/DTO in `lzt-eventus/src/lzt_eventus/web/`, this repo needs a
matching update in the same change — see `lzt-eventus`'s `AGENTS.md` / `CLAUDE.md` for the
cross-repo sync rule.

`.github/workflows/publish.yml` builds and publishes to PyPI on push to `master` via Trusted
Publishing (OIDC, no stored token) — **disabled by default**, gated behind the
`PYPI_PUBLISH_ENABLED` repo variable.

## Community

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and how to submit PRs. Use
[issues](https://github.com/open-lzt/lzt-eventus-sdk/issues/new/choose) for bugs and feature
requests.

<a href="https://github.com/zlexdev"><img src="https://github.com/zlexdev.png" width="48" height="48" style="border-radius:50%" alt="zlexdev"></a>

## License

[MIT](LICENSE) © 2026 zlexdev
