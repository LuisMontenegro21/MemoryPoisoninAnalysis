"""Command-line entry point for experiment setup and validation."""

import importlib.metadata
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer
from pydantic import ValidationError

from membench.contract import SUPPORTED_POLICIES, Mechanism, load_manifest
from membench.langgraph_store import (
    LangGraphStoreError,
    LangGraphStoreSettings,
    database_status,
    qualify_in_memory,
    qualify_store,
    run_postgres_service,
)
from membench.langgraph_store import package_versions as langgraph_versions
from membench.ollama import OllamaError, OllamaService, OllamaSettings
from membench.telemem import TeleMemError, TeleMemSettings
from membench.telemem import package_version as telemem_version
from membench.telemem import qualify as qualify_telemem

app = typer.Typer(help="Black-box memory-poisoning experiment harness.")
manifest_app = typer.Typer(help="Inspect and validate experiment manifests.")
ollama_app = typer.Typer(help="Inspect and qualify the shared Ollama endpoint.")
telemem_app = typer.Typer(help="Inspect and qualify the isolated TeleMem runtime.")
langgraph_app = typer.Typer(
    help="Manage and qualify the persistent LangGraph store."
)
app.add_typer(manifest_app, name="manifest")
app.add_typer(ollama_app, name="ollama")
app.add_typer(telemem_app, name="telemem")
app.add_typer(langgraph_app, name="langgraph")


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


@telemem_app.command("status")
def telemem_status() -> None:
    """Show the resolved TeleMem provider without importing vendor runtime state."""
    try:
        settings = TeleMemSettings.from_env()
        version = telemem_version()
    except (TeleMemError, ValueError) as exc:
        typer.echo(f"TeleMem check failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"TeleMem version: {version}")
    typer.echo(f"Provider: {settings.provider}")
    typer.echo(f"Endpoint: {settings.base_url}")
    typer.echo(f"Chat model: {settings.llm_model}")
    typer.echo(
        f"Embedding model: {settings.embedding_model} "
        f"({settings.embedding_dimensions} dimensions)"
    )
    typer.echo(f"Storage root: {settings.storage_root}")
    if settings.provider == "openai":
        configured = "yes" if settings.credential_configured else "no"
        typer.echo(f"OpenAI credential configured: {configured}")


@telemem_app.command("verify")
def telemem_verify(
    run_id: str = typer.Option(
        "",
        help=(
            "Unique run identifier; an isolated qualification ID is generated "
            "by default."
        ),
    ),
) -> None:
    """Run isolated direct and native-selective TeleMem write/search probes."""
    if not run_id:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"qualification-{timestamp}"
    try:
        settings = TeleMemSettings.from_env()
        result = qualify_telemem(settings, run_id)
    except (TeleMemError, ValueError, OSError) as exc:
        typer.echo(f"TeleMem qualification failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"TeleMem qualification passed: {result.run_id}")
    typer.echo(f"Provider: {settings.provider}")
    typer.echo(f"Storage: {result.storage_path}")
    typer.echo(
        "Direct path: "
        f"{result.direct_write_count} write(s), "
        f"{result.direct_search_count} search result(s)"
    )
    typer.echo(
        "Native-selective path: "
        f"{result.native_write_count} write(s), "
        f"{result.native_search_count} search result(s)"
    )


@langgraph_app.command("up")
def langgraph_up() -> None:
    """Start the pinned PostgreSQL/pgvector service and wait for health."""
    try:
        settings = LangGraphStoreSettings.from_env()
        output = run_postgres_service(settings, "up")
    except (LangGraphStoreError, ValueError) as exc:
        typer.echo(f"LangGraph PostgreSQL start failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if output:
        typer.echo(output)
    typer.echo(f"LangGraph PostgreSQL is ready: {settings.redacted_dsn}")


@langgraph_app.command("stop")
def langgraph_stop() -> None:
    """Stop PostgreSQL without deleting its persistent volume."""
    try:
        settings = LangGraphStoreSettings.from_env()
        output = run_postgres_service(settings, "stop")
    except (LangGraphStoreError, ValueError) as exc:
        typer.echo(f"LangGraph PostgreSQL stop failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if output:
        typer.echo(output)
    typer.echo("LangGraph PostgreSQL stopped; its volume was retained.")


@langgraph_app.command("status")
def langgraph_status() -> None:
    """Show package, database, and embedding status without exposing credentials."""
    try:
        settings = LangGraphStoreSettings.from_env()
        versions = langgraph_versions()
        server_version, vector_version = database_status(settings)
    except (LangGraphStoreError, ValueError) as exc:
        typer.echo(f"LangGraph store check failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    for package, version in versions.items():
        typer.echo(f"{package}: {version}")
    typer.echo(f"PostgreSQL: {server_version}")
    typer.echo(f"pgvector: {vector_version or 'not installed'}")
    typer.echo(f"Database: {settings.redacted_dsn}")
    typer.echo(f"Embedding endpoint: {settings.embedding_base_url}")
    typer.echo(
        f"Embedding model: {settings.embedding_model} "
        f"({settings.embedding_dimensions} dimensions)"
    )


@langgraph_app.command("verify")
def langgraph_verify(
    run_id: str = typer.Option(
        "",
        help=(
            "Unique run identifier; an isolated qualification ID is generated "
            "by default."
        ),
    ),
) -> None:
    """Run persistent write, read, semantic search, and isolation probes."""
    if not run_id:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"qualification-{timestamp}"
    try:
        settings = LangGraphStoreSettings.from_env()
        result = qualify_store(settings, run_id)
    except (LangGraphStoreError, ValueError) as exc:
        typer.echo(f"LangGraph store qualification failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"LangGraph store qualification passed: {result.run_id}")
    typer.echo(f"Namespace: {'/'.join(result.namespace)}")
    typer.echo(f"Exact read: {result.exact_read}")
    typer.echo(f"Semantic results: {result.semantic_results}")
    typer.echo(f"Isolated namespace empty: {result.isolated_namespace_empty}")


@langgraph_app.command("smoke")
def langgraph_smoke(
    run_id: str = typer.Option("smoke", help="Namespace identifier for the smoke run."),
) -> None:
    """Verify LangGraph and Ollama using a non-persistent in-memory store."""
    try:
        settings = LangGraphStoreSettings.from_env()
        result = qualify_in_memory(settings, run_id)
    except (LangGraphStoreError, ValueError) as exc:
        typer.echo(f"LangGraph in-memory smoke test failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo("LangGraph in-memory smoke test passed (non-persistent).")
    typer.echo(f"Namespace: {'/'.join(result.namespace)}")
    typer.echo(f"Exact read: {result.exact_read}")
    typer.echo(f"Semantic results: {result.semantic_results}")
    typer.echo(f"Isolated namespace empty: {result.isolated_namespace_empty}")
