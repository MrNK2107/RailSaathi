"""docs/API.md documents exactly the endpoints the app serves (method + path), in both directions.

Public routes come from the OpenAPI schema; the internal OIDC-protected routes are excluded from the schema on
purpose (`include_in_schema=False`) but are still documented in their own table, so they are collected from the
router. The only routes left out are the ones FastAPI generates for its own docs UI; they are not API endpoints."""

import re
from pathlib import Path

from fastapi.routing import APIRoute

from app.config import Settings
from app.main import create_app

API_MD = Path(__file__).resolve().parents[2] / "docs" / "API.md"
ROW = re.compile(r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)
# FastAPI's generated documentation routes (Starlette `Route`s, not `APIRoute`s); API.md mentions /docs and
# /openapi.json in prose. Listed so a change in how FastAPI registers them cannot silently widen the check.
FRAMEWORK_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def documented() -> set[tuple[str, str]]:
    rows = ROW.findall(API_MD.read_text(encoding="utf-8"))
    pairs = {(method, path) for method, path in rows}
    assert len(pairs) == len(rows), "an endpoint is documented twice"
    return pairs


def _api_routes(routes) -> list[APIRoute]:
    """APIRoutes of the app, including those inside included routers (FastAPI may wrap them lazily)."""
    found = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        inner = getattr(route, "original_router", None) or getattr(route, "router", None)
        if inner is not None and getattr(inner, "routes", None) is not route:
            found.extend(_api_routes(inner.routes))
    return found


def served(app) -> set[tuple[str, str]]:
    public = {(method.upper(), path) for path, item in app.openapi()["paths"].items() for method in item}
    hidden = {(method, route.path) for route in _api_routes(app.routes) if not route.include_in_schema
              for method in route.methods - {"HEAD", "OPTIONS"}}
    assert all(path.startswith("/internal/") for _, path in hidden), "only internal routes may hide from OpenAPI"
    return public | hidden


def test_every_served_endpoint_is_documented_and_every_documented_endpoint_exists():
    app = create_app(Settings(_env_file=None))
    have, docs = served(app), documented()
    assert not {p for _, p in have} & FRAMEWORK_ROUTES
    undocumented = sorted(have - docs)
    missing = sorted(docs - have)
    assert not undocumented, f"served but not in docs/API.md: {undocumented}"
    assert not missing, f"in docs/API.md but not served: {missing}"


def test_the_check_sees_internal_routes_and_parses_the_tables():
    app = create_app(Settings(_env_file=None))
    have = served(app)
    assert ("POST", "/internal/collect") in have and ("DELETE", "/internal/stations/{station_id}/disruptions") in have
    assert ("POST", "/api/navigation/route") in documented()
    assert len(have) >= 40
