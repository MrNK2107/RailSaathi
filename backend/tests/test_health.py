import fakeredis
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.main import create_app
from tests.conftest import FIXED_NOW


def make(redis=None, **overrides) -> TestClient:
    settings = Settings(_env_file=None, **overrides)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False, redis=redis)
    return TestClient(create_app(settings, container))


def dead_redis():
    server = fakeredis.FakeServer()
    server.connected = False
    return server, fakeredis.FakeStrictRedis(server=server, decode_responses=True)


def test_healthz_is_pure_liveness_even_with_dead_redis():
    _, redis = dead_redis()
    assert make(redis=redis).get("/healthz").json() == {"status": "ok"}


def test_readyz_without_redis_configured():
    body = make().get("/readyz").json()
    assert body["status"] == "ready"
    assert body["checks"] == {"redis": True, "data_provider": True, "station_catalogue": True, "railradar_key": True,
                              "delay_model": True, "navigation_stations": True}
    assert body["delay_model"]["mode"] == "trained_model"


def test_readyz_pings_redis():
    server = fakeredis.FakeServer()
    c = make(redis=fakeredis.FakeStrictRedis(server=server, decode_responses=True))
    assert c.get("/readyz").status_code == 200
    server.connected = False
    res = c.get("/readyz")
    assert res.status_code == 503 and res.json()["checks"]["redis"] is False


def test_readyz_requires_railradar_key_in_production_only():
    prod = make(app_env="production", session_signing_key="k" * 32)
    res = prod.get("/readyz")
    assert res.status_code == 503 and res.json()["checks"]["railradar_key"] is False
    ok = make(redis=fakeredis.FakeStrictRedis(decode_responses=True), app_env="production",
              session_signing_key="k" * 32, railradar_api_key="rr_key", RAILWAY_DATA_MODE="railradar")
    assert ok.get("/readyz").status_code == 200
    assert make().get("/readyz").status_code == 200


def test_llm_trouble_is_degraded_not_unready():
    c = make(llm_provider="bedrock", aws_region="ap-south-1", bedrock_model_id="m")
    body = c.get("/readyz").json()
    assert body["status"] == "ready" and "llm" in body["degraded"]


def test_health_routes_are_exempt_from_rate_limiting():
    c = make(rate_limit_per_minute=1)
    assert all(c.get(p).status_code == 200 for p in ("/healthz", "/readyz", "/api/health") for _ in range(3))


def test_api_health_keeps_shape_and_adds_dependency_status():
    body = make(redis=fakeredis.FakeStrictRedis(decode_responses=True)).get("/api/health").json()
    for key in ("status", "api_version", "data_mode", "data_provider", "ai"):
        assert key in body
    assert body["redis"] == {"configured": True, "ok": True}
    assert body["model"]["mode"] == "trained_model" and body["model"]["loaded"] is True
    assert "provider_setting" in body["llm"]
    assert make().get("/api/health").json()["redis"] == {"configured": False, "ok": None}


def test_demo_mode_is_refused_in_production():
    """RAILWAY_DATA_MODE=demo never serves simulated data when APP_ENV=production; readiness fails."""
    c = make(app_env="production", session_signing_key="k" * 32, RAILWAY_DATA_MODE="demo")
    container = c.app.state.container
    assert container.data_provider_status["reason"] == "demo_refused_in_production"
    assert container.provider.data_mode != "demo"
    res = c.get("/readyz")
    assert res.status_code == 503 and res.json()["checks"]["railradar_key"] is False
    assert make(RAILWAY_DATA_MODE="demo").app.state.container.provider.data_mode == "demo"


def test_readyz_not_ready_when_production_refused_demo_even_with_a_railradar_key():
    """A non-empty RAILRADAR_API_KEY must not make a demo-refused production instance look ready."""
    res = make(redis=fakeredis.FakeStrictRedis(decode_responses=True), app_env="production",
               session_signing_key="k" * 32, RAILWAY_DATA_MODE="demo", railradar_api_key="dummy").get("/readyz")
    assert res.status_code == 503
    assert res.json()["checks"]["data_provider"] is False and res.json()["checks"]["railradar_key"] is True


def test_readyz_production_requires_redis_configured():
    live = {"app_env": "production", "session_signing_key": "k" * 32, "railradar_api_key": "rr_key",
            "RAILWAY_DATA_MODE": "railradar"}
    res = make(**live).get("/readyz")
    assert res.status_code == 503 and res.json()["checks"]["redis"] is False
    assert make(redis=fakeredis.FakeStrictRedis(decode_responses=True), **live).get("/readyz").status_code == 200


def test_readyz_delay_model_history_only_needs_to_be_explicit(tmp_path):
    """A missing artifact degrades to history_only but is not ready; asking for history_only explicitly is."""
    missing = str(tmp_path / "nope.joblib")
    broken = make(delay_model_uri=missing).get("/readyz")
    assert broken.status_code == 503 and broken.json()["checks"]["delay_model"] is False
    assert broken.json()["delay_model"]["mode"] == "history_only"
    explicit = make(delay_model_uri=missing, delay_history_only=True).get("/readyz")
    assert explicit.status_code == 200 and explicit.json()["delay_model"]["mode"] == "history_only"
