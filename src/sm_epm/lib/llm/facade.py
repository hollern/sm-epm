"""``LLM``: one interface over the Anthropic and OpenAI APIs.

This is a facade. Callers pick one of the approved models in ``Model``, then call ``complete()`` with
provider-neutral ``Message`` and ``ToolSpec`` objects. Each provider's SDK, request shape, tool
format and stop reasons stay behind a backend in this package, so nothing outside ``sm_epm.lib.llm``
imports ``anthropic`` or ``openai``. SDK exceptions are converted to ``sm_epm.lib.errors`` classes
(``RateLimitError``, ``AuthenticationError`` and so on) before they leave a backend.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from sm_epm.lib.env import load_env
from sm_epm.lib.errors import ConfigurationError
from sm_epm.lib.llm.models import DEFAULT_MODEL, Model
from sm_epm.lib.llm.types import Completion, Message, ToolSpec

DEFAULT_MAX_TOKENS = 16000


class Backend(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        max_tokens: int,
    ) -> Completion: ...


class LLM:
    """An approved model from either provider behind the same interface:

        LLM()                          # Model.CLAUDE_OPUS_5, the default
        LLM(Model.CLAUDE_SONNET_5)
        LLM('gpt-5')                   # a registered model ID works too

    Only models in ``Model`` are accepted, and each knows its provider. Only API keys come from
    the environment or ``.env`` (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``), and only for the
    provider actually used.

    Args:
        model: A ``Model`` member or its ID.
        max_tokens: Cap on output tokens per response.
        client: A pre-built SDK client (``anthropic.Anthropic`` / ``openai.OpenAI``), for tests or
            custom endpoints. By default one is built from the environment.
        **options: Provider-specific settings, passed to the backend. Anthropic: ``effort``
            (``'low'`` to ``'max'``), ``fallbacks`` (bool), ``cache`` (bool). OpenAI:
            ``reasoning_effort``.

    Raises:
        ConfigurationError: the model isn't in ``Model``, or there are no credentials for its
            provider.
    """

    def __init__(
        self,
        model: Model | str = DEFAULT_MODEL,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,
        **options: Any,
    ) -> None:
        self.model = resolve_model(model)
        self.provider = self.model.provider
        self.max_tokens = max_tokens
        self._backend = _build_backend(self.provider, client, options)

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str = '',
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        """Send one request and return the model's next turn."""
        return self._backend.complete(
            model=self.model.value,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=self.max_tokens,
        )

    def ask(self, prompt: str, *, system: str = '') -> str:
        """Send a single prompt with no tools and return the reply text."""
        return self.complete([Message.user(prompt)], system=system).message.text

    def __repr__(self) -> str:
        return f'LLM({self.model.value!r}, provider={self.provider!r})'


def resolve_model(model: Model | str) -> Model:
    """The ``Model`` for a member or model ID. Anything unregistered is rejected."""
    try:
        return Model(model)
    except ValueError:
        approved = ', '.join(m.value for m in Model)
        raise ConfigurationError(
            f'model {model!r} is not approved. Use one of: {approved}. To approve another, add it to '
            'sm_epm.lib.llm.models.Model',
            service='llm',
        ) from None


def _build_backend(provider: str, client: Any, options: dict[str, Any]) -> Backend:
    if client is None:
        # The SDK reads its API key from the environment, so .env must be loaded first.
        load_env()
    # Imported here so an unused provider's SDK is never loaded.
    if provider == 'anthropic':
        from sm_epm.lib.llm._anthropic import AnthropicBackend

        return AnthropicBackend(client, **options)
    from sm_epm.lib.llm._openai import OpenAIBackend

    return OpenAIBackend(client, **options)
