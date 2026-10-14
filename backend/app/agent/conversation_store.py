"""Ticketing-agent conversation history, keyed by the verified session and the conversation id.

Only the passenger's messages and the agent's final (URL-sanitised) answers are stored: never tool output, which
is untrusted, and never provider-native state. Every conversation has a TTL and a bounded length.

`RedisConversationStore` (Memorystore in production, shared across instances): one Redis list per conversation,
appended with RPUSH + LTRIM + EXPIRE in a single MULTI so concurrent turns never corrupt it.
`InMemoryConversationStore`: tests and single-process development.
"""

import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from typing import Protocol

from redis import Redis

from app.llm.base import ChatMessage

CONVERSATION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_CONVERSATION_ID = re.compile(CONVERSATION_ID_PATTERN)


def new_conversation_id() -> str:
    return f"conv_{secrets.token_urlsafe(18)}"


def is_valid_conversation_id(value: str) -> bool:
    return bool(_CONVERSATION_ID.match(value or ""))


def _encode(role: str, text: str) -> str:
    return json.dumps({"role": role, "text": text}, ensure_ascii=False)


def _decode(raw: str | bytes) -> ChatMessage | None:
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("role") not in ("user", "assistant") or not isinstance(doc.get("text"), str):
        return None
    return ChatMessage(role=doc["role"], text=doc["text"])


class ConversationStore(Protocol):
    def load(self, session_id: str, conversation_id: str) -> list[ChatMessage]: ...

    def append_turn(self, session_id: str, conversation_id: str, user_text: str, answer: str) -> None: ...


class InMemoryConversationStore:
    def __init__(self, ttl_seconds: int, max_messages: int, max_conversations: int = 1000) -> None:
        self._ttl = ttl_seconds
        self._max_messages = max_messages
        self._max_conversations = max_conversations
        self._items: OrderedDict[tuple[str, str], tuple[float, list[str]]] = OrderedDict()
        self._lock = threading.Lock()

    def load(self, session_id: str, conversation_id: str) -> list[ChatMessage]:
        with self._lock:
            item = self._items.get((session_id, conversation_id))
            if item is None:
                return []
            expires, raws = item
            if time.monotonic() >= expires:
                del self._items[(session_id, conversation_id)]
                return []
            return [m for m in map(_decode, raws) if m is not None]

    def append_turn(self, session_id: str, conversation_id: str, user_text: str, answer: str) -> None:
        key = (session_id, conversation_id)
        with self._lock:
            _, raws = self._items.pop(key, (0.0, []))
            raws = (raws + [_encode("user", user_text), _encode("assistant", answer)])[-self._max_messages:]
            self._items[key] = (time.monotonic() + self._ttl, raws)
            while len(self._items) > self._max_conversations:
                self._items.popitem(last=False)


class RedisConversationStore:
    def __init__(self, client: Redis, ttl_seconds: int, max_messages: int, prefix: str = "rs") -> None:
        self._r = client
        self._ttl = ttl_seconds
        self._max_messages = max_messages
        self._prefix = prefix

    def _key(self, session_id: str, conversation_id: str) -> str:
        return f"{self._prefix}:conv:{session_id}:{conversation_id}"

    def load(self, session_id: str, conversation_id: str) -> list[ChatMessage]:
        raws = self._r.lrange(self._key(session_id, conversation_id), -self._max_messages, -1)
        return [m for m in map(_decode, raws) if m is not None]

    def append_turn(self, session_id: str, conversation_id: str, user_text: str, answer: str) -> None:
        key = self._key(session_id, conversation_id)
        pipe = self._r.pipeline(transaction=True)
        pipe.rpush(key, _encode("user", user_text), _encode("assistant", answer))
        pipe.ltrim(key, -self._max_messages, -1)
        pipe.expire(key, self._ttl)
        pipe.execute()
