#!/usr/bin/env python3
"""Background sync: reads Hyperloom cluster state every 60s and updates InferForge DB.
Run once in a terminal alongside the server — no restart or page refresh needed.
  python3 sync_hyperloom.py
"""
import sqlite3
import subprocess
import json
import time
import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "inferforge/inferforge.db")
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519_moba")
SSH_USER = "rghaffar"
POLL_INTERVAL = 45  # seconds


def ssh_run(host, cmd, timeout=15):
    result = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
         f"{SSH_USER}@{host}", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def get_running_sessions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, host, session_dir FROM hyperloom_sessions WHERE status = 'running'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_session_dir(host, hint_dir=None):
    """Find the most recent Hyperloom session directory on the cluster."""
    if hint_dir:
        check = ssh_run(host, f"test -f '{hint_dir}/state.json' && echo YES")
        if check == "YES":
            return hint_dir

    out = ssh_run(host,
        "ls -dt ~/hl-data/*/20*/ 2>/dev/null | head -1")
    return out.strip() if out else None


def read_cluster_state(host, session_dir):
    """Read coordinator.db from cluster to get current phase and task states.
    Uses coordinator.db instead of state.json (which is root-owned inside Docker).
    """
    db_path = session_dir.rstrip('/') + '/storage/coordinator.db'
    cmd = f"""python3 -c "
import sqlite3, json, sys
try:
    db = sqlite3.connect('{db_path}')
    db.row_factory = sqlite3.Row
    tasks = [dict(r) for r in db.execute('SELECT task_id, kind, state, created_at, updated_at FROM tasks ORDER BY created_at').fetchall()]
    # Get phase history from events
    phase_evts = [dict(r) for r in db.execute(
        \\\"SELECT payload, ts FROM events WHERE topic='event' OR payload LIKE '%phase_entered%' OR payload LIKE '%prelude_done%' OR payload LIKE '%sweep_done%' ORDER BY seq\\\").fetchall()]
    # Get any final stop from events
    stops = [dict(r) for r in db.execute(
        \\\"SELECT payload FROM events WHERE payload LIKE '%stop_reason%' ORDER BY seq DESC LIMIT 5\\\").fetchall()]
    print(json.dumps({{'tasks': tasks, 'phase_events': phase_evts, 'stops': stops}}))
except Exception as e:
    print('ERROR:' + str(e), file=sys.stderr)
    sys.exit(1)
" 2>/dev/null"""
    out = ssh_run(host, cmd)
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def infer_phase_from_tasks(tasks):
    """Determine current phase and approximate timestamps from coordinator.db tasks."""
    all_phases = ['PRELUDE', 'ENABLEMENT', 'FRAMEWORK_AGENT', 'KERNEL_AGENT', 'SWEEP', 'CLOSE']

    # Task kind → phase mapping
    kind_to_phase = {
        'baseline': 'PRELUDE',
        'target_analysis': 'PRELUDE',
        'integrate_patch': 'ENABLEMENT',
        'specialist': None,  # can be any phase
        'explore': 'FRAMEWORK_AGENT',
        'replay_warm_recipe': 'PRELUDE',
    }

    # Build phase timeline from task timestamps
    phase_times = {}

    baseline_done = any(t['kind'] == 'baseline' and t['state'] == 'succeeded' for t in tasks)
    has_integrate = any(t['kind'] == 'integrate_patch' for t in tasks)
    has_explore = any(t['kind'] == 'explore' for t in tasks)

    # Find baseline timing — PRELUDE starts at first task, ends when baseline succeeds
    prelude_start = 0
    prelude_end = 0
    for t in tasks:
        ts = _parse_ts(t.get('created_at', ''))
        if prelude_start == 0 or ts < prelude_start:
            prelude_start = ts
        if t['kind'] == 'baseline' and t['state'] == 'succeeded':
            prelude_end = _parse_ts(t.get('updated_at', ''))
    if prelude_start:
        phase_times['PRELUDE'] = {'start': prelude_start, 'end': prelude_end if baseline_done else 0}

    # ENABLEMENT starts exactly when PRELUDE ends (no gap) — first specialist after baseline
    if baseline_done and prelude_end:
        enablement_start = prelude_end  # continuous — no gap
        phase_times['ENABLEMENT'] = {'start': enablement_start, 'end': 0}

    # FRAMEWORK_AGENT starts when explore appears
    for t in tasks:
        if t['kind'] == 'explore':
            ts = _parse_ts(t.get('created_at', ''))
            if 'FRAMEWORK_AGENT' not in phase_times:
                phase_times['FRAMEWORK_AGENT'] = {'start': ts, 'end': 0}

    # Determine current phase
    has_running = {t['kind'] for t in tasks if t['state'] == 'running'}
    has_queued = {t['kind'] for t in tasks if t['state'] == 'queued'}

    if has_explore or 'explore' in has_running or 'explore' in has_queued:
        # Close ENABLEMENT end time if we moved to framework
        if 'ENABLEMENT' in phase_times and phase_times['ENABLEMENT']['end'] == 0:
            fa_start = phase_times.get('FRAMEWORK_AGENT', {}).get('start', 0)
            phase_times['ENABLEMENT']['end'] = fa_start
        current = 'FRAMEWORK_AGENT'
    elif has_integrate or 'integrate_patch' in has_running or 'integrate_patch' in has_queued:
        current = 'ENABLEMENT'
    elif baseline_done:
        current = 'ENABLEMENT'
    else:
        current = 'PRELUDE'

    # Check if all tasks done (session may be complete)
    all_done = all(t['state'] in ('succeeded', 'failed', 'cancelled') for t in tasks)
    session_done = all_done and len(tasks) > 3

    now = int(time.time())
    timeline = []
    for name in all_phases:
        times = phase_times.get(name, {})
        start = times.get('start', 0)
        end = times.get('end', 0)

        if start == 0:
            status = 'pending'
        elif name == current and not session_done:
            status = 'running'
            end = 0
        elif end > 0 or session_done:
            status = 'complete'
        else:
            status = 'running'

        timeline.append({
            'name': name,
            'start_time': start,
            'end_time': end,
            'duration': (end - start) if end > start else 0,
            'status': status,
        })

    return timeline, current, session_done


def _parse_ts(ts_str):
    """Parse 'HH:MM:SS' or ISO timestamp to unix int."""
    if not ts_str:
        return 0
    try:
        # Format: '08:01:28' (time only from coordinator.db)
        if len(ts_str) == 8 and ts_str[2] == ':':
            today = datetime.date.today()
            dt = datetime.datetime.strptime(f"{today} {ts_str}", "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp())
        # ISO format
        dt = datetime.datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return int(dt.timestamp())
    except Exception:
        return 0


def patch_session(session_id, timeline, status, gain_pct=None):
    conn = sqlite3.connect(DB_PATH)
    tl_json = json.dumps(timeline)
    if gain_pct:
        conn.execute(
            "UPDATE hyperloom_sessions SET status=?, timeline_json=?, outcome_gain_pct=? WHERE id=?",
            (status, tl_json, gain_pct, session_id)
        )
    else:
        conn.execute(
            "UPDATE hyperloom_sessions SET status=?, timeline_json=? WHERE id=?",
            (status, tl_json, session_id)
        )
    conn.commit()
    conn.close()


def sync_once():
    sessions = get_running_sessions()
    if not sessions:
        return

    for s in sessions:
        sid = s['id']
        host = s.get('host', '')
        if not host:
            continue

        session_dir = find_session_dir(host, s.get('session_dir'))
        if not session_dir:
            continue

        raw = read_cluster_state(host, session_dir)
        if not raw:
            continue

        tasks = raw.get('tasks', [])
        if not tasks:
            continue

        timeline, current_phase, session_done = infer_phase_from_tasks(tasks)

        if session_done:
            # Try to read gain from journal
            gain_cmd = f"python3 -c \"import json; d=json.load(open('{session_dir}/reports/optimization_journal.json')); print(d.get('total_gain_pct',0))\" 2>/dev/null"
            gain_out = ssh_run(host, gain_cmd)
            gain = float(gain_out) if gain_out else 0
            db_status = 'completed' if gain > 0 else 'stopped'
        else:
            gain = 0
            db_status = 'running'

        patch_session(sid, timeline, db_status, gain if gain > 0 else None)

        now = datetime.datetime.now().strftime('%H:%M:%S')
        print(f"[{now}] {sid[:12]} → {current_phase} | status={db_status} | tasks={len(tasks)}")


def main():
    print(f"Hyperloom sync started — polling every {POLL_INTERVAL}s")
    print(f"DB: {DB_PATH}")
    print("Press Ctrl+C to stop\n")
    while True:
        try:
            sync_once()
        except Exception as e:
            print(f"[sync error] {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
