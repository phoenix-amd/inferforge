"""HyperLoom session routes -- import, view, and manage optimization sessions."""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inferforge.db.connection import get_connection

router = APIRouter(prefix="/api/hyperloom", tags=["hyperloom"])


def _short_id() -> str:
    return str(uuid.uuid4())[:12]


class SessionImportRequest(BaseModel):
    breakdown_path: str


class SessionLaunchRequest(BaseModel):
    host: str
    model_name: str
    model_path: str
    framework_name: str = "vllm"
    gpu_type: str | None = None
    tp: int = 1
    ep: int = 0
    precision: str = "bf16"
    campaign_id: str | None = None
    conversation_id: str | None = None


@router.get("/sessions")
def api_list_sessions():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM hyperloom_sessions ORDER BY imported_at DESC LIMIT 50"
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        for jf in ("outcome_json", "timeline_json"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        results.append(d)
    return results


@router.post("/sessions/import", status_code=201)
def api_import_session(body: SessionImportRequest):
    bp = Path(body.breakdown_path)
    if not bp.exists():
        raise HTTPException(400, f"Breakdown file not found: {body.breakdown_path}")
    try:
        data = json.loads(bp.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(400, f"Failed to parse breakdown file: {e}")

    sid = _short_id()
    conn = get_connection()

    session_info = data if isinstance(data, dict) else {}
    outcome = session_info.get("outcome", {})
    timeline = session_info.get("timeline", [])

    with conn:
        conn.execute(
            "INSERT INTO hyperloom_sessions "
            "(id, claw_session_id, session_dir, host, model_name, model_path, "
            "framework_name, gpu_type, tp, ep, precision, stop_reason, "
            "outcome_gain_pct, outcome_json, schema_version, timeline_json, "
            "started_at, ended_at, elapsed_minutes, breakdown_path, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                session_info.get("session_id"),
                session_info.get("session_dir"),
                session_info.get("host"),
                session_info.get("model_name"),
                session_info.get("model_path"),
                session_info.get("framework_name"),
                session_info.get("gpu_type"),
                session_info.get("tp"),
                session_info.get("ep"),
                session_info.get("precision"),
                session_info.get("stop_reason"),
                outcome.get("gain_pct") if isinstance(outcome, dict) else None,
                json.dumps(outcome) if outcome else None,
                session_info.get("schema_version"),
                json.dumps(timeline) if timeline else None,
                session_info.get("started_at"),
                session_info.get("ended_at"),
                session_info.get("elapsed_minutes"),
                body.breakdown_path,
                "completed",
            ),
        )
    return {"id": sid, "status": "imported", "breakdown_path": body.breakdown_path}


@router.post("/sessions/launch", status_code=501)
def api_launch_session(body: SessionLaunchRequest):
    return {
        "status": "not_implemented",
        "message": "HyperLoom session launch requires the optimization engine. Use the agent chat to start sessions.",
    }


@router.get("/sessions/{session_id}")
def api_get_session(session_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Session {session_id} not found")
    d = dict(row)
    for jf in ("outcome_json", "timeline_json"):
        if d.get(jf):
            try:
                d[jf] = json.loads(d[jf])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


@router.post("/sessions/{session_id}/cancel")
def api_cancel_session(session_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, status FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Session {session_id} not found")
    with conn:
        conn.execute(
            "UPDATE hyperloom_sessions SET status = 'cancelled' WHERE id = ?",
            (session_id,),
        )
    return {"id": session_id, "status": "cancelled"}


@router.get("/sessions/{session_id}/timeline")
def api_get_timeline(session_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT timeline_json FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Session {session_id} not found")
    timeline = None
    raw = dict(row).get("timeline_json")
    if raw:
        try:
            timeline = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            timeline = []
    return {"session_id": session_id, "timeline": timeline or []}


@router.get("/sessions/{session_id}/optimizations")
def api_get_optimizations(session_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT outcome_json FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Session {session_id} not found")
    outcome = None
    raw = dict(row).get("outcome_json")
    if raw:
        try:
            outcome = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            outcome = {}
    optimizations = []
    if isinstance(outcome, dict):
        optimizations = outcome.get("optimizations", [])
    return {"session_id": session_id, "optimizations": optimizations}
