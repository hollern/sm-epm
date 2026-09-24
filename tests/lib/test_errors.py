"""Each service's exceptions map onto the same sm_epm.lib.errors classes."""

from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pandas as pd
import pytest
from anaplan_sdk.exceptions import (
    AnaplanActionError,
    AnaplanException,
    AnaplanTimeoutException,
    InvalidCredentialsException,
    InvalidIdentifierException,
)
from pigment import PigmentAPIError, PigmentAuthError

from sm_epm.lib.anaplan.errors import anaplan_errors
from sm_epm.lib.errors import (
    AuthenticationError,
    ConfigurationError,
    DataFormatError,
    EPMError,
    ErrorBoundary,
    NotFoundError,
    OperationFailedError,
    RateLimitError,
    RequestError,
    ServiceUnavailableError,
    error_for_status,
)
from sm_epm.lib.llm._errors import sdk_errors
from sm_epm.lib.pigment.errors import pigment_errors


def raised(boundary, exc):
    """What comes out of ``boundary`` when ``exc`` is raised inside it."""
    with pytest.raises(BaseException) as exc_info, boundary:
        raise exc
    return exc_info.value


@pytest.mark.parametrize(
    ('status', 'cls'),
    [
        (None, ServiceUnavailableError),
        (400, RequestError),
        (401, AuthenticationError),
        (403, AuthenticationError),
        (404, NotFoundError),
        (429, RateLimitError),
        (503, ServiceUnavailableError),
    ],
)
def test_error_for_status(status, cls):
    error = error_for_status(status, 'boom', service='x')
    assert type(error) is cls
    assert (error.service, error.status_code, str(error)) == ('x', status, 'x: boom')


def test_retryable_flags():
    assert RateLimitError('x', service='s').retryable
    assert ServiceUnavailableError('x', service='s').retryable
    assert not RequestError('x', service='s').retryable


def test_boundary_chains_cause_and_passes_other_errors_through():
    boundary = ErrorBoundary(lambda e: RequestError('bad', service='s') if isinstance(e, KeyError) else None)
    error = raised(boundary, KeyError('k'))
    assert isinstance(error, RequestError) and isinstance(error.__cause__, KeyError)
    assert isinstance(raised(boundary, TypeError('bug')), TypeError)  # programming errors untouched
    epm = NotFoundError('already converted', service='s')
    assert raised(boundary, epm) is epm


def test_boundary_works_as_decorator():
    @anaplan_errors
    def read():
        raise InvalidIdentifierException()

    with pytest.raises(NotFoundError):
        read()


def http_status_error(status):
    request = httpx2.Request('GET', 'https://example.com')
    response = httpx2.Response(status, request=request)
    return httpx2.HTTPStatusError('boom', request=request, response=response)


def anaplan_http_error(status):
    try:
        raise AnaplanException('boom') from http_status_error(status)
    except AnaplanException as exc:
        return exc


@pytest.mark.parametrize(
    ('exc', 'cls'),
    [
        (InvalidCredentialsException(), AuthenticationError),
        (InvalidIdentifierException(), NotFoundError),
        (AnaplanTimeoutException(), ServiceUnavailableError),
        (AnaplanActionError(), OperationFailedError),
        (AnaplanException('Rate limit exceeded.'), RateLimitError),
        (anaplan_http_error(401), AuthenticationError),
        (anaplan_http_error(500), ServiceUnavailableError),
        (anaplan_http_error(400), RequestError),
        (AnaplanException('no cause'), ServiceUnavailableError),
        (pd.errors.EmptyDataError('empty'), DataFormatError),
    ],
)
def test_anaplan_translation(exc, cls):
    error = raised(anaplan_errors, exc)
    assert type(error) is cls and error.service == 'anaplan'


@pytest.mark.parametrize(
    ('exc', 'cls', 'status'),
    [
        (PigmentAuthError('bad token'), AuthenticationError, None),
        (PigmentAPIError('slow down', status_code=429), RateLimitError, 429),
        (PigmentAPIError('request failed'), ServiceUnavailableError, None),
        (PigmentAPIError('bad body', status_code=400, payload={'m': 'x'}), RequestError, 400),
        (pd.errors.ParserError('bad csv'), DataFormatError, None),
    ],
)
def test_pigment_translation(exc, cls, status):
    error = raised(pigment_errors, exc)
    assert type(error) is cls and error.service == 'pigment' and error.status_code == status


def sdk_status_error(sdk, cls, status, headers=None):
    request = httpx2.Request('POST', 'https://example.com')
    response = httpx2.Response(status, request=request, headers=headers or {})
    return cls('boom', response=response, body={'error': 'boom'})


@pytest.mark.parametrize(('sdk', 'base'), [(anthropic, anthropic.AnthropicError), (openai, openai.OpenAIError)])
def test_llm_sdk_translation(sdk, base):
    boundary = sdk_errors(sdk, base, sdk.__name__)
    request = httpx2.Request('POST', 'https://example.com')
    cases = [
        (sdk.APITimeoutError(request=request), ServiceUnavailableError),
        (sdk.APIConnectionError(request=request), ServiceUnavailableError),
        (sdk_status_error(sdk, sdk.AuthenticationError, 401), AuthenticationError),
        (sdk_status_error(sdk, sdk.PermissionDeniedError, 403), AuthenticationError),
        (sdk_status_error(sdk, sdk.NotFoundError, 404), NotFoundError),
        (sdk_status_error(sdk, sdk.BadRequestError, 400), RequestError),
        (sdk_status_error(sdk, sdk.InternalServerError, 529), ServiceUnavailableError),
        (base('no api key'), ConfigurationError),
    ]
    for exc, cls in cases:
        error = raised(boundary, exc)
        assert type(error) is cls, (exc, error)
        assert error.service == sdk.__name__

    limited = raised(boundary, sdk_status_error(sdk, sdk.RateLimitError, 429, {'retry-after': '3'}))
    assert isinstance(limited, RateLimitError) and limited.retry_after == 3.0
    assert limited.payload == {'error': 'boom'}


def test_every_error_is_an_epm_error():
    for cls in (ConfigurationError, AuthenticationError, NotFoundError, RequestError, RateLimitError,
                ServiceUnavailableError, OperationFailedError, DataFormatError):
        assert issubclass(cls, EPMError)
    assert issubclass(DataFormatError, ValueError) and issubclass(RequestError, ValueError)


def test_llm_backend_converts_sdk_errors():
    from sm_epm.lib.llm import LLM, Message

    def create(**request):
        raise sdk_status_error(anthropic, anthropic.RateLimitError, 429)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(RateLimitError) as exc_info:
        LLM(client=client).complete([Message.user('hi')])
    assert exc_info.value.service == 'anthropic'
