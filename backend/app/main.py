"""
RailSaathi AI — Unified API Gateway (Pillars 1 to 5)
Consolidated, production-grade backend engine uniting:
- Pillar 1: Conversational Voice/Text Intent Planner & Goal-Based Meeting Journey Evaluator
- Pillar 2: Real-time Live Station Departure Boards & NTES Train Schedule Tracker
- Pillar 3: Curbside-to-Coach Berth Turn-by-Turn Wayfinding with 600m Platform Pillar Halting Decoder
- Pillar 4: Machine Learning Cascading Delay Predictor trained on 63k+ CRIS Historical Arrival Records
- Pillar 5: 2D Indoor Station Concourse Blueprint & Step-Free Wheelchair Accessibility Navigator
- Ticketing Guidance: Indian Railways RAC/WL, Tatkal, and Refund Regulatory Advisor
"""

import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware import AccessLogMiddleware, BodySizeLimitMiddleware, RateLimitMiddleware
from app.api.routes import router as conversational_planner_router
from app.api.goal_journey import router as goal_journey_router
from app.api.ticketing import router as ticketing_guidance_router
from app.api.navigation import router as navigation_router
from app.api.delay import router as delay_router
from app.api.live import router as live_router

from app.config import Settings, get_settings, DATA_DIR
from app.container import Container, build_container
from app.harness.errors import PlannerError

log = logging.getLogger("railsaathi")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(
        title="RailSaathi AI — Unified Rail Platform API",
        version=settings.api_version,
        description="Unified platform combining Smart Conversational Journey Planning, ML Delay Forecasting, 2D Concourse Blueprints, and WebAR Wayfinding.",
    )
    app.state.container = container or build_container(settings)

    # Middlewares
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_minute)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
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

    # Static files for 2D blueprints (maps, station assets)
    if DATA_DIR.exists():
        app.mount("/data", StaticFiles(directory=str(DATA_DIR.resolve())), name="data")

    @app.get("/")
    def platform_root():
        return {
            "name": "RailSaathi AI — Unified Rail Platform API",
            "version": settings.api_version,
            "status": "online",
            "pillars": {
                "pillar_1": "Smart Passenger Conversational Planner & Goal-Based Meeting Timetable Evaluator",
                "pillar_2": "Real-time Live Station Departure Boards & NTES Train Schedule Tracker",
                "pillar_3": "Curbside-to-Coach Berth Turn-by-Turn Wayfinding with Pillar Halting Decoder",
                "pillar_4": "ML Cascading Delay Predictor trained on 63k+ CRIS Historical Arrival Records",
                "pillar_5": "2D Indoor Station Concourse Blueprint & Step-Free Accessibility Navigator",
                "ticketing_guidance": "Indian Railways RAC/WL & Tatkal Regulatory Guidance AI"
            }
        }

    return app


def _register_errors(app: FastAPI) -> None:
    @app.exception_handler(PlannerError)
    async def planner_error(_: Request, exc: PlannerError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
        )

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


app = create_app()
