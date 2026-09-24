# Agents and the LLM facade

Agents in this project subclass `sm_epm.lib.agents.Agent` and run on Anthropic or OpenAI models through a single facade, `sm_epm.lib.llm.LLM`.

```python
from sm_epm.lib.agents import Agent, AnaplanToolkit, PigmentToolkit, tool
from sm_epm.lib.llm import LLM, Model


class ReconAgent(Agent):
    system_prompt = 'You reconcile Anaplan and Pigment opex ...'
    model = Model.CLAUDE_OPUS_5                    # the agent's model, chosen in code

    def default_toolkits(self):
        return [AnaplanToolkit(), PigmentToolkit()]

    @tool
    def fx_rate(self, currency: str) -> float:
        """Latest USD rate for a currency."""
        ...


agent = ReconAgent()                               # ReconAgent.model
agent = ReconAgent(Model.GPT_5)                    # another approved model
agent = ReconAgent(LLM(Model.CLAUDE_OPUS_5, effort='high'))  # an LLM, for provider options
result = agent.run('Do the Q3 vendor totals match?')
result.text, result.stop_reason, result.usage
agent.llm = Model.CLAUDE_SONNET_5                  # swap the model; the conversation carries over
agent.run('Break that down by department.')
```

## Where agents live

Implemented agents go in `src/sm_epm/agents/`, one module per agent. The building blocks stay in `src/sm_epm/lib/`, which must not import from `agents/`. Each agent module:

- subclasses `Agent`, sets `system_prompt`, and returns its toolkits from `default_toolkits()`
- adds any agent-specific tools as `@tool` methods
- has a `QUESTION` constant and an `if __name__ == '__main__':` block, so running the file asks it once (there's no CLI)
- has a test in `tests/agents/` that uses a scripted fake `LLM`, so it never calls a model

**Sample:** `sm_epm/agents/epm_explorer.py` (`EPMExplorer`) answers questions about where things live in Anaplan and Pigment and what the data says. It uses both read-only toolkits plus a `today` tool, so it can tell actuals months from forecast months.

## Layout

- `lib/llm/`: the facade. `LLM` is the only class callers use, and `models.py` holds `Model`, the registry of approved models, and `types.py` holds the provider-neutral `Message`, `ToolCall`, `ToolResult`, `ToolSpec`, `Completion` and `Usage`. `_anthropic.py` and `_openai.py` are the backends. **Nothing outside `lib/llm/` may import `anthropic` or `openai`.**
- `lib/agents/base.py`: `Agent`. `run()` sends the prompt, runs every tool the model calls (errors go back to the model as error results), and loops until the model stops or `max_turns` is hit.
- `lib/agents/tools.py`: `@tool` turns a method into a tool. The docstring becomes the description, and the signature becomes the JSON schema (pydantic). Use `Annotated[T, Field(description=...)]` to describe a parameter. Return values are rendered as text: DataFrames as CSV (first 200 rows plus shape and pages), pydantic models and lists as JSON, capped at 20,000 characters.
- `lib/agents/toolkits.py`: `AnaplanToolkit` and `PigmentToolkit`, read-only tools for browsing and reading both systems (they use `lib.anaplan.data` / `lib.pigment.data`, see [dataframes.md](dataframes.md)).

## Configuration

Models are chosen in code, never in `.env`, and only from the approved list in `sm_epm.lib.llm.Model`:

| Member | Model ID | Provider | Use |
|---|---|---|---|
| `CLAUDE_OPUS_5` (default) | `claude-opus-5` | Anthropic | Most capable Claude for everyday work |
| `CLAUDE_SONNET_5` | `claude-sonnet-5` | Anthropic | Faster and cheaper; high-volume or simpler agents |
| `CLAUDE_HAIKU_4_5` | `claude-haiku-4-5` | Anthropic | Fastest and cheapest; simple, high-volume tasks |
| `GPT_5` | `gpt-5` | OpenAI | OpenAI flagship |
| `GPT_5_MINI` | `gpt-5-mini` | OpenAI | Smaller, cheaper OpenAI model |

`LLM(model)` and `Agent(model)` take a member or its ID string. Anything else raises `ConfigurationError` listing the approved IDs. `for m in Model: m, m.provider, m.description` lists them, for example for a picker. `LLM()` with no model is `Model.CLAUDE_OPUS_5`, and an agent's default is its `model` class attribute. To approve a model, add a member to `Model` with its ID, provider and a one-line description. A deployment name on an OpenAI-compatible gateway is added the same way, with provider `openai`, and used with `LLM(..., client=openai.OpenAI(base_url=...))`. `.env` holds only API keys, `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, and only the key for the provider in use is needed. Missing credentials raise `ConfigurationError` when the `LLM` is built, not on the first request. `LLM(...)` keyword options go to the backend. For Anthropic they are `effort`, `fallbacks` and `cache`. For OpenAI it's `reasoning_effort`. `client=` takes a pre-built SDK client, for example an OpenAI-compatible endpoint built with `base_url=`.

## Errors

The backends convert SDK exceptions to `sm_epm.lib.errors` classes (see [error-handling.md](error-handling.md)), so `LLM.complete()` and `Agent.run()` raise `RateLimitError`, `AuthenticationError` and so on whichever provider is behind them. Errors inside a tool, including `EPMError`s from Anaplan or Pigment, don't propagate: they go back to the model as error results, so it can try something else. Agent setup mistakes (duplicate tool names, a tool with `**kwargs`) raise `ConfigurationError`.

## Decisions

### Facade over the Anthropic and OpenAI APIs
All model calls go through `LLM.complete(messages, system=, tools=)`. Each backend translates the neutral types to its SDK's request shape and normalizes the response and stop reason (`end_turn`, `tool_use`, `max_tokens`, `refusal`, `pause`).
**Why:** user direction. It also means agents are provider-agnostic, and a new provider is one backend file.
**Date:** 2026-09-24

### Hand-written tool loop instead of either SDK's agent helpers
`Agent.run()` owns the loop.
**Why:** the SDK tool runners are provider-specific, which would defeat the facade.
**Date:** 2026-09-24

### Anthropic defaults: `claude-opus-5`, `beta.messages.create`, refusal fallbacks and prompt caching on
Thinking is left at the model default (adaptive on current models). Assistant turns keep the original content blocks (`Message.native`) and replay them unchanged, which the API requires for thinking blocks. Server-side refusal fallbacks (`fallbacks='default'`, beta `server-side-fallback-2026-07-01`) are on by default for `claude-opus-5` and `claude-fable-5-1`, so a safety decline is retried on a fallback model inside the same call. Automatic prompt caching (`cache_control`) is on because agents resend the whole history every turn.
**Why:** these are the current Anthropic recommendations for these models. Pass `fallbacks=False` or `cache=False` to turn them off.
**Date:** 2026-09-24

### Only approved models, from a registry in code
`sm_epm.lib.llm.models.Model` lists every model that may be used, with its provider and a description. `LLM` rejects anything else, and the provider comes from the registry, so there's no `provider=` argument or ID-prefix guessing.
**Why:** user direction, so end users pick from models that have been accepted, and approving a new one is a reviewed one-line change.
**Date:** 2026-09-24

### Models are chosen and swapped in code, not in `.env`
`LLM(model)` takes an approved model. Each agent sets its `model` class attribute, a constructor argument overrides it, and assigning `agent.llm` (a model ID or an `LLM`) swaps the model mid-conversation. That works because the history is provider-neutral: turns from the same provider are replayed unchanged, and turns from the other provider are rebuilt from the neutral fields.
**Why:** user direction. Which model an agent uses is part of its code, and switching or comparing models shouldn't mean editing `.env`. This replaces `LLM.from_env()` and the `LLM_PROVIDER` / `LLM_MODEL` variables.
**Date:** 2026-09-24

### Credentials are checked when the `LLM` is built
The Anthropic backend checks that the SDK resolved some credential (`api_key`, `auth_token`, or a `credentials` provider from an `ant auth login` profile or workload identity). The OpenAI SDK already checks when its client is built. Both raise `ConfigurationError` naming the env var to set.
**Why:** the Anthropic SDK otherwise waits until the first request and raises a bare `TypeError` (`Could not resolve authentication method`), which the error boundary deliberately doesn't convert. Checking only `ANTHROPIC_API_KEY` would wrongly reject profile logins.
**Date:** 2026-09-24

### OpenAI uses Chat Completions
**Why:** Chat Completions also works with OpenAI-compatible gateways.
**Date:** 2026-09-24

### Toolkits are read-only
The shared toolkits never write to Anaplan or Pigment.
**Why:** the default Anaplan model is production (see [clients-and-auth.md](clients-and-auth.md)). If an agent needs a write tool, define it on that agent, with its own confirmation step.
**Date:** 2026-09-24

## Learnings

- `anthropic` 1.x and `openai` 3.x are installed. `fallbacks` and `cache_control` exist only on `client.beta.messages.create` in `anthropic` 1.8.
- A run that stops while the model is mid-tool-call (for example `max_tokens`) leaves calls without results, which both APIs reject on the next request. `Agent.run()` answers them with `Error: not run` before sending the next prompt.
- Tool results are sent back to the model provider. Agents using the toolkits send Anaplan and Pigment data (including vendor names) to Anthropic or OpenAI, so check that this is allowed for the data an agent reads.
- The OpenAI registry entries (`gpt-5`, `gpt-5-mini`) haven't been checked against the OpenAI models API, because there's no key. Check them before relying on them. The Anthropic IDs come from Anthropic's current model list.
- `LLM(...)` loads `.env` itself before building an SDK client, so keys in `.env` are found however the `LLM` is created.
- As of 2026-09-24 there are no LLM API keys in `.env`. The loop and both backends are tested only against fake clients built from the SDKs' own response types (`tests/lib/llm/`, `tests/lib/agents/`).
