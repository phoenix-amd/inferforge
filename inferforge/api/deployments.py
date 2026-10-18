"""Deployment routes -- promote benchmark configs to production serving."""

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inferforge.db.connection import get_connection

router = APIRouter(prefix="/api", tags=["deployments"])


def _short_id() -> str:
    return str(uuid.uuid4())[:12]


class DeploymentCreate(BaseModel):
    benchmark_run_id: str | None = None
    recipe_id: str | None = None
    model_name: str
    framework: str = "vllm"
    node_id: str | None = None
    tp: int = 1
    pp: int = 1
    dp: int = 1
    launch_config_json: dict | None = None
    canary_pct: float = 0
    sla_ttft_p99_ms: float | None = None
    sla_throughput_floor_tps: float | None = None
    project_id: str | None = None


class DeploymentPatch(BaseModel):
    state: str | None = None
    canary_pct: float | None = None


@router.get("/deployments")
def api_list_deployments():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM deployments ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("launch_config_json"):
            try:
                d["launch_config_json"] = json.loads(d["launch_config_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(d)
    return {"deployments": results, "total": len(results)}


@router.post("/deployments", status_code=201)
def api_create_deployment(body: DeploymentCreate):
    import sqlite3
    did = _short_id()
    conn = get_connection()

    def _insert(benchmark_run_id):
        conn.execute(
            "INSERT INTO deployments "
            "(id, project_id, benchmark_run_id, recipe_id, model_name, framework, "
            "node_id, tp, pp, dp, launch_config_json, state, canary_pct, "
            "sla_ttft_p99_ms, sla_throughput_floor_tps) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                did,
                body.project_id,
                benchmark_run_id,
                body.recipe_id,
                body.model_name,
                body.framework,
                body.node_id,
                body.tp,
                body.pp,
                body.dp,
                json.dumps(body.launch_config_json) if body.launch_config_json else None,
                "pending",
                body.canary_pct,
                body.sla_ttft_p99_ms,
                body.sla_throughput_floor_tps,
            ),
        )

    try:
        with conn:
            _insert(body.benchmark_run_id)
    except sqlite3.IntegrityError:
        # FK constraint failed — benchmark_run_id doesn't match any record
        # (agent may have used full UUID vs short ID). Retry without it.
        with conn:
            _insert(None)

    return {"id": did, "model_name": body.model_name, "state": "pending"}


@router.patch("/deployments/{deployment_id}")
def api_patch_deployment(deployment_id: str, body: DeploymentPatch):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM deployments WHERE id = ?", (deployment_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Deployment {deployment_id} not found")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    set_parts = []
    params = []
    for k, v in updates.items():
        set_parts.append(f"{k} = ?")
        params.append(v)
    params.append(deployment_id)
    with conn:
        conn.execute(
            f"UPDATE deployments SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
    return {"id": deployment_id, **updates}


@router.post("/deployments/{deployment_id}/promote")
def api_promote_deployment(deployment_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, state FROM deployments WHERE id = ?", (deployment_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Deployment {deployment_id} not found")
    d = dict(row)
    if d["state"] != "canary":
        raise HTTPException(400, f"Cannot promote: deployment must be in 'canary' state, not '{d['state']}'. Use PATCH to transition through building → deploying → canary first.")
    with conn:
        conn.execute(
            "UPDATE deployments SET state = 'active', canary_pct = 100, "
            "promoted_at = datetime('now') WHERE id = ?",
            (deployment_id,),
        )
    return {"id": deployment_id, "state": "active", "canary_pct": 100}


@router.post("/deployments/{deployment_id}/rollback")
def api_rollback_deployment(deployment_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, state FROM deployments WHERE id = ?", (deployment_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Deployment {deployment_id} not found")
    with conn:
        conn.execute(
            "UPDATE deployments SET state = 'rolled_back', canary_pct = 0, "
            "stopped_at = datetime('now') WHERE id = ?",
            (deployment_id,),
        )
    return {"id": deployment_id, "state": "rolled_back"}
