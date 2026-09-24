# sm-epm

Automations and analysis against SurveyMonkey's EPM systems: **Anaplan** and **Pigment**.

## Project layout

- `src/sm_epm/` is the package (src layout).
  - `lib/`: shared infrastructure that scripts and analysis import.
    - `env.py`: `.env` loading. `errors.py`: the `EPMError` hierarchy every lib module raises.
    - `anaplan/`, `pigment/`: one subpackage per system, each with `client.py` (`client_from_env()`), `data.py` (DataFrame readers) and `errors.py` (the error boundary). Absolute imports such as `from pigment import PigmentClient` still resolve to the library. Don't run a file inside `lib/` directly, because then `lib/` is on `sys.path` and `lib/pigment/` shadows the library.
    - `llm/`: the `LLM` facade over the Anthropic and OpenAI APIs, and `Model`, the registry of approved models. Only `lib/llm/` may import `anthropic` or `openai`.
    - `agents/`: the `Agent` base class, the `@tool` decorator, and read-only Anaplan and Pigment toolkits
  - `agents/`: implemented agents, one module per agent, each subclassing `lib.agents.Agent`. `epm_explorer.py` is the sample to copy.
  - `scripts/`: manually run scripts, grouped by purpose in subpackages, for example `scripts/anaplan_to_pigment/` for the migration loads. Run a file directly or call its `main()`. There's no CLI.
  - `analysis/`: analysis that spans both systems
- `tests/`: pytest suite, mirroring the package layout (`tests/lib/`, `tests/agents/`, `tests/scripts/`)
- `docs/`: the project knowledge base (see [Knowledge base](#knowledge-base-docs))

## Tooling

- Managed with **uv**. Python **>= 3.11** (the venv uses 3.13).
- `uv sync`: install dependencies into `.venv` (PyCharm uses the same interpreter)
- `uv run pytest`: run the tests
- `uv add <pkg>`: add a dependency. Don't edit `uv.lock` by hand.

## Dependencies

### `pigment` (internal, `../pigment-epm`)

- Installed in **editable** mode through `[tool.uv.sources]`, so changes in `../pigment-epm` show up here without reinstalling.
- If a Pigment API capability is missing, add it to the library in `../pigment-epm` rather than calling the API directly from this project.
- Import it as `from pigment import PigmentClient, PigmentConfig`.
- Credentials: build clients with `sm_epm.lib.pigment.client.client_from_env()`, which loads `.env` and then calls `PigmentConfig.from_env()` to read `PIGMENT_API_TOKEN` and `PIGMENT_BASE_URL`. See `.env.example`.
- API docs: start from https://kb.pigment.com/llms.txt. The OpenAPI spec is at https://pigment.app/api/swagger.

### `anaplan-sdk` (PyPI)

- Import it as `import anaplan_sdk`. It provides sync and async clients: `Client` and `AsyncClient`.
- Auth: we use **basic auth**. Build clients with `sm_epm.lib.anaplan.client.client_from_env()`, which reads `ANAPLAN_USER_EMAIL`, `ANAPLAN_PASSWORD`, `ANAPLAN_WORKSPACE_ID` and `ANAPLAN_MODEL_ID` from `.env` via python-dotenv. Extra keyword arguments are passed through to `anaplan_sdk.Client`.
- Docs: https://vinzenzklass.github.io/anaplan-sdk/

### `anthropic` / `openai` (PyPI)

- Used only inside `sm_epm.lib.llm`, behind the `LLM` facade. Everything else goes through `LLM`.

## Conventions

- Never commit credentials. Secrets go in `.env`, which is gitignored.
- Put anything a second script or analysis could reuse (clients, connectors, generic helpers) in `src/sm_epm/lib/`. Scripts in `scripts/` should call into `lib/` rather than duplicate it, and `lib/` must never import from `agents/`, `scripts/` or `analysis/`.
- Python strings use **single quotes**. Exceptions: docstrings stay `"""`, and a string that contains a single quote uses double quotes to avoid escaping.

## Knowledge base (`docs/`)

**Rule:** whenever a key learning, insight, decision, or process is established, write it to a Markdown file in `docs/` in the same session. Don't wait to be asked. For example:
- A decision and its reasoning (a tool choice, an auth method, a data-handling rule)
- A learning about Anaplan or Pigment behavior (API quirks, limits, model structure, gotchas)
- A repeatable process (running an import or export, reconciling the two systems, a month-end step)
- An analysis finding that later work will depend on

**How:**
1. If an existing file covers the topic, update it. Otherwise create `docs/<topic-in-kebab-case>.md`. Organize files by topic, not by date.
2. Start each file with a one-line summary. For decisions, state the decision, then **Why:**, then **Date:** (in `YYYY-MM-DD` format). When something is superseded, edit it in place and don't keep stale guidance.
3. Add or update the file's row in the index below. A doc that isn't in the index won't get loaded.
4. Keep CLAUDE.md itself lean. Put details in `docs/` and keep only the index here.
5. Don't record secrets, credentials, or personal data (for example employee names in HR or comp data) in `docs/`.

**When to load:** read a doc only when the current task matches its "Load when" column. Don't read the whole folder up front.

| Doc | Covers | Load when |
|---|---|---|
| [docs/clients-and-auth.md](docs/clients-and-auth.md) | Why these client libraries were chosen, Anaplan basic auth, `.env` loading through `sm_epm.lib.env.load_env()` (including a python-dotenv gotcha in notebooks and debuggers), and how to use the `client_from_env()` helpers | Connecting to Anaplan or Pigment, **before any Anaplan write action (the default model is production)**, changing credentials or auth, adding a client or dependency, or debugging a connection or auth failure |
| [docs/error-handling.md](docs/error-handling.md) | The `EPMError` hierarchy, how Anaplan, Pigment, Anthropic and OpenAI exceptions map onto it, and the `anaplan_errors` / `pigment_errors` boundaries | Catching or raising errors, adding a lib module or service, calling a raw client from a script, or debugging an unexpected exception type |
| [docs/dataframes.md](docs/dataframes.md) | `lib.anaplan.data` / `lib.pigment.data`: reading views, exports, lists, metrics and tables into DataFrames, format defaults, and the shape of each API's response | Loading Anaplan or Pigment data for analysis, changing the DataFrame readers, or adding a Pigment export method |
| [docs/agents.md](docs/agents.md) | The `LLM` facade (Anthropic and OpenAI backends), the approved `Model` registry, the `Agent` base class, `@tool`, the read-only toolkits, model and provider defaults, and LLM data-handling notes | Building or changing an agent or tool, calling an LLM, switching or approving a model, or adding a provider backend |
| [docs/agent-class-vs-cowork.md](docs/agent-class-vs-cowork.md) | How our `Agent` class compares with Claude Cowork: tools, toolsets, MCP connections, permissions, and when to use each | Choosing between a custom agent and Cowork, exposing our tools as an MCP server, or setting up Cowork connectors or plugins for Anaplan or Pigment |
| [docs/anaplan-to-pigment-opex-load.md](docs/anaplan-to-pigment-opex-load.md) | The `opex_planning_load` script: the module/export/import config mapping, column mapping, reshape rules, dry-run results, and open items before the first real load | Running or changing `opex_planning_load`, anything touching the Anaplan exports `116000000013` / `116000000014` or the Pigment `Vendor Planning` / `Non-Vendor Planning` lists, or building another Anaplan to Pigment load |
