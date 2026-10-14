"""Scripted `ChatLLM` for tests: replays a fixed list of turns and records every request."""

from collections.abc import Sequence

from app.llm.base import ChatMessage, Deadline, LLMError, LLMTurn, ToolCall, ToolSpec

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
