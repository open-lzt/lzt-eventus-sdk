from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import Any, cast

from lzt_eventus_sdk.dispatch.context import AccountContext
from lzt_eventus_sdk.dispatch.result import DispatchOutcome, DispatchResult
from lzt_eventus_sdk.dispatch.router import HandlerCallback, Router, SkipHandler
from lzt_eventus_sdk.events.event import ClientEvent
from lzt_eventus_sdk.events.registry import PayloadRegistry
from lzt_eventus_sdk.events.registry import events as default_registry
from lzt_eventus_sdk.middleware.base import BaseMiddleware, Handler


def _bind_kwargs(
    callback: HandlerCallback, event: ClientEvent, data: dict[str, Any]
) -> dict[str, Any]:
    """aiogram-style injection: a handler receives only the params it declares
    by name, resolved from `data` (plus the always-available `event`). A
    `**kwargs` catch-all receives everything.
    """
    sig = inspect.signature(callback)
    full = {**data, "event": event}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return full
    return {name: full[name] for name in sig.parameters if name in full}


class Dispatcher:
    """The single feed point (D2). Every transport normalises to a `ClientEvent`
    and calls `feed(event, ctx)` — there is no per-transport dispatch path.
    """

    def __init__(
        self,
        root_router: Router,
        *,
        outer_middleware: Sequence[BaseMiddleware] = (),
        inner_middleware: Sequence[BaseMiddleware] = (),
        registry: PayloadRegistry | None = None,
    ) -> None:
        self.root = root_router
        self._outer = list(outer_middleware)
        self._inner = list(inner_middleware)
        self._registry = registry or default_registry

    async def feed(self, event: ClientEvent, ctx: AccountContext) -> DispatchResult:
        data: dict[str, Any] = {
            "ctx": ctx,
            "client": ctx.client,
            "subscription_id": ctx.subscription_id,
        }
        payload = self._registry.parse(event.event_type, event.data)
        if payload is not None:
            data["payload"] = payload

        chain: Handler = self._walk_and_handle
        for middleware in reversed(self._outer):
            chain = _wrap(middleware, chain)

        result = await chain(event, data)
        return cast(DispatchResult, result)

    async def _walk_and_handle(self, event: ClientEvent, data: dict[str, Any]) -> DispatchResult:
        for router in self.root.walk():
            for handler_obj in router.handlers:
                extra: dict[str, Any] = {}
                matched = True
                for filt in handler_obj.filters:
                    outcome = await filt(event, data)
                    if not outcome:
                        matched = False
                        break
                    if isinstance(outcome, dict):
                        extra.update(outcome)
                if not matched:
                    continue

                handler_data = {**data, **extra}
                result = await self._run_handler(handler_obj.callback, event, handler_data)
                if result is _SKIPPED:
                    continue
                return cast(DispatchResult, result)
        return DispatchResult(outcome=DispatchOutcome.SKIPPED, event=event)

    async def _run_handler(
        self, callback: HandlerCallback, event: ClientEvent, data: dict[str, Any]
    ) -> DispatchResult | object:
        async def _call(ev: ClientEvent, d: dict[str, Any]) -> Any:
            kwargs = _bind_kwargs(callback, ev, d)
            return await callback(**kwargs)

        call: Handler = _call
        for middleware in reversed(self._inner):
            call = _wrap(middleware, call)

        try:
            await call(event, data)
        except SkipHandler:
            return _SKIPPED
        except Exception as exc:
            return DispatchResult(outcome=DispatchOutcome.ERRORED, event=event, error=exc)
        return DispatchResult(outcome=DispatchOutcome.HANDLED, event=event)


_SKIPPED = object()


def _wrap(middleware: BaseMiddleware, nxt: Handler) -> Handler:
    async def wrapped(event: ClientEvent, data: dict[str, Any]) -> Any:
        return await middleware(nxt, event, data)

    return wrapped
