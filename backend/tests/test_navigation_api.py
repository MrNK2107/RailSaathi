"""Navigation API: read-only runtime over a catalogue loaded once at startup, disruption writes only through the
OIDC-protected internal endpoints, and what-if closures never in production."""

import json
from unittest.mock import MagicMock, patch

import fakeredis
from fastapi.testclient import TestClient
from google.api_core.exceptions import NotFound

from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.main import create_app
from app.navigation.services import station_store
from app.navigation.services.routing_engine import find_route
from app.navigation.services.station_store import GcsStationSource, load_catalogue
from tests.conftest import FIXED_NOW
from tests.station_fixture import entry, png_bytes, station_raw, station_root, write_catalogue, write_station

AUDIENCE = "https://railsaathi-backend-abc.a.run.app"
ACCOUNT = "ops@proj.iam.gserviceaccount.com"
GOOD = {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": ACCOUNT, "email_verified": True}
VERIFY = "app.api.internal_auth._verify"
BEARER = {"Authorization": "Bearer tok"}
ROUTE = {"station_id": "test_station", "source": "ent", "destination": "p1", "preferences": {"wheelchair": True}}


def make(tmp_path, root=None, redis=None, **kw):
    settings = Settings(_env_file=None, stations_uri=str(root or station_root(tmp_path)), **kw)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False, redis=redis)
    return TestClient(create_app(settings, container)), container


def internal(tmp_path, **kw):
    return make(tmp_path, internal_oidc_audience=AUDIENCE, internal_oidc_service_account=ACCOUNT, **kw)


def closure(target_id="e_ramp", **kw):
    return {"target_type": "edge", "target_id": target_id, "reason": "Ramp flooded", "source": "control room", **kw}


# ---- read-only runtime ----------------------------------------------------------------------------------------

def test_catalogue_is_loaded_once_and_graphs_are_not_rebuilt_per_request(tmp_path):
    client, container = make(tmp_path)
    assert container.stations.ids() == ["test_station"]
    prebuilt = container.stations.get("test_station").graph
    with patch("app.api.navigation.find_route", wraps=find_route) as spy:
        for _ in range(3):
            assert client.post("/api/navigation/route", json=ROUTE).json()["status"] == "ok"
    assert spy.call_count == 3
    assert all(call.args[0] is prebuilt for call in spy.call_args_list)  # the startup graph, not a rebuilt one


def test_station_endpoints(tmp_path):
    client, _ = make(tmp_path)
    assert client.get("/api/stations").json() == [{
        "station_id": "test_station", "station_name": "Test Station", "node_count": 7, "edge_count": 8,
        "version": "local", "data_status": "mock", "city": "Testpur"}]
    details = client.get("/api/stations/test_station?draft=true").json()
    assert set(details) == {"station", "metadata", "version", "layout_basis", "provenance"}  # no drafts
    assert details["station"]["nodes"][0]["step_free"] == "unknown"
    assert details["station"]["edges"][0]["from"] == "ent"
    res = client.get("/api/stations/test_station/map")
    assert res.status_code == 200 and res.headers["content-type"] == "image/png" and res.content == png_bytes()
    assert client.get("/api/stations/test_station/info").json()["facts"] == {"note": "test"}
    for path in ("/api/stations/nowhere", "/api/stations/nowhere/map", "/api/stations/nowhere/info",
                 "/api/disruptions/nowhere"):
        assert client.get(path).status_code == 404


def test_there_are_no_public_write_endpoints(tmp_path):
    client, _ = make(tmp_path)
    assert client.post("/api/disruptions/test_station", json=closure()).status_code in (404, 405)
    assert client.delete("/api/disruptions/test_station").status_code in (404, 405)
    for method in ("put", "post", "delete"):
        assert getattr(client, method)("/api/stations/test_station").status_code in (404, 405)
    paths = set(client.app.openapi()["paths"])
    assert not any("draft" in p or "backup" in p or "admin" in p for p in paths)


def test_invalid_station_is_left_out_and_reported(tmp_path):
    root = station_root(tmp_path)
    bad = station_raw(station_id="bad_station")
    bad["edges"][0]["to"] = "nowhere"
    write_station(root, bad)
    write_catalogue(root, [entry(), entry("bad_station")])
    client, container = make(tmp_path, root=root)
    assert container.stations.ids() == ["test_station"]
    assert "unknown_node" in container.stations.failures["bad_station"]
    assert client.get("/api/stations/bad_station").status_code == 404
    ready = client.get("/readyz").json()
    assert ready["checks"]["navigation_stations"] is True and "navigation_stations" in ready["degraded"]


def test_missing_catalogue_means_not_ready(tmp_path):
    client, container = make(tmp_path, root=tmp_path / "empty")
    assert container.stations.ids() == [] and "catalogue" in container.stations.failures
    res = client.get("/readyz")
    assert res.status_code == 503 and res.json()["checks"]["navigation_stations"] is False
    assert client.get("/api/stations").json() == []


def test_map_size_mismatch_keeps_station_out(tmp_path):
    root = station_root(tmp_path)
    (root / "test_station" / "map.png").write_bytes(png_bytes(10, 10))
    _, container = make(tmp_path, root=root)
    assert "map_size_mismatch" in container.stations.failures["test_station"]


def test_cloud_storage_source_reads_the_published_version(tmp_path):
    root = station_root(tmp_path)
    objects = {"stations/catalogue.json": json.dumps({"schema_version": 1, "stations": [
        entry(path="test_station/v2", version="v2")]}).encode()}
    for name in ("station.json", "metadata.json", "info.json", "map.png"):
        objects[f"stations/test_station/v2/{name}"] = (root / "test_station" / name).read_bytes()

    def blob(name):
        b = MagicMock()
        b.download_as_bytes.side_effect = lambda: objects[name] if name in objects else (_ for _ in ()).throw(
            NotFound("missing"))
        return b

    client = MagicMock()
    client.bucket.return_value.blob.side_effect = blob
    catalogue = load_catalogue(GcsStationSource("bkt", "stations", client=client))
    client.bucket.assert_called_with("bkt")
    assert catalogue.ids() == ["test_station"] and catalogue.get("test_station").entry.version == "v2"
    del objects["stations/test_station/v2/map.png"]
    assert "missing_map" in load_catalogue(GcsStationSource("bkt", "stations", client=client)).failures["test_station"]


def test_gs_uri_builds_a_cloud_storage_source():
    with patch("google.cloud.storage.Client") as storage_client:
        source = station_store.build_source("gs://bkt/stations")
    assert isinstance(source, GcsStationSource)
    storage_client.return_value.bucket.assert_called_with("bkt")


def test_unreachable_station_source_does_not_stop_startup(tmp_path):
    with patch("app.container.build_source", side_effect=RuntimeError("no credentials")):
        _, container = make(tmp_path)
    assert container.stations.ids() == [] and "catalogue" in container.stations.failures


# ---- what-if closures (public, never in production) --------------------------------------------------------------

def test_simulated_closures_apply_to_one_request_only(tmp_path):
    client, container = make(tmp_path)
    res = client.post("/api/navigation/route", json={**ROUTE, "simulate_closures": ["e_ramp"]}).json()
    assert res["status"] == "no_route" and res["simulated_closures_applied"] == ["e_ramp"]
    assert client.post("/api/navigation/route", json=ROUTE).json()["status"] == "ok"
    assert container.station_disruptions.list("test_station") == []
    unknown = client.post("/api/navigation/route", json={**ROUTE, "simulate_closures": ["ghost"]})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "unknown_closure_target"


def test_simulated_closures_are_refused_when_disabled_or_in_production(tmp_path):
    off, _ = make(tmp_path, public_disruption_simulation=False)
    res = off.post("/api/navigation/route", json={**ROUTE, "simulate_closures": ["e_ramp"]})
    assert res.status_code == 403 and res.json()["error"]["code"] == "simulation_disabled"
    prod = Settings(_env_file=None, app_env="production", public_disruption_simulation=True)
    assert prod.disruption_simulation_enabled is False


# ---- internal disruption writes ----------------------------------------------------------------------------------

def test_internal_disruption_endpoints_are_disabled_without_oidc_settings(tmp_path):
    client, _ = make(tmp_path)
    assert client.post("/internal/stations/test_station/disruptions", json=closure(), headers=BEARER).status_code == 404


def test_internal_disruption_endpoints_require_a_valid_caller(tmp_path):
    client, container = internal(tmp_path)
    url = "/internal/stations/test_station/disruptions"
    assert client.post(url, json=closure()).status_code == 401
    with patch(VERIFY, side_effect=ValueError("bad")):
        assert client.post(url, json=closure(), headers=BEARER).status_code == 401
    with patch(VERIFY, return_value={**GOOD, "email": "someone@else.com"}):
        assert client.post(url, json=closure(), headers=BEARER).status_code == 403
        assert client.delete(url, headers=BEARER).status_code == 403
    assert container.station_disruptions.list("test_station") == []


def test_internal_disruption_lifecycle_changes_public_routes(tmp_path):
    redis = fakeredis.FakeRedis(decode_responses=True)
    client, _ = internal(tmp_path, redis=redis)
    url = "/internal/stations/test_station/disruptions"
    with patch(VERIFY, return_value=GOOD):
        created = client.post(url, json=closure(ttl_seconds=600), headers=BEARER)
        assert created.status_code == 201
        body = created.json()
        assert body["kind"] == "pathway_closure" and body["simulated"] is False and body["source"] == "control room"
        public = client.get("/api/disruptions/test_station").json()
        assert [d["id"] for d in public] == [body["id"]]
        blocked = client.post("/api/navigation/route", json=ROUTE).json()
        assert blocked["status"] == "no_route" and blocked["disruptions_applied"] == [body["id"]]
        ignored = client.post("/api/navigation/route", json={**ROUTE, "apply_disruptions": False}).json()
        assert ignored["status"] == "ok"
        assert client.delete(f"{url}/{body['id']}", headers=BEARER).json() == {"deleted": body["id"]}
        assert client.delete(f"{url}/{body['id']}", headers=BEARER).status_code == 404
        client.post(url, json=closure(), headers=BEARER)
        assert client.delete(url, headers=BEARER).json() == {"cleared": 1}
        assert client.post(url, json=closure("ghost"), headers=BEARER).status_code == 404
        assert client.post("/internal/stations/nowhere/disruptions", json=closure(), headers=BEARER).status_code == 404
        assert client.post(url, json={**closure(), "extra": 1}, headers=BEARER).status_code == 422
    assert client.post("/api/navigation/route", json=ROUTE).json()["status"] == "ok"


def test_simulated_disruptions_are_refused_in_production(tmp_path):
    client, container = internal(tmp_path, app_env="production", session_signing_key="k" * 32)
    url = "/internal/stations/test_station/disruptions"
    with patch(VERIFY, return_value=GOOD):
        res = client.post(url, json=closure(simulated=True), headers=BEARER)
        assert res.status_code == 403 and res.json()["error"]["code"] == "simulation_disabled"
        assert client.post(url, json=closure(), headers=BEARER).status_code == 201
    assert len(container.station_disruptions.list("test_station")) == 1


def test_disruption_store_outage_degrades_honestly(tmp_path):
    from redis.exceptions import ConnectionError as RedisConnectionError

    client, container = make(tmp_path)
    container.station_disruptions = MagicMock()
    container.station_disruptions.list.side_effect = RedisConnectionError("down")
    res = client.post("/api/navigation/route", json=ROUTE).json()
    assert res["status"] == "ok" and res["warnings"][0].startswith("Current closure information is unavailable")
    down = client.get("/api/disruptions/test_station")
    assert down.status_code == 503 and down.json()["error"]["code"] == "disruptions_unavailable"
    assert "down" not in down.text


def test_authoring_settings_are_gone():
    settings = Settings(_env_file=None)
    for name in ("admin_token", "max_backups", "data_dir"):
        assert not hasattr(settings, name)
