"""LangGraph PostgresStore configuration and qualification helpers."""

from __future__ import annotations

import importlib.metadata
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from dotenv import load_dotenv

from membench.ollama import OllamaService


class LangGraphStoreError(RuntimeError):
    """Raised when the LangGraph persistent store cannot be used safely."""


_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
_POSTGRES_IMAGE = (
    "pgvector/pgvector@"
    "sha256:eac621400b7b7ff52493883e41e930e3d104695fea5b68cc0c42370cf7880067"
)


@dataclass(frozen=True)
class LangGraphStoreSettings:
    """Resolved PostgreSQL and embedding settings for LangGraph memory."""

    dsn: str
    postgres_image: str
    postgres_container: str
    embedding_base_url: str
    embedding_model: str
    embedding_dimensions: int

    @classmethod
    def from_env(cls) -> LangGraphStoreSettings:
        load_dotenv(override=False)
        dimensions = int(os.getenv("OLLAMA_EMBEDDING_DIMENSIONS", "768"))
        if dimensions <= 0:
            raise ValueError("OLLAMA_EMBEDDING_DIMENSIONS must be positive")
        dsn = os.getenv("LANGGRAPH_POSTGRES_DSN", "").strip()
        if not dsn:
            raise ValueError("LANGGRAPH_POSTGRES_DSN is required")
        return cls(
            dsn=dsn,
            postgres_image=os.getenv("LANGGRAPH_POSTGRES_IMAGE", _POSTGRES_IMAGE),
            postgres_container=os.getenv(
                "LANGGRAPH_POSTGRES_CONTAINER", "membench-langgraph-postgres"
            ),
            embedding_base_url=os.getenv(
                "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
            ).rstrip("/"),
            embedding_model=os.getenv(
                "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:137m-v1.5-fp16"
            ),
            embedding_dimensions=dimensions,
        )

    @property
    def redacted_dsn(self) -> str:
        """Return a connection string safe for logs and status output."""
        parsed = urlsplit(self.dsn)
        if parsed.username is None:
            return self.dsn
        user = parsed.username
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"{user}:***@{host}{port}"
        return urlunsplit(
            (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
        )

    def compose_environment(self) -> dict[str, str]:
        """Derive Compose variables from the private DSN without logging them."""
        parsed = urlsplit(self.dsn)
        database = parsed.path.lstrip("/")
        if not parsed.username or parsed.password is None or not database:
            raise LangGraphStoreError(
                "LANGGRAPH_POSTGRES_DSN must include user, password, and database"
            )
        environment = os.environ.copy()
        environment.update(
            {
                "LANGGRAPH_POSTGRES_IMAGE": self.postgres_image,
                "LANGGRAPH_POSTGRES_CONTAINER": self.postgres_container,
                "LANGGRAPH_POSTGRES_USER": unquote(parsed.username),
                "LANGGRAPH_POSTGRES_PASSWORD": unquote(parsed.password),
                "LANGGRAPH_POSTGRES_DB": unquote(database),
                "LANGGRAPH_POSTGRES_PORT": str(parsed.port or 5432),
            }
        )
        return environment

    def namespace_for(self, run_id: str) -> tuple[str, ...]:
        """Return a run-specific namespace that cannot traverse storage paths."""
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError(
                "run_id must start with an alphanumeric character and contain only "
                "letters, numbers, '.', '_' or '-'"
            )
        return ("membench", "langgraph", run_id)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch through the already-qualified native Ollama endpoint."""
        service = OllamaService(self.embedding_base_url, timeout=180.0)
        vectors = [service.embed(self.embedding_model, text) for text in texts]
        for vector in vectors:
            if len(vector) != self.embedding_dimensions:
                raise LangGraphStoreError(
                    f"{self.embedding_model} returned {len(vector)} dimensions; "
                    f"expected {self.embedding_dimensions}"
                )
        return vectors

    def index_config(self) -> dict[str, Any]:
        """Build the semantic-index configuration consumed by PostgresStore."""
        return {
            "dims": self.embedding_dimensions,
            "embed": self.embed_documents,
            "fields": ["text"],
        }


@dataclass(frozen=True)
class LangGraphStoreQualification:
    """Non-secret result of an isolated persistent-store qualification."""

    run_id: str
    namespace: tuple[str, ...]
    exact_read: bool
    semantic_results: int
    isolated_namespace_empty: bool


def package_versions() -> dict[str, str]:
    """Return pinned runtime versions without importing database modules."""
    packages = ("langgraph", "langgraph-checkpoint-postgres", "psycopg")
    try:
        return {package: importlib.metadata.version(package) for package in packages}
    except importlib.metadata.PackageNotFoundError as exc:
        raise LangGraphStoreError(
            "LangGraph PostgreSQL dependencies are not installed in this environment; "
            "run this command from .venvs/langgraph"
        ) from exc


def run_postgres_service(settings: LangGraphStoreSettings, action: str) -> str:
    """Start or stop the pinned Compose service while keeping secrets out of args."""
    if action not in {"up", "stop"}:
        raise ValueError("service action must be 'up' or 'stop'")
    project_root = Path(__file__).resolve().parents[2]
    compose_file = project_root / "infra" / "langgraph" / "compose.yaml"
    command = ["docker", "compose", "-f", str(compose_file)]
    command.extend(["up", "-d", "--wait"] if action == "up" else ["stop"])
    try:
        result = subprocess.run(
            command,
            cwd=project_root,
            env=settings.compose_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise LangGraphStoreError(f"Docker could not be started: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise LangGraphStoreError(f"Docker Compose failed: {detail}")
    return (result.stdout or result.stderr).strip()


def database_status(settings: LangGraphStoreSettings) -> tuple[str, str | None]:
    """Return the server and pgvector versions through a read-only connection."""
    package_versions()
    try:
        import psycopg

        with psycopg.connect(settings.dsn, connect_timeout=5) as connection:
            server_version = connection.execute("SHOW server_version").fetchone()[0]
            vector_row = connection.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
    except Exception as exc:
        raise LangGraphStoreError(f"PostgreSQL is unavailable: {exc}") from exc
    vector_version = vector_row[0] if vector_row else None
    return server_version, vector_version


def _exercise_store(
    store: Any, settings: LangGraphStoreSettings, run_id: str
) -> LangGraphStoreQualification:
    namespace = settings.namespace_for(run_id)
    isolated_namespace = settings.namespace_for(f"{run_id}-isolated")
    initial = store.search(
        namespace,
        query="Which telescope mount is preferred?",
        limit=5,
    )
    if initial:
        raise LangGraphStoreError(
            f"qualification namespace is not empty for run_id={run_id!r}"
        )

    store.put(
        namespace,
        "qualification-canary",
        {
            "text": (
                "The qualification user prefers an equatorial telescope mount."
            ),
            "source": "langgraph-store-qualification",
        },
    )
    exact_item = store.get(namespace, "qualification-canary")
    semantic = store.search(
        namespace,
        query="What kind of mount should the telescope use?",
        limit=5,
    )
    isolated = store.search(
        isolated_namespace,
        query="What kind of mount should the telescope use?",
        limit=5,
    )

    semantic_match = any(
        "equatorial" in item.value.get("text", "").lower() for item in semantic
    )
    if exact_item is None or not semantic_match or isolated:
        raise LangGraphStoreError(
            "LangGraph store failed exact-read, semantic-search, or isolation checks"
        )
    return LangGraphStoreQualification(
        run_id=run_id,
        namespace=namespace,
        exact_read=True,
        semantic_results=len(semantic),
        isolated_namespace_empty=not isolated,
    )


def qualify_in_memory(
    settings: LangGraphStoreSettings, run_id: str
) -> LangGraphStoreQualification:
    """Verify the LangGraph/Ollama contract without persistent storage."""
    package_versions()
    try:
        from langgraph.store.memory import InMemoryStore

        store = InMemoryStore(index=settings.index_config())
        return _exercise_store(store, settings, run_id)
    except LangGraphStoreError:
        raise
    except Exception as exc:
        raise LangGraphStoreError(
            f"LangGraph InMemoryStore qualification failed: {exc}"
        ) from exc


def qualify_store(
    settings: LangGraphStoreSettings, run_id: str
) -> LangGraphStoreQualification:
    """Run migrations and verify write, exact read, search, and isolation."""
    package_versions()

    try:
        from langgraph.store.postgres import PostgresStore

        with PostgresStore.from_conn_string(
            settings.dsn, index=settings.index_config()
        ) as store:
            store.setup()
            return _exercise_store(store, settings, run_id)
    except LangGraphStoreError:
        raise
    except Exception as exc:
        raise LangGraphStoreError(
            f"LangGraph PostgresStore qualification failed: {exc}"
        ) from exc
