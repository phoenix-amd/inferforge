"""Fleet management routes -- GPU node inventory and reservations."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from inferforge.db.connection import get_connection

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


def _short_id() -> str:
    return str(uuid.uuid4())[:12]


class NodeCreate(BaseModel):
    hostname: str
    ip_address: str | None = None
    ssh_user: str | None = None
    ssh_key_path: str | None = None
    gpu_platform: str | None = None
    gpu_count: int = 0
    hbm_per_gpu_gb: float = 0
    rocm_version: str | None = None


class ReserveRequest(BaseModel):
    node_id: str
    gpu_start: int = 0
    gpu_count: int = 1
    campaign_id: str | None = None
    conversation_id: str | None = None
    expires_hours: float | None = None


def _row_to_node(r) -> dict:
    """Normalise a DB row into the shape Era's telemetry panel expects."""
    # Handle both sqlite3.Row and plain dict
    if not isinstance(r, dict):
        try:
            r = dict(r)
        except Exception:
            # Fallback: row is a tuple — build dict from known column order
            cols = ["id", "hostname", "ip_address", "ssh_user", "ssh_key_path",
                    "gpu_platform", "gpu_count", "hbm_per_gpu_gb", "rocm_version",
                    "status", "last_probed", "metadata_json"]
            r = {cols[i]: r[i] for i in range(min(len(cols), len(r)))}
    if r.get("metadata_json"):
        try:
            r["metadata_json"] = json.loads(r["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        **r,
        "ip":        r.get("ip_address") or r.get("hostname", ""),
        "gpu_model": r.get("gpu_platform") or "--",
        "hbm_per_gpu": r.get("hbm_per_gpu_gb", 0),
        "gpus":      [],
    }


@router.get("/nodes")
def api_list_nodes():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM fleet_nodes ORDER BY hostname"
    ).fetchall()
    nodes = [_row_to_node(dict(r)) for r in rows]
    # Return both shapes: Era expects {nodes:[...]}, older callers get the list
    return {"nodes": nodes, "total": len(nodes)}


@router.post("/nodes", status_code=201)
def api_add_node(body: NodeCreate):
    nid = _short_id()
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO fleet_nodes "
            "(id, hostname, ip_address, ssh_user, ssh_key_path, "
            "gpu_platform, gpu_count, hbm_per_gpu_gb, rocm_version, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                nid,
                body.hostname,
                body.ip_address,
                body.ssh_user,
                body.ssh_key_path,
                body.gpu_platform,
                body.gpu_count,
                body.hbm_per_gpu_gb,
                body.rocm_version,
                "unknown",
            ),
        )
    return {"id": nid, "hostname": body.hostname, "status": "unknown"}


@router.post("/nodes/{node_id}/probe", status_code=501)
def api_probe_node(node_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM fleet_nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Node {node_id} not found")
    return {"status": "not_implemented", "message": "SSH probe not yet implemented. Use the agent chat to probe nodes."}


@router.post("/reserve", status_code=201)
def api_reserve_gpus(body: ReserveRequest):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, gpu_count FROM fleet_nodes WHERE id = ?", (body.node_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Node {body.node_id} not found")
    if body.gpu_start + body.gpu_count > dict(row)["gpu_count"]:
        raise HTTPException(400, "Requested GPU range exceeds node capacity")
    rid = _short_id()
    expires_at = None
    if body.expires_hours:
        expires_at = f"datetime('now', '+{int(body.expires_hours * 3600)} seconds')"
    with conn:
        if expires_at:
            conn.execute(
                "INSERT INTO fleet_reservations "
                "(id, node_id, campaign_id, conversation_id, gpu_start, gpu_count, "
                "expires_at) VALUES (?,?,?,?,?,?, datetime('now', ? || ' seconds'))",
                (
                    rid, body.node_id, body.campaign_id, body.conversation_id,
                    body.gpu_start, body.gpu_count,
                    str(int(body.expires_hours * 3600)),
                ),
            )
        else:
            conn.execute(
                "INSERT INTO fleet_reservations "
                "(id, node_id, campaign_id, conversation_id, gpu_start, gpu_count) "
                "VALUES (?,?,?,?,?,?)",
                (
                    rid, body.node_id, body.campaign_id, body.conversation_id,
                    body.gpu_start, body.gpu_count,
                ),
            )
    return {"id": rid, "node_id": body.node_id, "gpu_start": body.gpu_start, "gpu_count": body.gpu_count}


class NodeUpsert(BaseModel):
    hostname: str
    ip_address: str | None = None
    ssh_user: str | None = None
    gpu_platform: str | None = None
    gpu_count: int | None = None
    hbm_per_gpu_gb: float | None = None
    status: str | None = None


@router.post("/nodes/upsert", status_code=200)
def api_upsert_node(body: NodeUpsert):
    """Insert or update a node by hostname OR ip_address (prevents duplicates).

    Only updates fields that are explicitly provided (non-None).
    This prevents saveConfig() from wiping GPU data with zeros.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM fleet_nodes WHERE hostname = ?", (body.hostname,)
    ).fetchone()
    if not row and body.ip_address:
        row = conn.execute(
            "SELECT id FROM fleet_nodes WHERE ip_address = ?", (body.ip_address,)
        ).fetchone()
    if row:
        nid = dict(row)["id"]
        # Build dynamic UPDATE — only set fields that were provided
        updates = {}
        if body.ip_address is not None:
            updates["ip_address"] = body.ip_address
        if body.ssh_user is not None:
            updates["ssh_user"] = body.ssh_user
        if body.gpu_platform is not None:
            updates["gpu_platform"] = body.gpu_platform
        if body.gpu_count is not None:
            # Sanity check: real GPU counts are 1-64. Reject obviously wrong values.
            if 1 <= body.gpu_count <= 64:
                updates["gpu_count"] = body.gpu_count
            else:
                log.warning("Rejected suspicious gpu_count=%d for node %s", body.gpu_count, body.hostname)
        if body.hbm_per_gpu_gb is not None:
            updates["hbm_per_gpu_gb"] = body.hbm_per_gpu_gb
        if body.status is not None:
            updates["status"] = body.status
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            params = list(updates.values()) + [nid]
            with conn:
                conn.execute(
                    f"UPDATE fleet_nodes SET {set_clause}, last_probed=datetime('now') WHERE id=?",
                    params,
                )
    else:
        nid = _short_id()
        with conn:
            conn.execute(
                "INSERT INTO fleet_nodes "
                "(id, hostname, ip_address, ssh_user, gpu_platform, gpu_count, "
                "hbm_per_gpu_gb, status) VALUES (?,?,?,?,?,?,?,?)",
                (nid, body.hostname, body.ip_address, body.ssh_user,
                 body.gpu_platform,
                 body.gpu_count if (body.gpu_count and 1 <= body.gpu_count <= 64) else 0,
                 body.hbm_per_gpu_gb or 0,
                 body.status or "unknown"),
            )
    return {"id": nid, "hostname": body.hostname, "status": body.status or "unknown"}


@router.delete("/nodes/{node_id}", status_code=204)
def api_delete_node(node_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM fleet_nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Node {node_id} not found")
    with conn:
        conn.execute("DELETE FROM fleet_nodes WHERE id = ?", (node_id,))
    return Response(status_code=204)


@router.delete("/reservations/{reservation_id}", status_code=204)
def api_release_reservation(reservation_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM fleet_reservations WHERE id = ?", (reservation_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Reservation {reservation_id} not found")
    with conn:
        conn.execute(
            "UPDATE fleet_reservations SET released_at = datetime('now') WHERE id = ?",
            (reservation_id,),
        )


# ---------------------------------------------------------------------------
# Live GPU telemetry via SSH (amd-smi)
# ---------------------------------------------------------------------------

async def _ssh_gpu_telemetry(ip: str, user: str, key_path: str | None) -> dict:
    """SSH to a node and run amd-smi to get live GPU util/temp/power."""
    key_arg = f"-i {key_path}" if key_path else "-i ~/.ssh/id_ed25519_moba"
    cmd = (
        f"ssh {key_arg} -o BatchMode=yes -o ConnectTimeout=5 "
        f"-o StrictHostKeyChecking=no {user}@{ip} "
        "'amd-smi metric --json 2>/dev/null || "
        "amd-smi monitor --json 2>/dev/null || "
        "rocm-smi --showuse --showtemp --showpower --json 2>/dev/null'"
    )
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return {"error": "empty response"}
        data = json.loads(raw)
        return _parse_amd_smi(data)
    except asyncio.TimeoutError:
        return {"error": "timeout"}
    except json.JSONDecodeError:
        return {"error": "invalid json"}
    except Exception as e:
        return {"error": str(e)}


def _extract_val(v) -> float:
    """Extract numeric value from amd-smi nested format like {value: 42, unit: 'C'} or plain number."""
    if isinstance(v, dict):
        return float(v.get("value", 0) or 0)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return 0.0
    return 0.0


def _parse_amd_smi(data: dict | list) -> dict:
    """Parse amd-smi JSON into normalised GPU stats.

    Handles multiple amd-smi output formats:
    - Modern: {gpu_data: [{gpu: 0, usage: {gfx_activity: {value: X, unit: '%'}}, ...}]}
    - Legacy: [{GPU use (%): X, Temperature: X, Power: X}]
    - rocm-smi: {card0: {GPU use (%): X, ...}}
    """
    gpus = []

    # Determine the GPU list from various formats
    if isinstance(data, list):
        items = data
    elif "gpu_data" in data:
        items = data["gpu_data"]
    elif "gpus" in data:
        items = data["gpus"]
    else:
        items = [data]

    for i, gpu in enumerate(items):
        util = 0.0
        temp = 0.0
        power = 0.0

        # --- Utilization ---
        if "usage" in gpu:
            u = gpu["usage"]
            if isinstance(u, dict):
                util = _extract_val(u.get("gfx_activity", 0))
        elif "gpu_activity" in gpu:
            util = _extract_val(gpu["gpu_activity"].get("gfx_activity", 0))
        elif "GPU use (%)" in gpu:
            util = _extract_val(gpu["GPU use (%)"])

        # --- Temperature ---
        if "temperature" in gpu:
            t = gpu["temperature"]
            if isinstance(t, dict):
                # Prefer hotspot > junction > edge > mem
                for key in ("hotspot", "junction", "edge", "mem"):
                    val = t.get(key)
                    if val and val != "N/A":
                        temp = _extract_val(val)
                        break
            else:
                temp = _extract_val(t)
        elif "Temperature (Sensor edge) (C)" in gpu:
            temp = _extract_val(gpu["Temperature (Sensor edge) (C)"])

        # --- Power ---
        if "power" in gpu:
            p = gpu["power"]
            if isinstance(p, dict):
                for key in ("socket_power", "average_socket_power", "current_socket_power"):
                    val = p.get(key)
                    if val and val != "N/A":
                        power = _extract_val(val)
                        break
            else:
                power = _extract_val(p)
        elif "Average Graphics Package Power (W)" in gpu:
            power = _extract_val(gpu["Average Graphics Package Power (W)"])

        gpus.append({
            "gpu_id": i,
            "utilization": round(util),
            "temperature": round(temp),
            "power": round(power),
        })

    avg_util = round(sum(g["utilization"] for g in gpus) / max(len(gpus), 1))
    avg_temp = round(sum(g["temperature"] for g in gpus) / max(len(gpus), 1))
    total_power = round(sum(g["power"] for g in gpus))
    return {"gpus": gpus, "avg_util": avg_util, "avg_temp": avg_temp, "total_power": total_power}


@router.get("/nodes/telemetry")
async def api_live_telemetry():
    """Poll all fleet nodes via SSH for live GPU util/temp/power."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, hostname, ip_address, ssh_user, ssh_key_path, status "
        "FROM fleet_nodes ORDER BY hostname"
    ).fetchall()

    tasks = []
    node_info = []
    for r in rows:
        r = dict(r)
        ip = r.get("ip_address") or r.get("hostname")
        user = r.get("ssh_user") or "rghaffar"
        key = r.get("ssh_key_path")
        if not ip:
            continue
        node_info.append({"id": r["id"], "hostname": r["hostname"], "ip": ip})
        tasks.append(_ssh_gpu_telemetry(ip, user, key))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    telemetry = []
    for info, result in zip(node_info, results):
        if isinstance(result, Exception):
            telemetry.append({**info, "error": str(result), "gpus": []})
        elif isinstance(result, dict) and "error" in result:
            telemetry.append({**info, **result, "gpus": result.get("gpus", [])})
        else:
            telemetry.append({**info, **result})

    return {"nodes": telemetry}
