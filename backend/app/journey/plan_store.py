"""Goal plans keyed by a server-issued `plan_id` and bound to the session that created them.

`PlanStore` is the protocol; `RedisPlanStore` is used whenever the container has Redis (Memorystore in
production, shared across instances, every key with a TTL); `InMemoryPlanStore` is for tests and single-process
development. Ownership is checked by `load_owned`, which treats a foreign id exactly like an unknown one."""

import hmac
import json
import secrets
import threading
import time
from collections import OrderedDict
from typing import Any, Protocol

from redis import Redis


class PlanStore(Protocol):
    def save(self, plan_id: str, owner: str, payload: dict[str, Any]) -> None: ...

    def load(self, plan_id: str) -> tuple[str, dict[str, Any]] | None: ...


def new_plan_id() -> str:
    return f"plan_{secrets.token_urlsafe(18)}"


def load_owned(store: PlanStore, plan_id: str, owner: str) -> dict[str, Any] | None:
    """The stored payload, or None when the plan is unknown, expired or belongs to another session."""
    found = store.load(plan_id)
    if found is None:
        return None
    stored_owner, payload = found
    return payload if hmac.compare_digest(stored_owner.encode(), owner.encode()) else None


class InMemoryPlanStore:
    def __init__(self, ttl_seconds: int, max_entries: int = 1000) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._items: OrderedDict[str, tuple[float, str, str]] = OrderedDict()
        self._lock = threading.Lock()

    def save(self, plan_id: str, owner: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._items.pop(plan_id, None)
            self._items[plan_id] = (time.monotonic() + self._ttl, owner, json.dumps(payload))
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def load(self, plan_id: str) -> tuple[str, dict[str, Any]] | None:
        with self._lock:
            item = self._items.get(plan_id)
            if item is None:
                return None
            expires, owner, raw = item
            if time.monotonic() >= expires:
                del self._items[plan_id]
                return None
            return owner, json.loads(raw)


class RedisPlanStore:
    def __init__(self, client: Redis, ttl_seconds: int, prefix: str = "rs") -> None:
        self._r = client
        self._ttl = ttl_seconds
        self._prefix = prefix

    def _key(self, plan_id: str) -> str:
        return f"{self._prefix}:plan:{plan_id}"

    def save(self, plan_id: str, owner: str, payload: dict[str, Any]) -> None:
        self._r.set(self._key(plan_id), json.dumps({"owner": owner, "payload": payload}), ex=self._ttl)

    def load(self, plan_id: str) -> tuple[str, dict[str, Any]] | None:
        raw = self._r.get(self._key(plan_id))
        if raw is None:
            return None
        doc = json.loads(raw)
        return doc["owner"], doc["payload"]
