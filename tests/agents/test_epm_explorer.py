from datetime import date

from sm_epm.agents.epm_explorer import EPMExplorer
from sm_epm.lib.llm import Completion, Message, ToolCall, Usage


class ScriptedLLM:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests = []

    def complete(self, messages, *, system='', tools=()):
        self.requests.append({'messages': list(messages), 'system': system, 'tools': list(tools)})
        text, calls, stop = self.turns.pop(0)
        return Completion(Message('assistant', text=text, tool_calls=calls), stop, Usage(), 'fake')


def test_has_both_toolkits_and_its_own_tool():
    names = set(EPMExplorer(ScriptedLLM()).tools)
    assert 'today' in names
    assert {'anaplan_list_modules', 'anaplan_read_view', 'pigment_list_blocks', 'pigment_read_block'} <= names


def test_run_uses_system_prompt_and_today_tool():
    llm = ScriptedLLM(
        ('', (ToolCall('c1', 'today', {}),), 'tool_use'),
        ('Forecast months start next month.', (), 'end_turn'),
    )
    agent = EPMExplorer(llm)
    result = agent.run('Which months are forecast?')

    assert result.text == 'Forecast months start next month.'
    assert 'Anaplan' in llm.requests[0]['system'] and 'Pigment' in llm.requests[0]['system']
    assert agent.messages[2].tool_results[0].content == date.today().isoformat()
