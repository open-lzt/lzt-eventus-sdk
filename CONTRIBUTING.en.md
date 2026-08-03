<p align="right"><b>English</b> · <a href="CONTRIBUTING.md">Русский</a></p>

# Contributing to lzt-eventus-sdk

Thanks for helping. This is a thin, httpx-only client — Python 3.12, managed by
[uv](https://docs.astral.sh/uv/).

## Setup

```bash
git clone https://github.com/open-lzt/lzt-eventus-sdk
cd lzt-eventus-sdk
uv sync --extra dev --extra ws
```

`uv` creates and manages the `.venv` for you. Prefix commands with `uv run`.

## The local CI floor

Run the exact gate `.github/workflows/ci.yml` enforces before opening a PR:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src                       # strict
uv run pytest -q
```

## Wire-contract coupling

This SDK mirrors [`lzt-eventus`](https://github.com/open-lzt/lzt-eventus)'s management API 1:1.
If your change is a response to a server-side route/DTO change, ship both repos in the same
change window, and re-capture
`tests/fixtures/api_captures.json` against a running server so the fixtures aren't stale guesses.

## Conventions

- **Typed boundaries.** Every request/response is a typed model (`models.py`) or `StrEnum`
  (`enums.py`) — never a raw `dict`. Public surface is `src/lzt_eventus_sdk/__init__.py`'s
  `__all__`; everything else is free to churn.
- **Errors are sacred.** Every non-2xx response raises a typed `ManagementApiError` subclass
  carrying the server's `code`/`detail`/`request_id` — never a bare `httpx` exception, never
  silenced.
- **No I/O at import time.** `import lzt_eventus_sdk` opens no socket. `websockets` (the `[ws]`
  extra) is imported lazily from `lzt_eventus_sdk.sources.ws`, never at the top level.

## Pull requests

Open against `main`. CI (ruff, ruff format, mypy strict, pytest) must pass. Describe the
server-side change this tracks, if any.
