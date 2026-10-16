"""Recipe routes -- pre-built serving configurations from the Experience KB."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inferforge.db.connection import get_connection

router = APIRouter(prefix="/api", tags=["recipes"])


@router.get("/recipes")
def api_list_recipes(
    model_family: str | None = None,
    gpu_type: str | None = None,
    framework: str | None = None,
):
    conn = get_connection()
    clauses: list[str] = []
    params: list = []
    if model_family:
        clauses.append("model_family = ?")
        params.append(model_family)
    if gpu_type:
        clauses.append("gpu_type = ?")
        params.append(gpu_type)
    if framework:
        clauses.append("framework = ?")
        params.append(framework)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(50)
    rows = conn.execute(
        f"SELECT * FROM recipes {where} ORDER BY gain_pct DESC NULLS LAST LIMIT ?",
        params,
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        for jf in ("optimizations_json", "kernel_patches_json"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        results.append(d)
    return results


@router.get("/recipes/{recipe_id}")
def api_get_recipe(recipe_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM recipes WHERE id = ?", (recipe_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Recipe {recipe_id} not found")
    d = dict(row)
    for jf in ("optimizations_json", "kernel_patches_json"):
        if d.get(jf):
            try:
                d[jf] = json.loads(d[jf])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


@router.post("/recipes/sync", status_code=501)
def api_sync_recipes():
    return {
        "status": "not_implemented",
        "message": "Experience KB sync requires HYPERLOOM_KB_URL and HYPERLOOM_KB_TOKEN configuration.",
    }
