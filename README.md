# MemoryPoisoninAnalysis

Reproducible black-box experiments for comparing memory-poisoning behavior across
TeleMem, Memanto, and LangGraph write policies.

## Bootstrap

The project is pinned to Python 3.12 and uses
[uv](https://docs.astral.sh/uv/) for environments and dependency locking.

```powershell
uv python install 3.12
uv sync --locked --group dev
uv run membench doctor
uv run pytest
```

Runtime integrations are separated into dependency groups. Create the isolated
environments described in `planning/config.md` with:

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venvs\telemem"
uv sync --locked --no-default-groups --group telemem-runtime

$env:UV_PROJECT_ENVIRONMENT = ".venvs\memanto"
uv sync --locked --no-default-groups --group memanto-runtime

$env:UV_PROJECT_ENVIRONMENT = ".venvs\langgraph"
uv sync --locked --no-default-groups --group langgraph-runtime

Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

Validate the starter experiment manifest and inspect the supported comparison
matrix:

```powershell
uv run membench manifest validate configs/experiments/blackbox/example.yaml
uv run membench matrix
```

## Shared Ollama endpoint

All mechanism adapters use the same host Ollama service. Native clients use
`OLLAMA_BASE_URL`; OpenAI-compatible clients use `OLLAMA_OPENAI_BASE_URL`.
The roles remain separate in experiment manifests even when they resolve to the
same server and model.

```powershell
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
uv run membench ollama status
uv run membench ollama verify
```

The initial local defaults are `qwen2.5:7b` for chat and
`nomic-embed-text` at 768 dimensions for embeddings. Freeze the model digests
reported by `membench ollama status` in resolved measured-run manifests.

Local credentials belong in `.env` (see `.env.example`). Runtime memory,
database volumes, and emitted evidence belong below `artifacts/`; neither is
committed.
