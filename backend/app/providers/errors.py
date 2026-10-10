"""Errors raised by railway data providers."""

from enum import StrEnum


class ProviderErrorKind(StrEnum):
    NOT_CONFIGURED = "not_configured"
    AUTH_FAILED = "auth_failed"  # missing/invalid/expired API key
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"  # network error or 5xx
    NOT_FOUND = "not_found"
    BAD_REQUEST = "bad_request"
    BAD_RESPONSE = "bad_response"  # response format not understood


class ProviderError(Exception):
    def __init__(self, kind: ProviderErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
