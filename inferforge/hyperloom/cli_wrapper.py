"""Async wrapper around `python -m hyperloom optimize` subprocess.

Launches Hyperloom optimization sessions, streams structured events from
stdout/stderr, and provides cancel/resume/status helpers.
"""

import asyncio
import json
import logging
import os
import re
import signal
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------

@dataclass
class SessionEvent:
    """Structured event emitted during a Hyperloom session."""

    type: str  # log_line | phase_change | measurement | completed | error
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Line parsers -- extract structured events from Hyperloom stdout
# ---------------------------------------------------------------------------

_RE_PHASE = re.compile(
    r"\[(?P<phase>BASELINE|KERNEL|FRAMEWORK|EVAL|DONE|ERROR)\]"
    r"\s*(?P<detail>.*)",
    re.IGNORECASE,
)
_RE_MEASUREMENT = re.compile(
    r"throughput[:\s]+(?P<tps>[\d.]+)\s*tok/s"
    r"|latency[:\s]+(?P<lat>[\d.]+)\s*ms"
    r"|ttft[:\s]+(?P<ttft>[\d.]+)\s*ms"
    r"|gain[:\s]+(?P<gain>[+-]?[\d.]+)%",
    re.IGNORECASE,
)
_RE_ERROR = re.compile(r"(?:error|traceback|exception|abort)", re.IGNORECASE)


def _parse_line(line: str) -> SessionEvent:
    """Parse a single stdout line into a SessionEvent."""
    stripped = line.strip()
    if not stripped:
        return SessionEvent(type="log_line", data={"line": line})

    # Phase changes
    m = _RE_PHASE.match(stripped)
    if m:
        return SessionEvent(
            type="phase_change",
            data={"phase": m.group("phase").upper(), "detail": m.group("detail")},
        )

    # Measurement values
    metrics: dict = {}
    for m in _RE_MEASUREMENT.finditer(stripped):
        if m.group("tps"):
            metrics["throughput_tps"] = float(m.group("tps"))
        if m.group("lat"):
            metrics["latency_ms"] = float(m.group("lat"))
        if m.group("ttft"):
            metrics["ttft_ms"] = float(m.group("ttft"))
        if m.group("gain"):
            metrics["gain_pct"] = float(m.group("gain"))
    if metrics:
        return SessionEvent(type="measurement", data=metrics)

    # Error lines
    if _RE_ERROR.search(stripped):
        return SessionEvent(type="error", data={"line": stripped})

    return SessionEvent(type="log_line", data={"line": stripped})


# ---------------------------------------------------------------------------
# Main launcher
# ---------------------------------------------------------------------------

async def launch_session(
    model_path: str,
    framework: str = "sglang",
    gpu_type: str = "mi300x",
    max_hours: float = 2.0,
    tp: int | None = None,
    ep: int | None = None,
    precision: str = "bf16",
    no_kernel: bool = False,
    no_framework_agent: bool = False,
    no_eval: bool = False,
    enablement: str = "all",
    max_latency_ms: float | None = None,
    max_power_w: int | None = None,
    extra_args: list[str] | None = None,
    session_dir: str | None = None,
    launch_info_file: str | None = None,
    env_override: dict[str, str] | None = None,
) -> AsyncGenerator[SessionEvent, None]:
    """Launch a Hyperloom optimization session and stream events.

    Yields :class:`SessionEvent` objects parsed from the subprocess output.
    The final event will be ``type="completed"`` (success) or ``type="error"``.

    Parameters
    ----------
    model_path:
        HuggingFace model ID or local path.
    framework:
        Inference framework: ``sglang``, ``vllm``, ``tgi``.
    gpu_type:
        Target GPU: ``mi300x``, ``mi325x``, etc.
    max_hours:
        Wall-clock budget for the optimization session.
    tp / ep:
        Tensor parallelism / Expert parallelism overrides.
    precision:
        Weight dtype: ``bf16``, ``fp16``, ``fp8``.
    no_kernel / no_framework_agent / no_eval:
        Disable specific optimization phases.
    enablement:
        Which enablements to try: ``all``, ``safe``, ``none``.
    max_latency_ms / max_power_w:
        SLA constraints.
    extra_args:
        Additional CLI flags passed verbatim.
    session_dir:
        Directory for session artifacts. Hyperloom default if None.
    launch_info_file:
        Path where Hyperloom writes launch identity JSON.
    env_override:
        Extra environment variables for the subprocess.
    """
    cmd = _build_command(
        model_path=model_path,
        framework=framework,
        gpu_type=gpu_type,
        max_hours=max_hours,
        tp=tp,
        ep=ep,
        precision=precision,
        no_kernel=no_kernel,
        no_framework_agent=no_framework_agent,
        no_eval=no_eval,
        enablement=enablement,
        max_latency_ms=max_latency_ms,
        max_power_w=max_power_w,
        extra_args=extra_args,
        session_dir=session_dir,
        launch_info_file=launch_info_file,
    )

    env = {**os.environ, **(env_override or {})}

    logger.info("Launching Hyperloom: %s", " ".join(cmd))
    yield SessionEvent(type="log_line", data={"line": f"Launching: {' '.join(cmd)}"})

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    assert proc.stdout is not None  # subprocess.PIPE guarantees this

    try:
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            event = _parse_line(line)
            yield event
    except asyncio.CancelledError:
        logger.warning("Session launch cancelled, terminating subprocess pid=%s", proc.pid)
        await cancel_session(proc.pid)
        yield SessionEvent(type="error", data={"reason": "cancelled"})
        return

    rc = await proc.wait()

    # Try to read the session breakdown on completion
    info_path = launch_info_file or "/tmp/inferforge_launch_info.json"
    breakdown_data = _try_read_launch_info(info_path)

    if rc == 0:
        yield SessionEvent(
            type="completed",
            data={
                "exit_code": rc,
                "launch_info": breakdown_data,
            },
        )
    else:
        yield SessionEvent(
            type="error",
            data={
                "exit_code": rc,
                "reason": f"Process exited with code {rc}",
                "launch_info": breakdown_data,
            },
        )


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------

def _build_command(
    model_path: str,
    framework: str,
    gpu_type: str,
    max_hours: float,
    tp: int | None,
    ep: int | None,
    precision: str,
    no_kernel: bool,
    no_framework_agent: bool,
    no_eval: bool,
    enablement: str,
    max_latency_ms: float | None,
    max_power_w: int | None,
    extra_args: list[str] | None,
    session_dir: str | None,
    launch_info_file: str | None,
) -> list[str]:
    """Build the ``python -m hyperloom optimize`` CLI argument list."""
    cmd: list[str] = ["python", "-m", "hyperloom", "optimize"]
    cmd.extend(["--model", model_path])
    cmd.extend(["--framework", framework])
    cmd.extend(["--gpu-type", gpu_type])
    cmd.extend(["--max-hours", str(max_hours)])

    if tp is not None:
        cmd.extend(["--tp", str(tp)])
    if ep is not None:
        cmd.extend(["--ep", str(ep)])

    cmd.extend(["--precision", precision])

    if no_kernel:
        cmd.append("--no-kernel")
    if no_framework_agent:
        cmd.append("--no-framework-agent")
    if no_eval:
        cmd.append("--no-eval")

    cmd.extend(["--enablement", enablement])

    if max_latency_ms is not None:
        cmd.extend(["--max-latency-ms", str(max_latency_ms)])
    if max_power_w is not None:
        cmd.extend(["--max-power-w", str(max_power_w)])

    if session_dir:
        cmd.extend(["--session-dir", session_dir])

    info_file = launch_info_file or "/tmp/inferforge_launch_info.json"
    cmd.extend(["--launch-info-file", info_file])

    if extra_args:
        cmd.extend(extra_args)

    return cmd


# ---------------------------------------------------------------------------
# Session control helpers
# ---------------------------------------------------------------------------

async def cancel_session(pid: int) -> bool:
    """Send SIGTERM to a running Hyperloom process. Returns True if signal sent."""
    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("Sent SIGTERM to pid %d", pid)
        # Give it a few seconds to clean up, then SIGKILL
        await asyncio.sleep(5)
        try:
            os.kill(pid, 0)  # Check if still alive
            os.kill(pid, signal.SIGKILL)
            logger.warning("Sent SIGKILL to pid %d (did not terminate gracefully)", pid)
        except ProcessLookupError:
            pass  # Already dead
        return True
    except ProcessLookupError:
        logger.info("Process %d already terminated", pid)
        return False
    except PermissionError:
        logger.error("Permission denied sending signal to pid %d", pid)
        return False


async def resume_session(
    session_dir: str,
    extra_args: list[str] | None = None,
    env_override: dict[str, str] | None = None,
) -> AsyncGenerator[SessionEvent, None]:
    """Resume a previously interrupted Hyperloom session.

    Launches ``python -m hyperloom optimize --resume-from <session_dir>``.
    """
    if not Path(session_dir).is_dir():
        yield SessionEvent(
            type="error",
            data={"reason": f"Session directory not found: {session_dir}"},
        )
        return

    cmd = ["python", "-m", "hyperloom", "optimize", "--resume-from", session_dir]
    if extra_args:
        cmd.extend(extra_args)

    env = {**os.environ, **(env_override or {})}
    logger.info("Resuming Hyperloom session: %s", " ".join(cmd))
    yield SessionEvent(type="log_line", data={"line": f"Resuming: {' '.join(cmd)}"})

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    assert proc.stdout is not None

    try:
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            yield _parse_line(line)
    except asyncio.CancelledError:
        await cancel_session(proc.pid)
        yield SessionEvent(type="error", data={"reason": "cancelled"})
        return

    rc = await proc.wait()
    if rc == 0:
        yield SessionEvent(type="completed", data={"exit_code": rc})
    else:
        yield SessionEvent(
            type="error",
            data={"exit_code": rc, "reason": f"Process exited with code {rc}"},
        )


def get_session_status(session_dir: str) -> dict:
    """Check status of a Hyperloom session directory.

    Returns a dict with keys: ``exists``, ``running``, ``has_breakdown``,
    ``breakdown_path``, ``pid_file``, ``pid``.
    """
    sdir = Path(session_dir)
    result: dict = {
        "exists": sdir.is_dir(),
        "running": False,
        "has_breakdown": False,
        "breakdown_path": None,
        "pid_file": None,
        "pid": None,
    }

    if not sdir.is_dir():
        return result

    # Check for breakdown file
    breakdown = sdir / "session_breakdown.json"
    if breakdown.is_file():
        result["has_breakdown"] = True
        result["breakdown_path"] = str(breakdown)

    # Check for PID file indicating a running session
    pid_file = sdir / ".pid"
    if pid_file.is_file():
        result["pid_file"] = str(pid_file)
        try:
            pid = int(pid_file.read_text().strip())
            result["pid"] = pid
            # Check if process is still alive
            os.kill(pid, 0)
            result["running"] = True
        except (ValueError, ProcessLookupError, PermissionError):
            result["running"] = False

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_read_launch_info(path: str) -> dict | None:
    """Attempt to read the launch info JSON written by Hyperloom."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.debug("Could not read launch info from %s: %s", path, exc)
        return None
