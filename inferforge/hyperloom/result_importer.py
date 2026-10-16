"""Import parsed V6 Hyperloom sessions into InferForge's SQLite database.

Handles the full import pipeline: read breakdown -> parse V6 -> insert
hyperloom_sessions row + benchmark_runs for each measurement round +
optional recipe extraction.
"""

import json
import logging
import uuid
from pathlib import Path

from ..db.connection import get_connection
from .session_adapter import read_session_breakdown, get_measurements
from .v6_parser import (
    v6_to_hyperloom_session,
    v6_to_benchmark_run,
    v6_to_recipe,
)

logger = logging.getLogger(__name__)


def import_session(
    db_path: str | None = None,
    breakdown_path: str | None = None,
    breakdown_data: dict | None = None,
    campaign_id: str | None = None,
    conversation_id: str | None = None,
    extract_recipe: bool = True,
) -> str:
    """Import a complete Hyperloom session into the database.

    Either ``breakdown_path`` (file on disk) or ``breakdown_data`` (pre-parsed
    dict) must be provided. Creates:
    - One ``hyperloom_sessions`` row
    - One ``benchmark_runs`` row per measurement round
    - Optionally one ``recipes`` row if the session achieved positive gain

    Returns the session_id.

    Raises
    ------
    ValueError
        If neither breakdown_path nor breakdown_data is provided, or if the
        breakdown cannot be parsed.
    """
    # Load breakdown
    if breakdown_data is None:
        if breakdown_path is None:
            raise ValueError("Either breakdown_path or breakdown_data must be provided")
        breakdown_data = read_session_breakdown(breakdown_path)
        if breakdown_data is None:
            raise ValueError(f"Could not read breakdown from {breakdown_path}")

    conn = get_connection(db_path)

    # Parse into table rows
    session_row = v6_to_hyperloom_session(breakdown_data)
    session_id = session_row["id"]

    # Add foreign keys
    if campaign_id:
        session_row["campaign_id"] = campaign_id
    if conversation_id:
        session_row["conversation_id"] = conversation_id
    if breakdown_path:
        session_row["breakdown_path"] = breakdown_path

    # Check for duplicate
    existing = conn.execute(
        "SELECT id FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if existing:
        logger.info("Session %s already imported, updating", session_id)
        _update_session(conn, session_id, session_row)
    else:
        _insert_session(conn, session_row)

    # Import measurement rounds as benchmark_runs
    rounds = breakdown_data.get("rounds", breakdown_data.get("measurements", []))
    run_ids: list[str] = []
    for rnd in rounds:
        if not isinstance(rnd, dict):
            continue
        run_row = v6_to_benchmark_run(breakdown_data, rnd)
        run_row["hyperloom_session_id"] = session_id
        if campaign_id:
            run_row["campaign_id"] = campaign_id
        if conversation_id:
            run_row["conversation_id"] = conversation_id

        run_id = _insert_benchmark_run(conn, run_row)
        run_ids.append(run_id)

    logger.info(
        "Imported session %s: %d benchmark runs",
        session_id,
        len(run_ids),
    )

    # Extract recipe if session was successful
    if extract_recipe:
        recipe = v6_to_recipe(breakdown_data)
        if recipe:
            recipe["source_session_id"] = session_id
            recipe_id = _insert_recipe(conn, recipe)
            logger.info("Extracted recipe %s from session %s", recipe_id, session_id)

    conn.commit()
    return session_id


def import_session_batch(
    db_path: str | None = None,
    breakdown_paths: list[str] | None = None,
    campaign_id: str | None = None,
) -> list[str]:
    """Import multiple session breakdowns. Returns list of session_ids."""
    if not breakdown_paths:
        return []

    session_ids: list[str] = []
    for path in breakdown_paths:
        try:
            sid = import_session(
                db_path=db_path,
                breakdown_path=path,
                campaign_id=campaign_id,
            )
            session_ids.append(sid)
        except (ValueError, Exception) as exc:
            logger.error("Failed to import %s: %s", path, exc)

    return session_ids


def get_imported_session(db_path: str | None = None, session_id: str = "") -> dict | None:
    """Retrieve an imported Hyperloom session by ID."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        return None
    return _deserialize_session_row(dict(row))


def list_imported_sessions(
    db_path: str | None = None,
    campaign_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List imported Hyperloom sessions with optional filters."""
    conn = get_connection(db_path)
    clauses: list[str] = []
    params: list = []

    if campaign_id:
        clauses.append("campaign_id = ?")
        params.append(campaign_id)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM hyperloom_sessions {where} ORDER BY imported_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_deserialize_session_row(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

_SESSION_COLUMNS = (
    "id", "campaign_id", "conversation_id", "claw_session_id", "session_dir",
    "host", "model_name", "model_path", "framework_name", "gpu_type",
    "tp", "ep", "precision", "stop_reason", "outcome_gain_pct",
    "outcome_json", "schema_version", "timeline_json", "started_at",
    "ended_at", "elapsed_minutes", "breakdown_path", "status",
)


def _insert_session(conn, row: dict) -> str:
    cols: list[str] = []
    vals: list = []
    for col in _SESSION_COLUMNS:
        if col in row:
            cols.append(col)
            vals.append(row[col])

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)

    with conn:
        conn.execute(
            f"INSERT INTO hyperloom_sessions ({col_names}) VALUES ({placeholders})",
            vals,
        )
    return row.get("id", "")


def _update_session(conn, session_id: str, row: dict) -> None:
    updates: list[str] = []
    vals: list = []
    skip = {"id", "imported_at"}
    for col in _SESSION_COLUMNS:
        if col in skip:
            continue
        if col in row:
            updates.append(f"{col} = ?")
            vals.append(row[col])

    if not updates:
        return

    vals.append(session_id)
    with conn:
        conn.execute(
            f"UPDATE hyperloom_sessions SET {', '.join(updates)} WHERE id = ?",
            vals,
        )


_BENCHMARK_COLUMNS = (
    "id", "conversation_id", "campaign_id", "hyperloom_session_id",
    "model_name", "model_hf_id", "model_params_b", "model_architecture",
    "gpu_platform", "gpu_count", "framework", "framework_version",
    "tp", "pp", "dp", "ep", "weight_dtype", "kv_dtype",
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


def _insert_benchmark_run(conn, row: dict) -> str:
    run_id = row.get("id") or str(uuid.uuid4())[:12]
    cols = ["id"]
    vals = [run_id]

    for col in _BENCHMARK_COLUMNS:
        if col == "id":
            continue
        if col in row:
            val = row[col]
            if col == "config_json" and isinstance(val, dict):
                val = json.dumps(val)
            cols.append(col)
            vals.append(val)

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)

    with conn:
        conn.execute(
            f"INSERT INTO benchmark_runs ({col_names}) VALUES ({placeholders})",
            vals,
        )
    return run_id


_RECIPE_COLUMNS = (
    "id", "model_family", "model_name", "gpu_type", "framework",
    "optimizations_json", "server_args", "kernel_patches_json",
    "baseline_tps", "optimized_tps", "gain_pct",
    "source", "source_session_id", "kb_record_id",
)


def _insert_recipe(conn, row: dict) -> str:
    recipe_id = row.get("id") or str(uuid.uuid4())[:12]
    cols = ["id"]
    vals = [recipe_id]

    for col in _RECIPE_COLUMNS:
        if col == "id":
            continue
        if col in row:
            cols.append(col)
            vals.append(row[col])

    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)

    with conn:
        conn.execute(
            f"INSERT INTO recipes ({col_names}) VALUES ({placeholders})",
            vals,
        )
    return recipe_id


def _deserialize_session_row(d: dict) -> dict:
    for json_col in ("outcome_json", "timeline_json"):
        if d.get(json_col):
            try:
                d[json_col] = json.loads(d[json_col])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
