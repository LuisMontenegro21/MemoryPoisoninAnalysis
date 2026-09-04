# Docker Hub CDN Pull Issues

## Summary

During local setup, Docker repeatedly failed to download image layers from
Docker Hub's `production.cloudfront.docker.com` endpoint. The failures affected
two unrelated services, indicating a shared Docker Hub/CDN delivery problem
rather than a Memanto, Moorcheh, LangGraph, or image-version incompatibility.

Typical errors included:

```text
failed to copy: httpReadSeeker: failed open
Get "https://production.cloudfront.docker.com/...": EOF
```

Retries sometimes completed and cached additional layers, but subsequent layers
failed with the same `EOF` condition.

## Affected services

### Moorcheh for Memanto

- Selected image: `moorcheh/server:v0.1.4`
- Immutable digest:
  `sha256:543158ca24391a6d83336f0cf5d20ab2fba79c46bfe89a357c31b7a26cb4e0fe`
- Result: image pull incomplete; no Moorcheh container or persistent data
  directory was created.
- Memanto on-prem configuration remains paused.

### PostgreSQL/pgvector for LangGraph

- Selected release: pgvector 0.8.6 on PostgreSQL 16/bookworm, Linux/AMD64
- Immutable digest:
  `sha256:eac621400b7b7ff52493883e41e930e3d104695fea5b68cc0c42370cf7880067`
- Result: image pull incomplete; no LangGraph PostgreSQL container or persistent
  volume was created.
- LangGraph's non-persistent `InMemoryStore` qualification with Ollama passes,
  but PostgreSQL persistence has not yet been qualified.
- LangMem now has a separately qualified persistent SQLite path at
  `artifacts/memory/langmem/<run_id>/store.sqlite`. This removes Docker from
  local LangMem development, but it does not qualify or replace the planned
  PostgreSQL pilot/final backend.

## Current handling

- Do not replace the pinned references with `latest` or another moving tag.
- Keep Docker's partially downloaded layers cached for a later resumable pull.
- Retry only when Docker Desktop's Linux engine is running and Docker Hub CDN
  connectivity is stable.
- After a successful pull, verify the local image digest before launching the
  service, then run its health and persistence qualification.
