"""Opaque HMAC-signed session tokens: `<session_id>.<signature>`.

The token proves the caller was issued the session by this service. It carries no other data; expiry is the
session's own TTL in the store."""

import base64
import hashlib
import hmac
import logging
import secrets

from app.config import Settings

log = logging.getLogger("railsaathi.security")
TOKEN_HEADER = "X-Session-Token"


class InvalidSessionToken(Exception):
    pass


class SessionTokenSigner:
    def __init__(self, key: bytes) -> None:
        if len(key) < 16:
            raise ValueError("session signing key must be at least 16 bytes")
        self._key = key

    def _sig(self, session_id: str) -> str:
        mac = hmac.new(self._key, b"session:" + session_id.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()

    def issue(self, session_id: str) -> str:
        return f"{session_id}.{self._sig(session_id)}"

    def verify(self, token: str | None) -> str:
        """Return the session id the token was issued for, or raise InvalidSessionToken."""
        if not token or "." not in token or len(token) > 256:
            raise InvalidSessionToken("malformed")
        session_id, _, sig = token.rpartition(".")
        if not session_id or not hmac.compare_digest(sig, self._sig(session_id)):
            raise InvalidSessionToken("bad signature")
        return session_id

    def verify_for(self, token: str | None, session_id: str) -> None:
        if not hmac.compare_digest(self.verify(token), session_id):
            raise InvalidSessionToken("session mismatch")


def build_signer(settings: Settings) -> SessionTokenSigner:
    key = settings.session_signing_key.get_secret_value().strip() if settings.session_signing_key else ""
    if key:
        return SessionTokenSigner(key.encode())
    if settings.is_production:
        raise ValueError("SESSION_SIGNING_KEY must be set when APP_ENV=production")
    log.warning("SESSION_SIGNING_KEY not set: using a random per-process key (tokens die on restart)")
    return SessionTokenSigner(secrets.token_bytes(32))
