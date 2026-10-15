"""Liveness (`/healthz`) and readiness (`/readyz`) probes, plus the shared dependency status used by /api/health.

Liveness does no I/O. Readiness fails only for things this service cannot work without (Redis when configured,
the station catalogue, the RailRadar key in production). Third-party outages such as the LLM being paused are
reported as `degraded` and never fail readiness."""

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
            **c.extractor.llm_status, "chat": c.chat_llm_status}


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
        "redis": redis["ok"] is not False,
        "station_catalogue": catalogue > 0,
        "railradar_key": not c.settings.is_production or _has_key(c),
        # Ready with the trained artifact, or in history_only mode when that was asked for explicitly.
        "delay_model": bool(c.delay_model and (c.delay_model.loaded or c.settings.delay_history_only)),
    }
    degraded = []
    llm = llm_status(c)
    if c.settings.llm_configured and not llm.get("active", False):
        degraded.append("llm")
    if not c.settings.knowledge_db_path.exists():
        degraded.append("knowledge")
    if c.data_provider_status.get("active") == "railradar" and not c.data_provider_status.get("configured"):
        degraded.append("railradar")
    ready = all(checks.values())
    return JSONResponse(status_code=200 if ready else 503,
                        content={"status": "ready" if ready else "not_ready", "checks": checks,
                                 "degraded": degraded,
                                 "delay_model": model_status(c)})


def _has_key(c: Container) -> bool:
    key = c.settings.railradar_api_key
    return bool(key and key.get_secret_value().strip())
