from typing import Annotated

import pandas as pd
import pytest
from pydantic import BaseModel, Field

from sm_epm.lib.agents import Agent, tool
from sm_epm.lib.agents.tools import MAX_RESULT_ROWS, Tool, collect_tools, format_result
from sm_epm.lib.errors import ConfigurationError, NotFoundError
from sm_epm.lib.llm import Completion, Message, Model, ToolCall, Usage


class ScriptedLLM:
    """Stands in for the LLM facade: returns queued completions and records each request."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests = []

    def complete(self, messages, *, system='', tools=()):
        self.requests.append({'messages': list(messages), 'system': system, 'tools': list(tools)})
        text, calls, stop = self.turns.pop(0)
        return Completion(Message('assistant', text=text, tool_calls=calls), stop, Usage(10, 5), 'fake')


class Toolkit:
    @tool
    def add(self, a: int, b: Annotated[int, Field(description='second number')] = 1) -> int:
        """Add two numbers."""
        return a + b


class MathAgent(Agent):
    system_prompt = 'You do arithmetic.'

    def default_toolkits(self):
        return [Toolkit()]

    @tool(name='fail')
    def always_fails(self) -> str:
        """Always raises."""
        raise RuntimeError('nope')


def test_tool_schema_from_signature():
    (add,) = collect_tools(Toolkit())
    assert add.name == 'add' and add.description == 'Add two numbers.'
    assert add.spec.parameters == {
        'type': 'object',
        'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer', 'default': 1, 'description': 'second number'}},
        'required': ['a'],
        'additionalProperties': False,
    }
    assert add.run({'a': 2, 'b': 3}) == '5'


def test_run_executes_tools_until_the_model_stops():
    llm = ScriptedLLM(
        ('', (ToolCall('c1', 'add', {'a': 2, 'b': 3}), ToolCall('c2', 'fail', {})), 'tool_use'),
        ('The answer is 5.', (), 'end_turn'),
    )
    agent = MathAgent(llm)
    result = agent.run('What is 2 + 3?')

    assert result.text == 'The answer is 5.'
    assert result.stop_reason == 'end_turn'
    assert result.turns == 2
    assert result.usage == Usage(20, 10)
    assert [c.name for c in result.tool_calls] == ['add', 'fail']
    assert llm.requests[0]['system'] == 'You do arithmetic.'
    assert {t.name for t in llm.requests[0]['tools']} == {'add', 'fail'}

    results = agent.messages[2].tool_results  # one message holds every result of the turn
    assert (results[0].content, results[0].is_error) == ('5', False)
    assert results[1].is_error and 'RuntimeError: nope' in results[1].content


@pytest.mark.parametrize(
    ('call', 'error'),
    [
        (ToolCall('c1', 'missing', {}), 'no tool named'),
        (ToolCall('c1', 'add', {'a': 'x'}), 'invalid arguments'),
        (ToolCall('c1', 'add', {}, invalid_arguments='{bad'), 'not valid JSON'),
    ],
)
def test_bad_calls_become_error_results(call, error):
    result = MathAgent(ScriptedLLM()).call_tool(call)
    assert result.is_error and error in result.content


def test_max_turns():
    class Loopy(MathAgent):
        max_turns = 2

    llm = ScriptedLLM(*[('', (ToolCall(f'c{i}', 'add', {'a': 1}),), 'tool_use') for i in range(2)])
    assert Loopy(llm).run('loop').stop_reason == 'max_turns'


def test_pause_resends_and_continues():
    llm = ScriptedLLM(('', (), 'pause'), ('Done.', (), 'end_turn'))
    result = MathAgent(llm).run('hi')
    assert result.text == 'Done.' and result.turns == 2


def test_conversation_continues_and_closes_unanswered_calls():
    llm = ScriptedLLM(
        ('', (ToolCall('c1', 'add', {'a': 1}),), 'max_tokens'),
        ('Hello again.', (), 'end_turn'),
    )
    agent = MathAgent(llm)
    assert agent.run('first').stop_reason == 'max_tokens'
    agent.run('second')
    roles = [m.role for m in llm.requests[1]['messages']]
    assert roles == ['user', 'assistant', 'tool_results', 'user']
    assert llm.requests[1]['messages'][2].tool_results[0].content == 'Error: not run'
    agent.reset()
    assert agent.messages == []


def test_duplicate_tool_names_rejected():
    with pytest.raises(ConfigurationError, match="two tools are named 'add'"):
        MathAgent(ScriptedLLM(), toolkits=[Toolkit(), Toolkit()])


def test_format_result_dataframe_is_capped():
    df = pd.DataFrame({'x': range(MAX_RESULT_ROWS + 5)})
    df.attrs['pages'] = {'Versions': 'Forecast'}
    text = format_result(df)
    assert text.startswith(f'{MAX_RESULT_ROWS + 5} rows x 1 columns (first {MAX_RESULT_ROWS} rows shown)')
    assert "pages: {'Versions': 'Forecast'}" in text


def test_format_result_pydantic_and_plain_values():
    class Module(BaseModel):
        id: int
        name: str

    assert format_result([Module(id=1, name='INPUT')]) == '[{"id": 1, "name": "INPUT"}]'
    assert format_result({'a': 1}) == '{"a": 1}'
    assert format_result('plain') == 'plain'


def test_tool_rejects_var_kwargs():
    def f(**kwargs):
        pass

    with pytest.raises(ConfigurationError, match='not supported'):
        Tool.from_function(f)


def test_service_errors_in_tools_go_back_to_the_model():
    class Lookup:
        @tool
        def lookup(self, view_id: int) -> str:
            """Look up a view."""
            raise NotFoundError(f'no view {view_id}', service='anaplan', status_code=404)

    result = MathAgent(ScriptedLLM(), toolkits=[Lookup()]).call_tool(ToolCall('c1', 'lookup', {'view_id': 9}))
    assert result.is_error and result.content == 'Error: NotFoundError: anaplan: no view 9'


def test_provider_errors_propagate_from_run():
    class FailingLLM:
        def complete(self, messages, *, system='', tools=()):
            raise ConfigurationError('no API key', service='anthropic')

    with pytest.raises(ConfigurationError, match='no API key'):
        MathAgent(FailingLLM()).run('hi')


def test_model_is_chosen_in_code_and_swappable(monkeypatch):
    monkeypatch.setattr('sm_epm.lib.llm.facade.load_env', lambda: None)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')

    class Pinned(MathAgent):
        model = Model.CLAUDE_SONNET_5

    assert Pinned().llm.model is Model.CLAUDE_SONNET_5
    agent = Pinned(Model.GPT_5)
    assert (agent.llm.provider, agent.llm.model) == ('openai', Model.GPT_5)
    agent.llm = 'claude-haiku-4-5'  # a registered ID works too
    assert (agent.llm.provider, agent.llm.model) == ('anthropic', Model.CLAUDE_HAIKU_4_5)
    with pytest.raises(ConfigurationError, match='not approved'):
        agent.llm = 'gpt-4-legacy'


def test_swapping_models_keeps_the_conversation():
    first = ScriptedLLM(('', (ToolCall('c1', 'add', {'a': 2}),), 'tool_use'), ('3.', (), 'end_turn'))
    second = ScriptedLLM(('Still 3.', (), 'end_turn'))
    agent = MathAgent(first)
    agent.run('What is 2 + 1?')
    agent.llm = second
    assert agent.run('Are you sure?').text == 'Still 3.'
    assert [m.role for m in second.requests[0]['messages']] == ['user', 'assistant', 'tool_results', 'assistant', 'user']
