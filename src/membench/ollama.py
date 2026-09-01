"""Shared Ollama configuration and qualification client."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


class OllamaError(RuntimeError):
    """Raised when the local Ollama service cannot satisfy a request."""


@dataclass(frozen=True)
class OllamaSettings:
    """Role-specific settings for one shared local Ollama server."""

    base_url: str
    openai_base_url: str
    chat_model: str
    chat_model_digest: str | None
    embedding_model: str
    embedding_model_digest: str | None
    embedding_dimensions: int

    @classmethod
    def from_env(cls) -> OllamaSettings:
        load_dotenv(override=False)
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        dimensions = int(os.getenv("OLLAMA_EMBEDDING_DIMENSIONS", "768"))
        if dimensions <= 0:
            raise ValueError("OLLAMA_EMBEDDING_DIMENSIONS must be positive")
        return cls(
            base_url=base_url.rstrip("/"),
            openai_base_url=os.getenv(
                "OLLAMA_OPENAI_BASE_URL", f"{base_url.rstrip('/')}/v1"
            ).rstrip("/"),
            chat_model=os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b"),
            chat_model_digest=os.getenv("OLLAMA_CHAT_MODEL_DIGEST") or None,
            embedding_model=os.getenv(
                "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"
            ),
            embedding_model_digest=os.getenv("OLLAMA_EMBEDDING_MODEL_DIGEST")
            or None,
            embedding_dimensions=dimensions,
        )


class OllamaService:
    """Small native-HTTP client used for health and compatibility checks."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                result = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise OllamaError(
                f"Ollama is unavailable at {self.base_url}: {exc}"
            ) from exc
        if not isinstance(result, dict):
            raise OllamaError("Ollama returned a non-object JSON response")
        return result

    def version(self) -> str:
        version = self._request_json("GET", "/api/version").get("version")
        if not isinstance(version, str) or not version:
            raise OllamaError("Ollama did not return a version")
        return version

    def models(self) -> list[dict[str, Any]]:
        models = self._request_json("GET", "/api/tags").get("models")
        if not isinstance(models, list):
            raise OllamaError("Ollama did not return a model list")
        return [model for model in models if isinstance(model, dict)]

    def model_names(self) -> set[str]:
        return {
            name
            for model in self.models()
            if isinstance((name := model.get("name")), str)
        }

    def has_model(self, model: str) -> bool:
        """Accept Ollama's implicit ``:latest`` alias for untagged model IDs."""
        return self.model_info(model) is not None

    def model_info(self, model: str) -> dict[str, Any] | None:
        """Return model metadata, resolving an omitted tag to ``:latest``."""
        accepted_names = {model}
        if ":" not in model:
            accepted_names.add(f"{model}:latest")
        return next(
            (item for item in self.models() if item.get("name") in accepted_names),
            None,
        )

    def verify_digest(self, model: str, expected: str | None) -> None:
        if expected is None:
            return
        info = self.model_info(model)
        actual = info.get("digest") if info else None
        if actual != expected:
            raise OllamaError(
                f"{model} digest is {actual or 'unknown'}; expected {expected}"
            )

    def embed(self, model: str, text: str) -> list[float]:
        response = self._request_json(
            "POST", "/api/embed", {"model": model, "input": text}
        )
        embeddings = response.get("embeddings")
        if (
            not isinstance(embeddings, list)
            or not embeddings
            or not isinstance(embeddings[0], list)
        ):
            raise OllamaError("Ollama returned no embedding vector")
        return embeddings[0]

    def chat(self, model: str, prompt: str) -> str:
        response = self._request_json(
            "POST",
            "/api/chat",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0, "num_predict": 12},
            },
        )
        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama returned no chat content")
        return content
