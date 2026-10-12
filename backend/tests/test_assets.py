"""Station assets are served only through allowlisted endpoints; the data directory is never mounted."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None)))


def test_station_map_is_served_for_known_station():
    res = _client().get("/api/stations/chennai_central/map")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_station_map_404_for_unknown_or_malformed_ids():
    c = _client()
    assert c.get("/api/stations/nowhere/map").status_code == 404
    assert c.get("/api/stations/..%2F..%2Fknowledge/map").status_code == 404


def test_data_directory_is_not_mounted():
    c = _client()
    assert c.get("/data/knowledge/railsaathi.db").status_code == 404
    assert c.get("/data/stations/chennai_central/map.png").status_code == 404
    assert c.get("/data/ml/train_delays.csv").status_code == 404


def test_station_info_still_available():
    res = _client().get("/api/stations/chennai_central/info")
    assert res.status_code == 200
    assert "helplines" in res.json()
