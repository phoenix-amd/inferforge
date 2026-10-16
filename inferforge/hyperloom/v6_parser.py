"""Parse Hyperloom V6 schema into InferForge-native data structures.

The V6 session_breakdown.json schema has a specific structure with
metadata, task_config, outcome, timeline, rounds, and optimization_stack
blocks. This module maps those structures into dicts suitable for
insertion into InferForge's SQLite tables (hyperloom_sessions,
benchmark_runs, recipes).
"""

import logging
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def parse_v6_metadata(breakdown: dict) -> dict:
    """Extract V6 metadata fields.

    Returns dict with: session_id, claw_session_id, schema_version,
    host, session_dir, started_at, ended_at, elapsed_minutes.
    """
    meta = breakdown.get("metadata", {})
    timing = breakdown.get("timing", meta)

    return {
        "session_id": meta.get("session_id", ""),
        "claw_session_id": meta.get("claw_session_id", ""),
        "schema_version": meta.get("schema_version", "v6"),
        "host": meta.get("host", meta.get("hostname", "")),
        "session_dir": meta.get("session_dir", ""),
        "started_at": timing.get("started_at", ""),
        "ended_at": timing.get("ended_at", ""),
        "elapsed_minutes": _safe_float(timing.get("elapsed_minutes"), 0.0),
    }


def parse_v6_task_config(breakdown: dict) -> dict:
    """Extract model/framework/GPU/parallelism configuration.

    Returns dict with: model_name, model_path, model_hf_id, model_params_b,
    model_architecture, framework_name, framework_version, gpu_type,
    gpu_count, tp, ep, pp, dp, precision.
    """
    task = breakdown.get("task_config", {})
    model = task.get("model", {})
    framework = task.get("framework", {})
    gpu = task.get("gpu", {})
    parallelism = task.get("parallelism", {})

    return {
        "model_name": model.get("name", ""),
        "model_path": model.get("path", ""),
        "model_hf_id": model.get("hf_id", model.get("huggingface_id", "")),
        "model_params_b": _safe_float(model.get("params_b", model.get("parameters_b"))),
        "model_architecture": model.get("architecture", ""),
        "framework_name": framework.get("name", ""),
        "framework_version": framework.get("version", ""),
        "gpu_type": gpu.get("type", gpu.get("model", "")),
        "gpu_count": _safe_int(gpu.get("count", gpu.get("num_gpus")), 1),
        "tp": _safe_int(parallelism.get("tp", parallelism.get("tensor_parallel")), 1),
        "ep": _safe_int(parallelism.get("ep", parallelism.get("expert_parallel")), 0),
        "pp": _safe_int(parallelism.get("pp", parallelism.get("pipeline_parallel")), 1),
        "dp": _safe_int(parallelism.get("dp", parallelism.get("data_parallel")), 1),
        "precision": task.get("precision", model.get("dtype", "bf16")),
    }


def parse_v6_outcome(breakdown: dict) -> dict:
    """Extract optimization outcome.

    Returns dict with: stop_reason, status, baseline metrics, final metrics,
    gain_pct, gain_tps.
    """
    outcome = breakdown.get("outcome", {})
    baseline = outcome.get("baseline", {})
    final = outcome.get("final", {})

    baseline_tps = _safe_float(baseline.get("throughput_tps"))
    final_tps = _safe_float(final.get("throughput_tps"))

    gain_pct = _safe_float(outcome.get("gain_pct"))
    if gain_pct is None and baseline_tps and final_tps and baseline_tps > 0:
        gain_pct = ((final_tps - baseline_tps) / baseline_tps) * 100.0

    return {
        "stop_reason": outcome.get("stop_reason", ""),
        "status": _outcome_to_status(outcome),
        "baseline": _parse_metric_block(baseline),
        "final": _parse_metric_block(final),
        "gain_pct": gain_pct,
        "gain_tps": (final_tps - baseline_tps) if baseline_tps and final_tps else None,
    }


def parse_v6_graded_axes(measurement: dict) -> dict:
    """Extract performance metrics from a V6 graded-axes measurement record.

    Returns a flat dict suitable for benchmark_runs columns:
    throughput_tps, ttft_p50/p90/p99, tpot_p50/p90/p99, itl_p50/p90/p99,
    e2e_p50/p90/p99, hbm_used_gb.
    """
    axes = measurement.get("graded_axes", measurement.get("metrics", measurement))
    if not isinstance(axes, dict):
        return {}

    result: dict = {}

    # Throughput
    throughput = axes.get("throughput", axes.get("throughput_tps"))
    if isinstance(throughput, dict):
        result["throughput_tps"] = _safe_float(throughput.get("value"))
        result["throughput_rps"] = _safe_float(throughput.get("rps"))
    else:
        result["throughput_tps"] = _safe_float(throughput)

    # Latency buckets: ttft, tpot, itl, e2e
    for metric_name in ("ttft", "tpot", "itl", "e2e"):
        block = axes.get(metric_name)
        if isinstance(block, dict):
            for pct in ("p50", "p90", "p95", "p99", "mean", "median"):
                val = _safe_float(block.get(pct))
                if val is not None:
                    result[f"{metric_name}_{pct}"] = val
        elif block is not None:
            # Scalar -- treat as mean
            result[f"{metric_name}_mean"] = _safe_float(block)

    # HBM usage
    hbm = axes.get("hbm_used_gb", axes.get("memory_gb"))
    if isinstance(hbm, dict):
        result["hbm_used_gb"] = _safe_float(hbm.get("value"))
    else:
        result["hbm_used_gb"] = _safe_float(hbm)

    hbm_pct = axes.get("hbm_util_pct", axes.get("memory_pct"))
    if isinstance(hbm_pct, dict):
        result["hbm_util_pct"] = _safe_float(hbm_pct.get("value"))
    else:
        result["hbm_util_pct"] = _safe_float(hbm_pct)

    # Power
    power = axes.get("power_w", axes.get("power"))
    if power is not None:
        result["power_w"] = _safe_float(power if not isinstance(power, dict) else power.get("value"))

    return {k: v for k, v in result.items() if v is not None}


def v6_to_benchmark_run(breakdown: dict, round_data: dict) -> dict:
    """Convert a V6 measurement round to a benchmark_runs table row.

    Merges task_config (model, gpu, parallelism) with the round's
    graded-axes metrics to produce a dict matching the benchmark_runs schema.
    """
    config = parse_v6_task_config(breakdown)
    metrics = parse_v6_graded_axes(round_data)
    meta = parse_v6_metadata(breakdown)

    return {
        "id": str(uuid.uuid4())[:12],
        "hyperloom_session_id": meta["session_id"],
        "model_name": config["model_name"],
        "model_hf_id": config["model_hf_id"],
        "model_params_b": config["model_params_b"],
        "model_architecture": config["model_architecture"],
        "gpu_platform": config["gpu_type"],
        "gpu_count": config["gpu_count"],
        "framework": config["framework_name"],
        "framework_version": config["framework_version"],
        "tp": config["tp"],
        "pp": config["pp"],
        "dp": config["dp"],
        "ep": config["ep"],
        "weight_dtype": config["precision"],
        "evidence_source": "hyperloom",
        "run_mode": "autonomous",
        # Metrics from graded axes
        **metrics,
        # Round metadata
        "config_json": {
            "round_number": round_data.get("round", round_data.get("round_number")),
            "phase": round_data.get("phase", ""),
            "label": round_data.get("label", ""),
            "timestamp": round_data.get("timestamp", ""),
        },
    }


def v6_to_hyperloom_session(breakdown: dict) -> dict:
    """Convert a full breakdown to a hyperloom_sessions table row."""
    meta = parse_v6_metadata(breakdown)
    config = parse_v6_task_config(breakdown)
    outcome = parse_v6_outcome(breakdown)
    import json

    return {
        "id": meta["session_id"] or str(uuid.uuid4())[:12],
        "claw_session_id": meta["claw_session_id"],
        "session_dir": meta["session_dir"],
        "host": meta["host"],
        "model_name": config["model_name"],
        "model_path": config["model_path"],
        "framework_name": config["framework_name"],
        "gpu_type": config["gpu_type"],
        "tp": config["tp"],
        "ep": config["ep"],
        "precision": config["precision"],
        "stop_reason": outcome["stop_reason"],
        "outcome_gain_pct": outcome["gain_pct"],
        "outcome_json": json.dumps(outcome),
        "schema_version": meta["schema_version"],
        "started_at": meta["started_at"],
        "ended_at": meta["ended_at"],
        "elapsed_minutes": meta["elapsed_minutes"],
        "status": outcome["status"],
    }


def v6_to_recipe(breakdown: dict) -> dict | None:
    """Extract a recipe from a successful optimization session.

    Returns None if the session has no optimization stack or gain <= 0.
    """
    outcome = parse_v6_outcome(breakdown)
    if not outcome["gain_pct"] or outcome["gain_pct"] <= 0:
        return None

    config = parse_v6_task_config(breakdown)
    stack = breakdown.get("optimization_stack", breakdown.get("stack", []))
    if not stack:
        return None

    import json

    # Extract server args from the final configuration
    final_config = breakdown.get("final_config", {})
    server_args = final_config.get("server_args", "")

    # Extract kernel patches
    kernel_patches = [
        item for item in stack
        if isinstance(item, dict) and item.get("category", "").lower() == "kernel"
    ]

    return {
        "id": str(uuid.uuid4())[:12],
        "model_family": _infer_model_family(config["model_name"]),
        "model_name": config["model_name"],
        "gpu_type": config["gpu_type"],
        "framework": config["framework_name"],
        "optimizations_json": json.dumps(stack),
        "server_args": server_args,
        "kernel_patches_json": json.dumps(kernel_patches) if kernel_patches else None,
        "baseline_tps": outcome["baseline"].get("throughput_tps"),
        "optimized_tps": outcome["final"].get("throughput_tps"),
        "gain_pct": outcome["gain_pct"],
        "source": "hyperloom",
        "source_session_id": parse_v6_metadata(breakdown)["session_id"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_metric_block(block: dict) -> dict:
    """Parse a baseline or final metric block into a flat dict."""
    if not isinstance(block, dict):
        return {}
    result: dict = {}
    for key, val in block.items():
        if isinstance(val, dict):
            result[key] = _safe_float(val.get("value", val.get("median")))
        else:
            result[key] = _safe_float(val)
    return {k: v for k, v in result.items() if v is not None}


def _outcome_to_status(outcome: dict) -> str:
    """Map V6 outcome to InferForge session status."""
    stop = outcome.get("stop_reason", "").lower()
    if stop in ("completed", "converged", "budget_exhausted"):
        return "completed"
    if stop in ("error", "crash", "oom"):
        return "failed"
    if stop in ("cancelled", "user_abort"):
        return "cancelled"
    if stop:
        return "completed"
    return "unknown"


def _safe_float(val: Any, default: float | None = None) -> float | None:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _infer_model_family(model_name: str) -> str:
    """Infer model family from name for recipe indexing."""
    name = model_name.lower()
    families = [
        "llama", "mistral", "mixtral", "qwen", "deepseek", "falcon",
        "phi", "gemma", "command", "dbrx", "jamba", "arctic",
        "yi", "internlm", "baichuan", "chatglm", "starcoder",
    ]
    for fam in families:
        if fam in name:
            return fam
    return "unknown"
