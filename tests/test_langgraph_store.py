import pytest

from membench.langgraph_store import LangGraphStoreSettings


def test_settings_redact_password_and_build_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LANGGRAPH_POSTGRES_DSN",
        "postgresql://membench:test-secret@127.0.0.1:5432/membench",
    )
    monkeypatch.setenv("OLLAMA_EMBEDDING_DIMENSIONS", "768")

    settings = LangGraphStoreSettings.from_env()

    assert settings.redacted_dsn == (
        "postgresql://membench:***@127.0.0.1:5432/membench"
    )
    assert settings.namespace_for("run-001") == (
        "membench",
        "langgraph",
        "run-001",
    )
    assert settings.postgres_image.startswith("pgvector/pgvector@sha256:")
    assert "latest" not in settings.postgres_image


def test_compose_environment_is_derived_from_private_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LANGGRAPH_POSTGRES_DSN",
        "postgresql://membench:test%2Dsecret@127.0.0.1:5544/testdb",
    )
    settings = LangGraphStoreSettings.from_env()

    environment = settings.compose_environment()

    assert environment["LANGGRAPH_POSTGRES_USER"] == "membench"
    assert environment["LANGGRAPH_POSTGRES_PASSWORD"] == "test-secret"
    assert environment["LANGGRAPH_POSTGRES_DB"] == "testdb"
    assert environment["LANGGRAPH_POSTGRES_PORT"] == "5544"


def test_run_id_rejects_path_traversal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LANGGRAPH_POSTGRES_DSN",
        "postgresql://membench:test-secret@127.0.0.1:5432/membench",
    )
    settings = LangGraphStoreSettings.from_env()

    with pytest.raises(ValueError, match="run_id"):
        settings.namespace_for("../other")


def test_index_uses_ollama_embedding_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LANGGRAPH_POSTGRES_DSN",
        "postgresql://membench:test-secret@127.0.0.1:5432/membench",
    )
    monkeypatch.setenv("OLLAMA_EMBEDDING_DIMENSIONS", "3")

    def fake_embed(_service: object, _model: str, text: str) -> list[float]:
        return [float(len(text)), 0.0, 1.0]

    monkeypatch.setattr("membench.langgraph_store.OllamaService.embed", fake_embed)
    settings = LangGraphStoreSettings.from_env()
    config = settings.index_config()
    embed = config["embed"]

    assert config["dims"] == 3
    assert config["fields"] == ["text"]
    assert embed(["one"]) == [[3.0, 0.0, 1.0]]
