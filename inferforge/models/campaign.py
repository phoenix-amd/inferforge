"""Pydantic models for benchmark campaigns."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class CampaignStatus(str, Enum):
    draft = "draft"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TopologyConfig(BaseModel):
    tp: int = Field(ge=1, le=64)
    pp: int = Field(default=1, ge=1, le=32)
    dp: int = Field(default=1, ge=1, le=64)
    ep: int = Field(default=0, ge=0, le=64)


class SLATargets(BaseModel):
    ttft_p95_ms: float | None = Field(default=None, ge=0)
    ttft_p99_ms: float | None = Field(default=None, ge=0)
    tpot_p99_ms: float | None = Field(default=None, ge=0)
    throughput_floor_tps: float | None = Field(default=None, ge=0)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2048)
    model_name: str | None = Field(default=None, max_length=256)
    model_hf_id: str | None = Field(default=None, max_length=256)

    frameworks: list[str] | None = Field(
        default=None,
        description="Frameworks to compare (e.g. ['vllm', 'sglang', 'tgi'])",
    )
    topologies: list[TopologyConfig] | None = Field(
        default=None,
        description="Parallelism configurations to compare",
    )
    dtypes: list[str] | None = Field(
        default=None,
        description="Weight dtypes to compare (e.g. ['bf16', 'fp8'])",
    )
    gpu_platforms: list[str] | None = Field(
        default=None,
        description="GPU models to compare (e.g. ['MI300X', 'MI325X'])",
    )

    input_len: int | None = Field(default=None, ge=1, le=1_000_000)
    output_len: int | None = Field(default=None, ge=1, le=1_000_000)
    num_prompts: int | None = Field(default=None, ge=1, le=100_000)
    request_rate: float | None = Field(default=None, ge=0.01)

    sla_ttft_p95_ms: float | None = Field(default=None, ge=0)
    sla_ttft_p99_ms: float | None = Field(default=None, ge=0)
    sla_tpot_p99_ms: float | None = Field(default=None, ge=0)
    sla_throughput_floor_tps: float | None = Field(default=None, ge=0)

    max_gpu_hours: float | None = Field(default=None, ge=0)
    max_wall_hours: float | None = Field(default=None, ge=0)

    project_id: str | None = Field(default=None, max_length=36)
    user_id: str | None = Field(default=None, max_length=36)

    @field_validator("frameworks")
    @classmethod
    def validate_frameworks(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        valid = {"vllm", "sglang", "tgi"}
        for fw in v:
            if fw.lower() not in valid:
                raise ValueError(f"Unknown framework '{fw}'. Valid: {sorted(valid)}")
        return [fw.lower() for fw in v]

    @field_validator("dtypes")
    @classmethod
    def validate_dtypes(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        valid = {"bf16", "fp16", "fp8", "int8", "int4", "fp32", "bfloat16", "float16"}
        for d in v:
            if d.lower() not in valid:
                raise ValueError(f"Unknown dtype '{d}'. Valid: {sorted(valid)}")
        return [d.lower() for d in v]


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2048)
    status: CampaignStatus | None = None
    winner_run_id: str | None = None


class CampaignSummary(BaseModel):
    total_runs: int = 0
    completed_runs: int = 0
    sla_compliant_runs: int = 0
    best_throughput_tps: float | None = None
    best_ttft_p99_ms: float | None = None
    winner_framework: str | None = None
    winner_topology: str | None = None


class CampaignResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: CampaignStatus = CampaignStatus.draft

    model_name: str | None = None
    model_hf_id: str | None = None

    frameworks: list[str] | None = None
    topologies: list[dict] | None = None
    dtypes: list[str] | None = None
    gpu_platforms: list[str] | None = None

    input_len: int | None = None
    output_len: int | None = None
    num_prompts: int | None = None
    request_rate: float | None = None

    sla_ttft_p95_ms: float | None = None
    sla_ttft_p99_ms: float | None = None
    sla_tpot_p99_ms: float | None = None
    sla_throughput_floor_tps: float | None = None

    max_gpu_hours: float | None = None
    max_wall_hours: float | None = None

    winner_run_id: str | None = None
    summary_json: CampaignSummary | dict | None = None

    project_id: str | None = None
    user_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    runs: list[dict] = Field(default_factory=list)


class CampaignComparison(BaseModel):
    campaign_id: str
    runs: list[dict] = Field(default_factory=list)
    count: int = 0
    winner_run_id: str | None = None
    sla_targets: SLATargets | None = None
