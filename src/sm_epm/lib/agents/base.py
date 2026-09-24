"""``Agent``: the base class every agent in this project inherits from."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import ValidationError

from sm_epm.lib.agents.tools import Tool, collect_tools
from sm_epm.lib.errors import ConfigurationError, EPMError
from sm_epm.lib.llm import DEFAULT_MODEL, LLM, Message, Model, StopReason, ToolCall, ToolResult, Usage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentResult:
    text: str
    # max_turns: the agent hit Agent.max_turns while the model was still calling tools.
    stop_reason: StopReason | Literal['max_turns']
    turns: int
    usage: Usage
    tool_calls: tuple[ToolCall, ...]


class Agent:
    """A tool-using agent that runs on any model behind the ``LLM`` facade.

    Subclass it and set ``system_prompt``, and ``model`` (a ``Model`` member) if the agent
    shouldn't use the default.
    Give the agent tools in either or both of two ways:

    - ``@tool`` methods on the subclass itself.
    - Toolkits: objects with ``@tool`` methods, such as ``AnaplanToolkit`` and
      ``PigmentToolkit``. Return them from ``default_toolkits()``, or pass ``toolkits=``.

    ``run()`` sends a prompt, runs every tool the model calls, and loops until the model stops
    calling tools. The conversation is kept, so a second ``run()`` continues it. ``reset()``
    clears it.

    The model can be changed at any time, including between two ``run()`` calls in one
    conversation, because the history is provider-neutral:

        agent = VarianceAgent()                        # its class's model
        agent = VarianceAgent(Model.GPT_5)             # another approved model, or an LLM(...)
        agent.llm = Model.CLAUDE_SONNET_5              # swap; the conversation carries over

    Errors from the model provider (``sm_epm.lib.errors`` classes) propagate out of ``run()``.
    Errors inside a tool don't: they go back to the model as error results.

    Example:
        class VarianceAgent(Agent):
            system_prompt = 'You explain forecast variances ...'

            def default_toolkits(self):
                return [AnaplanToolkit(), PigmentToolkit()]

        VarianceAgent().run('Why did Q3 opex move?').text
    """

    system_prompt: ClassVar[str] = ''
    model: ClassVar[Model] = DEFAULT_MODEL
    max_turns: ClassVar[int] = 25

    def __init__(self, llm: LLM | Model | str | None = None, *, toolkits: Sequence[object] | None = None) -> None:
        self.llm = llm or self.model
        self.toolkits = list(self.default_toolkits() if toolkits is None else toolkits)
        self.tools = self._collect_tools()
        self.messages: list[Message] = []

    @property
    def llm(self) -> LLM:
        return self._llm

    @llm.setter
    def llm(self, value: LLM | Model | str) -> None:
        """Accepts an ``LLM``, or a ``Model`` or its ID, which is wrapped in ``LLM(model)``."""
        self._llm = LLM(value) if isinstance(value, str) else value

    def default_toolkits(self) -> list[object]:
        """Toolkits used when none are passed to the constructor."""
        return []

    def instructions(self) -> str:
        """The system prompt for each request. Override to build it dynamically."""
        return self.system_prompt

    def run(self, prompt: str) -> AgentResult:
        self._close_unanswered_calls()
        self.messages.append(Message.user(prompt))
        specs = [t.spec for t in self.tools.values()]
        usage = Usage()
        calls: list[ToolCall] = []

        for turn in range(1, self.max_turns + 1):
            completion = self.llm.complete(self.messages, system=self.instructions(), tools=specs)
            self.messages.append(completion.message)
            usage += completion.usage

            if completion.stop_reason == 'pause':
                continue
            if completion.stop_reason != 'tool_use' or not completion.message.tool_calls:
                return AgentResult(completion.message.text, completion.stop_reason, turn, usage, tuple(calls))

            results = tuple(self.call_tool(c) for c in completion.message.tool_calls)
            calls.extend(completion.message.tool_calls)
            self.messages.append(Message.results(results))

        return AgentResult(completion.message.text, 'max_turns', self.max_turns, usage, tuple(calls))

    def reset(self) -> None:
        self.messages.clear()

    def call_tool(self, call: ToolCall) -> ToolResult:
        """Run one tool call. Failures go back to the model as error results, so it can recover."""
        logger.info('%s: calling %s(%s)', type(self).__name__, call.name, call.arguments)
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, f'Error: there is no tool named {call.name!r}', is_error=True)
        if call.invalid_arguments is not None:
            return ToolResult(call.id, f'Error: the arguments are not valid JSON: {call.invalid_arguments}', is_error=True)
        try:
            return ToolResult(call.id, tool.run(call.arguments))
        except ValidationError as exc:
            return ToolResult(call.id, f'Error: invalid arguments for {call.name}: {exc}', is_error=True)
        except EPMError as exc:
            logger.warning('%s: %s failed: %s', type(self).__name__, call.name, exc)
            return ToolResult(call.id, f'Error: {type(exc).__name__}: {exc}', is_error=True)
        except Exception as exc:
            logger.warning('%s: %s failed', type(self).__name__, call.name, exc_info=True)
            return ToolResult(call.id, f'Error: {type(exc).__name__}: {exc}', is_error=True)

    def _collect_tools(self) -> dict[str, Tool]:
        tools: dict[str, Tool] = {}
        for source in (self, *self.toolkits):
            for t in collect_tools(source):
                if t.name in tools:
                    raise ConfigurationError(f'two tools are named {t.name!r}', service='agents')
                tools[t.name] = t
        return tools

    def _close_unanswered_calls(self) -> None:
        """A run that stopped mid-tool-call (max_tokens, say) leaves calls without results, which
        both providers reject. Answer them before the next prompt."""
        last = self.messages[-1] if self.messages else None
        if last is not None and last.role == 'assistant' and last.tool_calls:
            self.messages.append(
                Message.results(tuple(ToolResult(c.id, 'Error: not run', is_error=True) for c in last.tool_calls))
            )
