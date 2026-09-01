"""Command-line entry point for experiment setup and validation."""

import importlib.metadata
import platform
import sys
from pathlib import Path

import typer
from pydantic import ValidationError

from membench.contract import SUPPORTED_POLICIES, Mechanism, load_manifest
from membench.ollama import OllamaError, OllamaService, OllamaSettings

app = typer.Typer(help="Black-box memory-poisoning experiment harness.")
manifest_app = typer.Typer(help="Inspect and validate experiment manifests.")
ollama_app = typer.Typer(help="Inspect and qualify the shared Ollama endpoint.")
app.add_typer(manifest_app, name="manifest")
app.add_typer(ollama_app, name="ollama")


@app.command()
def doctor() -> None:
    """Report whether the core development environment is ready."""
    typer.echo(f"Python: {platform.python_version()}")
    typer.echo(f"Executable: {sys.executable}")
    typer.echo("Core packages:")
    for package in ("pydantic", "PyYAML", "typer"):
        typer.echo(f"  {package}: {importlib.metadata.version(package)}")
    if sys.version_info[:2] != (3, 12):
        typer.echo("ERROR: this project requires Python 3.12.x", err=True)
        raise typer.Exit(1)
    typer.echo("Environment is ready.")


@app.command("matrix")
def show_matrix() -> None:
    """Print supported mechanism/write-policy combinations."""
    for mechanism in Mechanism:
        policies = ", ".join(sorted(p.value for p in SUPPORTED_POLICIES[mechanism]))
        typer.echo(f"{mechanism.value}: {policies}")


@manifest_app.command("validate")
def validate_manifest(path: Path) -> None:
    """Validate a resolved experiment manifest against schema version 1."""
    try:
        manifest = load_manifest(path)
    except (OSError, ValidationError, ValueError) as exc:
        typer.echo(f"Invalid manifest: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Valid manifest: {manifest.isolation.run_id} "
        f"({manifest.condition.mechanism.value}/"
        f"{manifest.condition.write_policy.value})"
    )


@ollama_app.command("status")
def ollama_status() -> None:
    """Show endpoint, server version, and locally installed model digests."""
    settings = OllamaSettings.from_env()
    service = OllamaService(settings.base_url)
    try:
        version = service.version()
        models = service.models()
    except (OllamaError, ValueError) as exc:
        typer.echo(f"Ollama check failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Endpoint: {settings.base_url}")
    typer.echo(f"OpenAI-compatible endpoint: {settings.openai_base_url}")
    typer.echo(f"Server version: {version}")
    if not models:
        typer.echo("Models: none installed")
        return
    typer.echo("Models:")
    for model in models:
        name = model.get("name", "unknown")
        digest = str(model.get("digest", "unknown"))
        typer.echo(f"  {name}: {digest}")


@ollama_app.command("verify")
def ollama_verify() -> None:
    """Exercise the configured chat and embedding models through native APIs."""
    settings = OllamaSettings.from_env()
    service = OllamaService(settings.base_url, timeout=180.0)
    try:
        required = {settings.chat_model, settings.embedding_model}
        missing = sorted(model for model in required if not service.has_model(model))
        if missing:
            raise OllamaError(f"missing configured models: {', '.join(missing)}")
        service.verify_digest(settings.chat_model, settings.chat_model_digest)
        service.verify_digest(
            settings.embedding_model, settings.embedding_model_digest
        )
        vector = service.embed(
            settings.embedding_model, "Ollama memory qualification probe"
        )
        if len(vector) != settings.embedding_dimensions:
            raise OllamaError(
                f"{settings.embedding_model} returned {len(vector)} dimensions; "
                f"expected {settings.embedding_dimensions}"
            )
        reply = service.chat(settings.chat_model, "Reply with exactly: OLLAMA_READY")
        if reply.strip() != "OLLAMA_READY":
            raise OllamaError(
                f"chat qualification returned an unexpected response: {reply!r}"
            )
    except (OllamaError, ValueError) as exc:
        typer.echo(f"Ollama qualification failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Chat model ready: {settings.chat_model}")
    typer.echo(
        f"Embedding model ready: {settings.embedding_model} "
        f"({len(vector)} dimensions)"
    )
