"""Station disruptions (pathway closures, facility outages) as a runtime overlay with a TTL.

The overlay never edits the station graph: layout, geometry and step-free properties stay as published.
`RedisDisruptionStore` is used whenever the container has Redis (shared across instances, every key expires);
`InMemoryDisruptionStore` is for tests and single-process development. Writes come only from the OIDC-protected
internal endpoint (`/internal/stations/{id}/disruptions`)."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Protocol

from redis import Redis

from app.clock import Clock
from app.navigation.models.station import Disruption, DisruptionCreate, Station


class DisruptionTargetNotFound(Exception):
    pass


class DisruptionStore(Protocol):
    def list(self, station_id: str) -> list[Disruption]: ...

    def add(self, disruption: Disruption) -> None: ...

    def delete(self, station_id: str, disruption_id: str) -> bool: ...

    def clear(self, station_id: str) -> int: ...


def new_disruption(station: Station, req: DisruptionCreate, now: datetime, default_ttl_seconds: int) -> Disruption:
    """Build a disruption for a node or edge that exists in the station graph."""
    if req.target_type == "edge":
        if req.target_id not in {e.id for e in station.edges}:
            raise DisruptionTargetNotFound(f"Unknown edge '{req.target_id}'")
        kind = "pathway_closure"
    else:
        if req.target_id not in {n.id for n in station.nodes}:
            raise DisruptionTargetNotFound(f"Unknown node '{req.target_id}'")
        kind = "facility_outage"
    return Disruption(
        id=f"dis_{uuid.uuid4().hex[:12]}",
        station_id=station.station_id,
        target_type=req.target_type,
        target_id=req.target_id,
        kind=kind,
        reason=req.reason,
        source=req.source,
        simulated=req.simulated,
        created_at=now,
        expires_at=now + timedelta(seconds=req.ttl_seconds or default_ttl_seconds),
    )


class InMemoryDisruptionStore:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._items: dict[str, dict[str, Disruption]] = {}
        self._lock = threading.Lock()

    def _live(self, station_id: str) -> dict[str, Disruption]:
        now = self._clock.now()
        events = self._items.setdefault(station_id, {})
        for key in [k for k, d in events.items() if d.expires_at <= now]:
            del events[key]
        return events

    def list(self, station_id: str) -> list[Disruption]:
        with self._lock:
            return sorted(self._live(station_id).values(), key=lambda d: (d.created_at, d.id))

    def add(self, disruption: Disruption) -> None:
        with self._lock:
            self._live(disruption.station_id)[disruption.id] = disruption

    def delete(self, station_id: str, disruption_id: str) -> bool:
        with self._lock:
            return self._live(station_id).pop(disruption_id, None) is not None

    def clear(self, station_id: str) -> int:
        with self._lock:
            n = len(self._live(station_id))
            self._items[station_id] = {}
            return n


class RedisDisruptionStore:
    """One key per disruption (``SET ... EX ttl``) plus a per-station sorted-set index scored by expiry time.
    The index expires with its longest-lived member, so nothing outlives its TTL."""

    def __init__(self, client: Redis, clock: Clock, prefix: str = "rs") -> None:
        self._r = client
        self._clock = clock
        self._prefix = prefix

    def _index(self, station_id: str) -> str:
        return f"{self._prefix}:navdis:{station_id}"

    def _key(self, station_id: str, disruption_id: str) -> str:
        return f"{self._prefix}:navdis:{station_id}:{disruption_id}"

    def list(self, station_id: str) -> list[Disruption]:
        index = self._index(station_id)
        now = self._clock.now()
        self._r.zremrangebyscore(index, "-inf", now.timestamp())
        ids = self._r.zrange(index, 0, -1)
        if not ids:
            return []
        raws = self._r.mget([self._key(station_id, i) for i in ids])
        events = [Disruption.model_validate_json(raw) for raw in raws if raw is not None]
        gone = [i for i, raw in zip(ids, raws) if raw is None]
        if gone:
            self._r.zrem(index, *gone)
        return sorted((d for d in events if d.expires_at > now), key=lambda d: (d.created_at, d.id))

    def add(self, disruption: Disruption) -> None:
        ttl = max(1, int((disruption.expires_at - self._clock.now()).total_seconds()))
        index = self._index(disruption.station_id)
        # One MULTI/EXEC: the index never exists without a TTL. NX gives a fresh index this TTL; GT only ever
        # lengthens it, so the index lives as long as its longest-lived member (Redis >= 7).
        pipe = self._r.pipeline(transaction=True)
        pipe.set(self._key(disruption.station_id, disruption.id), disruption.model_dump_json(), ex=ttl)
        pipe.zadd(index, {disruption.id: disruption.expires_at.timestamp()})
        pipe.expire(index, ttl + 1, nx=True)
        pipe.expire(index, ttl + 1, gt=True)
        pipe.execute()

    def delete(self, station_id: str, disruption_id: str) -> bool:
        removed = self._r.zrem(self._index(station_id), disruption_id)
        self._r.delete(self._key(station_id, disruption_id))
        return bool(removed)

    def clear(self, station_id: str) -> int:
        index = self._index(station_id)
        ids = self._r.zrange(index, 0, -1)
        n = len(self.list(station_id))
        if ids:
            self._r.delete(*[self._key(station_id, i) for i in ids])
        self._r.delete(index)
        return n


def build_disruption_store(clock: Clock, redis: Redis | None, prefix: str) -> DisruptionStore:
    if redis is not None:
        return RedisDisruptionStore(redis, clock, prefix)
    return InMemoryDisruptionStore(clock)
