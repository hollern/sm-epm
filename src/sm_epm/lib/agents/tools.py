"""Turn plain Python methods into tools an agent can call.

Mark a method with ``@tool``. Its name becomes the tool name, its docstring the description, and
its signature the JSON schema (built with pydantic). Describe a parameter with
``Annotated[int, Field(description='...')]``. Arguments from the model are validated against the
signature before the method runs.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import pandas as pd
from pydantic import BaseModel, ConfigDict, create_model

from sm_epm.lib.errors import ConfigurationError
from sm_epm.lib.llm import ToolSpec

MAX_RESULT_CHARS = 20_000
MAX_RESULT_ROWS = 200

_MARKER = '__agent_tool__'
F = TypeVar('F', bound=Callable[..., Any])


def tool(fn: F | None = None, *, name: str | None = None) -> Any:
    """Mark a method as an agent tool. Use as ``@tool`` or ``@tool(name='...')``."""

    def mark(f: F) -> F:
        setattr(f, _MARKER, name or f.__name__)
        return f

    return mark(fn) if fn is not None else mark


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    args_model: type[BaseModel]

    @classmethod
    def from_function(cls, fn: Callable[..., Any], name: str | None = None) -> Tool:
        fields: dict[str, Any] = {}
        # eval_str resolves string annotations (from `from __future__ import annotations`) in fn's module.
        for param in inspect.signature(fn, eval_str=True).parameters.values():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                raise ConfigurationError(f'tool {fn.__name__}: *args and **kwargs are not supported', service='agents')
            annotation = Any if param.annotation is param.empty else param.annotation
            fields[param.name] = (annotation, ... if param.default is param.empty else param.default)
        tool_name = name or fn.__name__
        model = create_model(f'{tool_name}_arguments', __config__=ConfigDict(extra='forbid'), **fields)
        return cls(tool_name, inspect.getdoc(fn) or tool_name, fn, model)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, _strip_titles(self.args_model.model_json_schema()))

    def run(self, arguments: dict[str, Any]) -> str:
        """Validate the arguments, call the function and format its return value as text."""
        args = self.args_model.model_validate(arguments)
        return format_result(self.fn(**{k: getattr(args, k) for k in type(args).model_fields}))


def collect_tools(obj: object) -> list[Tool]:
    """Every ``@tool`` method on ``obj``'s class, bound to ``obj``."""
    tools = []
    for attr in dir(type(obj)):
        fn = inspect.getattr_static(type(obj), attr, None)
        fn = getattr(fn, '__func__', fn)  # unwrap staticmethod / classmethod
        if callable(fn) and hasattr(fn, _MARKER):
            tools.append(Tool.from_function(getattr(obj, attr), getattr(fn, _MARKER)))
    return tools


def format_result(result: Any) -> str:
    """Render a tool's return value as text the model can read, capped at ``MAX_RESULT_CHARS``."""
    if isinstance(result, pd.DataFrame):
        text = _frame_text(result)
    elif isinstance(result, str):
        text = result
    else:
        text = json.dumps(_plain(result), default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f'\n[truncated: {len(text):,} characters in total]'
    return text


def _frame_text(df: pd.DataFrame) -> str:
    shown = df.head(MAX_RESULT_ROWS)
    header = f'{len(df):,} rows x {df.shape[1]:,} columns'
    if len(df) > len(shown):
        header += f' (first {len(shown)} rows shown)'
    pages = df.attrs.get('pages')
    if pages:
        header += f'\npages: {pages}'
    has_index = not isinstance(df.index, pd.RangeIndex)
    return f'{header}\n{shown.to_csv(index=has_index)}'


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _strip_titles(schema: Any) -> Any:
    """Pydantic adds a ``title`` to every schema node. Models don't need them."""
    if isinstance(schema, dict):
        return {k: _strip_titles(v) for k, v in schema.items() if k != 'title' or not isinstance(v, str)}
    if isinstance(schema, list):
        return [_strip_titles(v) for v in schema]
    return schema
