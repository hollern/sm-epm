"""One exception hierarchy for everything in ``sm_epm.lib``.

Whether a failure comes from Anaplan, Pigment, Anthropic or OpenAI, callers catch the same
classes. Every error carries the ``service`` it came from, the HTTP ``status_code`` and response
``payload`` when there was one, and whether it's ``retryable``. The original SDK exception is
chained as ``__cause__``.

    EPMError
    ├── ConfigurationError       missing or invalid settings: env vars, provider, model, tools
    ├── AuthenticationError      credentials rejected (401/403)
    ├── NotFoundError            unknown ID, model or endpoint (404)
    ├── RequestError             request rejected as invalid (other 4xx, or a bad argument)
    ├── RateLimitError           throttled (429), retryable, with retry_after when known
    ├── ServiceUnavailableError  network failure, timeout or 5xx, retryable
    ├── OperationFailedError     an import, export or action ran but failed
    │   └── OperationTimeoutError   it didn't finish in time
    └── DataFormatError          a response or file isn't in the expected shape

Each service package exposes a boundary (``anaplan_errors``, ``pigment_errors``) that converts
that service's exceptions. Use it as a decorator on library functions, or as a context manager
around raw client calls in scripts:

    with anaplan_errors:
        client.run_action(action_id)
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ContextDecorator
from typing import Any, ClassVar


class EPMError(Exception):
    retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        *,
        service: str,
        status_code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(f'{service}: {message}')
        self.message = message
        self.service = service
        self.status_code = status_code
        self.payload = payload


class ConfigurationError(EPMError):
    pass


class AuthenticationError(EPMError):
    pass


class NotFoundError(EPMError):
    pass


class RequestError(EPMError, ValueError):
    pass


class RateLimitError(EPMError):
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServiceUnavailableError(EPMError):
    retryable = True


class OperationFailedError(EPMError):
    pass


class OperationTimeoutError(OperationFailedError, TimeoutError):
    pass


class DataFormatError(EPMError, ValueError):
    pass


def parse_error(exc: BaseException, *, service: str) -> DataFormatError | None:
    """A ``DataFormatError`` for a file that pandas or the decoder couldn't read, else None."""
    import pandas as pd

    if isinstance(exc, (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError)):
        return DataFormatError(f'could not parse the response: {exc}', service=service)
    return None


def error_for_status(status_code: int | None, message: str, *, service: str, payload: Any = None) -> EPMError:
    """The error class for an HTTP status. No status means the request never got a response."""
    kwargs: dict[str, Any] = {'service': service, 'status_code': status_code, 'payload': payload}
    if status_code is None or status_code >= 500:
        return ServiceUnavailableError(message, **kwargs)
    if status_code in (401, 403):
        return AuthenticationError(message, **kwargs)
    if status_code == 404:
        return NotFoundError(message, **kwargs)
    if status_code == 429:
        return RateLimitError(message, **kwargs)
    return RequestError(message, **kwargs)


class ErrorBoundary(ContextDecorator):
    """Converts one service's exceptions into ``EPMError``, as a decorator or a ``with`` block.

    ``translate`` returns the ``EPMError`` for an exception, or None to let it through unchanged
    (programming errors such as ``TypeError`` aren't converted). ``EPMError`` always passes
    through, so boundaries can nest.
    """

    def __init__(self, translate: Callable[[BaseException], EPMError | None]) -> None:
        self._translate = translate

    def __enter__(self) -> ErrorBoundary:
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        if exc is None or isinstance(exc, EPMError):
            return False
        error = self._translate(exc)
        if error is None:
            return False
        raise error from exc
