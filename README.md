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

## LangGraph persistent store

LangGraph uses PostgreSQL 16 with pgvector 0.8.6. The Compose service references
the immutable Linux/AMD64 image digest, binds port 5432 only to localhost, and
derives its credentials from the ignored `LANGGRAPH_POSTGRES_DSN` without
printing them.

```powershell
.\.venvs\langgraph\Scripts\membench.exe langgraph up
.\.venvs\langgraph\Scripts\membench.exe langgraph status
.\.venvs\langgraph\Scripts\membench.exe langgraph verify
```

The qualification runs `PostgresStore.setup()`, writes one memory into a unique
namespace, verifies exact and semantic retrieval using the shared Ollama
embedding model, and confirms that a sibling namespace remains empty.

If Docker Hub is temporarily unavailable, validate the LangGraph/Ollama path
without persistence:

```powershell
.\.venvs\langgraph\Scripts\membench.exe langgraph smoke
```

Stop the service without deleting its persistent volume:

```powershell
.\.venvs\langgraph\Scripts\membench.exe langgraph stop
```

Local credentials belong in `.env` (see `.env.example`). Runtime memory,
database volumes, and emitted evidence belong below `artifacts/`; neither is
committed.

## LangMem selective writer

LangMem 0.0.30 is installed in the same isolated Python 3.12 environment as
LangGraph. It is an explicitly versioned selective writer over a LangGraph
Store, not a storage replacement and not a native capability of LangGraph
itself. Local development defaults to a run-specific SQLite database, so this
path does not require Docker or PostgreSQL:

```powershell
.\.venvs\langgraph\Scripts\membench.exe langmem status
.\.venvs\langgraph\Scripts\membench.exe langmem smoke
.\.venvs\langgraph\Scripts\membench.exe langmem verify
```

Semantic memory is the default. Episodic and procedural records can be enabled
for a separately declared condition and are written to distinct namespaces:

```powershell
$env:LANGMEM_MEMORY_TYPES = "semantic,episodic,procedural"
.\.venvs\langgraph\Scripts\membench.exe langmem verify
Remove-Item Env:LANGMEM_MEMORY_TYPES
```

The procedural schema stores reusable rules as inert records. Runtime prompt
optimization remains disabled because it is outside the current black-box
experiment scope. The example manifest is
`configs/experiments/blackbox/langmem_semantic.example.yaml`.

The writer and embedder are independently selectable. To move the writer to
OpenAI while retaining local Ollama embeddings and SQLite storage, set:

```dotenv
LANGMEM_PROVIDER=openai
LANGMEM_OPENAI_WRITER_MODEL=gpt-4o-mini-2024-07-18
LANGMEM_EMBEDDING_PROVIDER=ollama
OPENAI_API_KEY=replace-locally
```

Set `LANGMEM_EMBEDDING_PROVIDER=openai` plus the OpenAI embedding model and
dimensions only when remote embedding is intentional. Changing an embedding
model or its dimensions requires a fresh run ID and store.
