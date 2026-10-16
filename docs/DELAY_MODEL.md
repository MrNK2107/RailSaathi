# Delay estimate: model card

`GET /api/predict/delay` estimates how late a train will be at a station. This page explains:

- what the estimate is and how it was measured;
- where its data came from;
- what it must not be used for.

All numbers come from `backend/data/ml/model/metrics.json`, which is written by
`backend/scripts/train_delay_model.py` and committed next to the model.

## Summary

| | |
|---|---|
| Model version | `hgb-20261015-6233f815`, trained 2026-10-15 |
| Model | scikit-learn `HistGradientBoostingRegressor` (absolute-error loss) plus isotonic calibration for the on-time probability |
| **Typical error (MAE)** | **40.0 minutes** on trains held out from training (RMSE 96.1 min) |
| Baseline MAE | 45.7 min (per-pair mean, falling back to the station mean). Always predicting the global median scores 44.7 min |
| Improvement over baseline | 12.4 % |
| On-time probability (P(delay ≤ 15 min)) | Brier score 0.191, against 0.242 for always predicting the base rate (0.411 of held-out rows were on time) |
| API provenance | `mode: fallback`, with the note "Modelled statistical estimate from historical delay records, not live data. Typical error is about 40.04 min on held-out trains." |

**An error of 40 minutes is large.** The estimate is a rough historical tendency. It is not a forecast of
today's running and it must never be shown as one. The UI shows the MAE and the provenance next to every
estimate.

## Intended use

- A rough idea of how late a train has historically tended to be at a station, to help a passenger choose a buffer.
- **Not** for decisions that need today's status. For that, use live running status (`/api/live/trains/{n}/status`,
  RailRadar), or official Indian Railways channels.
- **Not** an official Indian Railways figure.

## Data provenance

| | |
|---|---|
| File | `backend/data/ml/train_delays.csv` |
| SHA-256 | `6233f815ed0a0fd0c81259b0775c2229e579c817cc83cdc82a9fb0077e8315d6` |
| Rows | 63,428 rows of (station code, train number, delay in minutes); 3,088 stations, 2,919 trains |
| Distribution | Median 21 min, mean 48.4 min, 90th percentile 122 min, max 1,415 min |
| Dates | **None.** Each row is one averaged delay per (station, train) pair, with no date, hour or weekday. So the model cannot learn season, day-of-week or time-of-day effects |
| Origin | **Not documented.** The file arrived in the repository with the 2026-10-10 refactor (commit `d74675a`) without a source, licence or collection date |

Earlier code called this file "CRIS records". That attribution could not be verified, so it was removed. Treat
the data as unverified historical averages of unknown age.

Live observations are a second, future source:

- `POST /internal/collect` (Cloud Scheduler) appends live running-status samples to `OBSERVATIONS_URI`.
- RailRadar's live status is per train and has no station, so the trainer skips these samples today
  (`observation_rows_skipped_no_station`). The current model uses **0** observation rows.

## Method

Inputs and features:

- **Inputs:** a train number and a station code. `current_delay` is echoed back but is **not** an input.
- **Features:** `train_number` (categorical), `train_class` (derived from the number series; a coarse heuristic:
  superfast, mail/express, suburban, MEMU and so on), and the station's mean and median delay.
- **Pair statistics:** they were measured as uninformative and are not used (`pair_features_informative: false`).
  On a train-grouped split, no held-out (train, station) pair exists in training, so a per-pair mean cannot help.

Split and leakage control:

- The split is by train (`GroupShuffleSplit`, seed 42). 20 % of trains are held out for test: 584 trains, 12,258
  rows.
- 20 % of the rest are used to calibrate the on-time probability: 9,998 rows.
- Training uses 41,172 rows from 1,868 trains.
- Station statistics are computed out of fold by train group, so a row never sees its own delay.

The served model:

- The deployed model looks up station statistics in the **training rows only**: 41,172 of the 63,428, about 65 %.
  This is the same history the metrics were measured with, so the reported error describes what is served.
- A station that is not in that history falls back as described under "What the API returns".

All metrics are measured on held-out trains. The summary in `metrics.json` states plainly when the model only
marginally beats the baseline (below 5 % improvement). This version clears that bar.

## What the API returns

The response has these fields:

- `predicted_delay_minutes` and `on_time_probability`;
- `risk_level` (LOW below 15 min, MODERATE below 40, HIGH at 40 or more);
- `mae_minutes` and `baseline_mae_minutes`;
- `historical_mean_delay_minutes` and `historical_scope` (`pair`, `station` or `none`);
- `model_version`, `basis` and `provenance`.

`basis` is one of:

| `basis` | When | What it means |
|---|---|---|
| `trained_model` | `model.joblib` loaded and its schema checked | Modelled estimate with the measured MAE |
| `history_only` | No artifact, an unreadable artifact, or `DELAY_HISTORY_ONLY=true` | The recorded historical average only. No probability and no accuracy claim |
| `none` | No historical data at all | `provenance.mode: unavailable`, no number |

A missing or unreadable artifact makes `/readyz` report not ready, unless `DELAY_HISTORY_ONLY=true` says that mode
is intended.

## Limitations

- Large error (MAE 40 min) and a heavy tail (RMSE 96 min). Delays of several hours occur in the data.
- No time features. The same train at the same station always gets the same estimate.
- Unknown data age and origin (see above). The data may not reflect current timetables.
- The train-class heuristic reads only the number series, so it misclassifies some trains.
- The error is measured on held-out *trains*, not held-out *stations*. For a station absent from the history, the
  error is not measured, even though the provenance note still quotes the overall MAE.

## Retraining

Retraining is a manual step. It is never automatic.

```bash
cd backend
uv run python scripts/train_delay_model.py                       # CSV -> data/ml/model/{model.joblib,metrics.json}
uv run python scripts/train_delay_model.py --observations <dir>  # plus collected JSONL observations
```

Then:

1. Review `metrics.json`: the MAE against the baseline, and the summary.
2. Commit the artifact, or upload it to `gs://…/model.joblib` and set `DELAY_MODEL_URI`.
3. Update this page.

The artifact is a pickle. Only load files your own pipeline wrote. The loader checks the artifact version and the
scikit-learn version.
