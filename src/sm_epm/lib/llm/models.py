"""The approved models. ``LLM`` and ``Agent`` accept only these.

Each member is the provider's model ID (it's a ``str``), plus the provider that serves it and a
short description for anyone choosing between them:

    from sm_epm.lib.llm import Model

    LLM(Model.CLAUDE_SONNET_5)
    for m in Model:
        print(m, m.provider, m.description)

To approve another model, add a member here. That's also the way to use a deployment name on an
OpenAI-compatible gateway: add it with provider ``'openai'`` and pass that gateway's client to
``LLM(..., client=...)``.
"""

from __future__ import annotations

from enum import StrEnum


class Model(StrEnum):
    # Anthropic. IDs from Anthropic's current model list (2026-09-24).
    CLAUDE_OPUS_5 = 'claude-opus-5', 'anthropic', 'Most capable Claude for everyday work. The default.'
    CLAUDE_SONNET_5 = 'claude-sonnet-5', 'anthropic', 'Faster and cheaper than Opus; good for high-volume or simpler agents.'
    CLAUDE_HAIKU_4_5 = 'claude-haiku-4-5', 'anthropic', 'Fastest and cheapest Claude; for simple, high-volume tasks.'

    # OpenAI. Not yet checked against the OpenAI models API (no key as of 2026-09-24).
    GPT_5 = 'gpt-5', 'openai', 'OpenAI flagship model.'
    GPT_5_MINI = 'gpt-5-mini', 'openai', 'Smaller, cheaper OpenAI model.'

    provider: str
    description: str

    def __new__(cls, model_id: str, provider: str, description: str) -> Model:
        member = str.__new__(cls, model_id)
        member._value_ = model_id
        member.provider = provider
        member.description = description
        return member


DEFAULT_MODEL = Model.CLAUDE_OPUS_5
