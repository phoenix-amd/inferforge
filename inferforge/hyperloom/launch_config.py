"""Build Hyperloom CLI arguments from InferForge campaign specifications.

Translates the campaign table schema (frameworks, topologies, dtypes,
SLA targets) into concrete Hyperloom CLI invocations.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Valid framework names understood by Hyperloom
_VALID_FRAMEWORKS = {"sglang", "vllm", "tgi"}

# Valid precision strings
_VALID_PRECISIONS = {"bf16", "fp16", "fp8", "int8", "int4"}

# Map InferForge GPU platform names to Hyperloom --gpu-type values
_GPU_TYPE_MAP = {
    "mi300x": "mi300x",
    "mi325x": "mi325x",
    "mi350x": "mi350x",
    "mi308x": "mi308x",
    "mi250x": "mi250x",
    "mi210": "mi210",
    "mi100": "mi100",
    # Allow direct pass-through for unknown types
}


def campaign_to_hyperloom_args(
    campaign: dict,
    topology: str,
    framework: str,
    dtype: str,
) -> list[str]:
    """Convert a campaign spec + specific topology/framework/dtype into Hyperloom CLI args.

    Parameters
    ----------
    campaign:
        Campaign row dict from the campaigns table (or equivalent API payload).
    topology:
        Parallelism topology string, e.g. ``"tp8"``, ``"tp4_ep2"``, ``"tp4_pp2"``.
    framework:
        Inference framework: ``"vllm"``, ``"sglang"``, ``"tgi"``.
    dtype:
        Weight precision: ``"bf16"``, ``"fp16"``, ``"fp8"``.

    Returns
    -------
    list[str]
        CLI arguments for ``python -m hyperloom optimize``.
    """
    args: list[str] = []

    # Model
    model = campaign.get("model_hf_id") or campaign.get("model_name", "")
    if not model:
        raise ValueError("Campaign has no model_name or model_hf_id")
    args.extend(["--model", model])

    # Framework
    fw = framework.lower()
    if fw not in _VALID_FRAMEWORKS:
        logger.warning("Unknown framework '%s', passing through", fw)
    args.extend(["--framework", fw])

    # GPU type
    gpu_platforms = _parse_csv(campaign.get("gpu_platforms", ""))
    gpu_type = gpu_platforms[0] if gpu_platforms else "mi300x"
    gpu_type = _GPU_TYPE_MAP.get(gpu_type.lower(), gpu_type.lower())
    args.extend(["--gpu-type", gpu_type])

    # Parallelism from topology string
    tp, ep, pp, dp = _parse_topology(topology)
    if tp:
        args.extend(["--tp", str(tp)])
    if ep:
        args.extend(["--ep", str(ep)])

    # Precision
    precision = dtype.lower()
    if precision not in _VALID_PRECISIONS:
        logger.warning("Unknown precision '%s', defaulting to bf16", precision)
        precision = "bf16"
    args.extend(["--precision", precision])

    # SLA constraints
    sla_ttft = campaign.get("sla_ttft_p99_ms") or campaign.get("sla_ttft_p95_ms")
    if sla_ttft:
        args.extend(["--max-latency-ms", str(sla_ttft)])

    # Time budget
    max_hours = campaign.get("max_wall_hours")
    if max_hours:
        args.extend(["--max-hours", str(max_hours)])
    else:
        args.extend(["--max-hours", "2.0"])

    # Enablement scope
    args.extend(["--enablement", "all"])

    return args


def campaign_to_session_matrix(campaign: dict) -> list[dict]:
    """Expand a campaign into the full matrix of Hyperloom sessions to run.

    Crosses frameworks x topologies x dtypes from the campaign config.
    Returns a list of dicts, each with keys: framework, topology, dtype, args.
    """
    frameworks = _parse_csv(campaign.get("frameworks", "vllm"))
    topologies = _parse_csv(campaign.get("topologies", "tp8"))
    dtypes = _parse_csv(campaign.get("dtypes", "bf16"))

    matrix: list[dict] = []
    for fw in frameworks:
        for topo in topologies:
            for dt in dtypes:
                try:
                    args = campaign_to_hyperloom_args(campaign, topo, fw, dt)
                    matrix.append({
                        "framework": fw,
                        "topology": topo,
                        "dtype": dt,
                        "args": args,
                        "label": f"{fw}_{topo}_{dt}",
                    })
                except ValueError as exc:
                    logger.error("Skipping %s/%s/%s: %s", fw, topo, dt, exc)

    return matrix


def build_benchmark_docker_cmd(
    model_path: str,
    framework: str,
    tp: int,
    gpu_type: str = "mi300x",
    dtype: str = "bf16",
    input_len: int = 1024,
    output_len: int = 128,
    num_prompts: int = 100,
    container_name: str | None = None,
) -> str:
    """Build a Docker run command string for direct benchmarking (non-Hyperloom).

    Uses the standard InferForge Docker templates with --network=host.
    """
    images = {
        "vllm": "rocm/vllm-dev:latest",
        "sglang": "lmsysorg/sglang:latest-rocm",
        "tgi": "ghcr.io/huggingface/text-generation-inference:latest-rocm",
    }
    image = images.get(framework.lower(), images["vllm"])
    name = container_name or f"inferforge-bench-{framework}"

    vllm_dtype = "bfloat16" if dtype == "bf16" else dtype

    if framework.lower() == "vllm":
        bench_cmd = (
            f"python3 /app/vllm/benchmarks/benchmark_throughput.py "
            f"--model {model_path} "
            f"--tensor-parallel-size {tp} "
            f"--dtype {vllm_dtype} "
            f"--input-len {input_len} --output-len {output_len} "
            f"--num-prompts {num_prompts} "
            f"--trust-remote-code"
        )
    elif framework.lower() == "sglang":
        bench_cmd = (
            f"python3 -m sglang.bench_serving "
            f"--model {model_path} "
            f"--tp {tp} "
            f"--input-len {input_len} --output-len {output_len} "
            f"--num-prompts {num_prompts}"
        )
    else:
        bench_cmd = f"echo 'Unsupported framework: {framework}'"

    docker_cmd = (
        f"docker run --rm -d "
        f"--device=/dev/kfd --device=/dev/dri --group-add video "
        f"--network=host "
        f"--shm-size 64g "
        f"--name {name} "
        f"-v ~/.cache/huggingface:/root/.cache/huggingface "
        f"-e VLLM_USE_V1=0 "
        f"-e HIPBLASLT_WORKSPACE_SIZE=131072 "
        f"-e HF_HUB_OFFLINE=1 "
        f"{image} "
        f"{bench_cmd}"
    )

    return docker_cmd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_topology(topology: str) -> tuple[int | None, int | None, int | None, int | None]:
    """Parse a topology string like ``tp8``, ``tp4_ep2``, ``tp4_pp2_dp2``.

    Returns (tp, ep, pp, dp) with None for unspecified values.
    """
    topology = topology.lower().strip()
    tp = ep = pp = dp = None

    import re
    for match in re.finditer(r"(tp|ep|pp|dp)(\d+)", topology):
        key = match.group(1)
        val = int(match.group(2))
        if key == "tp":
            tp = val
        elif key == "ep":
            ep = val
        elif key == "pp":
            pp = val
        elif key == "dp":
            dp = val

    return tp, ep, pp, dp


def _parse_csv(value: Any) -> list[str]:
    """Parse a comma-separated string or JSON list into a list of stripped strings."""
    if not value:
        return []

    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]

    if isinstance(value, str):
        # Try JSON first
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if str(v).strip()]
            except json.JSONDecodeError:
                pass
        # Fall back to CSV
        return [v.strip() for v in value.split(",") if v.strip()]

    return [str(value)]
