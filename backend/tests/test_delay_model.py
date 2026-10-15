"""Delay model: artifact load, history_only fallback, response schema, and the training script (2k-row smoke run)."""

import csv
import json
import random
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import joblib
import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import DELAY_MODEL_PATH, DELAYS_CSV_PATH, Settings
from app.container import build_container
from app.delay.model import load_delay_model
from app.main import create_app
from tests.conftest import FIXED_NOW

BACKEND = Path(__file__).resolve().parents[1]
SCHEMA_KEYS = {"train_number", "station_code", "train_class", "live_input_delay_minutes",
               "historical_mean_delay_minutes", "historical_scope", "predicted_delay_minutes", "on_time_probability",
               "risk_level", "model_version", "mae_minutes", "baseline_mae_minutes", "basis", "provenance",
               "insights"}


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def client(**kw) -> TestClient:
    s = settings(**kw)
    return TestClient(create_app(s, build_container(s, clock=FixedClock(FIXED_NOW), use_configured_llm=False)))


def trainer():
    sys.path.insert(0, str(BACKEND / "scripts"))
    import train_delay_model

    return train_delay_model


@pytest.fixture(scope="module")
def sample_csv(tmp_path_factory) -> Path:
    """A 2,000-row random sample of the real dataset."""
    with open(DELAYS_CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    path = tmp_path_factory.mktemp("ml") / "sample.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(random.Random(1).sample(rows, 2000))
    return path


@pytest.fixture(scope="module")
def trained(sample_csv, tmp_path_factory):
    out = tmp_path_factory.mktemp("model")
    assert trainer().main(["--csv", str(sample_csv), "--out", str(out)]) == 0
    return out


# ---- the committed artifact ----------------------------------------------------------------------------------

def test_committed_artifact_loads_and_metrics_match():
    model = load_delay_model(settings())
    assert model.mode == "trained_model" and model.loaded and model.reason is None
    metrics = json.loads((DELAY_MODEL_PATH.parent / "metrics.json").read_text(encoding="utf-8"))
    assert model.version == metrics["model_version"] and model.mae_minutes == metrics["mae_minutes"]
    assert metrics["n_test"] > 0 and metrics["data_source"]["rows"] > 60000
    # The summary states the comparison with the baseline, whatever it was.
    assert "baseline" in metrics["summary"]
    assert metrics["improvement_over_baseline_pct"] > 0 or "does not beat" in metrics["summary"]


def test_prediction_schema_for_trained_model():
    body = client().get("/api/predict/delay", params={"train_number": "12658", "destination": "mas",
                                                      "current_delay": "00:20"}).json()
    assert SCHEMA_KEYS <= body.keys()
    assert body["basis"] == "trained_model" and body["station_code"] == "MAS"
    assert body["live_input_delay_minutes"] == 20
    assert body["mae_minutes"] > 0 and body["baseline_mae_minutes"] > 0
    assert 0.0 <= body["on_time_probability"] <= 1.0 and body["risk_level"] in {"LOW", "MODERATE", "HIGH"}
    assert body["model_version"].startswith("hgb-")
    assert body["provenance"]["mode"] == "fallback" and "not live" in body["provenance"]["note"]
    text = json.dumps(body)
    assert "RNN" not in text and "CRIS records" not in text and "63,428" not in text


def test_unknown_station_still_answers_without_a_pair_record():
    body = client().get("/api/predict/delay", params={"train_number": "12658", "destination": "ZZZZ"}).json()
    assert body["historical_scope"] == "none" and body["historical_mean_delay_minutes"] is None
    assert body["predicted_delay_minutes"] is not None  # the model still has train features


def test_prediction_inputs_are_validated():
    c = client()
    assert c.get("/api/predict/delay", params={"train_number": "1; DROP"}).status_code == 422
    assert c.get("/api/predict/delay", params={"train_number": "12658", "hour": 99}).status_code == 422


# ---- fallback ------------------------------------------------------------------------------------------------

def test_missing_artifact_falls_back_to_history_only(tmp_path):
    model = load_delay_model(settings(delay_model_uri=str(tmp_path / "absent.joblib")))
    assert model.mode == "history_only" and not model.loaded
    assert model.reason.startswith("artifact_unavailable")


def test_corrupt_or_wrong_schema_artifact_falls_back(tmp_path):
    bad = tmp_path / "bad.joblib"
    joblib.dump({"artifact_version": 1}, bad)
    assert load_delay_model(settings(delay_model_uri=str(bad))).mode == "history_only"
    garbage = tmp_path / "garbage.joblib"
    garbage.write_bytes(b"not a pickle")
    assert load_delay_model(settings(delay_model_uri=str(garbage))).mode == "history_only"


def test_history_only_response_makes_no_model_claims():
    body = client(delay_history_only=True).get("/api/predict/delay",
                                               params={"train_number": "13009", "destination": "ACND"}).json()
    assert SCHEMA_KEYS <= body.keys()
    assert body["basis"] == "history_only" and body["model_version"] == "history-only"
    assert body["mae_minutes"] is None and body["baseline_mae_minutes"] is None
    assert body["on_time_probability"] is None
    assert body["historical_scope"] == "pair" and body["historical_mean_delay_minutes"] == 270.0
    assert body["provenance"]["mode"] == "fallback" and "no trained model" in body["provenance"]["note"].lower()


def test_no_data_at_all_is_unavailable_not_invented(monkeypatch, tmp_path):
    monkeypatch.setattr("app.delay.model.DELAYS_CSV_PATH", tmp_path / "missing.csv")
    result = load_delay_model(settings(delay_history_only=True)).predict("12658", "MAS")
    assert result.basis == "none" and result.predicted_delay_minutes is None
    assert result.provenance.mode.value == "unavailable"


def test_the_csv_is_not_loaded_at_import_time():
    import app.delay.model as m

    assert not hasattr(m, "HISTORICAL_DELAYS")
    assert "RNN" not in (BACKEND / "app" / "delay" / "model.py").read_text(encoding="utf-8")


def test_gcs_uri_is_read_through_google_cloud_storage(trained):
    blob = MagicMock()
    blob.download_as_bytes.return_value = (trained / "model.joblib").read_bytes()
    storage = MagicMock()
    storage.Client.return_value.bucket.return_value.blob.return_value = blob
    with patch("google.cloud.storage.Client", storage.Client):
        model = load_delay_model(settings(delay_model_uri="gs://models/delay/hgb-20261015/model.joblib"))
    assert model.loaded
    storage.Client.return_value.bucket.assert_called_with("models")
    storage.Client.return_value.bucket.return_value.blob.assert_called_with("delay/hgb-20261015/model.joblib")


def test_malformed_gcs_uri_falls_back():
    assert load_delay_model(settings(delay_model_uri="gs://only-bucket")).mode == "history_only"


# ---- training script -----------------------------------------------------------------------------------------

def test_training_smoke_on_2k_rows(trained):
    metrics = json.loads((trained / "metrics.json").read_text(encoding="utf-8"))
    for key in ("mae_minutes", "rmse_minutes", "baseline_mae_minutes", "n_train", "n_test", "trained_at",
                "data_source", "on_time_base_rate_test", "brier_calibrated", "summary", "model_version"):
        assert key in metrics
    assert metrics["n_train"] + metrics["n_calibration"] + metrics["n_test"] == 2000
    assert metrics["data_source"]["rows"] == 2000 and len(metrics["data_source"]["sha256"]) == 64
    assert metrics["mae_minutes"] > 0
    model = load_delay_model(settings(delay_model_uri=str(trained / "model.joblib")))
    assert model.loaded and model.version == metrics["model_version"]
    result = model.predict("12658", "MAS")
    assert result.basis == "trained_model" and result.predicted_delay_minutes >= 0


def test_summary_is_honest_when_the_model_does_not_beat_the_baseline():
    t = trainer()
    assert "does not beat" in t.summary_text(46.0, 45.0, -2.2, 0.0, 44.0)
    assert "only marginally better" in t.summary_text(44.0, 45.0, 2.2, 0.0, 44.0)
    assert " beats " in t.summary_text(40.0, 45.0, 11.1, 0.0, 44.0)


def test_observations_with_a_station_add_time_features(sample_csv, tmp_path):
    """JSONL observations that carry a station are trained on (with hour and weekday); station-less ones are skipped."""
    obs = tmp_path / "obs" / "2026" / "10"
    obs.mkdir(parents=True)
    rows = [{"train_no": "12658", "station_code": "MAS", "delay_minutes": 10 + i % 30, "hour": i % 24,
             "weekday": i % 7} for i in range(300)]
    rows.append({"train_no": "12658", "delay_minutes": 5, "hour": 3, "weekday": 1})  # no station
    (obs / "a.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    metrics = trainer().train(sample_csv, tmp_path / "m", tmp_path / "obs")
    assert metrics["data_source"]["observation_rows"] == 300
    assert metrics["data_source"]["observation_rows_skipped_no_station"] == 1
    assert {"hour", "weekday"} <= set(metrics["features"])
    assert load_delay_model(settings(delay_model_uri=str(tmp_path / "m" / "model.joblib"))).predict(
        "12658", "MAS", hour=9, weekday=2).basis == "trained_model"


def test_artifact_from_another_scikit_learn_release_falls_back(trained, tmp_path):
    artifact = joblib.load(trained / "model.joblib")
    path = tmp_path / "old.joblib"
    joblib.dump({**artifact, "metrics": {**artifact["metrics"], "sklearn_version": "0.24.2"}}, path)
    model = load_delay_model(settings(delay_model_uri=str(path)))
    assert model.mode == "history_only" and model.reason.startswith("artifact_unavailable")
    # a patch-level difference is fine
    major_minor = ".".join(artifact["metrics"]["sklearn_version"].split(".")[:2])
    joblib.dump({**artifact, "metrics": {**artifact["metrics"], "sklearn_version": major_minor + ".99"}}, path)
    assert load_delay_model(settings(delay_model_uri=str(path))).loaded


def test_serving_features_do_not_depend_on_history_size():
    from app.delay.features import BASE_FEATURES

    assert "station_count" not in BASE_FEATURES


def test_prediction_note_says_modelled():
    note = client().get("/api/predict/delay", params={"train_number": "12658", "destination": "MAS"}
                        ).json()["provenance"]["note"]
    assert "Modelled" in note and "not live" in note
