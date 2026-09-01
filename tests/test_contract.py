from pathlib import Path

import pytest
from pydantic import ValidationError

from membench.contract import load_manifest

EXAMPLE = Path("configs/experiments/blackbox/example.yaml")


def test_example_manifest_is_valid() -> None:
    manifest = load_manifest(EXAMPLE)
    assert manifest.schema_version == 1
    assert manifest.condition.mechanism.value == "telemem"


def test_langgraph_native_selective_is_rejected(tmp_path: Path) -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace("mechanism: telemem", "mechanism: langgraph")
    candidate = tmp_path / "unsupported.yaml"
    candidate.write_text(text, encoding="utf-8")

    with pytest.raises(ValidationError, match="does not support native_selective"):
        load_manifest(candidate)
