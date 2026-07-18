<p align="right"><a href="README.en.md">English</a> · <b>Русский</b></p>

<h1 align="center">lzt-eventus-sdk</h1>

<p align="center">
  <strong>Асинхронный Python-клиент для management API event_engine из lzt-eventus — подписка, поллинг, верификация.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/lzt-eventus-sdk/"><img src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="License"></a>
</p>

**lzt-eventus-sdk** — это httpx-only клиентская половина [`lzt-eventus`](https://github.com/open-lzt/lzt-eventus)
— self-hosted движка событий поверх каталога lzt.market. Ставьте только этот пакет, чтобы
подписываться, поллить или верифицировать вебхуки этого движка; он не тянет за собой ни
Postgres, ни Redis, ни FastAPI.

[Архитектура](docs/architecture.md) · [Доки для AI-агентов](docs/for_ai/index.md) ·
[lzt-eventus (сервер)](https://github.com/open-lzt/lzt-eventus) ·
[Issues](https://github.com/open-lzt/lzt-eventus-sdk/issues/new/choose)

## Зачем это нужно

`event_engine` (сервер) — это полноценный event-sourcing демон: durable append log, отслеживание
курсоров, DLQ, подпись вебхуков, Postgres — всё как полагается. **Потребителю** этого движка
(вебхук-приёмнику на другом хосте, cron-поллеру, админ-панели) ничего из этого не нужно. Ставить
весь движок только ради вызова `POST /subscriptions/create` означало бы тащить зависимости,
которые вы никогда не используете. Этот пакет — вторая половина: общение с движком только через
его HTTP wire-контракт.

## Быстрый старт

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

Enum-ы там, где обычная строка провоцирует опечатку, которую сервер поймает только в момент
запроса: `SubscriptionTransport`, `EventType` (полный подписываемый каталог), `MarketCategory`.
Это обычные `StrEnum` — передавайте их там, где ожидается `str`, и всё просто работает, `.value`
не нужен. Полный справочник по subscription/scope/transport — [ниже](#подписки).

## Примеры

Три непересекающихся способа реально *сделать что-то* с событием, а не просто напечатать его —
каждый сочетает этот SDK (принять событие) с [`pylzt`](https://github.com/open-lzt/pylzt)
(действовать по нему). Полные рабочие скрипты.

### Автобай на поллинге — без публичного эндпоинта

Берите, если предпочитаете именно опрашивать сервер, а не принимать пуш (за файрволом, проще
запускать из cron). Не нужно ни минтить, ни верифицировать вебхук-секрет; подписка сама
отслеживает свой курсор.

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

### Вебхук-приёмник — постит алерт в чат при падении цены

Берите, если у вас есть публичный эндпоинт и вы хотите push-доставку (докатка + retry + DLQ на
стороне сервера — не ваша забота). Верифицируйте подпись прежде, чем доверять телу запроса.

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

### Мультитранспортный диспетчер — меняем webhook/SSE/WS/polling, не трогая код хендлеров

Берите, если хотите, чтобы одна и та же логика хендлера работала под разными транспортами (dev на
поллинге, prod на вебхуке), или если несколько источников должны питать один роутер.

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

`WSSource` требует extra `[ws]` (`pip install lzt-eventus-sdk[ws]`) — импортируйте его явно из
`lzt_eventus_sdk.sources.ws`, чтобы базовая установка никогда не падала из-за отсутствия
`websockets`.

## Подписки

`scope` сужает то, что подписка реально получает:

| Scope | Что матчит |
|---|---|
| `NoScope()` *(по умолчанию)* | Всё, что запрошено в `event_types` |
| `CategoryScope(category=MarketCategory.STEAM)` | Каталожные события одной категории |
| `AccountScope(account_alias="my-alias")` | Персональные события одного аккаунта (например, `RATING_CHANGED`) |

Scope, который в принципе не может совпасть ни с одним из `event_types` — например, category
scope для `RATING_CHANGED` — отклоняется при создании подписки с ошибкой
`SubscriptionScopeMismatch`, а не молча принимается в подписку, которая никогда не сработает.

`ctx` несёт специфичные для транспорта настройки, ключ — `transport`:

| Transport | Ctx | Примечательное поле |
|---|---|---|
| `SubscriptionTransport.POLLING` | `PollingCtx` | `poll_delay_seconds` — long-poll ожидание при пустом батче `/events/pending` |
| `SubscriptionTransport.WEBHOOK` | `WebhookCtx` | — |
| `SubscriptionTransport.WEBSOCKET` | `WebSocketCtx` | — |
| `SubscriptionTransport.SSE` | `SseCtx` | — |

Не передавайте `ctx`, чтобы использовать значение по умолчанию для транспорта. Если `ctx.kind`
не совпадает с `transport`, будет выброшено `SubscriptionCtxMismatch`.

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

## Ошибки

Каждый не-2xx ответ выбрасывает типизированный подкласс `ManagementApiError` — никогда не голое
исключение `httpx` — несущий `code` / `detail` / `request_id` сервера:

```python
from lzt_eventus_sdk import SubscriptionNotFound

try:
    await mgmt.get_subscription("does-not-exist")
except SubscriptionNotFound as e:
    print(e.status, e.code, e.detail)  # 404 subscription_not_found {"subscription_id": "..."}
```

Ошибка соединения (таймаут, DNS, отказ) выбрасывает `ManagementApiConnectionError` — тоже
`ManagementApiError`, так что широкий `except ManagementApiError` ловит всё.

## Тестирование

`tests/fixtures/api_captures.json` хранит реальные ответы, захваченные с работающего
`event_engine` `TestClient` — а не написанные вручную догадки. Пересобирайте фикстуры после
любого изменения серверного API (см. `CONTRIBUTING.md`).

## Версионирование и совместимость

Этот SDK отслеживает management API wire-контракт `lzt-eventus` 1:1 — `SubscriptionTransport`,
`EventType`, `MarketCategory`, а формы `scope`/`ctx` зеркалят собственные enum-ы и DTO сервера по
значению. Если вы меняете route/DTO в `lzt-eventus/src/lzt_eventus/web/`, этому репозиторию
нужно соответствующее обновление в том же изменении — правило синхронизации между репозиториями
см. в `AGENTS.md` / `CLAUDE.md` `lzt-eventus`.

`.github/workflows/publish.yml` собирает и публикует пакет в PyPI при пуше в `master` через
Trusted Publishing (OIDC, без хранимого токена) — **по умолчанию отключено**, включается через
переменную репозитория `PYPI_PUBLISH_ENABLED`.

## Сообщество

Правила и порядок отправки PR — в [CONTRIBUTING.md](CONTRIBUTING.md). Для багов и предложений
используйте [issues](https://github.com/open-lzt/lzt-eventus-sdk/issues/new/choose).

<a href="https://github.com/zlexdev"><img src="https://github.com/zlexdev.png" width="48" height="48" style="border-radius:50%" alt="zlexdev"></a>

## Лицензия

[MIT](LICENSE) © 2026 zlexdev
