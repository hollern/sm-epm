# Our `Agent` class vs. Claude Cowork

How agents built on `sm_epm.lib.agents.Agent` compare with using Claude Cowork as the agent, covering tools, toolsets and MCP server connections, and when to use each.

The two work at different layers. Our `Agent` class is a harness we own: Python code that runs the loop, calls a model through the `LLM` facade, and runs tools in-process. Cowork is Anthropic's hosted harness: no loop to write, with tools coming in through connectors (MCP servers), plugins and skills.

## How the pieces line up

| Our `Agent` class | Cowork equivalent | Notes |
|---|---|---|
| An `Agent` subclass, e.g. `EPMExplorer` | A **plugin**, or a project with instructions | A plugin bundles connectors, skills, slash commands, hooks and sub-agents |
| `system_prompt` | A **skill** (loaded only when relevant) or project instructions | Skills can be shared with teammates |
| `@tool` method | An **MCP tool** exposed by a connector | Same idea: a name, a description and a JSON schema |
| Toolkit (`AnaplanToolkit`, `PigmentToolkit`) | An **MCP server / connector** | One server is one toolset |
| `default_toolkits()` | The plugin's `.mcp.json`, or connectors enabled for the session | |
| `Agent.run()` loop, `max_turns` | Cowork's own loop, with sub-agents for parallel work | Nothing to write or maintain |
| `LLM` facade and the `Model` list | Cowork's model picker | **Claude only.** OpenAI isn't an option |
| Read-only toolkits, by design | Per-tool policy (`allow` / `ask` / `blocked`) plus permission modes (Manual / Auto / Skip) | |
| Tool errors sent back to the model | MCP tool errors, handled the same way | |
| `QUESTION` + `if __name__ == '__main__'` | Typing a prompt, or a **scheduled task** | Scheduled tasks run without the user's laptop on |

## Tools

**Ours:**
- A tool is a Python method. Its type hints become the input definition, pydantic checks the model's arguments, and it runs in our process with our libraries.
- Results come back as text. A DataFrame is cut to 200 rows and 20,000 characters, because everything the model sees goes through its context.
- The model can't run code, so it only reasons over what a tool returns. Any real number-crunching has to live inside a tool.

**Cowork:**
- Tools come from connectors, plus built-in abilities: file access, running code in its sandbox, and browser actions.
- Because it can run code, Cowork can pull a full export into a file and analyze it with pandas, instead of reading a truncated sample. This is the biggest practical difference for FP&A-sized data.

## Toolsets

**Ours:** a toolkit is a Python object whose tools share one client, built from `.env` the first time it's used. It's put together in code, tested with fakes, and reviewed like any other code.

**Cowork:**
- An MCP server is the toolset.
- A plugin is the unit you distribute: MCP servers, skills, slash commands, hooks and sub-agents in one package.
- Admins can push plugins organization-wide through a plugin marketplace and lock individual tools, for example allowing `search` while blocking `delete_document`.

## MCP server connections

**Ours:** the `Agent` class has **no MCP support**. It can neither use MCP servers nor act as one. Everything is a direct Python call through `anaplan-sdk` and the `pigment` library.

**Cowork:**
- **Remote connectors (HTTP/SSE):** Claude connects to them **from Anthropic's cloud, not from the user's laptop**. A server on SurveyMonkey's internal network or on `localhost` isn't reachable that way. It has to be reachable from the internet, with sign-in handled by OAuth.
- **Local servers:** on the desktop app, users can add local MCP server processes under Settings → Developer, unless an admin has turned that off.
- **Whose permissions:** each person signs in to each connector, and Claude inherits that person's permissions in the connected system. Ours runs everything as the one Anaplan user and Pigment key in `.env`.
- **Existing Anaplan connector:** an Anaplan MCP server is already in use in Claude Code (seen on 2026-09-24). Its tools include writes such as `write_cells`, `run_import`, `delete_list_items` and `bulk_delete_models`. If it's used in Cowork, those should be blocked or set to "ask", because the default Anaplan model is production (see [clients-and-auth.md](clients-and-auth.md)).

## Where they differ

| | Our `Agent` class | Cowork |
|---|---|---|
| Who runs the loop | Our code | Anthropic |
| Models | Approved list; Claude **and** OpenAI; swappable mid-conversation | Claude |
| Where it runs | Wherever the Python runs (laptop, server, CI) | Isolated sessions on Anthropic's side; the desktop app adds local file and browser access |
| Access to Anaplan and Pigment | One shared set of credentials from `.env` | Each user signs in; their own permissions apply |
| Guardrails | Enforced in code: read-only toolkits, the model list, errors | Admin policy: per-tool locks, permission modes, managed plugins |
| Testing | Unit tests with a scripted fake model, fully repeatable | Manual; there's no test harness |
| Output | Python objects, returned to scripts and pipelines | Finished files: spreadsheets, decks, documents |
| Data analysis | Only what tools return, capped | Can run code over full files |
| Cost | Pay-per-token API billing | Included in each person's Claude plan |
| Build effort | You write and maintain the loop, tools and error handling | Configuration and writing skills |

## Recommendation (not yet decided)

- **Cowork for analysts' ad-hoc work:** "why did Q3 opex move?", building a deck, poking at an export. It's easier to use, can analyze full files, and applies each person's own permissions.
- **The `Agent` class for automated, repeatable work:** scheduled reconciliations, steps inside the migration scripts, anything that needs tests, OpenAI models, or results fed back into Python.
- **The bridge:** publish our toolkits as an MCP server. Each `@tool` method already has a name, a description and an input definition, so it maps one-to-one onto an MCP tool. Cowork, Claude Code and our `Agent` class would then all use the same reviewed, read-only Anaplan and Pigment tools, rather than a separate connector with write access. For Cowork it would need to be a remote server reachable from Anthropic's cloud, with OAuth. That's the main thing to plan with IT.

## Learnings

- Remote custom connectors are called from Anthropic's cloud in every Claude client (claude.ai, Desktop, Cowork, mobile), so internal-only MCP servers can't be used as remote connectors.
- Some admin details here (managed MCP servers via `managedMcpServers`, per-tool `toolPolicy` locks, org plugin directories) come from the docs for Claude Desktop with a third-party model provider. The standard claude.ai admin console may expose them differently. How SurveyMonkey's Cowork is configured is a question for #ithelp.
- Cowork details are from Anthropic's docs as of 2026-09-24.

Sources:
- [Get started with Claude Cowork](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork)
- [MCP, plugins, skills, and hooks (Cowork)](https://claude.com/docs/cowork/3p/extensions)
- [Get started with custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
- [Use connectors to extend Claude's capabilities](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities)
- [Use plugins in Claude](https://support.claude.com/en/articles/13837440-use-plugins-in-claude)
- [Cowork and plugins for teams across the enterprise](https://claude.com/blog/cowork-plugins-across-enterprise)
