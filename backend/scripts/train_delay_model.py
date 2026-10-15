"""Train the delay model and write `model.joblib` and `metrics.json`. Manual CLI run (retraining is not automatic).

Usage (from backend/):
    uv run python scripts/train_delay_model.py                       # data/ml/train_delays.csv -> data/ml/model/
    uv run python scripts/train_delay_model.py --observations data/ml/observations --out /tmp/model
    uv run python scripts/train_delay_model.py --sample 2000         # quick smoke run on a subset

Method
  * Rows are (station, train, delay). The split is by train (GroupShuffleSplit): 20% of trains are held out for the
    test set, and 20% of the remaining trains calibrate the on-time probability. Reported metrics are on held-out
    trains only.
  * Station and per-pair statistics (mean, median, count) are computed out-of-fold by train group, so a row never
    sees its own delay or its own train's other rows.
  * Model: HistGradientBoostingRegressor with absolute-error loss. On-time probability: isotonic regression from
    predicted delay to P(delay <= 15 min), fitted on the calibration trains.
  * Baseline: the per-pair mean (station, train) from the training trains, falling back to the station mean and then
    the global mean for unseen pairs. On a train-grouped split every held-out pair is unseen, so the baseline's
    coverage is reported next to it. Simpler baselines are reported too.
Whatever the result, metrics.json states it: when the model barely beats (or fails to beat) the baseline, its
`summary` says so, and the API repeats `mae_minutes` and `baseline_mae_minutes`.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DELAYS_CSV_PATH  # noqa: E402
from app.delay.features import (CLASS_CATEGORIES, ON_TIME_MINUTES, FrozenHistory, History, categorical_mask,  # noqa: E402
                                feature_names, feature_row, normalise_station, read_delay_csv)
from app.delay.model import ARTIFACT_VERSION  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "ml" / "model"
SEED = 42
MATERIAL_IMPROVEMENT_PCT = 5.0  # below this the model is reported as only marginally better than the baseline
Row = tuple[str, str, float, int | None, int | None]  # station, train, delay, hour, weekday


def load_rows(csv_path: Path, observations_dir: Path | None) -> tuple[list[Row], dict]:
    rows: list[Row] = [(s, t, d, None, None) for s, t, d in read_delay_csv(csv_path)]
    info = {"observation_rows": 0, "observation_rows_skipped_no_station": 0}
    if observations_dir is not None:
        for path in sorted(observations_dir.rglob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    obs = json.loads(line)
                    delay = float(obs["delay_minutes"])
                except (ValueError, KeyError, TypeError):
                    continue
                if not obs.get("station_code") or delay < 0:  # live status carries no station today
                    info["observation_rows_skipped_no_station"] += 1
                    continue
                rows.append((normalise_station(str(obs["station_code"])), str(obs["train_no"]).strip(), delay,
                             obs.get("hour"), obs.get("weekday")))
                info["observation_rows"] += 1
    return rows, info


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def out_of_fold_features(rows: list[Row], idx: np.ndarray, groups: np.ndarray, features: list[str],
                         folds: int = 5) -> np.ndarray:
    """Feature matrix for rows[idx]: statistics come from the other folds (grouped by train)."""
    from sklearn.model_selection import GroupKFold

    X = np.empty((len(idx), len(features)))
    k = min(folds, len(set(groups[idx])))
    for fit_pos, held_pos in GroupKFold(n_splits=max(k, 2)).split(idx, groups=groups[idx]):
        hist = History.build([(rows[i][0], rows[i][1], rows[i][2]) for i in idx[fit_pos]]).freeze()
        for pos in held_pos:
            s, t, _, h, w = rows[idx[pos]]
            X[pos] = feature_row(s, t, hist, features, h, w)
    return X


def matrix(rows: list[Row], idx: np.ndarray, hist: FrozenHistory, features: list[str]) -> np.ndarray:
    return np.array([feature_row(rows[i][0], rows[i][1], hist, features, rows[i][3], rows[i][4]) for i in idx])


def baselines(rows: list[Row], train_idx: np.ndarray, test_idx: np.ndarray) -> dict:
    hist = History.build([(rows[i][0], rows[i][1], rows[i][2]) for i in train_idx]).freeze()
    y = np.array([rows[i][2] for i in test_idx])
    global_mean = float(np.mean([rows[i][2] for i in train_idx]))
    pair_pred, station_pred, covered = [], [], 0
    for i in test_idx:
        s, t = rows[i][0], rows[i][1]
        st, pr = hist.station_stats(s), hist.pair_stats(s, t)
        covered += pr is not None
        station_pred.append(st[0] if st else global_mean)
        pair_pred.append(pr[0] if pr else station_pred[-1])

    def mae(pred) -> float:
        return float(np.mean(np.abs(y - np.array(pred))))

    return {"pair_mean_mae": mae(pair_pred), "pair_coverage": covered / len(test_idx),
            "station_mean_mae": mae(station_pred), "global_median_mae": mae([hist.global_median] * len(y))}


def _informative(column: np.ndarray) -> bool:
    present = ~np.isnan(column)
    return bool(present.any() and (not present.all() or np.ptp(column) > 0))


def summary_text(mae: float, base: float, improvement: float, coverage: float, median_mae: float) -> str:
    unseen = (f"the per-pair mean baseline ({base:.1f} min MAE; it knew {coverage:.0%} of the held-out "
              "train/station pairs; unknown pairs use the station mean)")
    tail = f" Always predicting the global median scores {median_mae:.1f} min; delays are very noisy."
    if improvement >= MATERIAL_IMPROVEMENT_PCT:
        return f"On trains held out from training, MAE {mae:.1f} min beats {unseen} by {improvement:.1f}%." + tail
    if improvement > 0:
        return (f"On trains held out from training, MAE {mae:.1f} min is only marginally better ({improvement:.1f}%) "
                f"than {unseen}: the model adds little beyond historical averages." + tail)
    return (f"On trains held out from training, MAE {mae:.1f} min does not beat {unseen}. Treat this as a "
            "historical-average estimate, not a better predictor." + tail)


def train(csv_path: Path, out_dir: Path, observations_dir: Path | None = None, sample: int | None = None) -> dict:
    import joblib
    import sklearn
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.isotonic import IsotonicRegression
    from sklearn.model_selection import GroupShuffleSplit

    rows, obs_info = load_rows(csv_path, observations_dir)
    if sample and sample < len(rows):
        keep = np.random.default_rng(SEED).choice(len(rows), size=sample, replace=False)
        rows = [rows[i] for i in sorted(keep)]
    if len(rows) < 100:
        raise SystemExit(f"Only {len(rows)} usable rows; refusing to train")
    include_time = any(r[3] is not None and r[4] is not None for r in rows)
    trains = np.array([r[1] for r in rows])
    y = np.array([r[2] for r in rows])
    all_idx = np.arange(len(rows))

    rest, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED).split(all_idx, groups=trains))
    fit_pos, cal_pos = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
                            .split(rest, groups=trains[rest]))
    fit_idx, cal_idx = rest[fit_pos], rest[cal_pos]
    if set(trains[test_idx]) & set(trains[rest]):
        raise RuntimeError("a train appears on both sides of the split")

    # Features with no information in the training rows (all missing, or constant) are dropped: pair statistics
    # when no pair has repeat records, hour and weekday when no training row has them.
    all_features = feature_names(include_time, True)
    X_fit = out_of_fold_features(rows, fit_idx, trains, all_features)
    X_cal = out_of_fold_features(rows, cal_idx, trains, all_features)
    keep = [j for j in range(len(all_features)) if _informative(X_fit[:, j])]
    features = [all_features[j] for j in keep]
    X_fit, X_cal = X_fit[:, keep], X_cal[:, keep]
    train_hist = History.build([(rows[i][0], rows[i][1], rows[i][2]) for i in rest]).freeze()
    X_test = matrix(rows, test_idx, train_hist, features)

    estimator = HistGradientBoostingRegressor(
        loss="absolute_error", learning_rate=0.05, max_iter=300, max_leaf_nodes=15, min_samples_leaf=40,
        l2_regularization=1.0, categorical_features=categorical_mask(features), early_stopping=True,
        validation_fraction=0.15, n_iter_no_change=20, random_state=SEED)
    estimator.fit(X_fit, y[fit_idx])

    pred_cal = np.maximum(estimator.predict(X_cal), 0)
    calibrator = IsotonicRegression(increasing=False, y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrator.fit(pred_cal, (y[cal_idx] <= ON_TIME_MINUTES).astype(float))

    pred = np.maximum(estimator.predict(X_test), 0)
    err = y[test_idx] - pred
    mae, rmse = float(np.mean(np.abs(err))), float(np.sqrt(np.mean(err**2)))
    base = baselines(rows, rest, test_idx)
    improvement = 100.0 * (base["pair_mean_mae"] - mae) / base["pair_mean_mae"]
    on_time = (y[test_idx] <= ON_TIME_MINUTES).astype(float)
    prob = np.clip(calibrator.predict(pred), 0, 1)
    full_hist = History.build([(r[0], r[1], r[2]) for r in rows]).freeze()  # deployed lookups use every row

    trained_at = datetime.now(timezone.utc).replace(microsecond=0)
    data_hash = sha256(csv_path)
    version = f"hgb-{trained_at:%Y%m%d}-{data_hash[:8]}"
    metrics = {
        "model_version": version, "trained_at": trained_at.isoformat(),
        "mae_minutes": round(mae, 2), "rmse_minutes": round(rmse, 2),
        "baseline_mae_minutes": round(base["pair_mean_mae"], 2),
        "baseline_pair_coverage": round(base["pair_coverage"], 4),
        "baseline_station_mean_mae_minutes": round(base["station_mean_mae"], 2),
        "baseline_global_median_mae_minutes": round(base["global_median_mae"], 2),
        "improvement_over_baseline_pct": round(improvement, 2),
        "beats_baseline_materially": bool(improvement >= MATERIAL_IMPROVEMENT_PCT),
        "summary": summary_text(mae, base["pair_mean_mae"], improvement, base["pair_coverage"],
                              base["global_median_mae"]),
        "on_time_threshold_minutes": ON_TIME_MINUTES,
        "on_time_base_rate_test": round(float(on_time.mean()), 4),
        "brier_calibrated": round(float(np.mean((prob - on_time) ** 2)), 4),
        "brier_constant_base_rate": round(float(np.mean((on_time.mean() - on_time) ** 2)), 4),
        "n_train": int(len(fit_idx)), "n_calibration": int(len(cal_idx)), "n_test": int(len(test_idx)),
        "n_train_trains": int(len(set(trains[fit_idx]))), "n_test_trains": int(len(set(trains[test_idx]))),
        "features": features, "train_classes": CLASS_CATEGORIES, "pair_features_informative": "pair_mean" in features,
        "data_source": {"name": csv_path.name, "sha256": data_hash, "rows": len(rows), **obs_info,
                        "note": "One averaged delay per (station, train) pair; no dates, so no time features "
                                "unless observations with a station and timestamp are added."},
        "sklearn_version": sklearn.__version__, "seed": SEED,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"artifact_version": ARTIFACT_VERSION, "model_version": version, "estimator": estimator,
                 "calibrator": calibrator, "history": full_hist, "features": features, "metrics": metrics},
                out_dir / "model.joblib", compress=3)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csv", type=Path, default=DELAYS_CSV_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--observations", type=Path, default=None, help="directory of collected JSONL observations")
    parser.add_argument("--sample", type=int, default=None, help="train on a random subset of this many rows")
    args = parser.parse_args(argv)
    metrics = train(args.csv, args.out, args.observations, args.sample)
    keys = ("model_version", "mae_minutes", "baseline_mae_minutes", "improvement_over_baseline_pct", "n_train",
            "n_test", "summary")
    print(json.dumps({k: metrics[k] for k in keys}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
