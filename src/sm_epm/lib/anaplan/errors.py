"""Converts ``anaplan_sdk`` exceptions into ``sm_epm.lib.errors`` classes."""

from __future__ import annotations

from anaplan_sdk.exceptions import (
    AnaplanActionError,
    AnaplanException,
    AnaplanTimeoutException,
    InvalidCredentialsException,
    InvalidIdentifierException,
)

from sm_epm.lib.errors import (
    AuthenticationError,
    EPMError,
    ErrorBoundary,
    NotFoundError,
    OperationFailedError,
    RateLimitError,
    ServiceUnavailableError,
    error_for_status,
    parse_error,
)

SERVICE = 'anaplan'


def translate(exc: BaseException) -> EPMError | None:
    if not isinstance(exc, AnaplanException):
        return parse_error(exc, service=SERVICE)
    message = str(exc) or type(exc).__name__
    if isinstance(exc, InvalidCredentialsException):
        return AuthenticationError(message, service=SERVICE)
    if isinstance(exc, InvalidIdentifierException):
        return NotFoundError(message, service=SERVICE, status_code=404)
    if isinstance(exc, AnaplanTimeoutException):
        return ServiceUnavailableError(message, service=SERVICE)
    if isinstance(exc, AnaplanActionError):
        return OperationFailedError(message, service=SERVICE)
    # The SDK raises a bare AnaplanException for rate limits after its own retries, and for
    # other HTTP errors with the httpx error chained as the cause.
    if message == 'Rate limit exceeded.':
        return RateLimitError(message, service=SERVICE, status_code=429)
    response = getattr(exc.__cause__, 'response', None)
    return error_for_status(getattr(response, 'status_code', None), message, service=SERVICE)


anaplan_errors = ErrorBoundary(translate)
