"""Backend tests against the SDKs' own response types, with fake clients (no network)."""

import json
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage
from openai.types.chat import ChatCompletion

from sm_epm.lib.errors import ConfigurationError
from sm_epm.lib.llm import LLM, Message, Model, ToolCall, ToolResult, ToolSpec
from sm_epm.lib.llm._anthropic import FALLBACK_BETA

SPEC = ToolSpec('lookup', 'Look something up.', {'type': 'object', 'properties': {'q': {'type': 'string'}}})


class Recorder:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return self.response


def anthropic_llm(content, stop_reason='tool_use', model='claude-opus-5', **options):
    message = BetaMessage.model_validate({
        'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'model': model,
        'content': content, 'stop_reason': stop_reason, 'stop_sequence': None,
        'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 100},
    })
    recorder = Recorder(message)
    client = SimpleNamespace(beta=SimpleNamespace(messages=recorder))
    return LLM(model, client=client, **options), recorder


def openai_llm(message, finish_reason='tool_calls'):
    completion = ChatCompletion.model_validate({
        'id': 'c1', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-5',
        'choices': [{'index': 0, 'finish_reason': finish_reason, 'message': {'role': 'assistant', **message}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
    })
    recorder = Recorder(completion)
    client = SimpleNamespace(chat=SimpleNamespace(completions=recorder))
    return LLM(Model.GPT_5, client=client), recorder


TOOL_USE = [
    {'type': 'thinking', 'thinking': '', 'signature': 'sig'},
    {'type': 'text', 'text': 'Checking.'},
    {'type': 'tool_use', 'id': 'tu_1', 'name': 'lookup', 'input': {'q': 'opex'}},
]


def test_anthropic_normalizes_tool_use_response():
    llm, _ = anthropic_llm(TOOL_USE)
    completion = llm.complete([Message.user('hi')], tools=[SPEC])
    assert completion.stop_reason == 'tool_use'
    assert completion.message.text == 'Checking.'
    assert completion.message.tool_calls == (ToolCall('tu_1', 'lookup', {'q': 'opex'}),)
    assert completion.usage.input_tokens == 110  # cached input tokens count too


def test_anthropic_request_shape():
    llm, recorder = anthropic_llm(TOOL_USE, effort='high')
    llm.complete([Message.user('hi')], system='Be brief.', tools=[SPEC])
    request = recorder.requests[0]
    assert request['system'] == 'Be brief.'
    assert request['tools'] == [{'name': 'lookup', 'description': 'Look something up.', 'input_schema': SPEC.parameters}]
    assert request['output_config'] == {'effort': 'high'}
    assert request['cache_control'] == {'type': 'ephemeral'}
    assert request['max_tokens'] == 16000
    assert request['betas'] == [FALLBACK_BETA] and request['fallbacks'] == 'default'


def test_anthropic_fallbacks_only_default_on_for_supported_models():
    llm, recorder = anthropic_llm(TOOL_USE, model=Model.CLAUDE_SONNET_5)
    llm.complete([Message.user('hi')])
    assert 'fallbacks' not in recorder.requests[0]


def test_anthropic_replays_native_blocks_and_batches_tool_results():
    llm, recorder = anthropic_llm(TOOL_USE)
    first = llm.complete([Message.user('hi')])
    history = [
        Message.user('hi'),
        first.message,
        Message.results((ToolResult('tu_1', 'found'), ToolResult('tu_2', 'boom', is_error=True))),
    ]
    llm.complete(history)
    assistant, results = recorder.requests[1]['messages'][1:]
    assert assistant['content'] is first.message.native  # thinking block included, unchanged
    assert results == {
        'role': 'user',
        'content': [
            {'type': 'tool_result', 'tool_use_id': 'tu_1', 'content': 'found', 'is_error': False},
            {'type': 'tool_result', 'tool_use_id': 'tu_2', 'content': 'boom', 'is_error': True},
        ],
    }


def test_anthropic_rebuilds_turns_from_another_provider():
    llm, recorder = anthropic_llm(TOOL_USE)
    foreign = Message('assistant', text='Hi.', tool_calls=(ToolCall('c1', 'lookup', {'q': 'x'}),), provider='openai')
    llm.complete([Message.user('hi'), foreign])
    assert recorder.requests[0]['messages'][1]['content'] == [
        {'type': 'text', 'text': 'Hi.'},
        {'type': 'tool_use', 'id': 'c1', 'name': 'lookup', 'input': {'q': 'x'}},
    ]


@pytest.mark.parametrize(
    ('native', 'normalized'),
    [('end_turn', 'end_turn'), ('max_tokens', 'max_tokens'), ('refusal', 'refusal'), ('pause_turn', 'pause')],
)
def test_anthropic_stop_reasons(native, normalized):
    llm, _ = anthropic_llm([{'type': 'text', 'text': 'x'}], stop_reason=native)
    assert llm.complete([Message.user('hi')]).stop_reason == normalized


def test_openai_normalizes_tool_calls():
    llm, recorder = openai_llm({
        'content': None,
        'tool_calls': [
            {'id': 'c1', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{"q": "opex"}'}},
            {'id': 'c2', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{not json'}},
        ],
    })
    completion = llm.complete([Message.user('hi')], system='Be brief.', tools=[SPEC])
    assert completion.stop_reason == 'tool_use'
    assert completion.message.tool_calls == (
        ToolCall('c1', 'lookup', {'q': 'opex'}),
        ToolCall('c2', 'lookup', {}, invalid_arguments='{not json'),
    )
    request = recorder.requests[0]
    assert request['messages'][0] == {'role': 'system', 'content': 'Be brief.'}
    assert request['tools'] == [
        {'type': 'function', 'function': {'name': 'lookup', 'description': 'Look something up.', 'parameters': SPEC.parameters}}
    ]
    assert request['max_completion_tokens'] == 16000


def test_openai_history_shape():
    llm, recorder = openai_llm({'content': 'Done.'}, finish_reason='stop')
    history = [
        Message.user('hi'),
        Message('assistant', tool_calls=(ToolCall('c1', 'lookup', {'q': 'x'}),)),
        Message.results((ToolResult('c1', 'found'),)),
    ]
    completion = llm.complete(history)
    assert completion.stop_reason == 'end_turn' and completion.message.text == 'Done.'
    assert recorder.requests[0]['messages'] == [
        {'role': 'user', 'content': 'hi'},
        {
            'role': 'assistant',
            'content': None,
            'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'lookup', 'arguments': json.dumps({'q': 'x'})}}],
        },
        {'role': 'tool', 'tool_call_id': 'c1', 'content': 'found'},
    ]


def test_openai_refusal():
    llm, _ = openai_llm({'content': None, 'refusal': 'No.'}, finish_reason='stop')
    assert llm.complete([Message.user('hi')]).stop_reason == 'refusal'


@pytest.mark.parametrize('model', list(Model))
def test_every_approved_model_builds_with_its_provider(model):
    llm = LLM(model, client=object())
    assert llm.model is model and llm.provider == model.provider in ('anthropic', 'openai')
    assert model.description


def test_facade_accepts_ids_and_defaults_to_opus():
    assert LLM(client=object()).model is Model.CLAUDE_OPUS_5
    assert LLM('gpt-5', client=object()).model is Model.GPT_5


def test_facade_rejects_unapproved_models():
    with pytest.raises(ConfigurationError, match="model 'gemini-pro' is not approved. Use one of: claude-opus-5"):
        LLM('gemini-pro', client=object())


@pytest.fixture
def no_credentials(monkeypatch, tmp_path):
    """No API keys, no .env, and an empty home directory so no `ant auth login` profile is found."""
    monkeypatch.setattr('sm_epm.lib.llm.facade.load_env', lambda: None)
    for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_PROFILE', 'ANTHROPIC_CONFIG_DIR',
                 'ANTHROPIC_FEDERATION_RULE_ID', 'ANTHROPIC_IDENTITY_TOKEN', 'ANTHROPIC_IDENTITY_TOKEN_FILE',
                 'OPENAI_API_KEY', 'XDG_CONFIG_HOME'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))


@pytest.mark.parametrize(('model', 'variable'), [(Model.CLAUDE_OPUS_5, 'ANTHROPIC_API_KEY'), (Model.GPT_5, 'OPENAI_API_KEY')])
def test_missing_credentials_fail_at_construction(no_credentials, model, variable):
    with pytest.raises(ConfigurationError, match=variable) as exc_info:
        LLM(model)
    assert exc_info.value.service == model.provider


def test_api_key_from_environment_is_enough(no_credentials, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test')
    assert LLM().model is Model.CLAUDE_OPUS_5


def test_direct_construction_loads_env_file(no_credentials, monkeypatch):
    loaded = []
    monkeypatch.setattr('sm_epm.lib.llm.facade.load_env', lambda: loaded.append(True))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test')
    LLM()
    assert loaded
