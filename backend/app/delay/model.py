"""Delay model: loads the trained artifact once at startup, answers predictions, and degrades to `history_only`.

Modes
  * trained_model - a scikit-learn HistGradientBoostingRegressor artifact (`model.joblib`, trained by
    `scripts/train_delay_model.py`) from a local path or `gs://bucket/object`, plus an isotonic calibrator for the
    on-time probability. `mae_minutes` is the artifact's MAE measured on trains held out from training.
  * history_only  - no artifact (or explicitly requested): the mean delay recorded for the train and station,
    else the station mean, else the global median. No probability is claimed.

Every response says which basis was used and carries provenance. Nothing here is a live prediction: the model does
not see the train's current delay (the training data has none)."""

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np
from pydantic import BaseModel, Field

from app.config import DELAYS_CSV_PATH, Settings
from app.delay.features import (FrozenHistory, History, ON_TIME_MINUTES, feature_names, feature_row,
                                normalise_station, read_delay_csv, train_class)
from app.domain.enums import DataMode
from app.domain.options import DataProvenance

log = logging.getLogger("railsaathi.delay")

ARTIFACT_VERSION = 1
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
REQUIRED_KEYS = {"artifact_version", "model_version", "estimator", "calibrator", "history", "features", "metrics"}
HISTORY_ONLY_VERSION = "history-only"
UTC = ZoneInfo("UTC")


class DelayPrediction(BaseModel):
    train_number: str
    station_code: str
    train_class: str  # derived from the train-number series, a coarse heuristic
    live_input_delay_minutes: int  # echoed; neither mode uses it as an input
    historical_mean_delay_minutes: float | None  # recorded mean for this train and station, else the station mean
    historical_scope: Literal["pair", "station", "none"]
    predicted_delay_minutes: int | None
    on_time_probability: float | None  # 0..1, P(delay <= 15 min); trained_model only
    on_time_threshold_minutes: int = ON_TIME_MINUTES
    risk_level: Literal["LOW", "MODERATE", "HIGH"] | None
    model_version: str
    mae_minutes: float | None  # measured on held-out trains; None when there is no trained model
    baseline_mae_minutes: float | None  # the per-pair-mean baseline's MAE on the same held-out trains
    basis: Literal["trained_model", "history_only", "none"]
    provenance: DataProvenance
    insights: list[str] = Field(default_factory=list)


def _risk(minutes: float) -> Literal["LOW", "MODERATE", "HIGH"]:
    return "LOW" if minutes < ON_TIME_MINUTES else "MODERATE" if minutes < 40 else "HIGH"


class DelayModel:
    def __init__(self, mode: Literal["trained_model", "history_only"], history: FrozenHistory, *,
                 version: str = HISTORY_ONLY_VERSION, estimator: Any = None, calibrator: Any = None,
                 features: list[str] | None = None, metrics: dict | None = None, reason: str | None = None,
                 history_source: str | None = None) -> None:
        self.mode = mode
        self.history = history
        self.version = version
        self.reason = reason  # why history_only was chosen (None for trained_model)
        self._estimator = estimator
        self._calibrator = calibrator
        self._features = features or feature_names(False, True)
        self.metrics = metrics or {}
        self._history_source = history_source or "none"
        trained_at = self.metrics.get("trained_at")
        self._as_of = datetime.fromisoformat(trained_at) if trained_at else datetime.now(UTC)

    @property
    def loaded(self) -> bool:
        return self.mode == "trained_model"

    @property
    def mae_minutes(self) -> float | None:
        return self.metrics.get("mae_minutes") if self.loaded else None

    def status(self) -> dict[str, Any]:
        return {"mode": self.mode, "loaded": self.loaded, "model_version": self.version, "reason": self.reason,
                "mae_minutes": self.mae_minutes, "baseline_mae_minutes": self.metrics.get("baseline_mae_minutes"),
                "stations_indexed": len(self.history.station)}

    def predict(self, train_number: str, station_code: str, current_delay: int = 0,
                hour: int | None = None, weekday: int | None = None) -> DelayPrediction:
        """Blocking (CPU-bound); callers run it through `offload` / `anyio.to_thread.run_sync`."""
        train, station = train_number.strip(), normalise_station(station_code)
        pair = self.history.pair_stats(station, train)
        stn = self.history.station_stats(station)
        scope = "pair" if pair else "station" if stn else "none"
        hist_mean = pair[0] if pair else stn[0] if stn else None
        insights: list[str] = []
        if pair:
            insights.append(f"Recorded mean delay for train {train} at {station}: {round(pair[0])} min "
                            f"({pair[1]} record{'s' if pair[1] != 1 else ''}).")
        elif stn:
            insights.append(f"No record for train {train} at {station}; the station's mean delay is "
                            f"{round(stn[0])} min over {stn[2]} records.")
        else:
            insights.append(f"Station {station} is not in the historical data.")
        if current_delay > 0:
            insights.append(f"Currently reported {current_delay} min late. The estimate does not use live delay.")

        if self.mode == "trained_model":
            row = feature_row(station, train, self.history, self._features, hour, weekday)
            predicted = max(0.0, float(self._estimator.predict(np.array([row]))[0]))
            prob = float(np.clip(self._calibrator.predict([predicted])[0], 0.0, 1.0))
            basis = "trained_model"
            insights.append(self.metrics.get("summary") or "Estimate from a trained statistical model.")
            note = ("Statistical estimate from historical delay records, not live data. Typical error is about "
                    f"{self.metrics.get('mae_minutes')} min on held-out trains.")
            source = f"RailSaathi delay model {self.version} ({self.metrics.get('data_source', {}).get('name', 'historical delays')})"
        else:
            predicted = hist_mean if hist_mean is not None else self.history.global_median
            prob = None
            basis = "history_only" if predicted is not None else "none"
            insights.append("No trained model is loaded: this is the recorded historical average, with no "
                            "accuracy measurement and no probability.")
            note = ("Historical average only (no trained model loaded), not live data."
                    if predicted is not None else "No historical data is available for this estimate.")
            source = f"RailSaathi historical delay averages ({self._history_source})"
        mode = DataMode.FALLBACK if predicted is not None else DataMode.UNAVAILABLE
        provenance = DataProvenance(mode=mode, source=source, as_of=self._as_of, note=note)
        minutes = None if predicted is None else round(predicted)
        return DelayPrediction(
            train_number=train, station_code=station, train_class=train_class(train),
            live_input_delay_minutes=current_delay,
            historical_mean_delay_minutes=None if hist_mean is None else round(hist_mean, 1),
            historical_scope=scope, predicted_delay_minutes=minutes, on_time_probability=prob,
            risk_level=None if predicted is None else _risk(predicted), model_version=self.version,
            mae_minutes=self.mae_minutes, baseline_mae_minutes=self.metrics.get("baseline_mae_minutes") if self.loaded else None,
            basis=basis, provenance=provenance, insights=insights)


def _read_bytes(uri: str) -> bytes:
    if uri.startswith("gs://"):
        from google.cloud import storage  # lazy: only needed when a bucket is configured

        bucket, _, name = uri[5:].partition("/")
        if not bucket or not name:
            raise ValueError("DELAY_MODEL_URI must look like gs://bucket/path/model.joblib")
        data = storage.Client().bucket(bucket).blob(name).download_as_bytes()
    else:
        path = Path(uri)
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact too large")
        data = path.read_bytes()
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact too large")
    return data


def _load_artifact(uri: str) -> dict:
    import joblib  # lazy: scikit-learn is only imported when an artifact exists

    # joblib artifacts are pickles: only ever load ones this project trained into its own storage.
    artifact = joblib.load(io.BytesIO(_read_bytes(uri)))
    if not isinstance(artifact, dict) or not REQUIRED_KEYS <= artifact.keys():
        raise ValueError("artifact has an unexpected schema")
    if artifact["artifact_version"] != ARTIFACT_VERSION:
        raise ValueError("artifact version not supported")
    if not isinstance(artifact["history"], FrozenHistory):
        raise ValueError("artifact history is invalid")
    features = artifact["features"]
    valid = set(feature_names(True, True))
    if not isinstance(features, list) or not features or not set(features) <= valid:
        raise ValueError("artifact features are invalid")
    if getattr(artifact["estimator"], "n_features_in_", len(features)) != len(features):
        raise ValueError("artifact feature count does not match this release")
    return artifact


def _history_from_csv(path: Path) -> tuple[FrozenHistory, str]:
    if not path.exists():
        return FrozenHistory({}, {}, None), "no data"
    rows = read_delay_csv(path)
    return History.build(rows).freeze(), f"{path.name}, {len(rows)} records"


def load_delay_model(settings: Settings) -> DelayModel:
    """Build the model at startup. Never raises: any problem degrades to history_only with a reason."""
    reason = "history_only_requested"
    if not settings.delay_history_only:
        uri = settings.delay_model_uri
        if uri:
            try:
                art = _load_artifact(uri)
                log.info("Delay model %s loaded", art["model_version"])
                return DelayModel("trained_model", art["history"], version=art["model_version"],
                                  estimator=art["estimator"], calibrator=art["calibrator"],
                                  features=list(art["features"]), metrics=art["metrics"])
            except Exception as exc:  # noqa: BLE001 - degrade, never fail startup
                log.warning("Delay model artifact could not be loaded (%s); using history_only", type(exc).__name__)
                reason = f"artifact_unavailable:{type(exc).__name__}"
        else:
            reason = "no_artifact_configured"
    history, source = _history_from_csv(DELAYS_CSV_PATH)
    return DelayModel("history_only", history, reason=reason, history_source=source)
