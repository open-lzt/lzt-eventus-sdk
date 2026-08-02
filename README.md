<p align="right"><a href="README.en.md">English</a> · <b>Русский</b></p>

# lzt-eventus-sdk

Async-клиент к management API движка [lzt-eventus](https://github.com/open-lzt/lzt-eventus). Подписки, опрос событий, проверка подписи вебхука.

Сам движок здесь не живёт — этот пакет только разговаривает с ним по HTTP.

```python
from lzt_eventus_sdk import EventType, ManagementClient, SubscriptionTransport

client = ManagementClient("http://127.0.0.1:27543", api_key="<admin-key>")

sub = await client.create_subscription(
    transport=SubscriptionTransport.POLLING,
    endpoint="autobuy",
    event_types=[EventType.NEW_LOT, EventType.PRICE_DROPPED],
)
```

## Установка

```bash
pip install lzt-eventus-sdk         # базовый пакет
pip install "lzt-eventus-sdk[ws]"   # + websockets, нужен только для WSSource
```

Python 3.12+. Единственная рантайм-зависимость — `httpx>=0.27`.

## Какой транспорт брать

| Транспорт | Когда | Что нужно на вашей стороне |
|---|---|---|
| `POLLING` | по умолчанию, за NAT, без публичного адреса | ничего — вы сами ходите за событиями |
| `WEBHOOK` | у вас есть публичный HTTPS-эндпоинт | приёмник + проверка подписи |
| `SSE` | долгий однонаправленный поток в браузер или демон | держать соединение |
| `WEBSOCKET` | двусторонний канал | `[ws]` extra + держать соединение |

## Webhook: создать подписку

Секрет подписи возвращается **один раз** при создании — второй раз его не покажут, сохраните сразу.

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
print(sub.id, sub.secret)   # secret — только сейчас
```

## Webhook: приёмник

```python
from fastapi import FastAPI, Request, Response
from lzt_eventus_sdk import SIGNATURE_HEADER, verify_webhook

app = FastAPI()
SECRET = "<секрет из sub.secret>"


@app.post("/hook")
async def hook(request: Request) -> Response:
    body = await request.body()
    if not verify_webhook(SECRET, body, request.headers.get(SIGNATURE_HEADER)):
        return Response(status_code=401)
    ...
    return Response(status_code=204)
```

Заголовки — константы пакета, не строки в вашем коде: `SIGNATURE_HEADER` (`X-LZT-Signature`, формат `sha256=<hex>`), `EVENT_ID_HEADER`, `EVENT_TYPE_HEADER`, `IDEMPOTENCY_HEADER`.

## Polling: цикл

`confirm_read` идемпотентен — повторный вызов с тем же `up_to_seq` ничего не сдвинет и не сломает.

```python
batch = await client.poll_pending(sub.id, limit=100)

for item in batch.items:
    handle(item.event_type, item.data)

if batch.items:
    await client.confirm_read(sub.id, batch.items[-1].seq)
```

`PendingBatch` несёт `items`, `next_seq`, `last_read_seq`, `drained`, `committed` — по `drained` видно, кончилась ли очередь.

## Dispatcher и Router

Роутер раскладывает события по хендлерам, источник качает их из движка.

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

Готовые middleware: `ErrorBoundaryMiddleware` (не роняет цикл на ошибке хендлера), `IdempotencyMiddleware` (дедуп по id события), `LoggingMiddleware`. Свой — подкласс `BaseMiddleware`.

## Публичный API

| Что | Одна строка |
|---|---|
| `ManagementClient(base_url, api_key, *, timeout=10.0, httpx_client=None)` | клиент management API |
| `create_subscription(*, transport, endpoint, event_types, scope=None, ctx=None, backfill=False)` | создать подписку, вернёт `SubscriptionCreated` |
| `poll_pending(subscription_id, *, event_type=None, limit=100, read_all=False)` | забрать пачку событий |
| `confirm_read(subscription_id, up_to_seq)` | подтвердить прочитанное, вернёт подтверждённый `last_seq` |
| `get_subscription` · `list_subscriptions` · `deactivate_subscription` | чтение и отключение подписок |
| `verify_webhook(secret, body, presented)` · `sign_webhook` · `signature_header` | подпись и её проверка |
| `SubscriptionTransport` · `EventType` · `MarketCategory` | `StrEnum` вместо строковых литералов |
| `NoScope` · `CategoryScope(category=...)` · `AccountScope(account_alias=...)` | во что сузить подписку |
| `Dispatcher` · `Router` · `AccountContext` | раскладка событий по хендлерам |
| `PollingSource` · `SSESource` · `WSSource` · `WebhookReceiver` | четыре источника событий |
| `MemoryStorage` · `CursorStore` · `IdempotencyStore` | курсор и дедуп; свой бэкенд — подкласс `BaseStorage` |

Переменных окружения пакет не читает: всё передаётся в конструктор.

## Разработка

```bash
pip install "lzt-eventus-sdk[dev]"
ruff check . && mypy src/lzt_eventus_sdk && pytest -q
```

Тесты гоняются на записанных ответах движка (`tests/fixtures/`), живой инстанс не нужен.

## Экосистема

[lzt-eventus](https://github.com/open-lzt/lzt-eventus) — сам движок · [pylzt](https://github.com/open-lzt/pylzt) — SDK маркета · [auto-lzt](https://github.com/open-lzt/auto-lzt) — no-code автоматизации · [весь стенд](https://github.com/open-lzt/open-lzt)

## Лицензия

[MIT](LICENSE)
