"""Shared request dependencies: session-token verification and settings-driven message limits."""

from fastapi import Request

from app.harness.errors import PlannerError
from app.security.tokens import TOKEN_HEADER, InvalidSessionToken


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
