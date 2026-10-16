"""Pydantic models for benchmark runs and structured metrics."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class WeightDtype(str, Enum):
    bf16 = "bf16"
    fp16 = "fp16"
    fp8 = "fp8"
    int8 = "int8"
    int4 = "int4"
    fp32 = "fp32"
    bfloat16 = "bfloat16"
    float16 = "float16"


class Framework(str, Enum):
    vllm = "vllm"
    sglang = "sglang"
    tgi = "tgi"


class EvidenceSource(str, Enum):
    benchmark_throughput = "benchmark_throughput"
    benchmark_serving = "benchmark_serving"
    hyperloom = "hyperloom"
    manual = "manual"
    simulation = "simulation"


class BenchmarkRunCreate(BaseModel):
    model_name: str = Field(min_length=1, max_length=256)
    gpu_platform: str = Field(min_length=1, max_length=64)
    framework: Framework = Framework.vllm
    gpu_count: int = Field(default=1, ge=1, le=512)
    tp: int = Field(default=1, ge=1, le=64)
    pp: int = Field(default=1, ge=1, le=32)
    dp: int = Field(default=1, ge=1, le=64)
    weight_dtype: str = Field(default="bf16", max_length=16)

    conversation_id: str | None = Field(default=None, max_length=36)
    campaign_id: str | None = Field(default=None, max_length=36)
    hyperloom_session_id: str | None = Field(default=None, max_length=36)

    model_hf_id: str | None = Field(default=None, max_length=256)
    model_params_b: float | None = Field(default=None, ge=0)
    model_architecture: str | None = Field(default=None, max_length=64)
    framework_version: str | None = Field(default=None, max_length=32)
    ep: int = Field(default=0, ge=0, le=64)
    kv_dtype: str | None = Field(default=None, max_length=16)
    seq_len: int | None = Field(default=None, ge=1)
    input_len: int | None = Field(default=None, ge=1)
    output_len: int | None = Field(default=None, ge=1)
    batch_size: int | None = Field(default=None, ge=1)
    max_num_seqs: int | None = Field(default=None, ge=1)
    chunked_prefill: int = Field(default=0, ge=0, le=1)

    # Latency metrics (milliseconds)
    ttft_p50: float | None = Field(default=None, ge=0)
    ttft_p90: float | None = Field(default=None, ge=0)
    ttft_p99: float | None = Field(default=None, ge=0)
    ttft_mean: float | None = Field(default=None, ge=0)
    tpot_p50: float | None = Field(default=None, ge=0)
    tpot_p90: float | None = Field(default=None, ge=0)
    tpot_p99: float | None = Field(default=None, ge=0)
    itl_p50: float | None = Field(default=None, ge=0)
    itl_p90: float | None = Field(default=None, ge=0)
    itl_p99: float | None = Field(default=None, ge=0)
    e2e_p50: float | None = Field(default=None, ge=0)
    e2e_p90: float | None = Field(default=None, ge=0)
    e2e_p99: float | None = Field(default=None, ge=0)

    # Throughput
    throughput_tps: float | None = Field(default=None, ge=0)
    throughput_rps: float | None = Field(default=None, ge=0)

    # Memory
    hbm_used_gb: float | None = Field(default=None, ge=0)
    hbm_util_pct: float | None = Field(default=None, ge=0, le=100)

    # Provenance
    run_mode: str = Field(default="autonomous", max_length=32)
    evidence_source: str | None = Field(default=None, max_length=64)
    raw_output_path: str | None = Field(default=None, max_length=512)
    config_json: dict | None = None

    @field_validator("tp", "pp", "dp")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Parallelism values must be >= 1")
        return v


class BenchmarkRunResponse(BaseModel):
    id: str
    model_name: str
    gpu_platform: str
    framework: str
    gpu_count: int
    tp: int
    pp: int
    dp: int
    ep: int = 0
    weight_dtype: str

    conversation_id: str | None = None
    campaign_id: str | None = None
    hyperloom_session_id: str | None = None

    model_hf_id: str | None = None
    model_params_b: float | None = None
    model_architecture: str | None = None
    framework_version: str | None = None
    kv_dtype: str | None = None
    seq_len: int | None = None
    input_len: int | None = None
    output_len: int | None = None
    batch_size: int | None = None
    max_num_seqs: int | None = None
    chunked_prefill: int = 0

    ttft_p50: float | None = None
    ttft_p90: float | None = None
    ttft_p99: float | None = None
    ttft_mean: float | None = None
    tpot_p50: float | None = None
    tpot_p90: float | None = None
    tpot_p99: float | None = None
    itl_p50: float | None = None
    itl_p90: float | None = None
    itl_p99: float | None = None
    e2e_p50: float | None = None
    e2e_p90: float | None = None
    e2e_p99: float | None = None

    throughput_tps: float | None = None
    throughput_rps: float | None = None
    hbm_used_gb: float | None = None
    hbm_util_pct: float | None = None

    run_mode: str = "autonomous"
    evidence_source: str | None = None
    raw_output_path: str | None = None
    config_json: dict | None = None
    created_at: str | None = None


class StructuredMetrics(BaseModel):
    """Structured metrics reported by the agent after parsing benchmark output.

    The agent MUST call the report_metrics tool with this schema after every
    benchmark parse, rather than relying on dashboard regex extraction.
    """

    model_name: str = Field(min_length=1)
    gpu_platform: str = Field(min_length=1)
    gpu_count: int = Field(ge=1)
    framework: Framework
    tp: int = Field(ge=1)
    pp: int = Field(default=1, ge=1)
    dp: int = Field(default=1, ge=1)
    ep: int = Field(default=0, ge=0)
    weight_dtype: str = Field(default="bf16")

    throughput_tps: float | None = Field(default=None, ge=0)
    ttft_p50: float | None = Field(default=None, ge=0)
    ttft_p99: float | None = Field(default=None, ge=0)
    ttft_mean: float | None = Field(default=None, ge=0)
    tpot_p50: float | None = Field(default=None, ge=0)
    tpot_p99: float | None = Field(default=None, ge=0)
    itl_p50: float | None = Field(default=None, ge=0)
    e2e_p50: float | None = Field(default=None, ge=0)
    hbm_used_gb: float | None = Field(default=None, ge=0)

    evidence_source: EvidenceSource = EvidenceSource.benchmark_serving
    conversation_id: str | None = None
    campaign_id: str | None = None
