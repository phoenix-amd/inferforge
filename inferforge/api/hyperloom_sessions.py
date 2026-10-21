"""HyperLoom session routes -- import, view, and manage optimization sessions."""

import datetime
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
        # Supersede any existing running sessions to prevent ghost sessions
        conn.execute(
            "UPDATE hyperloom_sessions SET status='stopped', stop_reason='superseded_by_new_run', "
            "ended_at=? WHERE status='running'",
            (now,),
        )
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
    model_name: str | None = None
    model_path: str | None = None
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
    if body.model_name is not None:
        updates["model_name"] = body.model_name
    if body.model_path is not None:
        updates["model_path"] = body.model_path
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


@router.post("/sessions/{session_id}/probe-phase")
def api_probe_phase(session_id: str):
    """SSH to the cluster, read Hyperloom state.json, and update the DB timeline.

    Called by the frontend every ~2.5 min for running sessions. Fails silently
    if SSH is down — the timeline just stays at its last known state.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT host, session_dir, status, started_at FROM hyperloom_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Session {session_id} not found")
    d = dict(row)
    if d.get("status") != "running":
        return {"status": "skipped", "reason": "not_running"}

    # Parse session start time so we can detect stale state.json from previous sessions
    session_started_ts = 0
    try:
        sa = d.get("started_at", "")
        if sa:
            dt = datetime.datetime.fromisoformat(sa.replace("Z", "+00:00"))
            session_started_ts = int(dt.timestamp())
    except Exception:
        pass

    host = d.get("host")
    session_dir = d.get("session_dir")
    if not host:
        return {"status": "skipped", "reason": "no_host"}

    # Find session_dir from state — scan hl-data for latest session dir if not stored
    ssh_key = "~/.ssh/id_ed25519_moba"
    ssh_prefix = (
        f"ssh -i {ssh_key} -o BatchMode=yes -o ConnectTimeout=10 "
        f"-o StrictHostKeyChecking=no rghaffar@{host}"
    )

    # Python snippet that extracts the fields we need from state.json.
    # Used by both docker exec (inside container) and host-side fallbacks.
    _extract_py = (
        "import json,glob,os,sys; "
        "dirs=sorted(glob.glob('{root}/*/2026*'),key=os.path.getmtime); "
        "sd=dirs[-1] if dirs else ''; "
        "s=json.load(open(sd+'/state.json')) if sd and os.path.exists(sd+'/state.json') else {{}}; "
        "print(json.dumps({{"
        "'phase':s.get('phase'),"
        "'tick':s.get('tick'),"
        "'baseline_tput':s.get('baseline_tput',0),"
        "'cumulative_gain':s.get('cumulative_gain_validated',0),"
        "'current_best_tput':s.get('current_best',{{}}).get('tput',0),"
        "'elapsed_sec':int(s.get('elapsed_charged_sec',0)),"
        "'stop_reason':s.get('stop_reason',''),"
        "'phase_history':[(x['to_phase'],x.get('ts_unix',0)) for x in s.get('phase_history',[])],"
        "'session_dir':sd}}))"
    )

    state = None
    probe_method = None

    # ── Method 1: docker exec (container running) ────────────────────────
    try:
        cmd = f'{ssh_prefix} "docker exec hyperloom-optimize python3 -c \\"{_extract_py.format(root="/hl-data")}\\" 2>/dev/null"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            state = json.loads(result.stdout.strip())
            probe_method = "docker_exec"
    except Exception:
        pass

    # ── Method 2: docker cp to temp file, parse via base64-encoded script ──
    # docker cp to /dev/stdout doesn't work, but to a temp file works on
    # stopped containers.  We base64-encode the parse script to avoid all
    # shell quoting issues when piping through SSH.
    import base64
    _parse_py = (
        'import json\n'
        's=json.load(open("/tmp/_hlprobe.json"))\n'
        'cb=s.get("current_best",{})\n'
        'r={"phase":s.get("phase"),"tick":s.get("tick"),'
        '"baseline_tput":s.get("baseline_tput",0),'
        '"cumulative_gain":s.get("cumulative_gain_validated",0),'
        '"current_best_tput":cb.get("tput",0),'
        '"elapsed_sec":int(s.get("elapsed_charged_sec",0)),'
        '"stop_reason":s.get("stop_reason",""),'
        '"phase_history":[(x["to_phase"],x.get("ts_unix",0)) for x in s.get("phase_history",[])],'
        '"best_extra_server_args":cb.get("extra_server_args",""),'
        '"best_ttft_p50":cb.get("ttft_p50_ms") or cb.get("ttft_mean_ms"),'
        '"best_tpot_p50":cb.get("tpot_p50_ms") or cb.get("tpot_mean_ms"),'
        '"best_tpot_p90":cb.get("tpot_p90_ms"),'
        '"best_e2el":cb.get("e2el_mean_ms"),'
        '"best_power":cb.get("gpu_power_avg_w"),'
        '"session_dir_internal":s.get("session_dir","")}\n'
        'print(json.dumps(r))\n'
    )
    _b64_script = base64.b64encode(_parse_py.encode()).decode()

    # Separate script to parse baseline inferencex_result.json
    _parse_baseline_py = (
        'import json\n'
        'd=json.load(open("/tmp/_hlbaseline.json"))\n'
        'print(json.dumps({"bl_tput":d.get("output_throughput",0),'
        '"bl_ttft_p50":d.get("median_ttft_ms"),'
        '"bl_ttft_p99":d.get("p99_ttft_ms"),'
        '"bl_tpot_p50":d.get("median_tpot_ms"),'
        '"bl_tpot_p99":d.get("p99_tpot_ms"),'
        '"bl_e2el_p50":d.get("median_e2el_ms"),'
        '"bl_itl_p50":d.get("median_itl_ms")}))\n'
    )
    _b64_baseline = base64.b64encode(_parse_baseline_py.encode()).decode()

    def _docker_cp_probe(container_path: str) -> dict | None:
        """Copy state.json from container to temp file, parse with b64 script."""
        try:
            cmd = (
                f'{ssh_prefix} "docker cp hyperloom-optimize:{container_path} /tmp/_hlprobe.json 2>/dev/null'
                f" && echo '{_b64_script}' | base64 -d | python3"
                f' ; rm -f /tmp/_hlprobe.json"'
            )
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout.strip())
        except Exception:
            pass
        return None

    if state is None:
        # 2a: Use the known session_dir from the DB
        if session_dir:
            sd_rel = session_dir.split("/hl-data/")[-1] if "/hl-data/" in session_dir else session_dir.lstrip("/")
            parsed = _docker_cp_probe(f"/hl-data/{sd_rel}/state.json")
            if parsed:
                state = parsed
                probe_method = "docker_cp_known_dir"

        # 2b: Scan container for the latest state.json
        if state is None:
            try:
                scan_cmd = (
                    f'{ssh_prefix} "docker cp hyperloom-optimize:/hl-data - 2>/dev/null '
                    f'| tar -tf - 2>/dev/null | grep state.json | sort | tail -1"'
                )
                scan = subprocess.run(scan_cmd, shell=True, capture_output=True, text=True, timeout=25)
                if scan.returncode == 0 and scan.stdout.strip():
                    latest = scan.stdout.strip()
                    cpath = "/" + latest if not latest.startswith("/") else latest
                    parsed = _docker_cp_probe(cpath)
                    if parsed:
                        state = parsed
                        probe_method = "docker_cp_scan"
            except Exception:
                pass

    # ── Method 3: host filesystem (state.json may be world-readable) ─────
    if state is None:
        try:
            cmd = f'{ssh_prefix} "python3 -c \\"{_extract_py.format(root="/home/rghaffari/hl-data")}\\" 2>/dev/null"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                parsed = json.loads(result.stdout.strip())
                # Only accept if it has real phase data (not empty {})
                if parsed.get("phase") or parsed.get("phase_history"):
                    state = parsed
                    probe_method = "host_filesystem"
        except Exception:
            pass

    # (Method 4 removed — tar stream unreliable with large /hl-data on Python 3.9)

    if state is None:
        return {"status": "ssh_failed", "error": "all 3 probe methods failed (docker_exec, docker_cp, host_fs)"}

    # ── Stale state.json guard ──────────────────────────────────────────────
    # During the first ~4 min after launch, hyperloom is installing packages
    # and hasn't created a new state.json yet.  The glob picks up the PREVIOUS
    # session's state.json (which has stop_reason set), causing the probe to
    # mark the current session as "completed" prematurely.
    #
    # Fix: if the newest phase_history timestamp is BEFORE this session's
    # started_at, the state.json belongs to an old run — skip the update.
    if session_started_ts > 0 and state.get("phase_history"):
        latest_phase_ts = max(
            (ts for _, ts in state["phase_history"] if isinstance(ts, (int, float)) and ts > 0),
            default=0,
        )
        if latest_phase_ts > 0 and latest_phase_ts < session_started_ts - 60:
            return {
                "status": "skipped",
                "reason": "stale_state_json",
                "detail": f"state.json phase_history ({latest_phase_ts}) predates session start ({session_started_ts})",
            }

    # Also skip if state.json is completely empty (install phase, no state yet)
    if not state.get("phase") and not state.get("phase_history"):
        return {"status": "skipped", "reason": "no_phase_data"}

    # Build timeline from phase_history (cluster state.json is authoritative)
    #
    # Hyperloom's phase_history may have:
    #  - Duplicate entries (e.g. PRELUDE appears twice if session restarted)
    #    → use the FIRST occurrence (that's when the phase truly began)
    #  - Skipped phases (e.g. ENABLEMENT missing — Hyperloom jumped over it)
    #    → infer timing from neighbors
    #  - Phase names that don't match our expected 6 phases
    #    → ignore unknown names
    phase_names = ["PRELUDE", "ENABLEMENT", "FRAMEWORK_AGENT", "KERNEL_AGENT", "SWEEP", "CLOSE"]
    phase_times = {}
    for ph, ts_unix in state.get("phase_history", []):
        ts = ts_unix if isinstance(ts_unix, (int, float)) and ts_unix > 0 else 0
        if ts > 0 and ph not in phase_times:
            phase_times[ph] = ts  # keep FIRST occurrence only

    # Build an ordered list of (start_time, phase_name) for phases that exist
    # so we can derive end times and fill gaps for skipped phases.
    ordered = sorted(
        [(t, n) for n, t in phase_times.items() if t > 0 and n in phase_names],
        key=lambda x: x[0],
    )

    # Fill skipped phases: if a phase in our expected list has no entry,
    # give it the same start_time as the next known phase (zero-width but
    # marked complete, so the chart still flows correctly).
    for i, name in enumerate(phase_names):
        if name not in phase_times:
            # Find the next phase that HAS a timestamp
            for j in range(i + 1, len(phase_names)):
                if phase_names[j] in phase_times:
                    phase_times[name] = phase_times[phase_names[j]]
                    break

    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    timeline = []
    for i, name in enumerate(phase_names):
        start = phase_times.get(name, 0)
        # End time = next phase's start time (if it exists)
        next_start = 0
        for j in range(i + 1, len(phase_names)):
            ns = phase_times.get(phase_names[j], 0)
            if ns > 0:
                next_start = ns
                break
        if name == state.get("phase"):
            status = "running"
            end = now_ts  # live clock so frontend gets a real duration
        elif start > 0 and next_start > 0:
            status = "complete"
            end = next_start
        elif start > 0:
            status = "complete"
            end = start  # phase completed but no next phase yet
        else:
            status = "pending"
            end = 0
        duration = (end - start) if end > 0 and start > 0 else 0
        # Mark zero-duration completed phases as "skipped" (Hyperloom bypassed them)
        if status == "complete" and duration == 0 and start > 0:
            status = "skipped"
        timeline.append({"name": name, "start_time": int(start), "end_time": int(end),
                         "duration": int(duration), "status": status})

    # When session completed normally (sweep_done), CLOSE always ran even if
    # phase_history didn't record it. Mark CLOSE as complete and any remaining
    # pending phases (like SWEEP) as skipped.
    if state.get("stop_reason") == "sweep_done":
        for p in timeline:
            if p["name"] == "CLOSE" and p["status"] in ("pending", "skipped", "running"):
                # CLOSE ran — use the last known end time
                last_end = max((t["end_time"] for t in timeline if t["end_time"] > 0), default=now_ts)
                p["status"] = "complete"
                p["start_time"] = last_end
                p["end_time"] = last_end
                p["duration"] = 0
            elif p["status"] == "pending":
                p["status"] = "skipped"

    # Update DB — only use columns that exist in the schema
    updates = {"timeline_json": json.dumps(timeline)}
    if state.get("cumulative_gain", 0) > 0:
        updates["outcome_gain_pct"] = round(state["cumulative_gain"], 2)
    if state.get("session_dir") and not d.get("session_dir"):
        updates["session_dir"] = state["session_dir"]
    if state.get("stop_reason"):
        updates["stop_reason"] = state["stop_reason"]
        updates["status"] = "completed"

        # ── Fetch baseline metrics from inferencex_result.json inside container ──
        # This has per-metric baseline data (TTFT, TPOT, E2E) that state.json lacks.
        bl_metrics = {}
        # Use session_dir from DB (reliable) — state.json may have it empty
        sdir_internal = session_dir or state.get("session_dir_internal", "")
        if sdir_internal:
            try:
                # Find baseline result file path via tar listing
                scan_cmd = (
                    f'{ssh_prefix} "docker cp hyperloom-optimize:/hl-data - 2>/dev/null '
                    f"| tar -tf - 2>/dev/null | grep '{sdir_internal.lstrip('/').split('/hl-data/')[-1]}.*runs/baseline.*measure_round.*inferencex_result' | tail -1\""
                )
                scan = subprocess.run(scan_cmd, shell=True, capture_output=True, text=True, timeout=25)
                if scan.returncode == 0 and scan.stdout.strip():
                    bl_path = "/" + scan.stdout.strip()
                    bl_cmd = (
                        f'{ssh_prefix} "docker cp hyperloom-optimize:{bl_path} /tmp/_hlbaseline.json 2>/dev/null'
                        f" && echo '{_b64_baseline}' | base64 -d | python3"
                        f' ; rm -f /tmp/_hlbaseline.json"'
                    )
                    bl_result = subprocess.run(bl_cmd, shell=True, capture_output=True, text=True, timeout=20)
                    if bl_result.returncode == 0 and bl_result.stdout.strip():
                        bl_metrics = json.loads(bl_result.stdout.strip())
            except Exception:
                pass

        # Build outcome_json with full baseline + optimized breakdown
        baseline_tput = state.get("baseline_tput", 0)
        best_tput = state.get("current_best_tput", 0)
        bl = {"throughput_tps": round(baseline_tput, 1)}
        opt = {"throughput_tps": round(best_tput, 1)}

        # Baseline metrics from inferencex_result.json
        def _r(v):
            return round(v, 1) if v is not None else None
        if bl_metrics.get("bl_ttft_p50") is not None:
            bl["ttft_p50_ms"] = _r(bl_metrics["bl_ttft_p50"])
        if bl_metrics.get("bl_ttft_p99") is not None:
            bl["ttft_p99_ms"] = _r(bl_metrics["bl_ttft_p99"])
        if bl_metrics.get("bl_tpot_p50") is not None:
            bl["tpot_p50_ms"] = _r(bl_metrics["bl_tpot_p50"])
        if bl_metrics.get("bl_e2el_p50") is not None:
            bl["e2e_p50_ms"] = _r(bl_metrics["bl_e2el_p50"])

        # Optimized metrics from state.json current_best
        ttft = state.get("best_ttft_p50")
        if ttft is not None:
            opt["ttft_p50_ms"] = _r(ttft)
        tpot = state.get("best_tpot_p50") or state.get("best_tpot_p90")
        if tpot is not None:
            opt["tpot_p50_ms"] = _r(tpot)
        e2el = state.get("best_e2el")
        if e2el is not None:
            opt["e2e_p50_ms"] = _r(e2el)

        extra_args = state.get("best_extra_server_args", "")
        outcome = {
            "baseline": bl,
            "optimized": opt,
            "winning_flags": extra_args.split() if extra_args else [],
        }
        updates["outcome_json"] = json.dumps(outcome)

    set_clause = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [session_id]
    with conn:
        conn.execute(f"UPDATE hyperloom_sessions SET {set_clause} WHERE id=?", vals)

    return {
        "status": "synced",
        "probe_method": probe_method,
        "phase": state.get("phase"),
        "tick": state.get("tick"),
        "gain": state.get("cumulative_gain"),
        "baseline": state.get("baseline_tput"),
        "best": state.get("current_best_tput"),
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
