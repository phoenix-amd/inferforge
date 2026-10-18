"""Pydantic models for deployment lifecycle management."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class DeploymentState(str, Enum):
    pending = "pending"
    building = "building"
    deploying = "deploying"
    canary = "canary"
    promoted = "promoted"
    rollback = "rollback"
    stopped = "stopped"


# Valid state transitions
_VALID_TRANSITIONS: dict[DeploymentState, set[DeploymentState]] = {
    DeploymentState.pending: {DeploymentState.building, DeploymentState.deploying, DeploymentState.stopped},
    DeploymentState.building: {DeploymentState.deploying, DeploymentState.rollback, DeploymentState.stopped},
    DeploymentState.deploying: {DeploymentState.canary, DeploymentState.promoted, DeploymentState.rollback, DeploymentState.stopped},
    DeploymentState.canary: {DeploymentState.promoted, DeploymentState.rollback, DeploymentState.stopped},
    DeploymentState.promoted: {DeploymentState.rollback, DeploymentState.stopped},
    DeploymentState.rollback: {DeploymentState.stopped, DeploymentState.pending},
    DeploymentState.stopped: {DeploymentState.pending},
}


def is_valid_transition(current: DeploymentState, target: DeploymentState) -> bool:
    return target in _VALID_TRANSITIONS.get(current, set())


class LaunchConfig(BaseModel):
    """Docker launch configuration for a deployment."""

    image: str = Field(default="rocm/vllm-dev:latest", max_length=512)
    model_path: str = Field(max_length=512)
    tp: int = Field(default=1, ge=1)
    pp: int = Field(default=1, ge=1)
    dp: int = Field(default=1, ge=1)
    dtype: str = Field(default="bfloat16", max_length=16)
    port: int = Field(default=8000, ge=1, le=65535)
    max_num_seqs: int | None = Field(default=None, ge=1)
    max_model_len: int | None = Field(default=None, ge=1)
    gpu_memory_utilization: float = Field(default=0.9, ge=0.1, le=1.0)
    env_vars: dict[str, str] = Field(default_factory=dict)
    extra_args: str = Field(default="", max_length=4096)
    network_mode: str = Field(default="host", max_length=32)
    shm_size: str = Field(default="64g", max_length=16)


class DeploymentCreate(BaseModel):
    model_name: str = Field(min_length=1, max_length=256)
    framework: str = Field(default="vllm", max_length=32)
    tp: int = Field(default=1, ge=1, le=64)
    pp: int = Field(default=1, ge=1, le=32)
    dp: int = Field(default=1, ge=1, le=64)

    benchmark_run_id: str | None = Field(default=None, max_length=36)
    recipe_id: str | None = Field(default=None, max_length=36)
    node_id: str | None = Field(default=None, max_length=36)
    project_id: str | None = Field(default=None, max_length=36)

    launch_config_json: LaunchConfig | dict | None = None
    canary_pct: float = Field(default=0, ge=0, le=100)
    sla_ttft_p99_ms: float | None = Field(default=None, ge=0)
    sla_throughput_floor_tps: float | None = Field(default=None, ge=0)

    @field_validator("framework")
    @classmethod
    def validate_framework(cls, v: str) -> str:
        valid = {"vllm", "sglang", "tgi"}
        if v.lower() not in valid:
            raise ValueError(f"Unknown framework '{v}'. Valid: {sorted(valid)}")
        return v.lower()


class DeploymentPatch(BaseModel):
    state: DeploymentState | None = None
    canary_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def at_least_one_field(self) -> DeploymentPatch:
        if self.state is None and self.canary_pct is None:
            raise ValueError("At least one of 'state' or 'canary_pct' must be provided")
        return self


class DeploymentResponse(BaseModel):
    id: str
    model_name: str
    framework: str = "vllm"
    state: DeploymentState = DeploymentState.pending
    tp: int = 1
    pp: int = 1
    dp: int = 1

    benchmark_run_id: str | None = None
    recipe_id: str | None = None
    node_id: str | None = None
    project_id: str | None = None

    launch_config_json: dict | None = None
    canary_pct: float = 0
    sla_ttft_p99_ms: float | None = None
    sla_throughput_floor_tps: float | None = None

    created_at: str | None = None
    deployed_at: str | None = None
    promoted_at: str | None = None
    stopped_at: str | None = None

    @property
    def is_active(self) -> bool:
        return self.state in (DeploymentState.canary, DeploymentState.promoted)

    @property
    def is_terminal(self) -> bool:
        return self.state in (DeploymentState.rollback, DeploymentState.stopped)
