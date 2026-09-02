"""Provider-selectable TeleMem configuration and qualification helpers."""

from __future__ import annotations

import importlib.metadata
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class TeleMemError(RuntimeError):
    """Raised when TeleMem cannot be configured or qualified."""


_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


@dataclass(frozen=True)
class TeleMemPaths:
    """Run-specific storage paths required for TeleMem isolation."""

    run_dir: Path
    mem0_dir: Path
    vector_dir: Path
    history_db: Path
    collection_name: str


@dataclass(frozen=True)
class TeleMemSettings:
    """Resolved TeleMem model, provider, and local-storage settings."""

    provider: str
    base_url: str
    llm_model: str
    embedding_model: str
    embedding_dimensions: int
    storage_root: Path
    buffer_size: int
    similarity_threshold: float
    api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> TeleMemSettings:
        load_dotenv(override=False)
        provider = os.getenv("TELEMEM_PROVIDER", "ollama").strip().lower()
        if provider == "ollama":
            base_url = os.getenv(
                "OLLAMA_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1"
            )
            api_key = os.getenv("OLLAMA_API_KEY", "ollama")
            llm_model = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
            embedding_model = os.getenv(
                "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:137m-v1.5-fp16"
            )
            dimensions_text = os.getenv("OLLAMA_EMBEDDING_DIMENSIONS", "768")
        elif provider == "openai":
            base_url = (
                os.getenv("TELEMEM_OPENAI_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or "https://api.openai.com/v1"
            )
            api_key = os.getenv("OPENAI_API_KEY") or None
            llm_model = os.getenv("TELEMEM_OPENAI_CHAT_MODEL", "gpt-5-mini")
            embedding_model = os.getenv(
                "TELEMEM_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
            )
            dimensions_text = os.getenv(
                "TELEMEM_OPENAI_EMBEDDING_DIMENSIONS", "1536"
            )
        else:
            raise ValueError("TELEMEM_PROVIDER must be 'ollama' or 'openai'")

        dimensions = int(dimensions_text)
        buffer_size = int(os.getenv("TELEMEM_BUFFER_SIZE", "64"))
        similarity_threshold = float(
            os.getenv("TELEMEM_SIMILARITY_THRESHOLD", "0.95")
        )
        if dimensions <= 0:
            raise ValueError("TeleMem embedding dimensions must be positive")
        if buffer_size <= 0:
            raise ValueError("TELEMEM_BUFFER_SIZE must be positive")
        if not 0 <= similarity_threshold <= 1:
            raise ValueError(
                "TELEMEM_SIMILARITY_THRESHOLD must be between zero and one"
            )

        return cls(
            provider=provider,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            llm_model=llm_model,
            embedding_model=embedding_model,
            embedding_dimensions=dimensions,
            storage_root=Path(
                os.getenv("TELEMEM_STORAGE_ROOT", "artifacts/memory/telemem")
            ),
            buffer_size=buffer_size,
            similarity_threshold=similarity_threshold,
        )

    @property
    def credential_configured(self) -> bool:
        """Report credential presence without exposing its value."""
        return bool(self.api_key)

    def validate_runtime(self) -> None:
        """Reject configurations that would silently fall back or fail remotely."""
        if not self.llm_model:
            raise TeleMemError("TeleMem chat model is empty")
        if not self.embedding_model:
            raise TeleMemError("TeleMem embedding model is empty")
        if self.provider == "openai" and not self.api_key:
            raise TeleMemError(
                "OPENAI_API_KEY is required when TELEMEM_PROVIDER=openai"
            )

    def paths_for(self, run_id: str) -> TeleMemPaths:
        """Resolve storage for one run without touching another run's state."""
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError(
                "run_id must start with an alphanumeric character and contain only "
                "letters, numbers, '.', '_' or '-'"
            )
        run_dir = self.storage_root / run_id
        return TeleMemPaths(
            run_dir=run_dir,
            mem0_dir=run_dir / "mem0",
            vector_dir=run_dir / "faiss",
            history_db=run_dir / "history.db",
            collection_name=f"telemem_{run_id}",
        )

    def memory_config(self, run_id: str) -> dict[str, Any]:
        """Build TeleMem's Mem0-compatible configuration for one isolated run."""
        self.validate_runtime()
        paths = self.paths_for(run_id)
        provider_config = {
            "model": self.llm_model,
            "openai_base_url": self.base_url,
            "api_key": self.api_key,
            "temperature": 0,
        }
        embedder_config = {
            "model": self.embedding_model,
            "openai_base_url": self.base_url,
            "api_key": self.api_key,
            "embedding_dims": self.embedding_dimensions,
        }
        return {
            # TeleMem's supported Ollama example intentionally uses the OpenAI
            # provider against Ollama's /v1 compatibility endpoint.
            "llm": {"provider": "openai", "config": provider_config},
            "embedder": {"provider": "openai", "config": embedder_config},
            "vector_store": {
                "provider": "faiss",
                "config": {
                    "collection_name": paths.collection_name,
                    "path": str(paths.vector_dir),
                    "embedding_model_dims": self.embedding_dimensions,
                },
            },
            "history_db_path": str(paths.history_db),
            "buffer_size": self.buffer_size,
            "similarity_threshold": self.similarity_threshold,
        }


@dataclass(frozen=True)
class TeleMemQualification:
    """Non-secret summary of one isolated TeleMem qualification run."""

    run_id: str
    storage_path: Path
    direct_write_count: int
    direct_search_count: int
    native_write_count: int
    native_search_count: int


def package_version() -> str:
    """Return the installed TeleMem version without importing the package."""
    try:
        return importlib.metadata.version("telemem")
    except importlib.metadata.PackageNotFoundError as exc:
        raise TeleMemError(
            "TeleMem is not installed in this environment; run this command from "
            ".venvs/telemem"
        ) from exc


def create_memory(settings: TeleMemSettings, run_id: str) -> Any:
    """Create TeleMem only after its run-specific MEM0_DIR has been selected."""
    package_version()
    settings.validate_runtime()
    paths = settings.paths_for(run_id)
    paths.mem0_dir.mkdir(parents=True, exist_ok=True)
    paths.vector_dir.mkdir(parents=True, exist_ok=True)
    paths.history_db.parent.mkdir(parents=True, exist_ok=True)

    os.environ["MEM0_DIR"] = str(paths.mem0_dir.resolve())
    os.environ.setdefault("MEM0_TELEMETRY", "False")

    try:
        import telemem
        from telemem.configs import TeleMemoryConfig

        config = TeleMemoryConfig.model_validate(settings.memory_config(run_id))
        return telemem.Memory(config=config)
    except Exception as exc:
        raise TeleMemError(f"TeleMem initialization failed: {exc}") from exc


def qualify(settings: TeleMemSettings, run_id: str) -> TeleMemQualification:
    """Exercise empty state, direct memory, and native-selective memory paths."""
    memory = create_memory(settings, run_id)
    user_id = "qualification-user"

    initial = memory.search(
        "What field notebook color is preferred?",
        user_id=user_id,
        run_id=run_id,
        limit=5,
        rerank=False,
    )
    if initial.get("results"):
        raise TeleMemError(
            f"qualification storage is not empty for run_id={run_id!r}"
        )

    direct_text = "My field notebook color is amber."
    direct_write = memory.add(
        direct_text,
        user_id=user_id,
        run_id=run_id,
        infer=False,
        metadata={"qualification": "direct"},
    )
    direct_search = memory.search(
        "What field notebook color do I prefer?",
        user_id=user_id,
        run_id=run_id,
        limit=5,
        rerank=False,
    )
    direct_results = direct_search.get("results", [])
    if not any("amber" in item.get("memory", "").lower() for item in direct_results):
        raise TeleMemError("TeleMem direct write was not retrieved")

    native_write = memory.add(
        [
            {
                "role": "user",
                "content": "Please remember that I take astronomy notes in amber ink.",
            },
            {
                "role": "assistant",
                "content": "I will remember your preference for amber ink.",
            },
        ],
        user_id=user_id,
        run_id=run_id,
        infer=True,
        metadata={"qualification": "native_selective"},
    )
    native_results_written = native_write.get("results", [])
    if not native_results_written:
        raise TeleMemError("TeleMem native-selective write produced no memory")

    native_search = memory.search(
        "What ink do I use for astronomy notes?",
        user_id=user_id,
        run_id=run_id,
        limit=5,
        rerank=False,
    )
    native_results = native_search.get("results", [])
    if not any("amber" in item.get("memory", "").lower() for item in native_results):
        raise TeleMemError("TeleMem native-selective memory was not retrieved")

    return TeleMemQualification(
        run_id=run_id,
        storage_path=settings.paths_for(run_id).run_dir,
        direct_write_count=len(direct_write.get("results", [])),
        direct_search_count=len(direct_results),
        native_write_count=len(native_results_written),
        native_search_count=len(native_results),
    )
