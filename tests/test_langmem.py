from pathlib import Path

import pytest

from membench.langmem import LangMemError, LangMemSettings, MemoryType


def _set_ollama_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGMEM_PROVIDER", "ollama")
    monkeypatch.setenv("LANGMEM_WRITER_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("LANGMEM_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv(
        "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:137m-v1.5-fp16"
    )
    monkeypatch.setenv("OLLAMA_EMBEDDING_DIMENSIONS", "3")
    monkeypatch.setenv("LANGMEM_MEMORY_TYPES", "semantic,episodic,procedural")
    monkeypatch.setenv("LANGMEM_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("LANGMEM_SQLITE_ROOT", "artifacts/memory/langmem")


def test_settings_keep_memory_families_and_storage_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ollama_defaults(monkeypatch)
    monkeypatch.setenv("OLLAMA_CHAT_MODEL_DIGEST", "sha256-pinned")

    settings = LangMemSettings.from_env()

    assert settings.memory_types == (
        MemoryType.SEMANTIC,
        MemoryType.EPISODIC,
        MemoryType.PROCEDURAL,
    )
    assert settings.namespace_for("run-001", MemoryType.EPISODIC) == (
        "membench",
        "langmem",
        "run-001",
        "episodic",
    )
    assert settings.sqlite_path_for("run-001") == Path(
        "artifacts/memory/langmem/run-001/store.sqlite"
    )
    assert settings.writer_model_digest == "sha256-pinned"


def test_run_id_rejects_path_traversal(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ollama_defaults(monkeypatch)
    settings = LangMemSettings.from_env()

    with pytest.raises(ValueError, match="run_id"):
        settings.sqlite_path_for("../other")


def test_langmem_index_covers_wrapped_and_direct_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ollama_defaults(monkeypatch)

    def fake_embed(_service: object, _model: str, text: str) -> list[float]:
        return [float(len(text)), 0.0, 1.0]

    monkeypatch.setattr("membench.langgraph_store.OllamaService.embed", fake_embed)
    settings = LangMemSettings.from_env()
    config = settings.index_config()

    assert config["fields"] == ["text", "content.text"]
    assert config["embed"](["one"]) == [[3.0, 0.0, 1.0]]


def test_openai_provider_requires_an_explicit_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ollama_defaults(monkeypatch)
    monkeypatch.setenv("LANGMEM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("membench.langmem.load_dotenv", lambda **_kwargs: None)

    with pytest.raises(LangMemError, match="OPENAI_API_KEY"):
        LangMemSettings.from_env()


def test_invalid_or_duplicate_memory_types_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ollama_defaults(monkeypatch)
    monkeypatch.setenv("LANGMEM_MEMORY_TYPES", "semantic,semantic")

    with pytest.raises(ValueError, match="duplicates"):
        LangMemSettings.from_env()
