"""
RailSathi AI — Conversation Manager

Server-side conversation state management with bounded history,
session isolation, and no persistent storage of sensitive data.
"""

import uuid
import time
import threading
from typing import Any
from google.genai import types


class ConversationManager:
    """
    In-memory conversation store with bounded history and session isolation.

    For production, this should be replaced with a persistent store (Redis, DB).
    For the current prototype, in-memory is sufficient with documented limitations.
    """

    # Limitations documented:
    # - Conversations are lost on server restart
    # - No authentication — security relies on unguessable session IDs
    # - Single-process only — not suitable for multi-worker deployment

    def __init__(self, max_history: int = 20, max_conversations: int = 1000,
                 conversation_ttl: int = 3600):
        """
        Args:
            max_history: Maximum number of messages per conversation.
            max_conversations: Maximum concurrent conversations.
            conversation_ttl: Time-to-live in seconds for inactive conversations.
        """
        self.max_history = max_history
        self.max_conversations = max_conversations
        self.conversation_ttl = conversation_ttl
        self._store: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_conversation(self) -> str:
        """Create a new conversation and return its ID."""
        with self._lock:
            # Enforce max conversations
            if len(self._store) >= self.max_conversations:
                self._evict_oldest()

            conversation_id = f"conv-{uuid.uuid4().hex[:16]}"
            self._store[conversation_id] = {
                "history": [],
                "created_at": time.time(),
                "last_active": time.time(),
                "topic_context": None,
                "source_ids_seen": set(),
            }
            return conversation_id

    def get_or_create(self, conversation_id: str | None) -> tuple[str, list[types.Content]]:
        """
        Get an existing conversation's history or create a new one.

        Returns:
            (conversation_id, history) tuple.
        """
        if conversation_id and conversation_id in self._store:
            with self._lock:
                conv = self._store[conversation_id]
                conv["last_active"] = time.time()
                return conversation_id, list(conv["history"])

        # Create new
        new_id = self.create_conversation()
        return new_id, []

    def add_exchange(self, conversation_id: str,
                     user_content: types.Content,
                     model_content: types.Content,
                     tool_contents: list[types.Content] | None = None) -> None:
        """
        Add a user-model exchange to conversation history.

        Enforces the max_history limit by trimming oldest messages.
        """
        with self._lock:
            if conversation_id not in self._store:
                return

            conv = self._store[conversation_id]
            conv["history"].append(user_content)

            if tool_contents:
                for tc in tool_contents:
                    conv["history"].append(tc)

            conv["history"].append(model_content)
            conv["last_active"] = time.time()

            # Trim to max_history (keeping most recent)
            if len(conv["history"]) > self.max_history:
                conv["history"] = conv["history"][-self.max_history:]

    def get_conversation_info(self, conversation_id: str) -> dict | None:
        """Get conversation metadata (not history) for an ID."""
        with self._lock:
            conv = self._store.get(conversation_id)
            if not conv:
                return None
            return {
                "conversation_id": conversation_id,
                "message_count": len(conv["history"]),
                "created_at": conv["created_at"],
                "last_active": conv["last_active"],
            }

    def _evict_oldest(self) -> None:
        """Remove the oldest inactive conversation."""
        if not self._store:
            return

        # First try to evict expired conversations
        now = time.time()
        expired = [
            cid for cid, conv in self._store.items()
            if now - conv["last_active"] > self.conversation_ttl
        ]
        for cid in expired:
            del self._store[cid]

        # If still at capacity, remove the oldest
        if len(self._store) >= self.max_conversations:
            oldest = min(self._store.items(), key=lambda x: x[1]["last_active"])
            del self._store[oldest[0]]
