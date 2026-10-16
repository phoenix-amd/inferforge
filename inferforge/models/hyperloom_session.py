"""Pydantic models for Hyperloom optimization sessions."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SessionStatus(str, Enum):
    pending = "pending"
    launching = "launching"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class HyperloomPhase(str, Enum):
    prelude = "PRELUDE"
    enablement = "ENABLEMENT"
    framework_agent = "FRAMEWORK_AGENT"
    kernel_agent = "KERNEL_AGENT"
    sweep = "SWEEP"
    close = "CLOSE"


class HyperloomSessionCreate(BaseModel):
    """Request body for launching a new Hyperloom optimization session."""

    host: str = Field(min_length=1, max_length=256)
    model_name: str = Field(min_length=1, max_length=256)
    model_path: str = Field(min_length=1, max_length=512)
    framework_name: str = Field(default="vllm", max_length=32)
    gpu_type: str | None = Field(default=None, max_length=64)
    tp: int = Field(default=1, ge=1, le=64)
    ep: int = Field(default=0, ge=0, le=64)
    precision: str = Field(default="bf16", max_length=16)

    campaign_id: str | None = Field(default=None, max_length=36)
    conversation_id: str | None = Field(default=None, max_length=36)

    no_kernel: bool = Field(
        default=False,
        description="Skip kernel optimization phase",
    )
    enablement_only: bool = Field(
        default=False,
        description="Run only the enablement phase",
    )
    max_latency_ms: float | None = Field(
        default=None,
        ge=0,
        description="SLA: abort configs exceeding this TTFT (ms)",
    )
    max_power_w: float | None = Field(
        default=None,
        ge=0,
        description="Power cap: abort configs exceeding this wattage",
    )

    @field_validator("framework_name")
    @classmethod
    def validate_framework(cls, v: str) -> str:
        valid = {"vllm", "sglang", "tgi"}
        if v.lower() not in valid:
            raise ValueError(f"Unknown framework '{v}'. Valid: {sorted(valid)}")
        return v.lower()


class HyperloomSessionImport(BaseModel):
    """Request body for importing a completed Hyperloom breakdown."""

    breakdown_path: str = Field(min_length=1, max_length=1024)


class HyperloomSessionResponse(BaseModel):
    id: str
    campaign_id: str | None = None
    conversation_id: str | None = None
    claw_session_id: str | None = None
    session_dir: str | None = None
    host: str | None = None

    model_name: str | None = None
    model_path: str | None = None
    framework_name: str | None = None
    gpu_type: str | None = None
    tp: int | None = None
    ep: int | None = None
    precision: str | None = None

    stop_reason: str | None = None
    outcome_gain_pct: float | None = None
    outcome_json: dict | None = None
    schema_version: str | None = None
    timeline_json: list[dict] | None = None

    started_at: str | None = None
    ended_at: str | None = None
    elapsed_minutes: float | None = None
    imported_at: str | None = None
    breakdown_path: str | None = None
    status: SessionStatus = SessionStatus.pending


class V6TimelineEvent(BaseModel):
    """A single event from the Hyperloom V6 timeline."""

    phase: HyperloomPhase
    round_number: int = Field(ge=0)
    label: str = Field(default="", max_length=256)
    timestamp: str | None = None
    elapsed_s: float | None = Field(default=None, ge=0)

    throughput_tps: float | None = Field(default=None, ge=0)
    ttft_p50: float | None = Field(default=None, ge=0)
    ttft_p99: float | None = Field(default=None, ge=0)
    tpot_p50: float | None = Field(default=None, ge=0)
    itl_p50: float | None = Field(default=None, ge=0)
    hbm_used_gb: float | None = Field(default=None, ge=0)
    power_w: float | None = Field(default=None, ge=0)

    delta_pct: float | None = Field(
        default=None,
        description="Throughput change vs baseline (%)",
    )
    is_best: bool = False
    is_baseline: bool = False
    config_changes: list[str] = Field(default_factory=list)


class OptimizationEntry(BaseModel):
    """A single optimization applied during a Hyperloom session."""

    category: str = Field(max_length=64)
    name: str = Field(max_length=256)
    description: str = Field(default="", max_length=1024)
    phase: HyperloomPhase | None = None
    round_number: int | None = Field(default=None, ge=0)

    applied: bool = True
    reverted: bool = False
    delta_tps: float | None = None
    delta_pct: float | None = None

    before_value: str | None = None
    after_value: str | None = None

    @property
    def effective(self) -> bool:
        return self.applied and not self.reverted


class SessionOutcome(BaseModel):
    """Summary outcome of a Hyperloom optimization session."""

    stop_reason: str = ""
    baseline_tps: float | None = Field(default=None, ge=0)
    final_tps: float | None = Field(default=None, ge=0)
    gain_pct: float | None = None
    gain_tps: float | None = None
    total_rounds: int = Field(default=0, ge=0)
    best_round: int | None = Field(default=None, ge=0)
    optimizations: list[OptimizationEntry] = Field(default_factory=list)
