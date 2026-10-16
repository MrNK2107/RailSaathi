"""Liveness (`/healthz`) and readiness (`/readyz`) probes, plus the shared dependency status used by /api/health.

Liveness does no I/O. Readiness fails only for things this service cannot work without: Redis (reachable when
configured; in production it must also be configured, since sessions, rate limits and the NTES/RailRadar request
budgets are shared through it), an active railway data provider (production refuses demo data, which leaves none;
NTES needs the ntes-client package installed), the station catalogue, at least one navigation station and, in
production with RAILWAY_DATA_MODE=railradar, the RailRadar key (NTES needs no key). Third-party outages such as the LLM
being paused are reported as `degraded` and never fail readiness."""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.api.deps import offload
from app.container import Container

log = logging.getLogger("railsaathi.health")
router = APIRouter(tags=["system"])


def redis_status(c: Container) -> dict[str, Any]:
    if c.redis is None:
        return {"configured": False, "ok": None}
    try:
        c.redis.ping()
        return {"configured": True, "ok": True}
    except (RedisError, OSError):
        log.warning("Redis ping failed", exc_info=True)
        return {"configured": True, "ok": False}


def llm_status(c: Container) -> dict[str, Any]:
    return {"provider_setting": c.settings.llm_provider, "configured": c.settings.llm_configured,
            **c.extractor.llm_status, "chat": c.chat_llm_status,
            "vision": {"provider": c.vision.name if c.vision else None, "reason": c.vision_reason}}


def model_status(c: Container) -> dict[str, Any]:
    return c.delay_model.status() if c.delay_model is not None else {"mode": "none", "loaded": False}


def dependency_status(c: Container) -> dict[str, Any]:
    return {"redis": redis_status(c), "model": model_status(c), "llm": llm_status(c)}


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    return await offload(_readyz, request.app.state.container)


def _readyz(c: Container) -> JSONResponse:
    redis = redis_status(c)
    catalogue = len(c.provider.stations())
    checks = {
        # Production needs Redis configured and reachable; elsewhere an unset REDIS_URL means in-memory state.
        "redis": redis["ok"] is True if c.settings.is_production else redis["ok"] is not False,
        # "none" when production refused RAILWAY_DATA_MODE=demo: every journey and board would be unavailable.
        "data_provider": _provider_active(c),
        "station_catalogue": catalogue > 0,
        # NTES needs no key; demo in production is refused (data_provider fails) and still reports the key.
        "railradar_key": not c.settings.is_production or _mode(c) == "ntes" or _has_key(c),
        # Ready with the trained artifact, or in history_only mode when that was asked for explicitly.
        "delay_model": bool(c.delay_model and (c.delay_model.loaded or c.settings.delay_history_only)),
        # At least one navigation station loaded and validated from the station data root.
        "navigation_stations": bool(c.stations and c.stations.stations),
    }
    degraded = []
    llm = llm_status(c)
    if c.settings.llm_configured and not llm.get("active", False):
        degraded.append("llm")
    if not c.settings.knowledge_db_path.exists():
        degraded.append("knowledge")
    if c.data_provider_status.get("active") == "railradar" and not c.data_provider_status.get("configured"):
        degraded.append("railradar")
    if _mode(c) == "ntes" and not c.data_provider_status.get("configured"):
        degraded.append("ntes")
    if c.stations and c.stations.failures:
        degraded.append("navigation_stations")  # some listed stations failed to load; see the startup log
    ready = all(checks.values())
    return JSONResponse(status_code=200 if ready else 503,
                        content={"status": "ready" if ready else "not_ready", "checks": checks,
                                 "degraded": degraded,
                                 "delay_model": model_status(c)})


def _mode(c: Container) -> str:
    return str(c.data_provider_status.get("requested") or c.settings.data_provider).lower()


def _provider_active(c: Container) -> bool:
    """An active provider; NTES counts only when the ntes-client package is installed."""
    active = c.data_provider_status.get("active")
    if active == "ntes":
        return bool(c.data_provider_status.get("configured"))
    return active not in (None, "none")


def _has_key(c: Container) -> bool:
    key = c.settings.railradar_api_key
    return bool(key and key.get_secret_value().strip())
