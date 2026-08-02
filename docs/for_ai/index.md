<p align="right"><a href="index.en.md">English</a> · <b>Русский</b></p>

# Доки для AI-агентов — карта модулей

Сжатый набор указателей для агента, работающего в этом репозитории. Полные повествовательные
доки для людей — в [`../../README.md`](../../README.md); эта страница нужна, чтобы агенту не
пришлось реверс-инжинирить пакет с нуля.

## Публичная поверхность

Всё, что импортируется с верхнего уровня, перечислено в `__all__` файла
`src/lzt_eventus_sdk/__init__.py` — это стабильный контракт; всё остальное свободно меняется.

- [`client.py`](../../src/lzt_eventus_sdk/client.py) — `ManagementClient`, async
  context-manager фасад над HTTP wire-контрактом сервера (`create_subscription`,
  `poll_pending`, `confirm_read`, `list_event_types`, `health`, ...).
- [`models.py`](../../src/lzt_eventus_sdk/models.py) — `NoScope` / `CategoryScope` /
  `AccountScope` (фильтры подписки), `PollingCtx` / `WebhookCtx` / `WebSocketCtx` / `SseCtx`
  (настройки по транспорту), `PendingBatch`, `Subscription`.
- [`enums.py`](../../src/lzt_eventus_sdk/enums.py) — `SubscriptionTransport`, `EventType`,
  `MarketCategory` — `StrEnum`, зеркалящие собственные enum-ы сервера по значению.
- [`errors.py`](../../src/lzt_eventus_sdk/errors.py) — корень `ManagementApiError`, типизированные
  подклассы под каждый серверный код ошибки (`SubscriptionNotFound`,
  `SubscriptionScopeMismatch`, `SubscriptionCtxMismatch`, ...), плюс
  `ManagementApiConnectionError` для сбоев транспорта.
- [`signing.py`](../../src/lzt_eventus_sdk/signing.py) — `verify_webhook`, `SIGNATURE_HEADER` —
  HMAC-верификация входящих доставок вебхуков.
- `dispatch/` — `Dispatcher`, `Router`, `AccountContext`; `sources/` — `PollingSource`,
  `SseSource`, `WsSource` (за extra `[ws]`), `WebhookSource` — четыре транспорта, нормализованные
  в одну форму `ClientEvent`, роутятся через общий диспетчер.
- `middleware/` — сквозные обёртки хендлеров (идемпотентность, логирование, обработка ошибок), тот
  же паттерн регистрации, что и transport middleware.
- `storage/` — ABC `BaseCursorStore` / `BaseIdempotencyStore` + in-memory реализации по умолчанию,
  для поллера, которому нужно помнить, на чём он остановился между запусками.

## Связанность с wire-контрактом — прочитать перед тем, как что-либо здесь трогать

Этот SDK зеркалит management API [`lzt-eventus`](https://github.com/open-lzt/lzt-eventus) 1:1 —
`SubscriptionTransport`, `EventType`, `MarketCategory`, формы `scope`/`ctx`. Любое изменение
route/DTO на стороне сервера требует соответствующего обновления здесь, в том же окне изменений.
`tests/fixtures/api_captures.json` хранит реальные захваченные ответы от работающего серверного
`TestClient`; пересобирайте их после любого серверного изменения API (см. `CONTRIBUTING.md`).

## Архитектура и охват

- [`../../README.md`](../../README.md) — быстрый старт, подписки, транспорты, примеры.
- [`../architecture.md`](../architecture.md) — модель события, разделение
  `Dispatcher`/`Router`/`sources`, инжекция контекста по аккаунту и ack/retry-политика в
  зависимости от источника.
