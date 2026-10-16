"""Tool definitions and executors for the InferForge agent."""

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from inferforge.config import BLOCKED_PATTERNS, PROJECT_DIR

# ---------------------------------------------------------------------------
# Tool definitions (sent to Claude as available tools)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "bash",
        "description": (
            "Execute a bash command. Has SSH access to cluster nodes and Docker control."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file on this machine.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to read",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path",
                },
                "content": {
                    "type": "string",
                    "description": "File content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "report_metrics",
        "description": (
            "Report structured benchmark metrics. Call this after parsing "
            "benchmark output to store typed metrics. Fields: model_name, "
            "framework, tp, pp, dp, weight_dtype, throughput_tps, ttft_p50, "
            "ttft_p99, tpot_p50, tpot_p99, itl_p50, hbm_used_gb, "
            "run_mode (simulation|real), evidence_source."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "object",
                    "description": "Structured benchmark metrics as JSON object",
                    "properties": {
                        "model_name": {"type": "string"},
                        "framework": {
                            "type": "string",
                            "enum": ["vllm", "sglang", "tgi"],
                        },
                        "gpu_platform": {"type": "string"},
                        "gpu_count": {"type": "integer"},
                        "tp": {"type": "integer"},
                        "pp": {"type": "integer"},
                        "dp": {"type": "integer"},
                        "weight_dtype": {"type": "string"},
                        "kv_dtype": {"type": "string"},
                        "throughput_tps": {"type": "number"},
                        "throughput_rps": {"type": "number"},
                        "ttft_p50": {"type": "number"},
                        "ttft_p90": {"type": "number"},
                        "ttft_p99": {"type": "number"},
                        "tpot_p50": {"type": "number"},
                        "tpot_p99": {"type": "number"},
                        "itl_p50": {"type": "number"},
                        "e2e_p50": {"type": "number"},
                        "hbm_used_gb": {"type": "number"},
                        "run_mode": {
                            "type": "string",
                            "enum": ["simulation", "real"],
                        },
                        "evidence_source": {"type": "string"},
                    },
                    "required": ["model_name", "framework"],
                }
            },
            "required": ["metrics"],
        },
    },
]


# ---------------------------------------------------------------------------
# Safety guard
# ---------------------------------------------------------------------------

def is_command_safe(command: str) -> tuple[bool, str]:
    """Check a bash command against the blocked-patterns deny list."""
    cmd_lower = command.lower().strip()
    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, f"BLOCKED: command contains '{pattern}'"
    return True, ""


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

async def execute_bash(
    command: str, timeout: int = 1800
) -> AsyncGenerator[dict, None]:
    """Run a bash command, streaming stdout line-by-line."""
    safe, reason = is_command_safe(command)
    if not safe:
        yield {"type": "tool_error", "content": reason}
        return

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_DIR),
        )

        output_lines: list[str] = []
        try:
            while True:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=timeout
                )
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                output_lines.append(decoded)
                yield {"type": "tool_output", "content": decoded}
        except asyncio.TimeoutError:
            proc.kill()
            yield {
                "type": "tool_output",
                "content": f"\n[TIMEOUT after {timeout}s]\n",
            }

        await proc.wait()
        yield {
            "type": "tool_done",
            "exit_code": proc.returncode,
            "full_output": "".join(output_lines),
        }

    except Exception as e:
        yield {"type": "tool_error", "content": f"Execution error: {e}"}


async def execute_read_file(path: str) -> AsyncGenerator[dict, None]:
    """Read a file and yield the result."""
    try:
        content = await asyncio.to_thread(
            lambda: Path(path).read_text(encoding="utf-8", errors="replace")
        )
        if len(content) > 100_000:
            content = (
                content[:100_000]
                + f"\n... [truncated at 100KB, file is {len(content)} bytes]"
            )
        yield {"type": "tool_done", "content": content}
    except Exception as e:
        yield {"type": "tool_error", "content": f"Error reading {path}: {e}"}


async def execute_write_file(path: str, content: str) -> AsyncGenerator[dict, None]:
    """Write content to a file and yield the result."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            lambda: target.write_text(content, encoding="utf-8")
        )
        yield {
            "type": "tool_done",
            "content": f"Wrote {len(content)} bytes to {path}",
        }
    except Exception as e:
        yield {"type": "tool_error", "content": f"Error writing {path}: {e}"}


async def execute_report_metrics(metrics_json: dict) -> AsyncGenerator[dict, None]:
    """Validate and store structured benchmark metrics.

    This tool does not persist to a database directly — it yields a
    ``metrics_reported`` event that the server layer can intercept
    to update the DB / broadcast to the frontend.
    """
    required = ("model_name", "framework")
    missing = [f for f in required if f not in metrics_json]
    if missing:
        yield {
            "type": "tool_error",
            "content": f"Missing required metric fields: {', '.join(missing)}",
        }
        return

    yield {
        "type": "metrics_reported",
        "data": metrics_json,
    }
    yield {
        "type": "tool_done",
        "content": json.dumps(
            {"status": "ok", "stored_fields": list(metrics_json.keys())},
            indent=2,
        ),
    }
