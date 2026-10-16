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


# ---- docs/SECURITY.md open risk R3 must name every script source the deployed CSP allows -------------------------
# (in the backend suite because the frontend's Vite test runner may not read files outside frontend/)

SECURITY_MD = API_MD.parent / "SECURITY.md"
SECURITY_HEADERS = API_MD.parents[1] / "frontend" / "nginx" / "security-headers.conf"


def script_src_sources() -> list[str]:
    match = re.search(r'^add_header Content-Security-Policy "([^"]*)" always;$', SECURITY_HEADERS.read_text(),
                      re.MULTILINE)
    assert match, "no Content-Security-Policy header in security-headers.conf"
    for directive in match.group(1).split(";"):
        name, *values = directive.split()
        if name == "script-src":
            return values
    raise AssertionError("the CSP has no script-src directive")


def test_security_threat_model_r3_lists_every_script_src_source():
    rows = [line for line in SECURITY_MD.read_text(encoding="utf-8").splitlines() if line.startswith("| R3 |")]
    assert len(rows) == 1, "SECURITY.md must have exactly one R3 row"
    sources = script_src_sources()
    assert "https://*.googleusercontent.com" in sources and "blob:" in sources  # the parse found the real list
    missing = [source for source in sources if source not in rows[0]]
    assert not missing, f"R3 in docs/SECURITY.md does not list these script-src sources: {missing}"
    # The two widest sources are called out by name, with the mitigation options.
    assert "**`https://*.googleusercontent.com`**" in rows[0] and "**`blob:`**" in rows[0]
    for option in ("'strict-dynamic'", "Report-Only"):
        assert option in rows[0]


# ---- NTES appears in the docs only in its honest form (Task 17: the owner chose the unofficial ntes-client) ----

DOCS_DIR = API_MD.parent
README_MD = DOCS_DIR.parent / "README.md"


def test_docs_describe_ntes_as_an_unofficial_client_and_drop_the_old_denials():
    texts = {p.name: p.read_text(encoding="utf-8") for p in [README_MD, *DOCS_DIR.glob("*.md")]}
    for name in ("README.md", "DATA_PROVIDERS.md", "LIMITATIONS.md", "SECURITY.md", "RUNBOOK.md"):
        assert "unofficial" in texts[name] and "NTES" in texts[name], name
    assert "NTES (unofficial client)" in texts["DATA_PROVIDERS.md"]
    for name, text in texts.items():
        lowered = text.lower()
        assert "no ntes integration" not in lowered and "any ntes feed" not in lowered, name
        for claim in ("official ntes integration", "authorised ntes integration", "official ntes api"):
            # Only ever negated ("not an official ... integration"), never claimed.
            for at in [i for i in range(len(lowered)) if lowered.startswith(claim, i)]:
                assert "not" in lowered[max(0, at - 40):at], (name, claim)
