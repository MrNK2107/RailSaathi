"""RailSaathi AI unified API.

Routers: conversational journey planner, goal-based journey planner, ticketing guidance,
indoor station navigation, delay estimation and live station information.

Use the factory with uvicorn so nothing is built at import time:
    uvicorn app.main:create_app --factory
"""

import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import AccessLogMiddleware, BodySizeLimitMiddleware, RateLimitMiddleware
from app.api.routes import router as conversational_planner_router
from app.api.goal_journey import router as goal_journey_router
from app.api.ticketing import router as ticketing_guidance_router
from app.api.navigation import router as navigation_router
from app.api.delay import router as delay_router
from app.api.live import router as live_router

from app.config import Settings, get_settings
from app.container import Container, build_container
from app.harness.errors import PlannerError
from app.sessions.redis_store import SessionLockTimeout
from app.security.rate_limit import InMemoryRateLimiter, RedisRateLimiter

log = logging.getLogger("railsaathi")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(
        title="RailSaathi AI — Unified Rail Platform API",
        version=settings.api_version,
        description="Conversational journey planning, goal-based planning, ticketing guidance, indoor station navigation, delay estimation and live station information.",
    )
    app.state.container = container or build_container(settings)

    # Middlewares
    # Last added is outermost: CORS > access log > rate limit > body size limit.
    c = app.state.container
    limiter = (RedisRateLimiter(c.redis, settings.redis_key_prefix) if c.redis is not None
               else InMemoryRateLimiter(settings.rate_limit_max_keys))
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(RateLimitMiddleware, limiter=limiter, per_minute=settings.rate_limit_per_minute,
                       llm_per_minute=settings.rate_limit_llm_per_minute, signer=c.signer,
                       trusted_hops=settings.trusted_proxy_hops)
    app.add_middleware(AccessLogMiddleware)
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_errors(app)

    # Mount unified routers
    app.include_router(conversational_planner_router)
    app.include_router(goal_journey_router)
    app.include_router(ticketing_guidance_router)
    app.include_router(navigation_router)
    app.include_router(delay_router)
    app.include_router(live_router)

    @app.get("/")
    def platform_root():
        return {
            "name": "RailSaathi AI — Unified Rail Platform API",
            "version": settings.api_version,
            "status": "online",
            "capabilities": {
                "conversational_planner": "Natural-language journey planning with deterministic validation and ranking",
                "goal_journey": "Reach-a-meeting journey evaluation with arrival buffers",
                "ticketing_guidance": "Indian Railways ticketing guidance grounded in a sourced knowledge base",
                "station_navigation": "Indoor concourse routing and curbside wayfinding for authored stations",
                "delay_estimate": "Historical-average delay estimate (statistical baseline, not a trained model yet)",
                "live_station_info": "Station search and live board (data provenance reported per response)",
            },
            "docs": "/docs",
        }

    return app


def _register_errors(app: FastAPI) -> None:
    @app.exception_handler(PlannerError)
    async def planner_error(_: Request, exc: PlannerError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
        )

    @app.exception_handler(SessionLockTimeout)
    async def session_busy(_: Request, __: SessionLockTimeout) -> JSONResponse:
        return JSONResponse(
            status_code=503, headers={"Retry-After": "2"},
            content={"error": {"code": "session_busy", "message": "This session is busy. Please retry shortly.",
                               "details": {}}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "The request is invalid.", "details": {"errors": details}}}
        )

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Something went wrong. Please try again.", "details": {}}}
        )

