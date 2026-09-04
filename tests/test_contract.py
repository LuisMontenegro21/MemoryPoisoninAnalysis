from pathlib import Path

import pytest
from pydantic import ValidationError

from membench.contract import load_manifest

EXAMPLE = Path("configs/experiments/blackbox/example.yaml")


def test_example_manifest_is_valid() -> None:
    manifest = load_manifest(EXAMPLE)
    assert manifest.schema_version == 1
    assert manifest.condition.mechanism.value == "telemem"


def test_unversioned_langgraph_native_selective_is_rejected(tmp_path: Path) -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace("mechanism: telemem", "mechanism: langgraph")
    candidate = tmp_path / "unsupported.yaml"
    candidate.write_text(text, encoding="utf-8")

    with pytest.raises(ValidationError, match="writer_implementation"):
        load_manifest(candidate)


def test_versioned_langmem_writer_enables_langgraph_selective_policy(
    tmp_path: Path,
) -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace("mechanism: telemem", "mechanism: langgraph")
    text = text.replace(
        "    infer: true",
        "    writer_implementation: langmem_store_manager_v1\n"
        "    writer_version: 0.0.30\n"
        "    memory_types: [semantic]\n"
        "    procedural_prompt_optimization: false",
    )
    candidate = tmp_path / "langmem.yaml"
    candidate.write_text(text, encoding="utf-8")

    manifest = load_manifest(candidate)

    assert manifest.condition.mechanism_options["memory_types"] == ["semantic"]


def test_langmem_writer_rejects_unknown_memory_family(tmp_path: Path) -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace("mechanism: telemem", "mechanism: langgraph")
    text = text.replace(
        "    infer: true",
        "    writer_implementation: langmem_store_manager_v1\n"
        "    writer_version: 0.0.30\n"
        "    memory_types: [semantic, imaginary]",
    )
    candidate = tmp_path / "unknown-memory.yaml"
    candidate.write_text(text, encoding="utf-8")

    with pytest.raises(ValidationError, match="LangMem memory_types"):
        load_manifest(candidate)
