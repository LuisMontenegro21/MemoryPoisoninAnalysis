from pathlib import Path

import pytest

from membench.telemem import TeleMemError, TeleMemSettings


def test_ollama_settings_build_isolated_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TELEMEM_PROVIDER", "ollama")
    monkeypatch.setenv("TELEMEM_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("OLLAMA_OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
    monkeypatch.setenv(
        "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:137m-v1.5-fp16"
    )
    monkeypatch.setenv("OLLAMA_EMBEDDING_DIMENSIONS", "768")

    settings = TeleMemSettings.from_env()
    config = settings.memory_config("run-001")

    assert config["llm"]["provider"] == "openai"
    assert config["llm"]["config"]["model"] == "qwen2.5:7b"
    assert config["embedder"]["config"]["embedding_dims"] == 768
    assert config["vector_store"]["config"]["path"] == str(
        tmp_path / "run-001" / "faiss"
    )
    assert config["history_db_path"] == str(tmp_path / "run-001" / "history.db")


def test_openai_settings_are_independent_from_ollama(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TELEMEM_PROVIDER", "openai")
    monkeypatch.setenv("TELEMEM_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("TELEMEM_OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("TELEMEM_OPENAI_CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("TELEMEM_OPENAI_EMBEDDING_MODEL", "test-embedding-model")
    monkeypatch.setenv("TELEMEM_OPENAI_EMBEDDING_DIMENSIONS", "1536")

    settings = TeleMemSettings.from_env()
    config = settings.memory_config("run-openai")

    assert settings.provider == "openai"
    assert settings.credential_configured
    assert config["llm"]["config"]["model"] == "test-chat-model"
    assert config["embedder"]["config"]["model"] == "test-embedding-model"
    assert config["llm"]["config"]["api_key"] == "test-secret"


def test_openai_runtime_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMEM_PROVIDER", "openai")
    # An explicit empty value prevents python-dotenv from loading a developer's
    # real key into this negative test.
    monkeypatch.setenv("OPENAI_API_KEY", "")

    settings = TeleMemSettings.from_env()

    with pytest.raises(TeleMemError, match="OPENAI_API_KEY"):
        settings.memory_config("run-openai")


def test_run_id_rejects_path_traversal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMEM_PROVIDER", "ollama")
    settings = TeleMemSettings.from_env()

    with pytest.raises(ValueError, match="run_id"):
        settings.paths_for("../another-run")
