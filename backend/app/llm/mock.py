"""Scripted `ChatLLM` and `VisionLocalizer` for tests: replay fixed answers and record every request."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.llm.base import ChatMessage, Deadline, LLMError, LLMTurn, ToolCall, ToolSpec

if TYPE_CHECKING:
    from app.llm.vision import LocalizeHint, LocalizeResult
    from app.navigation.models.station import Station

ScriptItem = str | list[ToolCall] | LLMTurn | LLMError


class MockChatLLM:
    name = "mock"

    def __init__(self, script: Sequence[ScriptItem]) -> None:
        self._script = list(script)
        self.calls: list[list[ChatMessage]] = []
        self.tools: list[list[ToolSpec]] = []

    def generate(self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec], deadline: Deadline) -> LLMTurn:
        self.calls.append(list(messages))
        self.tools.append(list(tools))
        if not self._script:
            return LLMTurn(text="")
        item = self._script.pop(0)
        if isinstance(item, LLMError):
            raise item
        if isinstance(item, LLMTurn):
            return item
        if isinstance(item, str):
            return LLMTurn(text=item)
        return LLMTurn(tool_calls=tuple(item))


class MockVisionLocalizer:
    """Scripted `VisionLocalizer` for tests: replays results (or raises LLMErrors) and records each call's
    station, hint and image size (never the image itself)."""

    name = "mock-vision"

    def __init__(self, script: Sequence["LocalizeResult | LLMError"]) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

    def localize(self, image_bytes: bytes, mime_type: str, station: "Station", hint: "LocalizeHint",
                 deadline: Deadline) -> "LocalizeResult":
        from app.llm.vision import LocalizeResult

        self.calls.append({"station_id": station.station_id, "mime_type": mime_type, "bytes": len(image_bytes),
                           "hint": hint})
        item = self._script.pop(0) if self._script else LocalizeResult(node_id=None, confidence=0.0)
        if isinstance(item, LLMError):
            raise item
        return item
