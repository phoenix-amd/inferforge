"""Inference state routes -- structured state without regex parsing."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["inference-state"])

_inference_state: dict = {
    "gpu_model": None,
    "gpu_count": None,
    "hbm_per_gpu_gb": None,
    "model_name": None,
    "model_params_b": None,
    "framework": None,
    "tp": None,
    "pp": None,
    "dp": None,
    "weight_dtype": None,
    "throughput_tps": None,
    "ttft_p50": None,
    "ttft_p99": None,
    "tpot_p50": None,
    "hbm_used_gb": None,
    "run_type": None,
    "status": "idle",
    "last_benchmark_raw": None,
}


class InferenceStateUpdate(BaseModel):
    gpu_model: str | None = None
    gpu_count: int | None = None
    hbm_per_gpu_gb: float | None = None
    model_name: str | None = None
    model_params_b: float | None = None
    framework: str | None = None
    tp: int | None = None
    pp: int | None = None
    dp: int | None = None
    weight_dtype: str | None = None
    throughput_tps: float | None = None
    ttft_p50: float | None = None
    ttft_p99: float | None = None
    tpot_p50: float | None = None
    hbm_used_gb: float | None = None
    run_type: str | None = None
    status: str | None = None
    last_benchmark_raw: str | None = None


def get_inference_state() -> dict:
    return _inference_state


def update_inference_state(updates: dict) -> dict:
    for key, value in updates.items():
        if key in _inference_state:
            _inference_state[key] = value
    return _inference_state


@router.get("/inference-state")
def api_get_inference_state():
    return _inference_state


@router.post("/inference-state")
def api_update_inference_state(body: InferenceStateUpdate):
    updates = body.model_dump(exclude_none=True)
    return update_inference_state(updates)


# ---------------------------------------------------------------------------
# Cluster config — persisted in memory, readable by all views
# ---------------------------------------------------------------------------

_cluster_config: dict = {}


@router.get("/config/cluster")
def api_get_cluster_config():
    return _cluster_config


class ClusterConfig(BaseModel):
    head_ip: str | None = None
    workers: str | None = None
    ssh_user: str | None = None
    ssh_key: str | None = None
    model: str | None = None
    model_path: str | None = None
    framework: str | None = None
    weight_dtype: str | None = None
    kv_dtype: str | None = None
    seq_len: int | None = None
    sla_ttft: int | None = None
    sla_tpot: int | None = None
    sla_throughput: int | None = None
    sla_e2e: int | None = None


@router.post("/config/cluster")
def api_save_cluster_config(body: ClusterConfig):
    _cluster_config.update(body.model_dump(exclude_none=True))
    return {"ok": True}
