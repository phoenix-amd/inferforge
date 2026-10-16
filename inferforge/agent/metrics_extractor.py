"""Fallback metrics extraction from raw benchmark output.

This module is used when the agent does not call the ``report_metrics`` tool
explicitly. It parses well-known output formats from vLLM, SGLang, and
rocm-smi / amd-smi to extract structured data.
"""

from __future__ import annotations

import json
import re


# ---------------------------------------------------------------------------
# Benchmark output parsing
# ---------------------------------------------------------------------------

# vLLM benchmark_serving.py patterns
_VLLM_SERVING_PATTERNS: dict[str, re.Pattern] = {
    "throughput_rps": re.compile(
        r"Request throughput\s*(?:\([^)]*\))?\s*:\s*([\d.]+)", re.IGNORECASE
    ),
    "throughput_tps": re.compile(
        r"Output token throughput\s*(?:\([^)]*\))?\s*:\s*([\d.]+)", re.IGNORECASE
    ),
    "ttft_p50": re.compile(
        r"Median TTFT\s*\(ms\)\s*:\s*([\d.]+)", re.IGNORECASE
    ),
    "ttft_p99": re.compile(
        r"P99 TTFT\s*\(ms\)\s*:\s*([\d.]+)", re.IGNORECASE
    ),
    "tpot_p50": re.compile(
        r"Median TPOT\s*\(ms\)\s*:\s*([\d.]+)", re.IGNORECASE
    ),
    "tpot_p99": re.compile(
        r"P99 TPOT\s*\(ms\)\s*:\s*([\d.]+)", re.IGNORECASE
    ),
    "itl_p50": re.compile(
        r"Median ITL\s*\(ms\)\s*:\s*([\d.]+)", re.IGNORECASE
    ),
    "e2e_p50": re.compile(
        r"Median E2EL?\s*\(ms\)\s*:\s*([\d.]+)", re.IGNORECASE
    ),
}

# vLLM benchmark_throughput.py pattern
_VLLM_THROUGHPUT_PATTERN = re.compile(
    r"Throughput:\s*([\d.]+)\s*requests/s.*?([\d.]+)\s*tokens/s",
    re.IGNORECASE,
)

# SGLang benchmark output patterns
_SGLANG_PATTERNS: dict[str, re.Pattern] = {
    "throughput_tps": re.compile(
        r"Output throughput.*?:\s*([\d.]+)\s*tok/s", re.IGNORECASE
    ),
    "ttft_p50": re.compile(
        r"TTFT.*?p50\s*[:=]\s*([\d.]+)", re.IGNORECASE
    ),
    "ttft_p99": re.compile(
        r"TTFT.*?p99\s*[:=]\s*([\d.]+)", re.IGNORECASE
    ),
}


def parse_benchmark_output(text: str) -> dict | None:
    """Attempt to extract structured metrics from raw benchmark output.

    Tries in order:
    1. JSON block embedded in the output (``report_metrics``-compatible)
    2. vLLM ``benchmark_serving.py`` text patterns
    3. vLLM ``benchmark_throughput.py`` text patterns
    4. SGLang benchmark patterns

    Returns a dict of extracted metrics, or ``None`` if nothing matched.
    """
    if not text or not text.strip():
        return None

    # 1. Try embedded JSON
    result = _try_json_block(text)
    if result:
        return result

    # 2. vLLM serving benchmark
    metrics: dict[str, float] = {}
    for key, pattern in _VLLM_SERVING_PATTERNS.items():
        m = pattern.search(text)
        if m:
            try:
                metrics[key] = float(m.group(1))
            except (ValueError, IndexError):
                pass

    if metrics:
        return metrics

    # 3. vLLM throughput benchmark
    m = _VLLM_THROUGHPUT_PATTERN.search(text)
    if m:
        try:
            return {
                "throughput_rps": float(m.group(1)),
                "throughput_tps": float(m.group(2)),
            }
        except (ValueError, IndexError):
            pass

    # 4. SGLang patterns
    for key, pattern in _SGLANG_PATTERNS.items():
        m = pattern.search(text)
        if m:
            try:
                metrics[key] = float(m.group(1))
            except (ValueError, IndexError):
                pass

    return metrics if metrics else None


def _try_json_block(text: str) -> dict | None:
    """Extract a JSON object from fenced code blocks or bare braces."""
    # Fenced JSON blocks: ```json ... ```
    json_fence = re.search(
        r"```(?:json)?\s*\n(\{.*?\})\s*\n```", text, re.DOTALL
    )
    if json_fence:
        try:
            data = json.loads(json_fence.group(1))
            if isinstance(data, dict) and ("model_name" in data or "throughput_tps" in data):
                return data
        except json.JSONDecodeError:
            pass

    # Bare JSON object that looks like metrics
    bare_json = re.search(
        r'\{[^{}]*"(?:model_name|throughput_tps|ttft_p50)"[^{}]*\}',
        text,
        re.DOTALL,
    )
    if bare_json:
        try:
            data = json.loads(bare_json.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# GPU info extraction
# ---------------------------------------------------------------------------

# amd-smi output: "GPU[0] : GPU_ASIC: gfx942 (MI300X)"
_AMDSMI_GPU_MODEL = re.compile(
    r"(?:MI\d{3}X?|Instinct\s+MI\d{3}X?)", re.IGNORECASE
)

# rocm-smi / amd-smi HBM patterns
_HBM_TOTAL = re.compile(
    r"(?:vram|hbm|memory)\s*(?:total|size)?\s*[:=]?\s*([\d.]+)\s*(MB|GB|MiB|GiB)",
    re.IGNORECASE,
)

# GPU count from device listing
_GPU_DEVICE_LINE = re.compile(
    r"GPU\[(\d+)\]", re.IGNORECASE
)


def extract_gpu_info(text: str) -> dict | None:
    """Extract GPU model, count, and HBM from rocm-smi / amd-smi output.

    Returns
    -------
    dict with keys ``gpu_model``, ``gpu_count``, ``hbm_per_gpu`` (in GB),
    or ``None`` if the text doesn't look like GPU diagnostic output.
    """
    if not text or not text.strip():
        return None

    # GPU model
    gpu_model_match = _AMDSMI_GPU_MODEL.search(text)
    gpu_model = gpu_model_match.group(0) if gpu_model_match else None

    # GPU count
    device_ids = set()
    for m in _GPU_DEVICE_LINE.finditer(text):
        device_ids.add(int(m.group(1)))
    gpu_count = len(device_ids) if device_ids else None

    # HBM per GPU
    hbm_per_gpu: float | None = None
    hbm_match = _HBM_TOTAL.search(text)
    if hbm_match:
        value = float(hbm_match.group(1))
        unit = hbm_match.group(2).upper()
        if unit in ("MB", "MIB"):
            value /= 1024.0
        hbm_per_gpu = round(value, 1)

    if not gpu_model and not gpu_count:
        return None

    result: dict = {}
    if gpu_model:
        result["gpu_model"] = gpu_model
    if gpu_count is not None:
        result["gpu_count"] = gpu_count
    if hbm_per_gpu is not None:
        result["hbm_per_gpu"] = hbm_per_gpu
    return result
