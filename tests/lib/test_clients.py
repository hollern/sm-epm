import pytest

from sm_epm.lib.anaplan import client as anaplan_client
from sm_epm.lib.errors import ConfigurationError
from sm_epm.lib.pigment import client as pigment_client


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(anaplan_client, 'load_env', lambda: None)
    monkeypatch.setattr(pigment_client, 'load_env', lambda: None)


def test_env_file_is_project_root():
    from pathlib import Path

    from sm_epm.lib.env import ENV_FILE

    assert ENV_FILE == Path(__file__).resolve().parents[2] / '.env'


def test_anaplan_client_from_env(monkeypatch):
    captured = {}
    monkeypatch.setattr(anaplan_client.anaplan_sdk, 'Client', lambda **kw: captured.update(kw))
    monkeypatch.setenv('ANAPLAN_USER_EMAIL', 'user@example.com')
    monkeypatch.setenv('ANAPLAN_PASSWORD', 'secret')
    monkeypatch.setenv('ANAPLAN_WORKSPACE_ID', 'ws')
    monkeypatch.setenv('ANAPLAN_MODEL_ID', '')

    anaplan_client.client_from_env(timeout=5)

    assert captured == {
        'user_email': 'user@example.com',
        'password': 'secret',
        'workspace_id': 'ws',
        'model_id': None,
        'timeout': 5,
    }


def test_anaplan_client_from_env_requires_credentials(monkeypatch):
    monkeypatch.delenv('ANAPLAN_USER_EMAIL', raising=False)
    monkeypatch.setenv('ANAPLAN_PASSWORD', 'secret')
    with pytest.raises(ConfigurationError, match='ANAPLAN_USER_EMAIL not set') as exc_info:
        anaplan_client.client_from_env()
    assert exc_info.value.service == 'anaplan'


def test_pigment_client_from_env_requires_token(monkeypatch):
    monkeypatch.delenv('PIGMENT_API_TOKEN', raising=False)
    with pytest.raises(ConfigurationError, match='PIGMENT_API_TOKEN'):
        pigment_client.client_from_env()


def test_pigment_client_from_env(monkeypatch):
    monkeypatch.setenv('PIGMENT_API_TOKEN', 'tok')
    assert isinstance(pigment_client.client_from_env(), pigment_client.PigmentClient)
