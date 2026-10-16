"""Campaign CRUD and execution routes."""

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inferforge.db.connection import get_connection

router = APIRouter(prefix="/api", tags=["campaigns"])


def _short_id() -> str:
    return str(uuid.uuid4())[:12]


class CampaignCreate(BaseModel):
    name: str
    model_name: str | None = None
    model_hf_id: str | None = None
    frameworks: list[str] | None = None
    topologies: list[dict] | None = None
    dtypes: list[str] | None = None
    gpu_platforms: list[str] | None = None
    input_len: int | None = None
    output_len: int | None = None
    num_prompts: int | None = None
    request_rate: float | None = None
    sla_ttft_p95_ms: float | None = None
    sla_ttft_p99_ms: float | None = None
    sla_tpot_p99_ms: float | None = None
    sla_throughput_floor_tps: float | None = None
    max_gpu_hours: float | None = None
    max_wall_hours: float | None = None
    description: str | None = None


class CampaignPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


@router.get("/campaigns")
def api_list_campaigns():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        for jf in ("frameworks", "topologies", "dtypes", "gpu_platforms", "summary_json"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        results.append(d)
    return results


@router.post("/campaigns", status_code=201)
def api_create_campaign(body: CampaignCreate):
    cid = _short_id()
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO campaigns "
            "(id, name, model_name, model_hf_id, frameworks, topologies, dtypes, "
            "gpu_platforms, input_len, output_len, num_prompts, request_rate, "
            "sla_ttft_p95_ms, sla_ttft_p99_ms, sla_tpot_p99_ms, "
            "sla_throughput_floor_tps, max_gpu_hours, max_wall_hours, description) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                body.name,
                body.model_name,
                body.model_hf_id,
                json.dumps(body.frameworks) if body.frameworks else None,
                json.dumps(body.topologies) if body.topologies else None,
                json.dumps(body.dtypes) if body.dtypes else None,
                json.dumps(body.gpu_platforms) if body.gpu_platforms else None,
                body.input_len,
                body.output_len,
                body.num_prompts,
                body.request_rate,
                body.sla_ttft_p95_ms,
                body.sla_ttft_p99_ms,
                body.sla_tpot_p99_ms,
                body.sla_throughput_floor_tps,
                body.max_gpu_hours,
                body.max_wall_hours,
                body.description,
            ),
        )
    return {"id": cid, "name": body.name, "status": "draft"}


@router.get("/campaigns/{campaign_id}")
def api_get_campaign(campaign_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Campaign {campaign_id} not found")
    d = dict(row)
    for jf in ("frameworks", "topologies", "dtypes", "gpu_platforms", "summary_json"):
        if d.get(jf):
            try:
                d[jf] = json.loads(d[jf])
            except (json.JSONDecodeError, TypeError):
                pass
    runs = conn.execute(
        "SELECT * FROM benchmark_runs WHERE campaign_id = ? ORDER BY created_at DESC",
        (campaign_id,),
    ).fetchall()
    d["runs"] = [dict(r) for r in runs]
    return d


@router.patch("/campaigns/{campaign_id}")
def api_patch_campaign(campaign_id: str, body: CampaignPatch):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Campaign {campaign_id} not found")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    set_parts = []
    params = []
    for k, v in updates.items():
        set_parts.append(f"{k} = ?")
        params.append(v)
    set_parts.append("updated_at = datetime('now')")
    params.append(campaign_id)
    with conn:
        conn.execute(
            f"UPDATE campaigns SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
    return {"id": campaign_id, **updates}


@router.post("/campaigns/{campaign_id}/launch")
def api_launch_campaign(campaign_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Campaign {campaign_id} not found")
    with conn:
        conn.execute(
            "UPDATE campaigns SET status = 'running', updated_at = datetime('now') "
            "WHERE id = ?",
            (campaign_id,),
        )
    return {"status": "not_implemented", "message": "Campaign launch is queued but execution engine is pending implementation."}


@router.get("/campaigns/{campaign_id}/comparison")
def api_campaign_comparison(campaign_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Campaign {campaign_id} not found")
    runs = conn.execute(
        "SELECT id, model_name, framework, tp, pp, dp, weight_dtype, "
        "throughput_tps, ttft_p50, ttft_p99, tpot_p50, itl_p50, "
        "hbm_used_gb, hbm_util_pct, gpu_platform, gpu_count "
        "FROM benchmark_runs WHERE campaign_id = ? ORDER BY throughput_tps DESC",
        (campaign_id,),
    ).fetchall()
    return {
        "campaign_id": campaign_id,
        "runs": [dict(r) for r in runs],
        "count": len(runs),
    }
