<p align="right"><b>English</b> · <a href="README.md">Русский</a></p>

# lzt-eventus-sdk

Async client for the management API of the [lzt-eventus](https://github.com/open-lzt/lzt-eventus) engine. Subscriptions, event polling, webhook signature verification.

The engine itself doesn't live here — this package only talks to it over HTTP.

```python
from lzt_eventus_sdk import EventType, ManagementClient, SubscriptionTransport

client = ManagementClient("http://127.0.0.1:27543", api_key="<admin-key>")

sub = await client.create_subscription(
    transport=SubscriptionTransport.POLLING,
    endpoint="autobuy",
    event_types=[EventType.NEW_LOT, EventType.PRICE_DROPPED],
)
```

## Install

```bash
pip install lzt-eventus-sdk         # base package
pip install "lzt-eventus-sdk[ws]"   # + websockets, needed only for WSSource
```

Python 3.12+. The only runtime dependency is `httpx>=0.27`.

## Which transport

| Transport | When | What it costs you |
|---|---|---|
| `POLLING` | default, behind NAT, no public address | you fetch events yourself |
| `WEBHOOK` | you have a public HTTPS endpoint | a receiver + signature check |
| `SSE` | a long one-way stream into a browser or daemon | hold the connection |
| `WEBSOCKET` | two-way channel | the `[ws]` extra + hold the connection |

## Webhook: create a subscription

The signing secret is returned **once**, at creation — it is never shown again, store it right away.

```python
from lzt_eventus_sdk import CategoryScope, EventType, ManagementClient, SubscriptionTransport

client = ManagementClient("http://127.0.0.1:27543", api_key="<admin-key>")

sub = await client.create_subscription(
    transport=SubscriptionTransport.WEBHOOK,
    endpoint="https://you.example/hook",
    event_types=[EventType.NEW_LOT],
    scope=CategoryScope(category="steam"),
    backfill=False,
)
print(sub.id, sub.secret)   # secret — only now
```

## Webhook: receiver

```python
from fastapi import FastAPI, Request, Response
from lzt_eventus_sdk import SIGNATURE_HEADER, verify_webhook

app = FastAPI()
SECRET = "<the secret from sub.secret>"


@app.post("/hook")
async def hook(request: Request) -> Response:
    body = await request.body()
    if not verify_webhook(SECRET, body, request.headers.get(SIGNATURE_HEADER)):
        return Response(status_code=401)
    ...
    return Response(status_code=204)
```

Headers are package constants, not string literals in your code: `SIGNATURE_HEADER` (`X-LZT-Signature`, format `sha256=<hex>`), `EVENT_ID_HEADER`, `EVENT_TYPE_HEADER`, `IDEMPOTENCY_HEADER`.

## Polling loop

`confirm_read` is idempotent — calling it again with the same `up_to_seq` moves nothing and breaks nothing.

```python
batch = await client.poll_pending(sub.id, limit=100)

for item in batch.items:
    handle(item.event_type, item.data)

if batch.items:
    await client.confirm_read(sub.id, batch.items[-1].seq)
```

`PendingBatch` carries `items`, `next_seq`, `last_read_seq`, `drained`, `committed` — `drained` tells you whether the queue is empty.

## Dispatcher and Router

The router fans events out to handlers, the source pulls them from the engine.

```python
import asyncio

from lzt_eventus_sdk import AccountContext, Dispatcher, EventType, Router
from lzt_eventus_sdk.sources import PollingSource

router = Router()


@router.on(EventType.NEW_LOT)
async def on_new_lot(event) -> None:
    print(event.data["item_id"])


dispatcher = Dispatcher(router)
source = PollingSource(AccountContext(client, sub.id, label="main"))

asyncio.run(dispatcher.run(source))
```

Middleware included: `ErrorBoundaryMiddleware` (a failing handler doesn't kill the loop), `IdempotencyMiddleware` (dedup by event id), `LoggingMiddleware`. Your own — subclass `BaseMiddleware`.

## Public API

| What | One line |
|---|---|
| `ManagementClient(base_url, api_key, *, timeout=10.0, httpx_client=None)` | management API client |
| `create_subscription(*, transport, endpoint, event_types, scope=None, ctx=None, backfill=False)` | create a subscription, returns `SubscriptionCreated` |
| `poll_pending(subscription_id, *, event_type=None, limit=100, read_all=False)` | fetch a batch of events |
| `confirm_read(subscription_id, up_to_seq)` | confirm progress, returns the committed `last_seq` |
| `get_subscription` · `list_subscriptions` · `deactivate_subscription` | read and deactivate subscriptions |
| `verify_webhook(secret, body, presented)` · `sign_webhook` · `signature_header` | signing and verification |
| `SubscriptionTransport` · `EventType` · `MarketCategory` | `StrEnum` instead of string literals |
| `NoScope` · `CategoryScope(category=...)` · `AccountScope(account_alias=...)` | how to narrow a subscription |
| `Dispatcher` · `Router` · `AccountContext` | fan events out to handlers |
| `PollingSource` · `SSESource` · `WSSource` · `WebhookReceiver` | four event sources |
| `MemoryStorage` · `CursorStore` · `IdempotencyStore` | cursor and dedup; your own backend — subclass `BaseStorage` |

The package reads no environment variables: everything goes through the constructor.

## Development

```bash
pip install "lzt-eventus-sdk[dev]"
ruff check . && mypy src/lzt_eventus_sdk && pytest -q
```

Tests run against recorded engine responses (`tests/fixtures/`) — no live instance needed.

## Ecosystem

[lzt-eventus](https://github.com/open-lzt/lzt-eventus) — the engine itself · [pylzt](https://github.com/open-lzt/pylzt) — market SDK · [auto-lzt](https://github.com/open-lzt/auto-lzt) — no-code automation · [the whole stand](https://github.com/open-lzt/open-lzt)

## License

[MIT](LICENSE)
