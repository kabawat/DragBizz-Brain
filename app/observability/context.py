"""Request-scoped identity for structured logs (not metric labels).

``request_id`` is always set by middleware. ``user_id`` / ``store_id`` /
``session_id`` are set only after authentication from JWT ``sub`` and
validated request fields — never from client identity headers.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("ai_request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("ai_user_id", default=None)
_store_id: ContextVar[str | None] = ContextVar("ai_store_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("ai_session_id", default=None)


def set_request_id(request_id: str) -> Token:
    return _request_id.set(request_id)


def reset_request_id(token: Token) -> None:
    _request_id.reset(token)


def set_auth_context(
    *,
    user_id: str,
    store_id: str,
    session_id: str,
) -> tuple[Token, Token, Token]:
    """Bind auth-derived identity for the remainder of the request."""
    return (
        _user_id.set(user_id),
        _store_id.set(store_id),
        _session_id.set(session_id),
    )


def _reset_var(var: ContextVar[str | None], token: Token) -> None:
    """Reset when possible; clear if Token belongs to another Context.

    Starlette StreamingResponse iterates the body in a different context
    than the route handler, so ``Token.reset`` can raise ValueError.
    """
    try:
        var.reset(token)
    except ValueError:
        var.set(None)


def reset_auth_context(tokens: tuple[Token, Token, Token]) -> None:
    user_token, store_token, session_token = tokens
    _reset_var(_user_id, user_token)
    _reset_var(_store_id, store_token)
    _reset_var(_session_id, session_token)


def get_request_id() -> str | None:
    return _request_id.get()


def get_user_id() -> str | None:
    return _user_id.get()


def get_store_id() -> str | None:
    return _store_id.get()


def get_session_id() -> str | None:
    return _session_id.get()


def correlation_fields() -> dict[str, str]:
    """Fields safe to attach to log extras (omit unset identity)."""
    fields: dict[str, str] = {}
    request_id = get_request_id()
    if request_id:
        fields["request_id"] = request_id
    user_id = get_user_id()
    if user_id:
        fields["user_id"] = user_id
    store_id = get_store_id()
    if store_id:
        fields["store_id"] = store_id
    session_id = get_session_id()
    if session_id:
        fields["session_id"] = session_id
    return fields
