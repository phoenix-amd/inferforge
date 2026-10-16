"""Batch sweep analysis for LLM inference serving configurations.

Sweeps max-num-seqs values with chunked-prefill ON/OFF to estimate
KV cache usage, HBM utilization, throughput, and latency impact.
"""


def generate_batch_sweep(
    config: dict,
    gpu_spec: dict,
    weight_per_gpu: float,
    kv_per_req_per_gpu: float,
    mem_bw_tbps: float,
) -> list[dict]:
    """Analyze batching parameters for a given parallelism config.

    Args:
        config:              Parallelism config dict (tp, pp, dp, kv_budget_per_gpu_gb, etc.).
        gpu_spec:            GPU spec dict with hbm_gb.
        weight_per_gpu:      Weight memory per GPU in GB (after TP+PP sharding).
        kv_per_req_per_gpu:  KV cache per request per GPU in GB (after TP+PP sharding).
        mem_bw_tbps:         Memory bandwidth in TB/s per GPU.

    Returns:
        List of sweep result dicts, each with max_num_seqs, chunked_prefill,
        memory stats, estimated throughput, and recommendation labels.
    """
    hbm_per_gpu = gpu_spec["hbm_gb"]
    kv_budget = config["kv_budget_per_gpu_gb"]
    dp = config.get("dp", 1)

    seq_candidates = [32, 64, 128, 256, 512]
    chunked_options = [True, False]

    sweep = []
    for max_seqs in seq_candidates:
        if max_seqs > config["max_batch_size"]:
            continue

        kv_used = max_seqs * kv_per_req_per_gpu
        kv_util_pct = round(kv_used / kv_budget * 100, 1) if kv_budget > 0 else 999
        hbm_total_used = weight_per_gpu + kv_used
        hbm_util_pct = round(hbm_total_used / hbm_per_gpu * 100, 1)
        kv_headroom = kv_budget - kv_used

        for chunked in chunked_options:
            # Chunked prefill impact:
            #   ON:  ~3% decode throughput overhead, ~40% lower TTFT p99
            #   OFF: baseline decode throughput, TTFT spikes under load
            throughput_factor = 0.97 if chunked else 1.0
            ttft_factor = 0.6 if chunked else 1.0  # noqa: F841

            # Memory-bandwidth-bound throughput estimate
            weight_bytes = weight_per_gpu * (1024 ** 3)
            raw_tps = (mem_bw_tbps * 1e12) / (2 * weight_bytes) if weight_bytes > 0 else 0
            batch_eff = min(max_seqs, 128) / 128
            est_tps = raw_tps * min(batch_eff, 1.0) * 0.7 * throughput_factor
            est_tps *= dp

            sweep.append({
                "max_num_seqs": max_seqs,
                "chunked_prefill": chunked,
                "kv_used_gb": round(kv_used, 1),
                "kv_util_pct": kv_util_pct,
                "kv_headroom_gb": round(kv_headroom, 1),
                "hbm_util_pct": hbm_util_pct,
                "est_throughput_tps": round(est_tps),
                "est_ttft_impact": "lower p99 (varies by workload)" if chunked else "baseline",
                "est_decode_impact": "small overhead (varies by workload)" if chunked else "baseline",
                "recommendation": "",
            })

    _label_recommendations(sweep)
    return sweep


def _label_recommendations(sweep: list[dict]) -> None:
    """Apply Best-for-latency / throughput / balanced labels in place."""
    if not sweep:
        return

    # Best for latency: chunked=True, moderate KV utilization
    latency_candidates = [s for s in sweep if s["chunked_prefill"] and s["kv_util_pct"] < 80]
    if latency_candidates:
        best_lat = latency_candidates[len(latency_candidates) // 2]
        best_lat["recommendation"] = "Best for latency"

    # Best for throughput: chunked=False, highest seqs that fits under 90% KV
    tp_candidates = [s for s in sweep if not s["chunked_prefill"] and s["kv_util_pct"] < 90]
    if tp_candidates:
        best_tp = tp_candidates[-1]
        best_tp["recommendation"] = "Best for throughput"

    # Balanced: chunked=True, highest seqs under 70% KV util
    bal_candidates = [s for s in sweep if s["chunked_prefill"] and s["kv_util_pct"] < 70]
    if bal_candidates:
        best_bal = bal_candidates[-1]
        if not best_bal["recommendation"]:
            best_bal["recommendation"] = "Balanced"
