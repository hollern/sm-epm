"""Provider-agnostic access to Anthropic and OpenAI models through the ``LLM`` facade."""

from sm_epm.lib.llm.facade import LLM
from sm_epm.lib.llm.models import DEFAULT_MODEL, Model
from sm_epm.lib.llm.types import Completion, Message, StopReason, ToolCall, ToolResult, ToolSpec, Usage

__all__ = ['LLM', 'Model', 'DEFAULT_MODEL', 'Completion', 'Message', 'StopReason', 'ToolCall', 'ToolResult', 'ToolSpec', 'Usage']
