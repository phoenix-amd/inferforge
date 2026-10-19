"""HyperLoom session routes -- import, view, and manage optimization sessions."""

import json
import subprocess
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
    return {"sessions": results, "total": len(results)}


class SessionCreateRequest(BaseModel):
    model_name: str
    framework_name: str = "vllm"
    host: str | None = None
    model_path: str | None = None
    gpu_type: str | None = None
    tp: int = 1
    ep: int = 0
    precision: str = "bf16"
    status: str = "running"
    timeline_json: list | None = None
    conversation_id: str | None = None
    campaign_id: str | None = None


@router.post("/sessions", status_code=201)
def api_create_session(body: SessionCreateRequest):
    sid = _short_id()
    conn = get_connection()
    now = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    timeline = json.dumps(body.timeline_json) if body.timeline_json else None
    with conn:
        conn.execute(
            "INSERT INTO hyperloom_sessions "
            "(id, host, model_name, model_path, framework_name, gpu_type, "
            "tp, ep, precision, timeline_json, started_at, status, "
            "conversation_id, campaign_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid, body.host, body.model_name, body.model_path,
                body.framework_name, body.gpu_type, body.tp, body.ep,
                body.precision, timeline, now, body.status,
                body.conversation_id, body.campaign_id,
            ),
        )
    return {"id": sid, "model_name": body.model_name, "status": body.status}


class SessionPatchRequest(BaseModel):
    status: str | None = None
    timeline_json: list | None = None
    outcome_json: dict | None = None
    outcome_gain_pct: float | None = None
    ended_at: str | None = None
    elapsed_minutes: float | None = None
    stop_reason: str | None = None


@router.patch("/sessions/{session_id}")
def api_patch_session(session_id: str, body: SessionPatchRequest):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Session {session_id} not found")
    updates = {}
    if body.status is not None:
        updates["status"] = body.status
    if body.timeline_json is not None:
        updates["timeline_json"] = json.dumps(body.timeline_json)
    if body.outcome_json is not None:
        updates["outcome_json"] = json.dumps(body.outcome_json)
    if body.outcome_gain_pct is not None:
        updates["outcome_gain_pct"] = body.outcome_gain_pct
    if body.ended_at is not None:
        updates["ended_at"] = body.ended_at
    if body.elapsed_minutes is not None:
        updates["elapsed_minutes"] = body.elapsed_minutes
    if body.stop_reason is not None:
        updates["stop_reason"] = body.stop_reason
    if not updates:
        raise HTTPException(400, "No fields to update")
    set_parts = [f"{k} = ?" for k in updates]
    params = list(updates.values()) + [session_id]
    with conn:
        conn.execute(
            f"UPDATE hyperloom_sessions SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
    return {"id": session_id, **{k: v for k, v in updates.items() if k != "timeline_json"}}


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


@router.post("/sessions/launch")
def api_launch_session(body: SessionLaunchRequest):
    from inferforge.config import HYPERLOOM_KB_URL, HYPERLOOM_KB_TOKEN
    missing = []
    if not HYPERLOOM_KB_URL:
        missing.append("HYPERLOOM_KB_URL")
    if not HYPERLOOM_KB_TOKEN:
        missing.append("HYPERLOOM_KB_TOKEN")
    if missing:
        return {
            "status": "not_configured",
            "missing": missing,
            "message": (
                "Hyperloom is not configured. "
                f"Add {' and '.join(missing)} to /home/rghaffari/inferforge/.env "
                "then restart the server (python3 -m inferforge.server)."
            ),
        }
    return {
        "status": "not_implemented",
        "message": "Hyperloom credentials found but launch integration is not yet wired. Use the agent chat.",
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


@router.delete("/sessions/{session_id}", status_code=200)
def api_delete_session(session_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Session {session_id} not found")
    with conn:
        conn.execute("DELETE FROM hyperloom_sessions WHERE id = ?", (session_id,))
    return {"id": session_id, "deleted": True}


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
        "SELECT timeline_json, status FROM hyperloom_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Session {session_id} not found")
    d = dict(row)
    session_status = d.get("status", "running")
    timeline = None
    raw = d.get("timeline_json")
    if raw:
        try:
            timeline = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            timeline = []
    phases = timeline or []
    current_phase = None
    if phases:
        for p in reversed(phases):
            if isinstance(p, dict) and p.get("status") in ("running", "active"):
                current_phase = p.get("name") or p.get("phase")
                break
        if not current_phase and phases:
            last = phases[-1]
            current_phase = last.get("name") or last.get("phase") if isinstance(last, dict) else None
    return {
        "session_id": session_id,
        "phases": phases,
        "current_phase": current_phase,
        "session_status": session_status,
    }


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


@router.post("/kill")
def api_kill_cluster_jobs():
    """Kill ALL running Hyperloom Docker containers on the cluster and mark sessions stopped.

    SSHes to every unique host that has a running session and runs:
      docker stop hyperloom-optimize && docker rm hyperloom-optimize
    Also kills vLLM/ray processes. Marks all running sessions as stopped.
    """
    conn = get_connection()
    running = conn.execute(
        "SELECT id, host FROM hyperloom_sessions WHERE status = 'running'"
    ).fetchall()

    killed_hosts: list[str] = []
    errors: list[str] = []
    seen_hosts: set[str] = set()

    ssh_key = str(Path.home() / ".ssh" / "id_ed25519_moba")
    kill_cmd = (
        "docker stop hyperloom-optimize 2>/dev/null; "
        "docker rm -f hyperloom-optimize 2>/dev/null; "
        # Also kill any stray vllm / ray processes not inside Docker
        "pkill -f 'hyperloom optimize' 2>/dev/null; "
        # Remove stale optimizer.lock files so next run doesn't fail
        "find /hl-data -name 'optimizer.lock' -delete 2>/dev/null; "
        "echo KILLED"
    )

    for row in running:
        host = dict(row).get("host") or ""
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        try:
            result = subprocess.run(
                ["ssh", "-i", ssh_key,
                 "-o", "BatchMode=yes",
                 "-o", "ConnectTimeout=10",
                 "-o", "StrictHostKeyChecking=no",
                 f"rghaffar@{host}", kill_cmd],
                capture_output=True, text=True, timeout=20,
            )
            killed_hosts.append(host)
        except Exception as e:
            errors.append(f"{host}: {e}")

    # Mark all running sessions as stopped
    with conn:
        conn.execute(
            "UPDATE hyperloom_sessions SET status='stopped', stop_reason='user_killed' "
            "WHERE status='running'"
        )

    return {
        "killed_hosts": killed_hosts,
        "sessions_stopped": len(running),
        "errors": errors,
    }
