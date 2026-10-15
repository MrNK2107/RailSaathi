"""RailSaathi AI unified API.

Routers: conversational journey planner, goal-based journey planner, ticketing guidance,
indoor station navigation, delay estimation and live station information.

Use the factory with uvicorn so nothing is built at import time:
    uvicorn app.main:create_app --factory
"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.middleware import BodySizeLimitMiddleware, RateLimitMiddleware
from app.api.observability import ObservabilityMiddleware, configure_logging
from app.api.routes import router as conversational_planner_router
from app.api.goal_journey import router as goal_journey_router
from app.api.ticketing import router as ticketing_guidance_router
from app.api.navigation import router as navigation_router
from app.api.delay import router as delay_router
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.live import router as live_router

from app.config import Settings, get_settings
from app.container import Container, build_container
from app.security.rate_limit import InMemoryRateLimiter, RedisRateLimiter

log = logging.getLogger("railsaathi")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_format)

    app = FastAPI(
        title="RailSaathi AI — Unified Rail Platform API",
        version=settings.api_version,
        description="Conversational journey planning, goal-based planning, ticketing guidance, indoor station navigation, delay estimation and live station information.",
    )
    app.state.container = container or build_container(settings)

    # Middlewares
    # Last added is outermost: observability > CORS > rate limit > body size limit.
    c = app.state.container
    limiter = (RedisRateLimiter(c.redis, settings.redis_key_prefix) if c.redis is not None
               else InMemoryRateLimiter(settings.rate_limit_max_keys))
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(RateLimitMiddleware, limiter=limiter, per_minute=settings.rate_limit_per_minute,
                       llm_per_minute=settings.rate_limit_llm_per_minute, signer=c.signer,
                       trusted_hops=settings.trusted_proxy_hops)
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(ObservabilityMiddleware, gcp_project=settings.gcp_project)

    register_error_handlers(app)

    # Mount unified routers
    app.include_router(conversational_planner_router)
    app.include_router(goal_journey_router)
    app.include_router(ticketing_guidance_router)
    app.include_router(navigation_router)
    app.include_router(delay_router)
    app.include_router(live_router)
    app.include_router(health_router)
    app.include_router(internal_router)

    @app.get("/")
    async def platform_root():
        return {
            "name": "RailSaathi AI — Unified Rail Platform API",
            "version": settings.api_version,
            "status": "online",
            "capabilities": {
                "conversational_planner": "Natural-language journey planning with deterministic validation and ranking",
                "goal_journey": "Reach-a-meeting journey evaluation with arrival buffers",
                "ticketing_guidance": "Indian Railways ticketing guidance grounded in a sourced knowledge base",
                "station_navigation": "Indoor concourse routing and curbside wayfinding for authored stations",
                "delay_estimate": "Statistical delay estimate from historical records (trained model or historical average, with measured error and provenance)",
                "live_station_info": "Station search and live board (data provenance reported per response)",
            },
            "docs": "/docs",
        }

    return app
