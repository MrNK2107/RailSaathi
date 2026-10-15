"""Cloud Run OIDC verification for internal (service-to-service) endpoints such as `/internal/collect`.

Cloud Scheduler (or another Google service) sends `Authorization: Bearer <Google ID token>` minted for the target
service URL by a dedicated service account. This module verifies, using google-auth:
  * the signature against Google's public keys and that the token has not expired,
  * the audience equals INTERNAL_OIDC_AUDIENCE,
  * the issuer is Google,
  * the verified email equals INTERNAL_OIDC_SERVICE_ACCOUNT.
Anything else is rejected. When either setting is empty the internal endpoints are disabled (404), so a
misconfigured deploy never exposes them. Error bodies never say which check failed.

Use `require_internal_caller` as a route dependency: `Depends(require_internal_caller)`."""

import hmac
import logging

from fastapi import HTTPException, Request
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.api.deps import offload

log = logging.getLogger("railsaathi.internal_auth")

GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def _reject(status: int, code: str, message: str) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return HTTPException(status, detail={"code": code, "message": message}, headers=headers)


def _verify(token: str, audience: str) -> dict:
    return id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)


async def require_internal_caller(request: Request) -> str:
    """Return the verified caller's service-account email, or raise 404 (disabled), 401 or 403."""
    settings = request.app.state.container.settings
    audience, account = settings.internal_oidc_audience, settings.internal_oidc_service_account
    if not audience or not account:
        raise _reject(404, "not_found", "Not Found")
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _reject(401, "unauthorized", "A valid identity token is required.")
    try:
        claims = await offload(_verify, token.strip(), audience)
    except (ValueError, google_auth_exceptions.GoogleAuthError):
        raise _reject(401, "unauthorized", "A valid identity token is required.") from None
    except Exception:  # noqa: BLE001 - certificate fetch failures and the like: fail closed
        log.warning("OIDC token verification failed unexpectedly", exc_info=True)
        raise _reject(401, "unauthorized", "A valid identity token is required.") from None
    email = str(claims.get("email") or "").lower()
    if (claims.get("iss") not in GOOGLE_ISSUERS or claims.get("email_verified") is not True
            or not hmac.compare_digest(email.encode(), account.strip().lower().encode())):
        log.warning("Internal call rejected: unexpected issuer or caller")
        raise _reject(403, "forbidden", "This caller is not allowed.")
    return email
