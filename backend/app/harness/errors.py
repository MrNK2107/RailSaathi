def safe_validation_errors(exc: ValueError) -> list[dict[str, str]]:
    """[{field, message}] from a pydantic ValidationError: never the offending input values."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return []
    return [{"field": ".".join(str(p) for p in e.get("loc", ())), "message": str(e.get("msg", "invalid"))}
            for e in errors(include_input=False, include_url=False)]


class PlannerError(Exception):
    """Domain error with a stable code the API maps to an HTTP status."""

    STATUS = {
        "session_not_found": 404,
        "session_expired": 410,
        "invalid_transition": 409,
        "not_ready": 409,
        "no_recommendations": 409,
        "stale_recommendations": 409,
        "session_cancelled": 409,
        "invalid_option": 422,
        "validation_failed": 422,
        "unknown_event": 404,
        "no_relevant_event": 409,
        "data_unavailable": 503,
        "invalid_session_token": 401,
        "message_too_long": 422,
    }

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def http_status(self) -> int:
        return self.STATUS.get(self.code, 400)
