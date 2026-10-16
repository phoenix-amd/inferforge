"""Read and interpret Hyperloom session_breakdown.json files.

Provides pure-function helpers to extract summary, timeline, optimization
stack, and measurement data from the V6 breakdown schema.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def read_session_breakdown(path: str) -> dict | None:
    """Read and validate a Hyperloom session_breakdown.json file.

    Returns the parsed dict, or None if the file is missing / invalid.
    """
    p = Path(path)
    if not p.is_file():
        logger.warning("Breakdown file not found: %s", path)
        return None

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read breakdown %s: %s", path, exc)
        return None

    if not isinstance(data, dict):
        logger.error("Breakdown file is not a JSON object: %s", path)
        return None

    # Minimal validation: expect a session_id or metadata block
    if not (data.get("session_id") or data.get("metadata")):
        logger.warning("Breakdown file lacks session_id and metadata: %s", path)

    return data


def get_session_summary(breakdown: dict) -> dict:
    """Extract a concise summary from a breakdown.

    Returns dict with keys: session_id, model, framework, gpu_type, tp, ep,
    precision, stop_reason, status, outcome, gain_pct, elapsed_minutes,
    started_at, ended_at.
    """
    meta = breakdown.get("metadata", {})
    task = breakdown.get("task_config", {})
    outcome = breakdown.get("outcome", {})
    timing = breakdown.get("timing", {})

    model_cfg = task.get("model", {})
    framework_cfg = task.get("framework", {})
    gpu_cfg = task.get("gpu", {})
    parallelism = task.get("parallelism", {})

    return {
        "session_id": meta.get("session_id") or breakdown.get("session_id", ""),
        "schema_version": meta.get("schema_version", ""),
        "model": model_cfg.get("name", "") or model_cfg.get("path", ""),
        "model_path": model_cfg.get("path", ""),
        "framework": framework_cfg.get("name", ""),
        "framework_version": framework_cfg.get("version", ""),
        "gpu_type": gpu_cfg.get("type", ""),
        "gpu_count": gpu_cfg.get("count", 0),
        "tp": parallelism.get("tp", 1),
        "ep": parallelism.get("ep", 0),
        "precision": task.get("precision", ""),
        "stop_reason": outcome.get("stop_reason", ""),
        "status": _derive_status(outcome),
        "gain_pct": outcome.get("gain_pct", 0.0),
        "baseline_tps": _safe_float(outcome.get("baseline", {}).get("throughput_tps")),
        "final_tps": _safe_float(outcome.get("final", {}).get("throughput_tps")),
        "elapsed_minutes": timing.get("elapsed_minutes", 0.0),
        "started_at": timing.get("started_at", ""),
        "ended_at": timing.get("ended_at", ""),
    }


def get_session_timeline(breakdown: dict) -> list[dict]:
    """Extract an ordered timeline of events from the breakdown.

    Each entry has: phase, action, timestamp, round_number, measurements (if any).
    """
    timeline_raw = breakdown.get("timeline", [])
    events: list[dict] = []

    for entry in timeline_raw:
        if not isinstance(entry, dict):
            continue
        event = {
            "phase": entry.get("phase", ""),
            "action": entry.get("action", ""),
            "timestamp": entry.get("timestamp", ""),
            "round_number": entry.get("round", entry.get("round_number", 0)),
            "duration_s": entry.get("duration_s", 0.0),
            "detail": entry.get("detail", ""),
        }

        # Attach measurements if present
        meas = entry.get("measurement") or entry.get("metrics")
        if isinstance(meas, dict):
            event["measurements"] = _flatten_measurements(meas)

        events.append(event)

    return events


def get_optimization_stack(breakdown: dict) -> list[dict]:
    """Extract the ordered list of optimizations in the final stack.

    Each entry has: name, category, enabled, delta_tps, delta_pct, parameters.
    """
    stack_raw = breakdown.get("optimization_stack", breakdown.get("stack", []))
    if not isinstance(stack_raw, list):
        return []

    stack: list[dict] = []
    for item in stack_raw:
        if not isinstance(item, dict):
            continue
        stack.append({
            "name": item.get("name", ""),
            "category": item.get("category", ""),
            "enabled": item.get("enabled", True),
            "delta_tps": _safe_float(item.get("delta_tps")),
            "delta_pct": _safe_float(item.get("delta_pct")),
            "parameters": item.get("parameters", item.get("params", {})),
            "round_applied": item.get("round", item.get("round_applied")),
        })

    return stack


def get_measurements(breakdown: dict) -> list[dict]:
    """Extract all measurement records from the breakdown.

    Returns a flat list of measurement dicts, each with round_number, phase,
    and the graded axes values.
    """
    rounds = breakdown.get("rounds", breakdown.get("measurements", []))
    if not isinstance(rounds, list):
        return []

    measurements: list[dict] = []
    for rnd in rounds:
        if not isinstance(rnd, dict):
            continue
        meas = {
            "round_number": rnd.get("round", rnd.get("round_number", 0)),
            "phase": rnd.get("phase", ""),
            "label": rnd.get("label", ""),
            "timestamp": rnd.get("timestamp", ""),
        }

        # Flatten graded axes / metrics
        axes = rnd.get("graded_axes", rnd.get("metrics", {}))
        if isinstance(axes, dict):
            meas.update(_flatten_measurements(axes))

        measurements.append(meas)

    return measurements


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_status(outcome: dict) -> str:
    """Map outcome fields to a simple status string."""
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


def _safe_float(val: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _flatten_measurements(axes: dict) -> dict:
    """Flatten nested graded axes into a flat metric dict.

    Handles both flat ``{"throughput_tps": 100}`` and nested
    ``{"throughput": {"value": 100, "unit": "tok/s"}}`` structures.
    """
    flat: dict = {}
    for key, val in axes.items():
        if isinstance(val, dict):
            # Nested: extract value
            v = val.get("value", val.get("median", val.get("mean")))
            if v is not None:
                flat[key] = v
            # Also extract percentiles if present
            for pct in ("p50", "p90", "p95", "p99"):
                if pct in val:
                    flat[f"{key}_{pct}"] = val[pct]
        else:
            flat[key] = val
    return flat
