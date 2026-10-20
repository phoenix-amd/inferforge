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


# ---------------------------------------------------------------------------
#  PREFLIGHT HEALTH CHECK
# ---------------------------------------------------------------------------

class PreflightRequest(BaseModel):
    node_ids: list[str] | None = None
    clean_stale: bool = True


async def _ssh_preflight_check(
    ip: str, user: str, key_path: str | None, clean_stale: bool,
) -> dict:
    """SSH to a node and collect health data + optionally kill stale jobs."""
    key_arg = f"-i {key_path}" if key_path else "-i ~/.ssh/id_ed25519_moba"

    clean_block = (
        # Kill hyperloom container
        "docker stop hyperloom-optimize 2>/dev/null; "
        "docker rm -f hyperloom-optimize 2>/dev/null; "
        # Kill any vLLM/SGLang/ray containers holding GPU memory
        "docker ps -q --filter name=vllm --filter name=sglang --filter name=inferforge "
        "2>/dev/null | xargs -r docker stop 2>/dev/null; "
        # Kill stray host processes (not in Docker)
        "pkill -f 'hyperloom optimize' 2>/dev/null; "
        "pkill -f 'vllm.entrypoints' 2>/dev/null; "
        # Remove lock files
        "find /hl-data -name 'optimizer.lock' -delete 2>/dev/null; "
        # Wait a moment for GPU memory to be released
        "sleep 2; "
        "echo CLEANED"
    ) if clean_stale else "echo SKIPPED"

    remote_cmd = (
        "echo '---PING---'; echo PONG; "
        "echo '---RAM---'; free -g 2>/dev/null | awk '/^Mem:/{print $2,$4,$7}'; "
        # GPU count — try multiple methods for reliability
        "echo '---GPU---'; "
        "(amd-smi list 2>/dev/null | grep -c '^GPU:') || "
        "(rocm-smi --showproductname 2>/dev/null | grep -c 'GPU\\[') || "
        "(ls /dev/dri/card* 2>/dev/null | wc -l) || echo 0; "
        # GPU HBM usage (used/total per GPU in GB)
        "echo '---HBM---'; amd-smi metric --vram 2>/dev/null | "
        "awk '/VRAM Usage/{u=$3} /VRAM Total/{t=$3; printf \"%s/%s\\n\",u,t}' | head -8; "
        "echo '---STALE---'; "
        "docker ps -a --filter name=hyperloom --filter name=vllm --filter name=sglang "
        "--format '{{.Names}} {{.Status}}' 2>/dev/null; "
        f"echo '---CLEAN---'; {clean_block}; "
        "echo '---DONE---'"
    )

    cmd = (
        f"ssh {key_arg} -o BatchMode=yes -o ConnectTimeout=5 "
        f"-o StrictHostKeyChecking=no {user}@{ip} '{remote_cmd}'"
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        out = stdout_b.decode(errors="replace")
    except asyncio.TimeoutError:
        return {"is_reachable": False, "error": "timeout"}
    except Exception as e:
        return {"is_reachable": False, "error": str(e)}

    if "PONG" not in out:
        return {"is_reachable": False, "error": "ssh_failed"}

    result: dict = {"is_reachable": True, "error": None}

    # Parse RAM
    try:
        ram_line = out.split("---RAM---")[1].split("---GPU---")[0].strip()
        parts = ram_line.split()
        if len(parts) >= 3:
            result["total_ram_gb"] = int(parts[0])
            result["free_ram_gb"] = int(parts[1])
            result["available_ram_gb"] = int(parts[2])
        elif len(parts) >= 2:
            result["total_ram_gb"] = int(parts[0])
            result["free_ram_gb"] = int(parts[1])
            result["available_ram_gb"] = int(parts[1])
    except Exception:
        result["total_ram_gb"] = 0
        result["free_ram_gb"] = 0
        result["available_ram_gb"] = 0

    # Parse GPU count
    try:
        gpu_str = out.split("---GPU---")[1].split("---STALE---")[0].strip()
        result["gpu_count"] = int(gpu_str) if gpu_str.isdigit() else 0
    except Exception:
        result["gpu_count"] = 0

    # Parse stale containers
    try:
        stale_str = out.split("---STALE---")[1].split("---CLEAN---")[0].strip()
        result["stale_containers"] = [s for s in stale_str.splitlines() if s.strip()]
    except Exception:
        result["stale_containers"] = []

    # Parse cleanup
    result["cleaned"] = "CLEANED" in out.split("---CLEAN---")[-1] if "---CLEAN---" in out else False
    result["stale_containers_killed"] = len(result["stale_containers"]) if result["cleaned"] else 0

    return result


@router.post("/preflight")
async def api_preflight(body: PreflightRequest = PreflightRequest()):
    """Check fleet node health, kill stale jobs, return best node for next run."""
    import time
    t0 = time.monotonic()
    conn = get_connection()

    if body.node_ids:
        placeholders = ",".join("?" for _ in body.node_ids)
        rows = conn.execute(
            f"SELECT * FROM fleet_nodes WHERE id IN ({placeholders})",
            body.node_ids,
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM fleet_nodes ORDER BY hostname").fetchall()

    if not rows:
        return {"nodes": [], "best_node": None, "unreachable": [], "checked_at": None}

    tasks = []
    node_info = []
    for r in rows:
        r = dict(r)
        ip = r.get("ip_address")
        if not ip:
            continue
        user = r.get("ssh_user") or "rghaffar"
        key = r.get("ssh_key_path") or "~/.ssh/id_ed25519_moba"
        node_info.append({"id": r["id"], "hostname": r["hostname"], "ip": ip})
        tasks.append(_ssh_preflight_check(ip, user, key, body.clean_stale))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    nodes_out = []
    unreachable = []
    now_iso = __import__("datetime").datetime.utcnow().isoformat() + "Z"

    for info, result in zip(node_info, results):
        if isinstance(result, Exception):
            result = {"is_reachable": False, "error": str(result)}

        reachable = result.get("is_reachable", False)
        # Only mark degraded if genuinely unreachable GPU probe AND no existing gpu_count in DB
        db_gpu_count = conn.execute(
            "SELECT gpu_count FROM fleet_nodes WHERE id = ?", (info["id"],)
        ).fetchone()
        known_gpu_count = (db_gpu_count[0] or 0) if db_gpu_count else 0
        probed_gpu_count = result.get("gpu_count", 0)
        effective_gpu_count = probed_gpu_count or known_gpu_count  # trust DB if probe fails
        status = "healthy" if reachable else "unreachable"
        if reachable and effective_gpu_count == 0:
            status = "degraded"  # truly no GPUs found by any method

        # Update DB
        with conn:
            conn.execute(
                "UPDATE fleet_nodes SET status=?, last_probed=?, metadata_json=? WHERE id=?",
                (status, now_iso, json.dumps(result), info["id"]),
            )

        entry = {
            **info,
            "status": status,
            "free_ram_gb": result.get("free_ram_gb", 0),
            "total_ram_gb": result.get("total_ram_gb", 0),
            "available_ram_gb": result.get("available_ram_gb", 0),
            "gpu_count": result.get("gpu_count", 0),
            "stale_containers_killed": result.get("stale_containers_killed", 0),
            "cleaned": result.get("cleaned", False),
            "error": result.get("error"),
        }
        nodes_out.append(entry)
        if not reachable:
            unreachable.append(info["hostname"])

    # Rank healthy nodes: most free RAM first, then GPU count
    healthy = [n for n in nodes_out if n["status"] in ("healthy", "degraded") and n.get("free_ram_gb", 0) > 0]
    healthy.sort(key=lambda n: (n.get("free_ram_gb", 0), n.get("gpu_count", 0)), reverse=True)

    best = None
    if healthy:
        best = {"id": healthy[0]["id"], "hostname": healthy[0]["hostname"], "ip": healthy[0]["ip"]}

    return {
        "nodes": nodes_out,
        "best_node": best,
        "unreachable": unreachable,
        "checked_at": now_iso,
        "elapsed_seconds": round(time.monotonic() - t0, 2),
    }


@router.post("/nodes/{node_id}/recover")
async def api_recover_node(node_id: str):
    """Kill all GPU-holding processes on a node to free HBM and make it ready for next run.

    This is more aggressive than preflight clean_stale — it kills ALL Docker containers
    (not just hyperloom-optimize), all vLLM/ray processes, and removes lock files.
    Use this when a node is stuck with full HBM from a crashed or zombie job.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM fleet_nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Node {node_id} not found")

    r = dict(row)
    ip = r.get("ip_address")
    if not ip:
        raise HTTPException(400, "Node has no IP address configured")

    user = r.get("ssh_user") or "rghaffar"
    key_path = r.get("ssh_key_path") or "~/.ssh/id_ed25519_moba"
    key_arg = f"-i {key_path}"

    # Aggressive recovery: kill all GPU-holding containers and processes
    recover_cmd = (
        # Stop all running containers (not just hyperloom)
        "docker ps -q 2>/dev/null | xargs -r docker stop 2>/dev/null; "
        # Force remove any zombie containers
        "docker ps -aq 2>/dev/null | xargs -r docker rm -f 2>/dev/null; "
        # Kill vLLM, SGLang, ray processes running on host
        "pkill -9 -f 'vllm.entrypoints' 2>/dev/null; "
        "pkill -9 -f 'sglang' 2>/dev/null; "
        "pkill -9 -f 'hyperloom' 2>/dev/null; "
        "pkill -9 -f 'ray::' 2>/dev/null; "
        "ray stop --force 2>/dev/null; "
        # Remove lock files
        "find /hl-data -name 'optimizer.lock' -delete 2>/dev/null; "
        # Wait for GPU memory release
        "sleep 3; "
        # Report free RAM and GPU status after recovery
        "free -g | awk '/^Mem:/{print \"RAM free:\",$4,\"GB\"}'; "
        "amd-smi list 2>/dev/null | grep -c '^GPU:' | awk '{print \"GPUs:\",$1}'; "
        "echo RECOVERED"
    )

    ssh_cmd = (
        f"ssh {key_arg} -o BatchMode=yes -o ConnectTimeout=10 "
        f"-o StrictHostKeyChecking=no {user}@{ip} '{recover_cmd}'"
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            ssh_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=40)
        out = stdout_b.decode(errors="replace")
        success = "RECOVERED" in out
    except asyncio.TimeoutError:
        raise HTTPException(504, "Recovery timed out after 40s")
    except Exception as e:
        raise HTTPException(500, f"SSH failed: {e}")

    # Update node status in DB
    now_iso = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    with conn:
        conn.execute(
            "UPDATE fleet_nodes SET status='online', last_probed=? WHERE id=?",
            (now_iso, node_id),
        )

    return {
        "node_id": node_id,
        "hostname": r.get("hostname"),
        "ip": ip,
        "recovered": success,
        "output": out.strip(),
    }


@router.get("/nodes/ping")
async def api_ping_nodes():
    """Quick SSH reachability check for all fleet nodes with running Hyperloom sessions.
    Called by the frontend every 2 minutes when a job is running.
    Returns within 8 seconds (ConnectTimeout=6).
    """
    conn = get_connection()
    # Get unique hosts from running Hyperloom sessions
    running_hosts = conn.execute(
        "SELECT DISTINCT host FROM hyperloom_sessions WHERE status='running' AND host IS NOT NULL"
    ).fetchall()
    host_set = {dict(r)["host"] for r in running_hosts if dict(r).get("host")}

    # Also ping all fleet nodes
    fleet_rows = conn.execute("SELECT * FROM fleet_nodes").fetchall()

    results = []
    tasks = []
    node_info = []

    for r in fleet_rows:
        r = dict(r)
        ip = r.get("ip_address")
        if not ip:
            continue
        user = r.get("ssh_user") or "rghaffar"
        key_path = r.get("ssh_key_path") or "~/.ssh/id_ed25519_moba"
        key_arg = f"-i {key_path}"
        node_info.append({"ip": ip, "hostname": r.get("hostname", ip), "has_running_job": ip in host_set})

        async def _ping(ip=ip, user=user, key_arg=key_arg):
            cmd = (
                f"ssh {key_arg} -o BatchMode=yes -o ConnectTimeout=6 "
                f"-o StrictHostKeyChecking=no {user}@{ip} 'echo PONG' 2>/dev/null"
            )
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
                return "PONG" in stdout_b.decode(errors="replace")
            except Exception:
                return False

        tasks.append(_ping())

    pong_results = await asyncio.gather(*tasks, return_exceptions=True)

    for info, reachable in zip(node_info, pong_results):
        if isinstance(reachable, Exception):
            reachable = False
        results.append({
            "ip": info["ip"],
            "hostname": info["hostname"],
            "reachable": bool(reachable),
            "has_running_job": info["has_running_job"],
        })

    unreachable_with_job = [n for n in results if n["has_running_job"] and not n["reachable"]]

    return {
        "nodes": results,
        "any_unreachable_with_job": len(unreachable_with_job) > 0,
        "unreachable_job_nodes": [n["ip"] for n in unreachable_with_job],
    }
