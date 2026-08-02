<p align="right"><a href="CONTRIBUTING.en.md">English</a> · <b>Русский</b></p>

# Контрибуция в lzt-eventus-sdk

Спасибо за помощь. Это тонкий клиент на одном httpx. Python 3.12, менеджер — [uv](https://docs.astral.sh/uv/).

## Установка

```bash
git clone https://github.com/open-lzt/lzt-eventus-sdk
cd lzt-eventus-sdk
uv sync --extra dev --extra ws
```

`uv` сам создаёт и ведёт `.venv`. Команды запускайте через `uv run`.

## Локальный пол CI

Прогоните ровно тот гейт, который требует `.github/workflows/ci.yml`, до открытия PR:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src                       # strict
uv run pytest -q
```

## Связь с контрактом сервера

SDK повторяет management API [`lzt-eventus`](https://github.com/open-lzt/lzt-eventus) один в один. Если ваша правка — реакция на изменение маршрута или DTO на стороне сервера, выкатывайте оба репозитория в одно окно и перезапишите `tests/fixtures/api_captures.json` с живого сервера, иначе фикстуры превратятся в устаревшие догадки.

## Соглашения

- **Границы типизированы.** Каждый запрос и ответ — типизированная модель (`models.py`) или `StrEnum` (`enums.py`), но не голый `dict`. Публичная поверхность — `__all__` в `src/lzt_eventus_sdk/__init__.py`; всё остальное вправе меняться свободно.
- **Ошибки священны.** Любой ответ не из 2xx поднимает типизированный подкласс `ManagementApiError`, несущий серверные `code`, `detail` и `request_id`. Ни голого исключения `httpx`, ни молчания.
- **Никакого ввода-вывода на импорте.** `import lzt_eventus_sdk` не открывает сокетов. `websockets` (extra `[ws]`) импортируется лениво внутри `lzt_eventus_sdk.sources.ws`, а не на верхнем уровне.

## Pull request'ы

PR идут в `main`. CI (ruff, ruff format, mypy strict, pytest) должен быть зелёным. Опишите, какое изменение на сервере отслеживает ваша правка, если такое было.
