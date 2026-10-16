"""Async monitor for running Hyperloom sessions.

Watches a session directory for new log lines, status file changes,
and measurement artifacts. Yields structured events suitable for
WebSocket streaming to the frontend.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# How often to poll for new content (seconds)
_POLL_INTERVAL = 1.0

# Maximum lines to buffer on initial catch-up
_MAX_CATCHUP_LINES = 500

# Log line patterns
_RE_PHASE = re.compile(
    r"\[(?P<phase>BASELINE|KERNEL|FRAMEWORK|EVAL|DONE|ERROR)\]",
    re.IGNORECASE,
)
_RE_ROUND = re.compile(
    r"round\s+(?P<num>\d+)",
    re.IGNORECASE,
)
_RE_METRIC = re.compile(
    r"(?:throughput|tps)[:\s]+(?P<tps>[\d.]+)"
    r"|(?:ttft)[:\s]+(?P<ttft>[\d.]+)"
    r"|(?:gain)[:\s]+(?P<gain>[+-]?[\d.]+)%",
    re.IGNORECASE,
)


async def monitor_session(
    session_dir: str,
    poll_interval: float = _POLL_INTERVAL,
    max_catchup: int = _MAX_CATCHUP_LINES,
) -> AsyncGenerator[dict, None]:
    """Tail session logs and yield structured events.

    Watches the session directory for:
    - ``session.log`` -- main log file, tailed line by line
    - ``status.json`` -- session status updates
    - ``session_breakdown.json`` -- final results (triggers completion event)
    - Round measurement files (``round_*.json``)

    Yields dicts with ``type`` and ``data`` keys.

    Parameters
    ----------
    session_dir:
        Path to the Hyperloom session directory.
    poll_interval:
        Seconds between filesystem checks.
    max_catchup:
        Maximum number of existing log lines to replay on start.
    """
    sdir = Path(session_dir)

    if not sdir.is_dir():
        yield _event("error", {"reason": f"Session directory not found: {session_dir}"})
        return

    yield _event("monitor_start", {
        "session_dir": session_dir,
        "timestamp": _now(),
    })

    # State tracking
    log_offset = 0
    seen_rounds: set[str] = set()
    last_status_mtime = 0.0
    completed = False

    # Initial catch-up: read existing log lines (tail)
    log_path = sdir / "session.log"
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, len(lines) - max_catchup)
        for line in lines[start:]:
            event = _parse_log_line(line)
            if event:
                yield event
        log_offset = log_path.stat().st_size

    # Check for already-existing rounds
    for rnd_file in sorted(sdir.glob("round_*.json")):
        seen_rounds.add(rnd_file.name)

    # Main monitoring loop
    try:
        while not completed:
            await asyncio.sleep(poll_interval)

            # Tail log file
            if log_path.is_file():
                try:
                    current_size = log_path.stat().st_size
                    if current_size > log_offset:
                        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(log_offset)
                            new_text = f.read()
                            log_offset = f.tell()

                        for line in new_text.splitlines():
                            event = _parse_log_line(line)
                            if event:
                                yield event
                    elif current_size < log_offset:
                        # Log was truncated/rotated
                        log_offset = 0
                except OSError as exc:
                    logger.debug("Error reading log: %s", exc)

            # Check status.json for updates
            status_path = sdir / "status.json"
            if status_path.is_file():
                try:
                    mtime = status_path.stat().st_mtime
                    if mtime > last_status_mtime:
                        last_status_mtime = mtime
                        status_data = json.loads(
                            status_path.read_text(encoding="utf-8")
                        )
                        yield _event("status_update", status_data)

                        # Check for terminal status
                        st = status_data.get("status", "").lower()
                        if st in ("completed", "failed", "cancelled", "error"):
                            completed = True
                except (json.JSONDecodeError, OSError) as exc:
                    logger.debug("Error reading status: %s", exc)

            # Check for new round files
            for rnd_file in sorted(sdir.glob("round_*.json")):
                if rnd_file.name not in seen_rounds:
                    seen_rounds.add(rnd_file.name)
                    try:
                        rnd_data = json.loads(
                            rnd_file.read_text(encoding="utf-8")
                        )
                        yield _event("round_complete", {
                            "file": rnd_file.name,
                            "round": rnd_data,
                        })
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.debug("Error reading round file %s: %s", rnd_file, exc)

            # Check for session_breakdown.json (final result)
            breakdown_path = sdir / "session_breakdown.json"
            if breakdown_path.is_file() and not completed:
                try:
                    breakdown = json.loads(
                        breakdown_path.read_text(encoding="utf-8")
                    )
                    yield _event("session_complete", {
                        "breakdown_path": str(breakdown_path),
                        "session_id": breakdown.get("metadata", {}).get("session_id", ""),
                        "outcome": breakdown.get("outcome", {}),
                    })
                    completed = True
                except (json.JSONDecodeError, OSError) as exc:
                    logger.debug("Error reading breakdown: %s", exc)

            # Check if the process is still alive (via PID file)
            pid_file = sdir / ".pid"
            if pid_file.is_file() and not completed:
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)  # Check if alive
                except (ValueError, ProcessLookupError):
                    # Process died without writing breakdown
                    if not completed:
                        yield _event("session_died", {
                            "reason": "Process exited without completion signal",
                        })
                        completed = True
                except PermissionError:
                    pass  # Process alive but we can't signal it

    except asyncio.CancelledError:
        yield _event("monitor_cancelled", {"timestamp": _now()})
        return

    yield _event("monitor_stop", {"timestamp": _now()})


async def wait_for_session_dir(path: str, timeout: float = 60.0) -> bool:
    """Wait for a session directory to appear. Returns True if found."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if Path(path).is_dir():
            return True
        await asyncio.sleep(1.0)
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(event_type: str, data: dict) -> dict:
    """Create a structured monitor event."""
    return {"type": event_type, "data": data, "timestamp": _now()}


def _parse_log_line(line: str) -> dict | None:
    """Parse a log line into a structured event, or None if not interesting."""
    stripped = line.strip()
    if not stripped:
        return None

    # Phase change
    m = _RE_PHASE.search(stripped)
    if m:
        return _event("phase_change", {
            "phase": m.group("phase").upper(),
            "line": stripped,
        })

    # Round indicator
    m = _RE_ROUND.search(stripped)
    if m:
        return _event("round_start", {
            "round_number": int(m.group("num")),
            "line": stripped,
        })

    # Metric values
    metrics: dict = {}
    for m in _RE_METRIC.finditer(stripped):
        if m.group("tps"):
            metrics["throughput_tps"] = float(m.group("tps"))
        if m.group("ttft"):
            metrics["ttft_ms"] = float(m.group("ttft"))
        if m.group("gain"):
            metrics["gain_pct"] = float(m.group("gain"))
    if metrics:
        return _event("measurement", {**metrics, "line": stripped})

    # Error lines
    if any(kw in stripped.lower() for kw in ("error", "traceback", "exception", "abort", "oom")):
        return _event("error_line", {"line": stripped})

    # Regular log line (not emitted to avoid noise)
    return None


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"
