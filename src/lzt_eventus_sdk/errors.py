"""Typed errors for `ManagementClient` — mirrors the server's error-code catalog
(`{"error": code, "detail": {...}, "request_id": ...}`) so a caller branches on
type, never a raw string."""

from __future__ import annotations

from typing import Any


class ManagementApiError(Exception):
    """Base for every error the management API can return. Carries the full
    server envelope (`code`, `detail`, `request_id`) plus the HTTP status."""

    def __init__(
        self, *, status: int, code: str, detail: dict[str, Any], request_id: str | None
    ) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        self.request_id = request_id
        super().__init__(f"{code} ({status}): {detail}")


class BadRequest(ManagementApiError):
    pass


class Unauthorized(ManagementApiError):
    pass


class Forbidden(ManagementApiError):
    pass


class NotFound(ManagementApiError):
    pass


class Conflict(ManagementApiError):
    pass


class ServiceUnavailable(ManagementApiError):
    pass


class SubscriptionNotFound(NotFound):
    pass


class UnknownEventType(BadRequest):
    pass


class InvalidLimit(BadRequest):
    pass


class LimitTooLarge(BadRequest):
    pass


class NotAPollingSubscription(BadRequest):
    pass


class SubscriptionCtxMismatch(BadRequest):
    """`ctx.kind` doesn't match the subscription's `transport`."""


class SubscriptionScopeMismatch(BadRequest):
    """`scope` can never match any of the subscription's `event_types`."""


# Server `code` -> client exception class. Anything unlisted still raises loudly —
# the base status-family class (BadRequest/NotFound/...), never silently swallowed.
_CODE_MAP: dict[str, type[ManagementApiError]] = {
    "unauthorized": Unauthorized,
    "forbidden": Forbidden,
    "not_found": NotFound,
    "conflict": Conflict,
    "service_unavailable": ServiceUnavailable,
    "subscription_not_found": SubscriptionNotFound,
    "unknown_event_type": UnknownEventType,
    "invalid_limit": InvalidLimit,
    "limit_too_large": LimitTooLarge,
    "not_a_polling_subscription": NotAPollingSubscription,
    "subscription_ctx_mismatch": SubscriptionCtxMismatch,
    "subscription_scope_mismatch": SubscriptionScopeMismatch,
}

_STATUS_FALLBACK: dict[int, type[ManagementApiError]] = {
    400: BadRequest,
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
    503: ServiceUnavailable,
}


def build_error(
    *, status: int, code: str, detail: dict[str, Any], request_id: str | None
) -> ManagementApiError:
    cls = _CODE_MAP.get(code) or _STATUS_FALLBACK.get(status, ManagementApiError)
    return cls(status=status, code=code, detail=detail, request_id=request_id)


class ManagementApiConnectionError(ManagementApiError):
    """The request never got a response (timeout, DNS, connection refused, ...)."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            status=0, code="connection_error", detail={"reason": reason}, request_id=None
        )


class MissingDependencyError(Exception):
    """Raised when an optional feature (e.g. `WSSource`) is imported without its
    extra installed — never a bare `ImportError`."""

    def __init__(self, *, extra: str, package: str) -> None:
        self.extra = extra
        self.package = package
        super().__init__(
            f"'{package}' is required for this feature; install with "
            f"`pip install lzt-eventus-sdk[{extra}]`"
        )
