"""EPMExplorer: a sample agent that answers questions about what's in Anaplan and Pigment.

It shows the pattern every agent in this package follows: subclass ``Agent``, write a system
prompt, pick toolkits in ``default_toolkits()``, and add agent-specific ``@tool`` methods.

It's read-only. Everything it reads is sent to the model provider, so ask about data you're allowed
to share with Anthropic or OpenAI.

Run the file directly to ask ``QUESTION``, or from a Python console:

    from sm_epm.agents.epm_explorer import EPMExplorer
    from sm_epm.lib.llm import Model

    agent = EPMExplorer()                        # EPMExplorer.model
    agent = EPMExplorer(Model.GPT_5)             # or any other approved model
    agent.run('Which Pigment blocks hold vendor planning data?').text
    agent.llm = Model.CLAUDE_SONNET_5            # swap models mid-conversation
    agent.run('And how many rows are in each?').text
"""

from datetime import date

from sm_epm.lib.agents import Agent, AnaplanToolkit, PigmentToolkit, tool
from sm_epm.lib.llm import Model

SYSTEM_PROMPT = """\
You help SurveyMonkey's FP&A team find their way around two planning systems: Anaplan (the \
current system) and Pigment (the one being migrated to). You answer questions about where things \
live, how they're structured, and what the data says.

Use the tools to look things up rather than answering from memory. List before you read: find the \
module, view, application or block first, then read it. Keep data reads small, and say when a \
result you relied on was truncated.

Anaplan views often include rollups next to the detail: quarter and FY columns next to months, and \
parent rows next to leaf items. Don't sum across them.

In your answer, name the Anaplan and Pigment objects you used, with their IDs, so the team can \
find them. If the tools don't show something, say so rather than guessing.\
"""

QUESTION = 'Which Anaplan modules hold opex planning inputs, and which Pigment blocks do they correspond to?'


class EPMExplorer(Agent):
    system_prompt = SYSTEM_PROMPT
    model = Model.CLAUDE_OPUS_5
    max_turns = 30

    def default_toolkits(self) -> list[object]:
        return [AnaplanToolkit(), PigmentToolkit()]

    @tool
    def today(self) -> str:
        """Today's date (ISO 8601). Use it to tell which months are actuals and which are forecast."""
        return date.today().isoformat()


if __name__ == '__main__':
    result = EPMExplorer().run(QUESTION)
    print(result.text)
    print(f'\n[{result.stop_reason}: {result.turns} turns, {len(result.tool_calls)} tool calls, '
          f'{result.usage.input_tokens:,} in / {result.usage.output_tokens:,} out tokens]')
