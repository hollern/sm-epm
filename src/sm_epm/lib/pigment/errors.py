"""Converts ``pigment`` library exceptions into ``sm_epm.lib.errors`` classes."""

from __future__ import annotations

from pigment import PigmentAPIError, PigmentAuthError, PigmentError

from sm_epm.lib.errors import AuthenticationError, EPMError, ErrorBoundary, RequestError, error_for_status, parse_error

SERVICE = 'pigment'


def translate(exc: BaseException) -> EPMError | None:
    if isinstance(exc, PigmentAuthError):
        return AuthenticationError(str(exc), service=SERVICE)
    if isinstance(exc, PigmentAPIError):
        # No status code means the request never got a response (network error or timeout).
        return error_for_status(exc.status_code, str(exc), service=SERVICE, payload=exc.payload)
    if isinstance(exc, PigmentError):
        return RequestError(str(exc), service=SERVICE)
    return parse_error(exc, service=SERVICE)


pigment_errors = ErrorBoundary(translate)
