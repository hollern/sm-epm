# sm-epm

Automations and analysis against SurveyMonkey's EPM systems: Anaplan and Pigment.

## Layout

- `src/sm_epm/lib/`: shared infrastructure: `.env` loading, the Anaplan client (uses [`anaplan-sdk`](https://vinzenzklass.github.io/anaplan-sdk/)) and the Pigment client (uses the `pigment` client from `../pigment-epm`), DataFrame readers for both systems, the `LLM` facade over Anthropic and OpenAI, and the `Agent` base class
- `src/sm_epm/agents/`: implemented agents, one module per agent (`epm_explorer.py` is a sample)
- `src/sm_epm/scripts/`: manually run scripts, grouped by purpose (for example `anaplan_to_pigment/`)
- `src/sm_epm/analysis/`: analysis that spans both systems
- `tests/`: pytest suite, mirroring the package layout
- `docs/`: project knowledge base (decisions, learnings, processes), indexed in `CLAUDE.md`

## Setup

Managed with [uv](https://docs.astral.sh/uv/). The `pigment` library is installed in editable mode from `../pigment-epm`, so changes you make there show up here right away.

```bash
uv sync
cp .env.example .env
uv run pytest
```
