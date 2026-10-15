"""Delay observation collection: which trains users looked at recently, and the JSONL samples taken of them.

`SeenTrains` remembers train numbers seen by the live endpoints (Redis sorted set with TTL; in-process fallback).
`collect_observations` samples each train's running status through the container's LiveSource and writes one JSONL
object per run to an `ObservationSink` (a local directory in development, `gs://bucket/prefix` in production).
Cloud Storage objects cannot be appended to, so every run writes a new object; retraining reads them all.

A sample is only recorded when the status is fresh (`live`) and states a delay. Cached, stale and unavailable
answers are counted but never written, so the dataset holds real observations only. The live status carries no
station, so a sample is a train-level running delay; `scripts/train_delay_model.py` uses only rows that have a
station code."""

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Protocol

from redis import Redis

from app.clock import Clock
from app.domain.enums import DataMode
from app.providers.live_source import LiveSource

TRAIN_NO = re.compile(r"^[A-Za-z0-9]{1,8}$")


class SeenTrains(Protocol):
    def record(self, train_nos: list[str]) -> None: ...

    def recent(self, limit: int) -> list[str]: ...


class InMemorySeenTrains:
    def __init__(self, clock: Clock, ttl_seconds: int, max_entries: int = 5000) -> None:
        self._clock, self._ttl, self._max = clock, ttl_seconds, max_entries
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def record(self, train_nos: list[str]) -> None:
        now = self._clock.now().timestamp()
        with self._lock:
            for n in train_nos:
                if TRAIN_NO.match(n):
                    self._seen[n.upper()] = now
            if len(self._seen) > self._max:  # drop the oldest
                for k in sorted(self._seen, key=self._seen.get)[: len(self._seen) - self._max]:
                    del self._seen[k]

    def recent(self, limit: int) -> list[str]:
        cutoff = self._clock.now().timestamp() - self._ttl
        with self._lock:
            live = sorted(((t, n) for n, t in self._seen.items() if t >= cutoff), reverse=True)
        return [n for _, n in live[:limit]]


class RedisSeenTrains:
    def __init__(self, redis: Redis, clock: Clock, ttl_seconds: int, prefix: str = "rs") -> None:
        self._r, self._clock, self._ttl = redis, clock, ttl_seconds
        self._key = f"{prefix}:delay:seen_trains"

    def record(self, train_nos: list[str]) -> None:
        valid = {n.upper(): self._clock.now().timestamp() for n in train_nos if TRAIN_NO.match(n)}
        if valid:
            pipe = self._r.pipeline()
            pipe.zadd(self._key, valid)
            pipe.expire(self._key, self._ttl)
            pipe.execute()

    def recent(self, limit: int) -> list[str]:
        self._r.zremrangebyscore(self._key, "-inf", self._clock.now().timestamp() - self._ttl)
        return [n.decode() if isinstance(n, bytes) else n for n in self._r.zrevrange(self._key, 0, limit - 1)]


class ObservationSink(Protocol):
    def write(self, name: str, text: str) -> str: ...


class LocalObservationSink:
    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)

    def write(self, name: str, text: str) -> str:
        path = self._dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)


class GcsObservationSink:
    def __init__(self, bucket: str, prefix: str, client=None) -> None:
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self._bucket = client.bucket(bucket)
        self._bucket_name = bucket
        self._prefix = prefix.strip("/")

    def write(self, name: str, text: str) -> str:
        key = f"{self._prefix}/{name}" if self._prefix else name
        self._bucket.blob(key).upload_from_string(text, content_type="application/x-ndjson")
        return f"gs://{self._bucket_name}/{key}"


def build_sink(uri: str) -> ObservationSink:
    if uri.startswith("gs://"):
        bucket, _, prefix = uri[5:].partition("/")
        if not bucket:
            raise ValueError("OBSERVATIONS_URI must look like gs://bucket/prefix")
        return GcsObservationSink(bucket, prefix)
    return LocalObservationSink(uri)


def collect_observations(live: LiveSource, seen: SeenTrains, sink: ObservationSink, clock: Clock,
                         max_trains: int) -> dict:
    """Sample running status for recently seen trains and append the fresh ones as JSONL. Blocking."""
    now = clock.now()
    trains = seen.recent(max_trains)
    lines: list[str] = []
    skipped = 0
    for train_no in trains:
        status = live.live_status(train_no, now.date())
        if status.provenance.mode is not DataMode.LIVE or status.delay_minutes is None:
            skipped += 1
            continue
        observed = status.provenance.as_of
        lines.append(json.dumps({
            "train_no": train_no, "run_date": status.run_date.isoformat(), "delay_minutes": status.delay_minutes,
            "cancelled": status.cancelled, "observed_at": observed.isoformat(), "hour": observed.hour,
            "weekday": observed.weekday(), "source": status.provenance.source}, separators=(",", ":")))
    written = None
    if lines:
        name = f"{now:%Y/%m/%d}/obs-{now:%H%M%S}-{uuid.uuid4().hex[:8]}.jsonl"
        written = sink.write(name, "\n".join(lines) + "\n")
    return {"trains_seen": len(trains), "observations_written": len(lines), "skipped_not_fresh": skipped,
            "object": written, "collected_at": now.isoformat()}
