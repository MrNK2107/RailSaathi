"""Feature construction shared by the training script and the runtime model, so both sides compute identical inputs.

The historical dataset holds one averaged delay per (station, train) pair. Features therefore describe the train
(number, class derived from the number range) and the station and pair history (mean, median, count) taken from
training data only. Hour and weekday exist only for collected observations and are used when the training data
has them."""

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

ON_TIME_MINUTES = 15  # a train is "on time" when it is at most this many minutes late
CLASS_CATEGORIES = ["special", "mail_express", "superfast", "premium", "express_2xxxx", "suburban", "passenger",
                    "memu", "dmu", "unknown"]
# station_count is deliberately not a feature: it scales with the size of the history it was counted in, which
# differs between training folds and serving. Counts stay in FrozenHistory for display only.
BASE_FEATURES = ["train_number", "train_class", "station_mean", "station_median", "pair_mean", "pair_count"]
TIME_FEATURES = ["hour", "weekday"]


def train_class(train_no: str) -> str:
    """Coarse class from the Indian Railways train-number series (a heuristic, not an authoritative type)."""
    digits = train_no.strip()
    if not (digits.isdigit() and len(digits) == 5):
        return "unknown"
    two, first = digits[:2], digits[0]
    if two in ("12", "22"):
        return "superfast"
    if two in ("20", "21"):
        return "premium"
    return {"0": "special", "1": "mail_express", "2": "express_2xxxx", "3": "suburban", "4": "suburban",
            "5": "passenger", "6": "memu", "7": "dmu", "8": "special", "9": "suburban"}[first]


def normalise_station(code: str) -> str:
    return code.strip().upper()


@dataclass
class History:
    """Delay statistics per station and per (station, train) pair, built from training rows only."""

    pair: dict[tuple[str, str], list[float]] = field(default_factory=lambda: defaultdict(list))
    station: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    all_delays: list[float] = field(default_factory=list)

    @classmethod
    def build(cls, rows: "list[tuple[str, str, float]]") -> "History":
        h = cls()
        for station, train, delay in rows:
            h.pair[(station, train)].append(delay)
            h.station[station].append(delay)
            h.all_delays.append(delay)
        return h

    def freeze(self) -> "FrozenHistory":
        """Compact lookup tables for the artifact: only means, medians and counts are kept."""
        return FrozenHistory(
            pair={f"{s}|{t}": (float(np.mean(v)), len(v)) for (s, t), v in self.pair.items()},
            station={s: (float(np.mean(v)), float(statistics.median(v)), len(v)) for s, v in self.station.items()},
            global_median=float(statistics.median(self.all_delays)) if self.all_delays else None,
        )


@dataclass
class FrozenHistory:
    pair: dict[str, tuple[float, int]]  # "STATION|TRAIN" -> (mean, count)
    station: dict[str, tuple[float, float, int]]  # station -> (mean, median, count)
    global_median: float | None

    def pair_stats(self, station: str, train: str) -> tuple[float, int] | None:
        return self.pair.get(f"{station}|{train}")

    def station_stats(self, station: str) -> tuple[float, float, int] | None:
        return self.station.get(station)


def feature_row(station: str, train: str, hist: FrozenHistory, features: list[str],
                hour: int | None = None, weekday: int | None = None) -> list[float]:
    """One feature vector in the order of `features`. Unknown values are NaN (HistGradientBoosting handles missing
    values natively); train_class is its index in CLASS_CATEGORIES."""
    nan = float("nan")
    st = hist.station_stats(station)
    pr = hist.pair_stats(station, train)
    values = {
        "train_number": float(train) if train.isdigit() else nan,
        "train_class": float(CLASS_CATEGORIES.index(train_class(train))),
        "station_mean": st[0] if st else nan, "station_median": st[1] if st else nan,
        "pair_mean": pr[0] if pr else nan, "pair_count": float(pr[1]) if pr else 0.0,
        "hour": float(hour) if hour is not None else nan, "weekday": float(weekday) if weekday is not None else nan,
    }
    return [values[name] for name in features]


def feature_names(include_time: bool, include_pair: bool = True) -> list[str]:
    """Pair features are dropped when no pair has more than one record (they would be constant)."""
    names = [n for n in BASE_FEATURES if include_pair or not n.startswith("pair_")]
    return names + (TIME_FEATURES if include_time else [])


def categorical_mask(features: list[str]) -> list[bool]:
    return [name == "train_class" for name in features]


def read_delay_csv(path) -> list[tuple[str, str, float]]:
    """Rows (station, train, delay_minutes) from the headerless historical CSV; malformed rows are skipped."""
    import csv

    rows: list[tuple[str, str, float]] = []
    with open(path, encoding="utf-8", errors="ignore", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 3:
                continue
            try:
                delay = float(row[2].strip())
            except ValueError:
                continue
            if delay != delay or delay < 0:  # NaN or negative
                continue
            rows.append((normalise_station(row[0]), row[1].strip(), delay))
    return rows
