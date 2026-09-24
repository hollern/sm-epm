# Error handling

Everything in `sm_epm.lib` raises one exception hierarchy, `sm_epm.lib.errors.EPMError`, whether the failure came from Anaplan, Pigment, Anthropic or OpenAI.

```python
from sm_epm.lib.errors import EPMError, NotFoundError, RateLimitError

try:
    df = anaplan_data.view_df(view_id)
except NotFoundError:
    ...                       # bad ID, in any service
except EPMError as exc:
    exc.service, exc.status_code, exc.payload, exc.retryable, exc.__cause__
```

| Class | Raised when | `retryable` |
|---|---|---|
| `ConfigurationError` | A setting is missing or invalid: env vars, LLM provider or model, duplicate tool names | no |
| `AuthenticationError` | Credentials are rejected (401/403) | no |
| `NotFoundError` | An ID, model or endpoint doesn't exist (404) | no |
| `RequestError` | A request is rejected as invalid (other 4xx), or a bad argument such as an unknown Pigment block type. Also a `ValueError` | no |
| `RateLimitError` | Throttled (429). `retry_after` is set when the service sends it | yes |
| `ServiceUnavailableError` | Network failure, timeout, or 5xx | yes |
| `OperationFailedError` | An import, export or action ran but failed. `OperationTimeoutError` (also a `TimeoutError`) when it didn't finish in time | no |
| `DataFormatError` | A response or file isn't in the expected shape, including files pandas can't parse. Also a `ValueError` | no |

`str(exc)` starts with the service, for example `anaplan: Invalid identifier.`. The original SDK exception is always chained as `__cause__`.

## How it's wired

- **Boundaries.** `sm_epm.lib.anaplan.errors.anaplan_errors` and `sm_epm.lib.pigment.errors.pigment_errors` convert that service's exceptions. Each one works as a decorator (every public function in `anaplan/data.py` and `pigment/data.py` has one) and as a context manager. In a script that calls a raw client, wrap the call:

  ```python
  with anaplan_errors:
      client.run_action(action_id)
  ```
- **LLM backends.** `lib/llm/_errors.py` builds the same kind of boundary for the Anthropic and OpenAI SDKs, and both backends wrap client construction and every request in it.
- **Pass-through.** A boundary never converts an `EPMError` (so boundaries nest), and it never converts programming errors such as `TypeError` or `AttributeError`, which should surface as bugs.

## Decisions

### One hierarchy across all four services, with the SDK exception chained
**Why:** user direction. It also means callers, retries and agents handle failures by kind (auth, not found, rate limit) and never need to import an SDK's exception classes. Chaining keeps the full SDK detail for debugging.
**Date:** 2026-09-24

### `DataFormatError` and `RequestError` also subclass `ValueError`
**Why:** the data readers and the migration script raised `ValueError` before, so existing `except ValueError` code keeps working.
**Date:** 2026-09-24

### No retries were added
Callers decide whether to retry, using `retryable`.
**Why:** the Anthropic and OpenAI SDKs already retry connection errors, 429s and 5xx twice by default, and `anaplan-sdk` retries HTTP errors (`retry_count`). The `pigment` library doesn't retry. That's the gap to fill if a script needs it.
**Date:** 2026-09-24

## Learnings

- **`anaplan-sdk` raises a bare `AnaplanException` for most HTTP errors**, with the HTTP status error chained as `__cause__`. The translator reads the status from there. Rate limits come as `AnaplanException('Rate limit exceeded.')` with no status, so the translator matches that message. 404s come as `InvalidIdentifierException`.
- **`pigment` raises `PigmentAPIError` with `status_code=None` for transport failures** (the request never got a response), and those map to `ServiceUnavailableError`. `PigmentConfig.from_env()` raises a plain `ValueError` for a missing token, and `client_from_env()` turns that into `ConfigurationError`.
- **`anthropic.Anthropic()` builds without an API key and fails on the first request, with a bare `TypeError`** (`Could not resolve authentication method`). The Anthropic backend therefore checks the client's resolved credentials when it's built. `openai.OpenAI()` raises `OpenAIError` at construction. Both come out as `ConfigurationError` naming the env var to set.
- Verified live on 2026-09-24: a bad Anaplan view ID and bad Pigment view and metric IDs all raise `NotFoundError` with status 404.
