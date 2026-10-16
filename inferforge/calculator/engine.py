#!/usr/bin/env python3
"""InferForge Memory & Parallelism Calculator.

Deterministic calculator for LLM inference memory requirements and valid
parallelism configurations on AMD Instinct GPUs. Reads gpu_specs.json and
model_registry.json from the data/ directory.

Usage:
    # Built-in model
    python3 -m inferforge.calculator.engine --model llama-3.3-70b --gpu MI300X --dtype bf16 --gpu-count 8

    # Custom model
    python3 -m inferforge.calculator.engine --params 70 --layers 80 --heads 64 --kv-heads 8 \\
        --hidden 8192 --gpu MI300X --gpu-count 8

    # With custom sequence length
    python3 -m inferforge.calculator.engine --model llama-3.3-70b --gpu MI300X --seq-len 16384

    # JSON output only (for agent parsing)
    python3 -m inferforge.calculator.engine --model llama-3.3-70b --gpu MI300X --json

    # Separate weight and KV dtypes
    python3 -m inferforge.calculator.engine --model llama-3.3-70b --gpu MI300X --dtype bf16 --kv-dtype fp8
"""

import argparse
import json
import math  # noqa: F401
import os
import sys

# Allow running as: python3 inferforge/calculator/engine.py (not just python3 -m)
_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from inferforge.calculator.kv_cache import (
    calc_kv_cache_per_token_bytes,
    calc_kv_cache_per_request_gb,
)
from inferforge.calculator.batch_sweep import generate_batch_sweep

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
GPU_SPECS_PATH = os.path.join(DATA_DIR, "gpu_specs.json")
MODEL_REGISTRY_PATH = os.path.join(DATA_DIR, "model_registry.json")

BYTES_PER_PARAM = {"bf16": 2, "fp16": 2, "fp8": 1, "int8": 1, "fp4": 0.5, "int4": 0.5}
OVERHEAD_FRACTION = 0.10  # 10% reserved for runtime, activations, fragmentation


def load_json(path):
    with open(path) as f:
        return json.load(f)


def _resolve_model_key(model_str: str, registry: dict) -> str | None:
    """Return registry key matching model_str exactly or via HF ID / slug fuzzy match."""
    if model_str in registry:
        return model_str
    # Try matching by hf_model_id stored in registry entries
    lower = model_str.lower()
    for key, entry in registry.items():
        hf_id = (entry.get("hf_model_id") or "").lower()
        if hf_id and (lower == hf_id or lower.endswith("/" + hf_id) or hf_id.endswith("/" + lower)):
            return key
    # Slug fallback: strip org prefix, lowercase, replace _ with -
    slug = lower.split("/")[-1].replace("_", "-")
    if slug in registry:
        return slug
    # Partial match (e.g. "llama-3.1-8b" in "llama-3.1-8b-instruct")
    for key in registry:
        if slug.startswith(key) or key.startswith(slug):
            return key
    return None


def get_model_params(args, registry):
    """Resolve model parameters from registry or CLI args."""
    resolved_key = _resolve_model_key(args.model, registry) if args.model else None
    if resolved_key and resolved_key in registry:
        m = registry[resolved_key]
        return {
            "name": m.get("display_name", resolved_key),
            "params_b": m["params_b"],
            "layers": m["layers"],
            "heads": m["heads"],
            "kv_heads": m["kv_heads"],
            "hidden": m["hidden_dim"],
            "head_dim": m.get("head_dim", m["hidden_dim"] // m["heads"]),
            "vocab_size": m.get("vocab_size", 32000),
            "max_seq_len": m.get("max_seq_len", 4096),
            "architecture": m.get("architecture", "dense"),
            "attention_type": m.get("attention_type", "gqa"),
            "mla_config": m.get("mla_config"),
            "num_experts": m.get("num_experts"),
            "top_k_experts": m.get("top_k_experts"),
            "active_params_b": m.get("active_params_b"),
            "hf_model_id": m.get("hf_model_id"),
            "warning": m.get("_note"),
        }
    elif args.params:
        return {
            "name": f"Custom {args.params}B",
            "params_b": args.params,
            "layers": args.layers or 80,
            "heads": args.heads or 64,
            "kv_heads": args.kv_heads or 8,
            "hidden": args.hidden or 8192,
            "head_dim": (args.hidden or 8192) // (args.heads or 64),
            "vocab_size": args.vocab_size or 32000,
            "max_seq_len": args.seq_len or 4096,
            "architecture": "dense",
            "attention_type": "gqa",
            "mla_config": None,
            "num_experts": None,
            "top_k_experts": None,
            "active_params_b": None,
            "hf_model_id": None,
        }
    else:
        if args.model:
            keys = ", ".join(sorted(registry.keys()))
            print(f"ERROR: Model '{args.model}' not found in registry.\nValid names: {keys}", file=sys.stderr)
        else:
            print("ERROR: Specify --model <name> or --params <billions>", file=sys.stderr)
        sys.exit(1)


def calc_weight_memory_gb(params_b, dtype):
    """Total model weight memory in GB."""
    bpp = BYTES_PER_PARAM.get(dtype, 2)
    return params_b * 1e9 * bpp / (1024 ** 3)


def valid_tp_values(kv_heads, max_gpus):
    """Valid TP values: powers of 2, divide kv_heads evenly, <= max_gpus."""
    valid = []
    tp = 1
    while tp <= max_gpus:
        if kv_heads % tp == 0:
            valid.append(tp)
        tp *= 2
    return valid


def generate_configs(model, gpu_spec, weight_dtype, kv_dtype, seq_len, gpu_count):
    """Generate all valid parallelism configurations with memory analysis.

    Args:
        model:        Model parameter dict.
        gpu_spec:     GPU spec dict.
        weight_dtype: Data type for model weights (bf16, fp16, fp8, etc.).
        kv_dtype:     Data type for KV cache (can differ from weight_dtype).
        seq_len:      Sequence length for KV cache sizing.
        gpu_count:    Total number of GPUs available.

    Returns:
        Tuple of (configs_list, weight_gb, kv_per_token_bytes, kv_per_request_gb).
    """
    weight_gb = calc_weight_memory_gb(model["params_b"], weight_dtype)

    attention_type = model.get("attention_type", "gqa")
    mla_config = model.get("mla_config")

    kv_per_token = calc_kv_cache_per_token_bytes(
        num_layers=model["layers"],
        num_kv_heads=model["kv_heads"],
        head_dim=model["head_dim"],
        kv_dtype=kv_dtype,
        attention_type=attention_type,
        mla_config=mla_config,
    )
    kv_per_request_gb = calc_kv_cache_per_request_gb(kv_per_token, seq_len)

    hbm_per_gpu = gpu_spec["hbm_gb"]
    usable_hbm = hbm_per_gpu * (1 - OVERHEAD_FRACTION)
    mem_bw_bytes = gpu_spec["memory_bw_tbps"] * 1e12

    configs = []
    tp_candidates = valid_tp_values(model["kv_heads"], gpu_count)

    for tp in tp_candidates:
        for pp in [1, 2, 4, 8]:
            if tp * pp > gpu_count:
                continue
            if gpu_count % (tp * pp) != 0:
                continue

            dp = gpu_count // (tp * pp)
            if dp < 1:
                continue

            # Weights split across both TP and PP stages
            weight_per_gpu_pp = weight_gb / (tp * pp)
            if weight_per_gpu_pp > usable_hbm:
                continue

            kv_budget_per_gpu = usable_hbm - weight_per_gpu_pp
            if kv_budget_per_gpu <= 0:
                continue

            # KV per request per GPU: TP shards KV heads, PP shards layers
            kv_per_req_per_gpu = kv_per_request_gb / (tp * pp)
            max_batch = int(kv_budget_per_gpu / kv_per_req_per_gpu) if kv_per_req_per_gpu > 0 else 999

            if max_batch < 1:
                continue

            overhead_gb = hbm_per_gpu * OVERHEAD_FRACTION
            kv_budget_formula = (
                f"{hbm_per_gpu} GB - {weight_per_gpu_pp:.1f} GB weights "
                f"- {overhead_gb:.1f} GB overhead (10%) = {kv_budget_per_gpu:.1f} GB"
            )
            max_batch_formula = (
                f"floor({kv_budget_per_gpu:.1f} GB / {kv_per_req_per_gpu:.2f} GB/req) = {max_batch}"
            )

            # Rough throughput estimate (memory-bound decode)
            weight_bytes = weight_per_gpu_pp * (1024 ** 3)
            if weight_bytes > 0:
                raw_tps = mem_bw_bytes / (2 * weight_bytes)
                batch_eff = min(max_batch, 128) / 128
                est_tps = raw_tps * dp * min(batch_eff, 1.0) * 0.7
            else:
                est_tps = 0

            # EP for MoE models
            ep = 1
            if model["architecture"] == "moe" and model["num_experts"]:
                for ep_cand in [1, 2, 4, 8, 16, 32]:
                    if ep_cand <= tp and model["num_experts"] % ep_cand == 0:
                        ep = ep_cand

            configs.append({
                "tp": tp,
                "pp": pp,
                "dp": dp,
                "ep": ep if model["architecture"] == "moe" else None,
                "weight_per_gpu_gb": round(weight_per_gpu_pp, 1),
                "kv_budget_per_gpu_gb": round(kv_budget_per_gpu, 1),
                "kv_budget_formula": kv_budget_formula,
                "kv_per_request_gb": round(kv_per_req_per_gpu, 2),
                "max_batch_size": max_batch,
                "max_batch_formula": max_batch_formula,
                "est_output_tps": round(est_tps),
                "total_gpus_used": tp * pp * dp,
            })

    configs.sort(key=lambda c: c["est_output_tps"], reverse=True)
    return configs, weight_gb, kv_per_token, kv_per_request_gb


def recommend(configs, model):
    """Pick the best config based on throughput + capacity balance."""
    if not configs:
        return None, "No valid configuration found -- model too large for available GPUs."

    viable = [c for c in configs if c["max_batch_size"] >= 4]
    if not viable:
        viable = configs

    best = viable[0]
    for c in viable:
        if c["dp"] > 1 and c["est_output_tps"] >= best["est_output_tps"] * 0.8:
            if c["tp"] <= best["tp"]:
                best = c
                break

    reason_parts = []
    if best["dp"] > 1:
        reason_parts.append(f"TP{best['tp']}/DP{best['dp']} provides {best['dp']} independent replicas")
    else:
        reason_parts.append(f"TP{best['tp']} is the minimum sharding needed")
    if best["pp"] > 1:
        reason_parts.append(f"PP{best['pp']} splits layers across nodes")
    reason_parts.append(f"~{best['est_output_tps']} tokens/s estimated")
    reason_parts.append(f"max {best['max_batch_size']} concurrent requests")

    return best, "; ".join(reason_parts)


def print_human_readable(model, gpu_spec, gpu_name, weight_dtype, kv_dtype, seq_len,
                         gpu_count, weight_gb, kv_per_token, kv_per_request_gb,
                         configs, best, reason):
    """Print formatted summary to stderr."""
    out = sys.stderr
    print("\n" + "=" * 72, file=out)
    print("  InferForge -- Memory & Parallelism Analysis", file=out)
    print("=" * 72, file=out)

    print(f"\n  Model:        {model['name']}", file=out)
    print(f"  Parameters:   {model['params_b']}B ({model['architecture'].upper()})", file=out)
    if model.get("active_params_b"):
        print(f"  Active Params: {model['active_params_b']}B (MoE top-{model.get('top_k_experts', '?')})", file=out)
    print(f"  Layers:       {model['layers']}", file=out)
    attn_type = model.get("attention_type", "gqa").upper()
    print(f"  Heads:        {model['heads']} attn, {model['kv_heads']} KV ({attn_type})", file=out)
    print(f"  Hidden:       {model['hidden']}, head_dim: {model['head_dim']}", file=out)
    dtype_str = weight_dtype if weight_dtype == kv_dtype else f"{weight_dtype} (weights), {kv_dtype} (KV)"
    print(f"  Dtype:        {dtype_str}", file=out)
    print(f"  Seq Length:   {seq_len:,}", file=out)

    print(f"\n  GPU Platform: {gpu_spec.get('display_name', gpu_name)}", file=out)
    print(f"  GPU Count:    {gpu_count}", file=out)
    print(f"  HBM/GPU:      {gpu_spec['hbm_gb']} GB {gpu_spec.get('hbm_type', '')}", file=out)
    print(f"  Total HBM:    {gpu_spec['hbm_gb'] * gpu_count} GB", file=out)
    print(f"  Mem BW:       {gpu_spec['memory_bw_tbps']} TB/s per GPU", file=out)

    print(f"\n  --- Memory Breakdown ---", file=out)
    print(f"  Weight Memory:        {weight_gb:.1f} GB ({weight_dtype})", file=out)
    print(f"  KV Cache/Token:       {kv_per_token:,} bytes (all layers)", file=out)
    print(f"  KV Cache/Request:     {kv_per_request_gb:.2f} GB (@ {seq_len:,} tokens)", file=out)
    overhead_gb = gpu_spec["hbm_gb"] * OVERHEAD_FRACTION
    print(f"  Activation Overhead:  ~{overhead_gb:.1f} GB (10% of {gpu_spec['hbm_gb']} GB HBM)", file=out)
    if configs:
        ref = max(configs, key=lambda c: c["weight_per_gpu_gb"])
        print(f"  KV Budget/GPU:        {gpu_spec['hbm_gb']} GB - {ref['weight_per_gpu_gb']:.1f} GB weights"
              f" - {overhead_gb:.1f} GB overhead = {ref['kv_budget_per_gpu_gb']:.1f} GB"
              f"  [TP={ref['tp']}]", file=out)
        print(f"  Max Batch Size:       floor({ref['kv_budget_per_gpu_gb']:.1f} GB / "
              f"{ref['kv_per_request_gb']:.2f} GB/req) = {ref['max_batch_size']}"
              f"  [TP={ref['tp']}]", file=out)

    if not configs:
        print(f"\n  ERROR: Model does not fit on {gpu_count}x {gpu_name}!", file=out)
        print(f"  Weight memory ({weight_gb:.0f} GB) exceeds total usable HBM.", file=out)
        return

    print(f"\n  --- Valid Configurations ({len(configs)} found) ---", file=out)
    header = f"  {'Config':<8} {'TP':>3} {'PP':>3} {'DP':>3}"
    if model["architecture"] == "moe":
        header += f" {'EP':>3}"
    header += f" {'Wt/GPU':>8} {'KV Bud':>8} {'MaxBat':>7} {'Est TPS':>9}"
    print(header, file=out)
    print("  " + "-" * len(header.strip()), file=out)

    for i, c in enumerate(configs[:10]):
        marker = " *" if c == best else "  "
        line = f"{marker}{chr(65 + i):<6} {c['tp']:>3} {c['pp']:>3} {c['dp']:>3}"
        if model["architecture"] == "moe":
            line += f" {c['ep'] or '-':>3}"
        line += f" {c['weight_per_gpu_gb']:>7.1f}G {c['kv_budget_per_gpu_gb']:>7.1f}G {c['max_batch_size']:>7} {c['est_output_tps']:>8,}"
        print(line, file=out)

    if best:
        print(f"\n  RECOMMENDED: Config {chr(65 + configs.index(best))}", file=out)
        tp_str = f"TP={best['tp']}"
        pp_str = f" PP={best['pp']}" if best['pp'] > 1 else ""
        dp_str = f" DP={best['dp']}" if best['dp'] > 1 else ""
        ep_str = f" EP={best['ep']}" if best.get('ep') and best['ep'] > 1 else ""
        print(f"  Layout: {tp_str}{pp_str}{dp_str}{ep_str}", file=out)
        print(f"  Reason: {reason}", file=out)

        kv_per_req_per_gpu = kv_per_request_gb / (best["tp"] * best.get("pp", 1))
        batch_sweep = generate_batch_sweep(
            best, gpu_spec, best["weight_per_gpu_gb"],
            kv_per_req_per_gpu, gpu_spec["memory_bw_tbps"],
        )
        if batch_sweep:
            print(f"\n  --- Batching Optimization (on recommended config) ---", file=out)
            print(f"  {'MaxSeqs':>8} {'Chunked':>8} {'KV Used':>8} {'KV%':>5} {'HBM%':>5} {'Est TPS':>8} {'TTFT Impact':>16} {'Note':>20}", file=out)
            print("  " + "-" * 90, file=out)
            for s in batch_sweep:
                chunked_str = "ON" if s["chunked_prefill"] else "OFF"
                rec = f" <- {s['recommendation']}" if s["recommendation"] else ""
                print(f"  {s['max_num_seqs']:>8} {chunked_str:>8} {s['kv_used_gb']:>7.1f}G {s['kv_util_pct']:>5.1f} {s['hbm_util_pct']:>5.1f} {s['est_throughput_tps']:>8} {s['est_ttft_impact']:>16}{rec}", file=out)

    print("=" * 72 + "\n", file=out)


def main():
    parser = argparse.ArgumentParser(description="InferForge Memory & Parallelism Calculator")
    parser.add_argument("--model", type=str, help="Model key from registry (e.g., llama-3.3-70b)")
    parser.add_argument("--params", type=float, help="Parameter count in billions (custom model)")
    parser.add_argument("--layers", type=int, help="Number of transformer layers")
    parser.add_argument("--heads", type=int, help="Number of attention heads")
    parser.add_argument("--kv-heads", type=int, help="Number of KV heads (GQA)")
    parser.add_argument("--hidden", type=int, help="Hidden dimension size")
    parser.add_argument("--vocab-size", type=int, default=32000)
    parser.add_argument("--gpu", type=str, default="MI300X",
                        help="GPU platform (MI250X, MI300X, MI308X, MI325X, MI350X, MI355X, MI455X, Helios)")
    parser.add_argument("--gpu-count", type=int, default=8, help="Total GPU count")
    parser.add_argument("--dtype", type=str, default="bf16",
                        help="Weight data type (bf16, fp16, fp8, int8, fp4, int4, bfloat16, float16)")
    parser.add_argument("--kv-dtype", type=str, default=None,
                        help="KV cache data type (defaults to weight dtype)")
    parser.add_argument("--seq-len", type=int, help="Sequence length (override model default)")
    parser.add_argument("--json", action="store_true", help="Output JSON only (for agent parsing)")
    parser.add_argument("--list-models", action="store_true", help="List available models")
    parser.add_argument("--list-gpus", action="store_true", help="List available GPU platforms")
    args = parser.parse_args()

    # Normalize verbose dtype names (bfloat16→bf16, float16→fp16, float8→fp8)
    _dtype_aliases = {"bfloat16": "bf16", "float16": "fp16", "float8": "fp8",
                      "float32": "fp16", "int4": "int4", "int8": "int8", "fp4": "fp4"}
    if args.dtype in _dtype_aliases:
        args.dtype = _dtype_aliases[args.dtype]
    if args.kv_dtype and args.kv_dtype in _dtype_aliases:
        args.kv_dtype = _dtype_aliases[args.kv_dtype]

    gpu_specs = load_json(GPU_SPECS_PATH)
    registry = load_json(MODEL_REGISTRY_PATH)

    if args.list_models:
        print(json.dumps({k: {"name": v.get("display_name", k), "params": v["params_b"],
                               "arch": v.get("architecture", "dense")}
                          for k, v in registry.items()}, indent=2))
        return

    if args.list_gpus:
        print(json.dumps({k: {"name": v.get("display_name", k), "hbm_gb": v["hbm_gb"],
                               "mem_bw_tbps": v.get("memory_bw_tbps"),
                               "max_tp": v.get("max_tp_per_node", v.get("gpus_per_node"))}
                          for k, v in gpu_specs.items()}, indent=2))
        return

    model = get_model_params(args, registry)
    seq_len = args.seq_len or model["max_seq_len"]

    # Resolve weight dtype
    weight_dtype = args.dtype

    # Resolve KV dtype: explicit > fp8-auto > same-as-weights
    if args.kv_dtype:
        kv_dtype = args.kv_dtype
    elif weight_dtype == "fp8":
        kv_dtype = "fp8"
    else:
        kv_dtype = weight_dtype

    # Handle short-name aliases
    gpu_name = args.gpu.upper()
    gpu_aliases = {"MI300": "MI300X", "MI350": "MI350X", "MI450": "MI455X", "HELIOS": "Helios"}
    gpu_name = gpu_aliases.get(gpu_name, gpu_name)
    if gpu_name not in gpu_specs:
        print(f"ERROR: Unknown GPU '{gpu_name}'. Available: {', '.join(gpu_specs.keys())}", file=sys.stderr)
        sys.exit(1)
    gpu_spec = gpu_specs[gpu_name]

    configs, weight_gb, kv_per_token, kv_per_request_gb = generate_configs(
        model, gpu_spec, weight_dtype, kv_dtype, seq_len, args.gpu_count
    )

    best, reason = recommend(configs, model)

    # Build batch sweep for recommended config
    batch_sweep_result = []
    if best:
        kv_per_req_per_gpu = kv_per_request_gb / (best["tp"] * best.get("pp", 1))
        batch_sweep_result = generate_batch_sweep(
            best, gpu_spec, best["weight_per_gpu_gb"],
            kv_per_req_per_gpu, gpu_spec["memory_bw_tbps"],
        )

    result = {
        "model": model["name"],
        "params_billions": model["params_b"],
        "architecture": model["architecture"],
        "attention_type": model.get("attention_type", "gqa"),
        "gpu_platform": gpu_name,
        "gpu_count": args.gpu_count,
        "hbm_per_gpu_gb": gpu_spec["hbm_gb"],
        "total_hbm_gb": gpu_spec["hbm_gb"] * args.gpu_count,
        "weight_dtype": weight_dtype,
        "kv_dtype": kv_dtype,
        "seq_len": seq_len,
        "weight_memory_gb": round(weight_gb, 1),
        "kv_per_token_bytes": kv_per_token,
        "kv_per_request_gb": round(kv_per_request_gb, 2),
        "overhead_gb": round(gpu_spec["hbm_gb"] * OVERHEAD_FRACTION, 1),
        "usable_hbm_per_gpu_gb": round(gpu_spec["hbm_gb"] * (1 - OVERHEAD_FRACTION), 1),
        "valid_configs": configs[:15],
        "recommended": best,
        "recommendation_reason": reason,
        "batch_sweep": batch_sweep_result,
        "model_warning": model.get("warning"),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result, indent=2))
        print_human_readable(model, gpu_spec, gpu_name, weight_dtype, kv_dtype, seq_len,
                             args.gpu_count, weight_gb, kv_per_token, kv_per_request_gb,
                             configs, best, reason)


if __name__ == "__main__":
    main()
