"""Benchmark run CRUD operations."""

import json
import uuid

from .connection import get_connection

_JSON_FIELDS = ("config_json",)

_ALL_COLUMNS = (
    "id", "conversation_id", "campaign_id", "hyperloom_session_id",
    "model_name", "model_hf_id", "model_params_b", "model_architecture",
    "gpu_platform", "gpu_count", "framework", "framework_version",
    "tp", "pp", "dp", "ep",
    "weight_dtype", "kv_dtype",
    "seq_len", "input_len", "output_len", "batch_size", "max_num_seqs",
    "chunked_prefill",
    "ttft_p50", "ttft_p90", "ttft_p99", "ttft_mean",
    "tpot_p50", "tpot_p90", "tpot_p99",
    "itl_p50", "itl_p90", "itl_p99",
    "e2e_p50", "e2e_p90", "e2e_p99",
    "throughput_tps", "throughput_rps",
    "hbm_used_gb", "hbm_util_pct",
    "run_mode", "evidence_source", "raw_output_path", "config_json",
)


def _short_id() -> str:
    return str(uuid.uuid4())[:12]


def _serialize(value, col: str):
    if col in _JSON_FIELDS and value is not None and not isinstance(value, str):
        return json.dumps(value)
    return value


def _deserialize_row(row) -> dict:
    d = dict(row)
    for col in _JSON_FIELDS:
        if d.get(col):
            try:
                d[col] = json.loads(d[col])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def save_benchmark_run(**kwargs) -> str:
    run_id = kwargs.pop("id", None) or _short_id()
    cols = ["id"]
    vals = [run_id]
    for col in _ALL_COLUMNS:
        if col == "id":
            continue
        if col in kwargs:
            cols.append(col)
            vals.append(_serialize(kwargs[col], col))

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    conn = get_connection()
    with conn:
        conn.execute(
            f"INSERT INTO benchmark_runs ({col_names}) VALUES ({placeholders})",
            vals,
        )
    return run_id


def get_benchmark_run(run_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM benchmark_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return _deserialize_row(row) if row else None


def list_benchmark_runs(
    conversation_id: str | None = None,
    campaign_id: str | None = None,
    model_name: str | None = None,
    limit: int = 50,
) -> list[dict]:
    conn = get_connection()
    clauses: list[str] = []
    params: list = []
    if conversation_id is not None:
        clauses.append("conversation_id = ?")
        params.append(conversation_id)
    if campaign_id is not None:
        clauses.append("campaign_id = ?")
        params.append(campaign_id)
    if model_name is not None:
        clauses.append("model_name = ?")
        params.append(model_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM benchmark_runs {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_deserialize_row(r) for r in rows]
