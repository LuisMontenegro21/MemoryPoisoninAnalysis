"""Typed, versioned contract for resolved black-box experiment manifests."""

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mechanism(StrEnum):
    TELEMEM = "telemem"
    MEMANTO = "memanto"
    LANGGRAPH = "langgraph"


class WritePolicy(StrEnum):
    DIRECT = "direct"
    SHARED_GUARDED = "shared_guarded"
    NATIVE_SELECTIVE = "native_selective"


SUPPORTED_POLICIES: dict[Mechanism, frozenset[WritePolicy]] = {
    Mechanism.TELEMEM: frozenset(WritePolicy),
    Mechanism.MEMANTO: frozenset(WritePolicy),
    Mechanism.LANGGRAPH: frozenset(WritePolicy),
}

LANGMEM_WRITER_IMPLEMENTATION = "langmem_store_manager_v1"
LANGMEM_WRITER_VERSION = "0.0.30"
LANGMEM_MEMORY_TYPES = frozenset({"semantic", "episodic", "procedural"})


class DatasetConfig(StrictModel):
    name: str = Field(pattern=r"^personamem_v2$")
    revision: str = Field(min_length=1)
    subset: str = Field(pattern=r"^blackbox_battery_v1$")


class ConditionConfig(StrictModel):
    mechanism: Mechanism
    mechanism_version: str = Field(min_length=1)
    write_policy: WritePolicy
    mechanism_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def policy_must_be_supported(self) -> "ConditionConfig":
        if self.write_policy not in SUPPORTED_POLICIES[self.mechanism]:
            raise ValueError(
                f"{self.mechanism.value} does not support "
                f"{self.write_policy.value}"
            )
        if (
            self.mechanism == Mechanism.LANGGRAPH
            and self.write_policy == WritePolicy.NATIVE_SELECTIVE
        ):
            implementation = self.mechanism_options.get("writer_implementation")
            version = self.mechanism_options.get("writer_version")
            if implementation != LANGMEM_WRITER_IMPLEMENTATION:
                raise ValueError(
                    "LangGraph native_selective requires the explicitly versioned "
                    f"writer_implementation={LANGMEM_WRITER_IMPLEMENTATION!r}"
                )
            if version != LANGMEM_WRITER_VERSION:
                raise ValueError(
                    "LangGraph native_selective requires "
                    f"writer_version={LANGMEM_WRITER_VERSION!r}"
                )
            memory_types = self.mechanism_options.get("memory_types")
            if (
                not isinstance(memory_types, list)
                or not memory_types
                or any(
                    not isinstance(item, str) or item not in LANGMEM_MEMORY_TYPES
                    for item in memory_types
                )
                or len(set(memory_types)) != len(memory_types)
            ):
                allowed = ", ".join(sorted(LANGMEM_MEMORY_TYPES))
                raise ValueError(
                    "LangMem memory_types must be a non-empty unique list containing "
                    f"only: {allowed}"
                )
            if self.mechanism_options.get("procedural_prompt_optimization", False):
                raise ValueError(
                    "procedural prompt optimization is outside this experiment track"
                )
        return self


class ModelRef(StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class ModelsConfig(StrictModel):
    writer: ModelRef
    responder: ModelRef
    embedding: ModelRef


class RetrievalConfig(StrictModel):
    top_k: int = Field(gt=0)
    threshold: float | None = None
    context_token_budget: int = Field(gt=0)


class AttackConfig(StrictModel):
    knowledge: str = Field(pattern=r"^black_box$")
    delivery: str = Field(pattern=r"^conversation$")
    battery: str = Field(pattern=r"^pmv2_blackbox_battery_v1$")
    attack_id: str = Field(pattern=r"^bb-(pi|opc)-\d{3}$")


class IsolationConfig(StrictModel):
    run_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    config_ref: str = "planning/config.md"


class ReplicationConfig(StrictModel):
    seed: int = Field(ge=0)
    response_replicates: int = Field(gt=0)


class ExperimentManifest(StrictModel):
    schema_version: int = Field(ge=1, le=1)
    experiment_track: str = Field(pattern=r"^blackbox_memory_poisoning$")
    dataset: DatasetConfig
    condition: ConditionConfig
    models: ModelsConfig
    retrieval: RetrievalConfig
    attack: AttackConfig
    isolation: IsolationConfig
    replication: ReplicationConfig


def load_manifest(path: Path) -> ExperimentManifest:
    """Load and validate one experiment manifest."""
    with path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    return ExperimentManifest.model_validate(data)
