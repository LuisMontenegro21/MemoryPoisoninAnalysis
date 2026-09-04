# Local Memory Mechanism Configuration

## Purpose

This document defines the recommended local runtime layout for TeleMem, Memanto,
LangGraph, and the optional LangMem selective writer. It isolates Python
environments and persisted memory while keeping the mechanisms easy to debug
locally.

The preferred setup is hybrid:

- Run each Python adapter in its own uv virtual environment.
- Store every trial in a mechanism-specific directory, collection, agent, or
  database namespace.
- Run Moorcheh and PostgreSQL as local Docker services.
- Run Ollama once on the host, or as an optional shared container.
- Continue using OpenAI-compatible APIs when desired; storage remains local, but
  content sent for inference or embeddings leaves the machine.

## Runtime layout

```text
Host
|-- .venvs/
|   |-- telemem/
|   |-- memanto/
|   `-- langgraph/
|-- artifacts/memory/
|   |-- telemem/
|   |-- memanto/
|   |-- langgraph/
|   `-- langmem/<run_id>/store.sqlite
|-- Moorcheh container        # Memanto storage and retrieval
|-- PostgreSQL container      # LangGraph persistent Store
`-- Ollama                    # Optional shared local model endpoint
```

Runtime directories and credentials must not be committed. Add `.venvs/`, local
memory artifacts, database volumes, and `.env` files to `.gitignore` before the
runtime is implemented.

## Version management

The repository requires Python 3.12.x and locks these versions:

| Package | Locked version |
| --- | ---: |
| TeleMem | 1.10.0 |
| Memanto | 0.2.17 |
| LangGraph | 1.2.11 |
| LangMem | 0.0.30 |
| LangChain Ollama | 1.1.0 |
| LangChain OpenAI | 1.6.0 |
| LangGraph SQLite checkpoint/store | 3.1.1 |

Every environment must be created from the repository's `pyproject.toml` and
`uv.lock`:

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venvs\langgraph"
uv sync --locked --no-default-groups --group langgraph-runtime
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

Use the corresponding dependency group and environment path for TeleMem or
Memanto. Clear or replace `UV_PROJECT_ENVIRONMENT` before operating on another
environment.

Runtime dependencies are separated into uv dependency groups. The current
LangGraph environment includes the storage layer, LangMem writer, and both model
provider adapters using exact direct-dependency versions:

```toml
[dependency-groups]
telemem-runtime = ["telemem==1.10.0"]
memanto-runtime = ["memanto==0.2.17", "moorcheh-client==0.1.5"]
langgraph-runtime = [
    "langgraph==1.2.11",
    "langchain-ollama==1.1.0",
    "langchain-openai==1.6.0",
    "langgraph-checkpoint-postgres==3.1.2",
    "langgraph-checkpoint-sqlite==3.1.1",
    "langmem==0.0.30",
]
```

Regenerate `uv.lock` only after an intentional dependency edit, then review the
resolved version changes before syncing. Do not install untracked packages
directly inside an environment.

## Storage isolation contract

Every trial must receive a unique `run_id`. The runner must derive all storage
identifiers from it and reject reused or non-empty targets unless resume mode was
explicitly requested.

| Mechanism | Required isolation boundary |
| --- | --- |
| TeleMem | Unique local directory, vector-store path, and collection |
| Memanto | Unique agent and namespace; dedicated backend for parallel trials |
| LangGraph | Unique namespace and PostgreSQL schema or database |
| LangMem | Unique run and memory-type namespace; run-specific SQLite file by default |

Virtual environments alone do not isolate user-profile files, ports, services,
environment variables, or databases.

## TeleMem

TeleMem runs directly in its uv environment. Configure all paths explicitly and
set environment variables before importing `telemem`.

Required per trial:

- `MEM0_DIR` pointing to the trial directory.
- A unique FAISS or local Qdrant path.
- A unique collection name.
- A local history database path.
- An OpenAI-compatible or Ollama LLM and embedding configuration.

Example target layout:

```text
artifacts/memory/<run_id>/telemem/
|-- vectors/
|-- history.db
`-- metadata/
```

Do not use `Memory()` defaults in measured runs because default paths and
collection names may be shared across trials.

## Memanto

Run the Memanto CLI or adapter in its uv environment and use Moorcheh On-Prem as
the local backend.

Required:

- Docker Desktop or Docker Engine.
- A pinned Moorcheh container image.
- A persistent Moorcheh data volume.
- A unique Memanto agent and namespace for each trial.
- An embedding provider: OpenAI, Cohere, or Ollama.
- An LLM provider when conversation extraction or grounded answers are used.

Memanto also maintains configuration and active-session state under
`~/.memanto`. A separate uv environment does not isolate this directory.
Consequently:

- Sequential trials may share one Memanto installation if each uses a unique
  agent and namespace.
- Parallel trials should use separate Memanto/Moorcheh containers or another
  fully isolated user-profile boundary.
- Moorcheh should run as a sibling service, not through Docker-in-Docker.

In the current development shell, set `DEBUG=false` when invoking Memanto because
the ambient `DEBUG=release` value is incompatible with Memanto's Boolean setting.

## LangGraph

Use `InMemoryStore` only for smoke tests. It is local but loses its contents when
the process exits and does not enable semantic search by default.

For pilot and final runs, use `PostgresStore` with:

- A pinned local PostgreSQL container image.
- A persistent database volume.
- A unique schema/database and LangGraph namespace per trial.
- `store.setup()` during an explicit initialization or migration step.
- A configured embedding provider and matching dimensions when semantic search
  is enabled.

The initial Windows/Linux-AMD64 development service is pinned to pgvector 0.8.6
on PostgreSQL 16/bookworm using this immutable platform manifest:

```text
pgvector/pgvector@sha256:eac621400b7b7ff52493883e41e930e3d104695fea5b68cc0c42370cf7880067
```

The moving `latest` and `pg16` tags are not used. Service configuration lives in
`../infra/langgraph/compose.yaml`; credentials are derived from the ignored
`LANGGRAPH_POSTGRES_DSN` only at process launch.

LangGraph does not decide what becomes memory. The selected write policy must
explicitly call `put()` or `aput()`.

### LangMem writer over LangGraph

LangMem is available as `langmem_store_manager_v1`, pinned to 0.0.30. It adds a
selective extraction/update writer while retaining LangGraph as the storage
contract. The local development default is `SqliteStore`, with one database at
`artifacts/memory/langmem/<run_id>/store.sqlite`; `InMemoryStore` is used only by
the smoke command. Set `LANGMEM_STORAGE_BACKEND=postgres` to reuse the configured
`LANGGRAPH_POSTGRES_DSN` for a pilot or final condition.

Memory families are independent, comma-separated configuration values:

- `semantic`: durable facts, preferences, relationships, goals, or decisions;
- `episodic`: specific events and outcomes;
- `procedural`: reusable rules stored as inert records.

The default is `LANGMEM_MEMORY_TYPES=semantic`. Every family receives its own
namespace below `membench/langmem/<run_id>/`. Enabling procedural storage does
not enable LangMem's prompt optimizer; runtime prompt optimization remains out
of scope.

The writer and embedding roles can each use `ollama` or `openai`. The default is
fully local Ollama for both roles. Any OpenAI role requires `OPENAI_API_KEY`, and
the status output reports only whether a credential is present. SQLite remains
local even when inference or embedding is remote.

## Model-provider configuration

Keep these settings separate in the resolved experiment manifest:

- Writer/extraction model.
- Reader/response model.
- Embedding model.
- Memory mechanism.
- Storage backend and path/namespace.

OpenAI may be used while the database remains local. However, memory text or
queries sent for extraction, answering, or embedding are processed remotely. For
strictly local processing, use Ollama for both the LLM and embeddings.

A single shared Ollama service is preferred when all mechanisms are evaluated
with the same model. Separate Ollama instances are only necessary when testing
different Ollama versions, server configurations, or incompatible model states.

## Trial lifecycle

Before each run, the runner should:

1. Resolve and validate a unique `run_id`.
2. Create or validate empty mechanism-specific storage.
3. Set mechanism environment variables before importing vendor packages.
4. Start and health-check Moorcheh, PostgreSQL, or Ollama when required.
5. Record package versions, container image digests, model identifiers,
   configuration hashes, storage identifiers, and random seeds.
6. Execute ingestion, attack delivery, retrieval, and response generation.
7. Preserve raw events, resolved configuration, logs, and evaluation inputs.
8. Stop services without deleting persistent evidence unless cleanup was
   explicitly requested.

## When to use full Docker Compose isolation

The hybrid setup is appropriate for development and sequential experiments. Use
a complete Compose stack per mechanism or trial when:

- Trials run concurrently.
- Results must reproduce on another machine or in CI.
- Vendor packages write uncontrolled global state.
- Different native libraries or system dependencies conflict.
- A trial requires a clean, disposable filesystem and network boundary.

Full Docker isolation provides stronger reproducibility and cleanup but adds image
build time, disk usage, networking complexity, volume permissions, and possible
GPU configuration for Ollama.

## Recommended rollout

- **Smoke:** separate uv environments and isolated storage; LangGraph may use
  `InMemoryStore`.
- **Pilot:** hybrid setup with Moorcheh and PostgreSQL containers.
- **Final:** pinned services, persistent per-run storage, complete provenance, and
  either the validated hybrid setup or per-trial Compose isolation for parallel
  execution.
