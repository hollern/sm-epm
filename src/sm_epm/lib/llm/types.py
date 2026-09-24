"""Provider-neutral request and response types used by the ``LLM`` facade.

Agents build and read these. Only the backends know how they map to Anthropic or OpenAI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# end_turn: the model finished. tool_use: it wants tool results. max_tokens: output was cut off.
# refusal: the provider declined the request. pause: resend the conversation as-is to continue.
StopReason = Literal['end_turn', 'tool_use', 'max_tokens', 'refusal', 'pause']


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of an object


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    # The raw argument string when the provider returned JSON that doesn't parse.
    invalid_arguments: str | None = None


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    role: Literal['user', 'assistant', 'tool_results']
    text: str = ''
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    # The provider's own form of an assistant turn, replayed unchanged to the same provider.
    # Anthropic needs this to pass thinking blocks back.
    provider: str | None = None
    native: Any = field(default=None, compare=False, repr=False)

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role='user', text=text)

    @classmethod
    def results(cls, results: tuple[ToolResult, ...]) -> Message:
        return cls(role='tool_results', tool_results=results)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


@dataclass(frozen=True)
class Completion:
    message: Message
    stop_reason: StopReason
    usage: Usage
    model: str
