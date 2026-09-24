"""Converts Anthropic and OpenAI SDK exceptions into ``sm_epm.lib.errors`` classes.

Both SDKs are generated from the same template and share exception names, so one translator,
given the SDK module, covers both.
"""

from __future__ import annotations

from types import ModuleType

from sm_epm.lib.errors import (
    AuthenticationError,
    ConfigurationError,
    EPMError,
    ErrorBoundary,
    NotFoundError,
    RateLimitError,
    RequestError,
    ServiceUnavailableError,
)


def sdk_errors(sdk: ModuleType, base: type[Exception], service: str) -> ErrorBoundary:
    """An ``ErrorBoundary`` for ``sdk`` (the ``anthropic`` or ``openai`` module), whose exceptions
    all derive from ``base``."""

    def translate(exc: BaseException) -> EPMError | None:
        # Most specific first: APITimeoutError is an APIConnectionError, and the typed status
        # errors are all APIStatusErrors.
        if isinstance(exc, sdk.APIConnectionError):
            return ServiceUnavailableError(str(exc), service=service)
        if isinstance(exc, sdk.APIStatusError):
            kwargs = {'service': service, 'status_code': exc.status_code, 'payload': exc.body}
            if isinstance(exc, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
                return AuthenticationError(exc.message, **kwargs)
            if isinstance(exc, sdk.NotFoundError):
                return NotFoundError(exc.message, **kwargs)
            if isinstance(exc, sdk.RateLimitError):
                return RateLimitError(exc.message, retry_after=_retry_after(exc), **kwargs)
            if exc.status_code >= 500:
                return ServiceUnavailableError(exc.message, **kwargs)
            return RequestError(exc.message, **kwargs)
        if isinstance(exc, base):
            # Raised before any request is sent, for example no API key.
            return ConfigurationError(str(exc), service=service)
        return None

    return ErrorBoundary(translate)


def _retry_after(exc: Exception) -> float | None:
    try:
        return float(exc.response.headers['retry-after'])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
