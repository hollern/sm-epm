"""Anthropic Messages API backend for the ``LLM`` facade."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import anthropic

from sm_epm.lib.errors import ConfigurationError
from sm_epm.lib.llm._errors import sdk_errors
from sm_epm.lib.llm.types import Completion, Message, StopReason, ToolCall, ToolSpec, Usage

# Server-side refusal fallbacks: on a safety decline the API reruns the request on a fallback
# model it picks by refusal category, inside the same call.
FALLBACK_BETA = 'server-side-fallback-2026-07-01'
FALLBACK_MODELS = frozenset({'claude-opus-5', 'claude-fable-5-1'})

_errors = sdk_errors(anthropic, anthropic.AnthropicError, 'anthropic')

_STOP_REASONS: dict[str, StopReason] = {
    'end_turn': 'end_turn',
    'stop_sequence': 'end_turn',
    'tool_use': 'tool_use',
    'max_tokens': 'max_tokens',
    'model_context_window_exceeded': 'max_tokens',
    'refusal': 'refusal',
    'pause_turn': 'pause',
}


class AnthropicBackend:
    """Calls ``client.beta.messages.create``. Thinking is left at the model's default (adaptive on
    current models), and assistant turns are replayed with their original content blocks so
    thinking blocks go back unchanged.

    Args:
        effort: ``output_config.effort``. None keeps the model's default.
        fallbacks: Turn server-side refusal fallbacks on or off. None turns them on for the
            models in ``FALLBACK_MODELS``.
        cache: Automatic prompt caching of the conversation prefix. Agents resend the whole
            history every turn, so this is on by default.
    """

    def __init__(self, client: Any = None, *, effort: str | None = None, fallbacks: bool | None = None, cache: bool = True):
        if client is None:
            with _errors:
                client = anthropic.Anthropic()
            _require_credentials(client)
        self._client = client
        self._effort = effort
        self._fallbacks = fallbacks
        self._cache = cache

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        max_tokens: int,
    ) -> Completion:
        request: dict[str, Any] = {
            'model': model,
            'max_tokens': max_tokens,
            'messages': [n for n in map(_to_native, messages) if n['content']],
        }
        if system:
            request['system'] = system
        if tools:
            request['tools'] = [{'name': t.name, 'description': t.description, 'input_schema': t.parameters} for t in tools]
        if self._effort:
            request['output_config'] = {'effort': self._effort}
        if self._cache:
            request['cache_control'] = {'type': 'ephemeral'}
        if self._fallbacks if self._fallbacks is not None else model in FALLBACK_MODELS:
            request['betas'] = [FALLBACK_BETA]
            request['fallbacks'] = 'default'

        with _errors:
            response = self._client.beta.messages.create(**request)

        blocks = response.content
        message = Message(
            role='assistant',
            text=''.join(b.text for b in blocks if b.type == 'text'),
            tool_calls=tuple(ToolCall(b.id, b.name, dict(b.input)) for b in blocks if b.type == 'tool_use'),
            provider='anthropic',
            native=blocks,
        )
        usage = response.usage
        return Completion(
            message=message,
            stop_reason=_STOP_REASONS.get(response.stop_reason or '', 'end_turn'),
            usage=Usage(
                input_tokens=usage.input_tokens
                + (usage.cache_read_input_tokens or 0)
                + (usage.cache_creation_input_tokens or 0),
                output_tokens=usage.output_tokens,
            ),
            model=response.model,
        )


def _require_credentials(client: anthropic.Anthropic) -> None:
    """Fail at construction, not on the first request. The SDK resolves credentials when the
    client is built (API key, auth token, an ``ant auth login`` profile or workload identity) but
    only complains on the first request, and then with a ``TypeError``."""
    if not (client.api_key or client.auth_token or client.credentials):
        raise ConfigurationError(
            'no Anthropic credentials found. Set ANTHROPIC_API_KEY in .env (see .env.example), '
            'or sign in with `ant auth login`',
            service='anthropic',
        )


def _to_native(message: Message) -> dict[str, Any]:
    if message.role == 'user':
        return {'role': 'user', 'content': message.text}
    if message.role == 'tool_results':
        # All results for one assistant turn go back in a single user message.
        return {
            'role': 'user',
            'content': [
                {'type': 'tool_result', 'tool_use_id': r.call_id, 'content': r.content, 'is_error': r.is_error}
                for r in message.tool_results
            ],
        }
    if message.provider == 'anthropic' and message.native is not None:
        return {'role': 'assistant', 'content': message.native}
    content: list[dict[str, Any]] = [{'type': 'text', 'text': message.text}] if message.text else []
    content += [{'type': 'tool_use', 'id': c.id, 'name': c.name, 'input': c.arguments} for c in message.tool_calls]
    return {'role': 'assistant', 'content': content}
