from membench.ollama import OllamaService, OllamaSettings


def test_settings_keep_native_and_openai_endpoints_separate(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/")
    monkeypatch.setenv("OLLAMA_OPENAI_BASE_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("OLLAMA_EMBEDDING_DIMENSIONS", "768")

    settings = OllamaSettings.from_env()

    assert settings.base_url == "http://localhost:11434"
    assert settings.openai_base_url == "http://localhost:11434/v1"


def test_service_extracts_embedding_vector(monkeypatch) -> None:
    service = OllamaService("http://localhost:11434")
    monkeypatch.setattr(
        service,
        "_request_json",
        lambda method, path, payload=None: {"embeddings": [[0.1, 0.2, 0.3]]},
    )

    assert service.embed("example", "text") == [0.1, 0.2, 0.3]


def test_service_accepts_implicit_latest_model_tag(monkeypatch) -> None:
    service = OllamaService("http://localhost:11434")
    monkeypatch.setattr(
        service,
        "models",
        lambda: [{"name": "nomic-embed-text:latest"}, {"name": "qwen2.5:7b"}],
    )

    assert service.has_model("nomic-embed-text")
    assert service.has_model("qwen2.5:7b")


def test_service_verifies_model_digest(monkeypatch) -> None:
    service = OllamaService("http://localhost:11434")
    monkeypatch.setattr(
        service,
        "models",
        lambda: [{"name": "example:latest", "digest": "sha256-example"}],
    )

    service.verify_digest("example", "sha256-example")
