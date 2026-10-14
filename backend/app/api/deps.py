"""Shared request dependencies: session-token verification, settings-driven message limits and `offload` for
running blocking work (Redis, SQLite, model inference, LLM calls) off the event loop."""

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import anyio.to_thread
from fastapi import Request

from app.harness.errors import PlannerError
from app.security.tokens import TOKEN_HEADER, InvalidSessionToken

T = TypeVar("T")


async def offload(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run blocking `fn` in the worker thread pool so async handlers never block the event loop.
    Context variables (request id) are carried into the thread."""
    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))


def verify_session_token(request: Request) -> None:
    """Route dependency for `/planner/sessions/{session_id}/...`: the X-Session-Token must be issued for that id."""
    signer = request.app.state.container.signer
    try:
        signer.verify_for(request.headers.get(TOKEN_HEADER), str(request.path_params["session_id"]))
    except InvalidSessionToken as exc:
        raise PlannerError("invalid_session_token", "A valid session token is required.") from exc


def enforce_message_limit(request: Request, text: str | None, field: str = "message") -> None:
    """Reject chat-like text longer than Settings.max_message_chars with 422."""
    limit = request.app.state.container.settings.max_message_chars
    if text is not None and len(text) > limit:
        raise PlannerError("message_too_long", f"{field} must be at most {limit} characters.",
                           {"field": field, "max_chars": limit})
