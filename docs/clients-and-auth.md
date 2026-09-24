# Clients and auth

Which client libraries this project uses to connect to Anaplan and Pigment, how they authenticate, and how credentials are loaded.

## Decisions

### Anaplan client: `anaplan-sdk` (PyPI)
We don't have an internal Anaplan library, so we use `anaplan-sdk`, the actively maintained community client (docs: https://vinzenzklass.github.io/anaplan-sdk/).
**Why:** it provides both sync and async clients, supports every Anaplan auth method, and has typed models.
**Date:** 2026-09-23

### Anaplan auth: basic auth (email + password)
Build clients with `sm_epm.lib.anaplan.client.client_from_env()`. It reads these variables:
- `ANAPLAN_USER_EMAIL` (required)
- `ANAPLAN_PASSWORD` (required)
- `ANAPLAN_WORKSPACE_ID` (optional; a blank value becomes `None`)
- `ANAPLAN_MODEL_ID` (optional; a blank value becomes `None`)

Any extra keyword arguments go straight to `anaplan_sdk.Client`, for example `timeout`, `retry_count` or `page_size`. A missing email or password raises `ConfigurationError` (see [error-handling.md](error-handling.md)), as does a missing `PIGMENT_API_TOKEN` for the Pigment helper.
**Why:** team decision.
**Date:** 2026-09-23

### Pigment client: internal `pigment` library (`../pigment-epm`)
Installed in editable mode. Build clients with `sm_epm.lib.pigment.client.client_from_env()`, which reads `PIGMENT_API_TOKEN` and `PIGMENT_BASE_URL`. If you need API coverage the library doesn't have, add it in `../pigment-epm`.
**Why:** a single maintained client for Pigment instead of scattered direct API calls.
**Date:** 2026-09-23

### Credential loading: `python-dotenv`
Both helpers call `sm_epm.lib.env.load_env()`. It loads the project-root `.env` from an explicit path (`sm_epm.lib.env.ENV_FILE`), so it finds the same file whatever the current working directory. Variables already set in the environment (your shell or a PyCharm run configuration) win over `.env`. New code that needs `.env` values should call `load_env()`, not `load_dotenv()` directly.
**Why:** a single local file for secrets without manual exporting, and `.env` is gitignored.
**Date:** 2026-09-23

## Learnings

- The basic-auth connection through `client_from_env()` was verified on 2026-09-23 with read-only calls. The account can see 2 workspaces and 248 models.
- **The default `ANAPLAN_MODEL_ID` in `.env` points to the `FP&A Production` model.** Imports, processes, deletes and cell writes made with the default client change production data. Confirm with the user before running any write action. For testing, point `ANAPLAN_MODEL_ID` at a non-production model or pass `model_id=` explicitly.
- The Pigment connection through `client_from_env()` was verified on 2026-09-24 with read-only metadata calls. The API key can see 17 applications, including the numbered production apps (for example `2. General Data Hub`, `3. Workforce Planning`, `4. OpEx & COGS`), `Survey Monkey UAT`, and several Academy training apps. Some Academy apps return 0 blocks. Export permission was verified on 2026-09-24, when `export_view` worked. Import permission hasn't been tested yet.
- `list_applications()` and `list_blocks()` return plain lists of dicts. Applications have the keys `id` and `name`, and blocks have `id`, `name` and `type`.
- The Anaplan client's read methods are named `get_*`, for example `get_workspaces`, `get_models`, `get_actions`, `get_imports`, `get_exports`, `get_processes` and `get_files`.

- The `anaplan_sdk.Client` doesn't read environment variables itself, so always use the helper rather than calling `Client()` directly.
- If you call `load_dotenv()` with no arguments in a REPL, a Jupyter notebook, or a debugger (including PyCharm's debug mode), it looks for `.env` starting from the current working directory, not from the calling file. That's why `load_env()` passes an explicit path. (Confirmed in python-dotenv 1.2.3's source.)
- The tests replace `anaplan_sdk.Client` and `load_env` with stand-ins so they never touch the network or your real `.env`. See `tests/lib/test_clients.py`.
