"""OpenAI Chat Completions backend for the ``LLM`` facade."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import openai

from sm_epm.lib.errors import ConfigurationError
from sm_epm.lib.llm._errors import sdk_errors
from sm_epm.lib.llm.types import Completion, Message, StopReason, ToolCall, ToolSpec, Usage

_errors = sdk_errors(openai, openai.OpenAIError, 'openai')

_STOP_REASONS: dict[str, StopReason] = {
    'stop': 'end_turn',
    'tool_calls': 'tool_use',
    'length': 'max_tokens',
    'content_filter': 'refusal',
}


class OpenAIBackend:
    """Calls ``client.chat.completions.create``. Chat Completions also works with
    OpenAI-compatible endpoints: pass a client built with ``base_url=``.

    Args:
        reasoning_effort: For reasoning models, for example ``'low'`` or ``'high'``. None keeps
            the model's default.
    """

    def __init__(self, client: Any = None, *, reasoning_effort: str | None = None):
        if client is None:
            try:
                client = openai.OpenAI()
            except openai.OpenAIError as exc:
                # The SDK checks for credentials when the client is built.
                raise ConfigurationError(
                    f'no OpenAI credentials found. Set OPENAI_API_KEY in .env (see .env.example). {exc}',
                    service='openai',
                ) from exc
        self._client = client
        self._reasoning_effort = reasoning_effort

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        max_tokens: int,
    ) -> Completion:
        native: list[dict[str, Any]] = [{'role': 'system', 'content': system}] if system else []
        for m in messages:
            native.extend(_to_native(m))
        request: dict[str, Any] = {'model': model, 'messages': native, 'max_completion_tokens': max_tokens}
        if tools:
            request['tools'] = [
                {'type': 'function', 'function': {'name': t.name, 'description': t.description, 'parameters': t.parameters}}
                for t in tools
            ]
        if self._reasoning_effort:
            request['reasoning_effort'] = self._reasoning_effort

        with _errors:
            response = self._client.chat.completions.create(**request)

        choice = response.choices[0]
        reply = choice.message
        message = Message(
            role='assistant',
            text=reply.content or '',
            tool_calls=tuple(_tool_call(c) for c in reply.tool_calls or () if c.type == 'function'),
            provider='openai',
        )
        stop = 'refusal' if reply.refusal else _STOP_REASONS.get(choice.finish_reason, 'end_turn')
        usage = response.usage
        return Completion(
            message=message,
            stop_reason=stop,
            usage=Usage(usage.prompt_tokens, usage.completion_tokens) if usage else Usage(),
            model=response.model,
        )


def _tool_call(call: Any) -> ToolCall:
    raw = call.function.arguments or '{}'
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError:
        return ToolCall(call.id, call.function.name, {}, invalid_arguments=raw)
    return ToolCall(call.id, call.function.name, arguments if isinstance(arguments, dict) else {})


def _to_native(message: Message) -> list[dict[str, Any]]:
    if message.role == 'user':
        return [{'role': 'user', 'content': message.text}]
    if message.role == 'tool_results':
        return [{'role': 'tool', 'tool_call_id': r.call_id, 'content': r.content} for r in message.tool_results]
    native: dict[str, Any] = {'role': 'assistant', 'content': message.text or None}
    if message.tool_calls:
        native['tool_calls'] = [
            {
                'id': c.id,
                'type': 'function',
                'function': {'name': c.name, 'arguments': c.invalid_arguments or json.dumps(c.arguments)},
            }
            for c in message.tool_calls
        ]
    return [native]
