"""Benchmark run CRUD routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inferforge.db import (
    save_benchmark_run,
    get_benchmark_run,
    list_benchmark_runs,
)

router = APIRouter(prefix="/api", tags=["benchmarks"])


class BenchmarkRunCreate(BaseModel):
    model_name: str
    gpu_platform: str
    framework: str = "vllm"
    gpu_count: int = 1
    tp: int = 1
    pp: int = 1
    dp: int = 1
    weight_dtype: str = "bf16"
    conversation_id: str | None = None
    campaign_id: str | None = None
    model_hf_id: str | None = None
    model_params_b: float | None = None
    model_architecture: str | None = None
    framework_version: str | None = None
    ep: int = 0
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


@router.get("/benchmark-runs")
def api_list_benchmark_runs(
    conversation_id: str | None = None,
    campaign_id: str | None = None,
    model_name: str | None = None,
):
    runs = list_benchmark_runs(
        conversation_id=conversation_id,
        campaign_id=campaign_id,
        model_name=model_name,
    )
    return {"runs": runs, "total": len(runs)}


@router.post("/benchmark-runs", status_code=201)
def api_create_benchmark_run(body: BenchmarkRunCreate):
    data = body.model_dump(exclude_none=True)
    run_id = save_benchmark_run(**data)
    return {"id": run_id, **data}


@router.get("/benchmark-runs/{run_id}")
def api_get_benchmark_run(run_id: str):
    run = get_benchmark_run(run_id)
    if not run:
        raise HTTPException(404, f"Benchmark run {run_id} not found")
    return run
