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
ollama pull nomic-embed-text:137m-v1.5-fp16
uv run membench ollama status
uv run membench ollama verify
```

The initial local defaults are `qwen2.5:7b` for chat and
`nomic-embed-text:137m-v1.5-fp16` at 768 dimensions for embeddings. Freeze the
model digests reported by `membench ollama status` in resolved measured-run
manifests.

## TeleMem provider setup

TeleMem uses isolated FAISS and history storage for every run. The default
`TELEMEM_PROVIDER=ollama` configuration routes TeleMem through Ollama's
OpenAI-compatible endpoint. Run its qualification from the TeleMem environment:

```powershell
.\.venvs\telemem\Scripts\membench.exe telemem status
.\.venvs\telemem\Scripts\membench.exe telemem verify
```

The verification creates a unique directory below
`artifacts/memory/telemem/`, confirms empty initial state, and exercises both
`infer=False` direct writes and `infer=True` native-selective writes.

To use real OpenAI models later, set the following in `.env`; the API key is
read at runtime and must not be committed:

```dotenv
TELEMEM_PROVIDER=openai
OPENAI_API_KEY=replace-locally
TELEMEM_OPENAI_BASE_URL=https://api.openai.com/v1
TELEMEM_OPENAI_CHAT_MODEL=gpt-5-mini
TELEMEM_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
TELEMEM_OPENAI_EMBEDDING_DIMENSIONS=1536
```

Changing the embedding provider, model, or dimension requires a fresh run ID
and therefore a new vector store.

Local credentials belong in `.env` (see `.env.example`). Runtime memory,
database volumes, and emitted evidence belong below `artifacts/`; neither is
committed.
