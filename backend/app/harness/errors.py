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
    }

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def http_status(self) -> int:
        return self.STATUS.get(self.code, 400)
