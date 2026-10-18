"""WebSocket endpoints -- agent chat streaming, HyperLoom events, fleet telemetry."""

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from fastapi import Request

from inferforge.config import API_KEY, BASE_URL, MODEL, CUSTOM_HEADERS, is_api_configured
from inferforge.db import (
    get_conversation,
    get_messages,
    add_message,
)
from inferforge.db.benchmarks import save_benchmark_run
from inferforge.db.connection import get_connection
from inferforge.agent.loop import run_agent
from inferforge.api.inference_state import update_inference_state

logger = logging.getLogger("inferforge.ws")

router = APIRouter(tags=["websocket"])

# Track active WebSocket connections per conversation
_active_sockets: dict[str, list[WebSocket]] = defaultdict(list)

# Track Docker containers started by the agent (for cleanup)
_docker_containers: dict[str, set[str]] = defaultdict(set)

# Track active agent tasks for cancellation
_active_tasks: dict[str, asyncio.Task] = {}

# Message buffer for replay on reconnect (last N events per conversation)
_BUFFER_SIZE = 200
_message_buffers: dict[str, list[dict]] = defaultdict(list)


async def _cleanup_containers(cid: str) -> list[str]:
    """Stop and remove any Docker containers tracked for this conversation.
    Also SSH to fleet nodes to kill any vLLM/SGLang containers."""
    stopped = []

    # 1. Stop explicitly tracked containers
    containers = _docker_containers.pop(cid, set())
    for name in containers:
        try:
            proc = await asyncio.create_subprocess_shell(
                f"docker stop {name} 2>/dev/null && docker rm {name} 2>/dev/null",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)
            stopped.append(name)
        except Exception as e:
            logger.warning("Failed to stop container %s: %s", name, e)

    # 2. SSH to fleet nodes and kill any inferforge/vLLM/SGLang containers
    conn = get_connection()
    rows = conn.execute(
        "SELECT ip_address, ssh_user, ssh_key_path FROM fleet_nodes WHERE status != 'offline'"
    ).fetchall()

    for r in rows:
        r = dict(r)
        ip = r.get("ip_address")
        user = r.get("ssh_user") or "rghaffar"
        key = r.get("ssh_key_path") or "~/.ssh/id_ed25519_moba"
        if not ip:
            continue
        cmd = (
            f"ssh -i {key} -o BatchMode=yes -o ConnectTimeout=5 "
            f"-o StrictHostKeyChecking=no {user}@{ip} "
            "'docker ps --filter name=inferforge --filter name=vllm --filter name=sglang "
            "-q 2>/dev/null | xargs -r docker stop 2>/dev/null'"
        )
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if stdout.strip():
                stopped.append(f"remote:{ip}")
        except Exception as e:
            logger.debug("Remote cleanup on %s: %s", ip, e)

    return stopped


@router.post("/api/cancel/{conversation_id}")
async def api_cancel_job(conversation_id: str):
    """Cancel a running agent job and clean up Docker containers."""
    # Cancel the active agent task
    task = _active_tasks.pop(conversation_id, None)
    if task and not task.done():
        task.cancel()

    # Clean up containers
    stopped = await _cleanup_containers(conversation_id)

    # Notify connected WebSocket clients
    event = {"type": "error", "content": "Job cancelled by user."}
    for ws in _active_sockets.get(conversation_id, []):
        try:
            await ws.send_json(event)
        except Exception:
            pass

    return {"status": "cancelled", "containers_stopped": stopped}


def _buffer_event(cid: str, event: dict) -> None:
    buf = _message_buffers[cid]
    buf.append(event)
    if len(buf) > _BUFFER_SIZE:
        _message_buffers[cid] = buf[-_BUFFER_SIZE:]


async def _broadcast(cid: str, event: dict) -> None:
    _buffer_event(cid, event)
    dead: list[WebSocket] = []
    for ws in _active_sockets[cid]:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            _active_sockets[cid].remove(ws)
        except ValueError:
            pass


async def _run_agent_task(cid: str, api_messages: list, skill: str, mode: str,
                          run_type: str):
    """Run the agent in a background task so the WebSocket loop stays responsive."""
    assistant_text_parts: list[str] = []
    try:
        async for event in run_agent(
            messages=api_messages,
            skill=skill,
            mode=mode,
            run_type=run_type,
            conversation_id=cid,
            api_key=API_KEY,
            base_url=BASE_URL,
            model=MODEL,
            custom_headers=CUSTOM_HEADERS or None,
        ):
            event_type = event.get("type", "")

            if event_type == "text_delta":
                assistant_text_parts.append(event.get("content", ""))

            elif event_type == "tool_use_start":
                tool_input = event.get("input", {})
                cmd = tool_input.get("command", "")
                if "docker run" in cmd and "--name" in cmd:
                    parts = cmd.split("--name")
                    if len(parts) > 1:
                        container_name = parts[1].strip().split()[0]
                        _docker_containers[cid].add(container_name)

            elif event_type == "metrics_reported":
                metrics_data = event.get("data", {})
                if metrics_data.get("model_name") and metrics_data.get("framework"):
                    try:
                        save_benchmark_run(
                            conversation_id=cid,
                            **{k: v for k, v in metrics_data.items() if v is not None},
                        )
                    except Exception as e:
                        logger.warning("Failed to save benchmark run: %s", e)
                _update_state_from_metrics(metrics_data)

            elif event_type == "message_complete":
                full_text = "".join(assistant_text_parts)
                if full_text.strip():
                    add_message(cid, "assistant", full_text)
                if cid in _docker_containers and _docker_containers[cid]:
                    asyncio.create_task(_cleanup_containers(cid))

            await _broadcast(cid, event)

    except asyncio.CancelledError:
        # Agent was cancelled — save partial text and notify
        full_text = "".join(assistant_text_parts)
        if full_text.strip():
            add_message(cid, "assistant", full_text + "\n\n*[Stopped by user]*")
        await _broadcast(cid, {"type": "error", "content": "Job stopped by user."})
        await _broadcast(cid, {"type": "message_complete"})
        if cid in _docker_containers and _docker_containers[cid]:
            asyncio.create_task(_cleanup_containers(cid))
    except Exception as e:
        logger.exception("Agent error for conversation %s", cid)
        await _broadcast(cid, {"type": "error", "content": str(e)})
        await _broadcast(cid, {"type": "message_complete"})
    finally:
        _active_tasks.pop(cid, None)


@router.websocket("/ws/chat/{cid}")
async def ws_chat(websocket: WebSocket, cid: str):
    await websocket.accept()
    _active_sockets[cid].append(websocket)

    # Replay buffered events on reconnect
    _replay_ok = True
    job_running = cid in _active_tasks and not _active_tasks[cid].done()
    for event in _message_buffers.get(cid, []):
        try:
            await websocket.send_json(event)
        except Exception:
            _replay_ok = False
            break

    if not _replay_ok:
        if websocket in _active_sockets[cid]:
            _active_sockets[cid].remove(websocket)
        return

    # Tell the client whether a job is already running
    await websocket.send_json({"type": "connected", "job_running": job_running})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "Invalid JSON"})
                continue

            msg_type = data.get("type", "message")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "stop":
                # Cancel the running agent task
                task = _active_tasks.get(cid)
                if task and not task.done():
                    task.cancel()
                    logger.info("Agent task cancelled for conversation %s", cid)
                await websocket.send_json({"type": "stopped", "content": "Agent stopped by user."})
                continue

            if msg_type != "message":
                continue

            user_text = data.get("content", "").strip()
            if not user_text:
                continue

            # Don't start a new agent if one is already running
            existing_task = _active_tasks.get(cid)
            if existing_task and not existing_task.done():
                await websocket.send_json({
                    "type": "error",
                    "content": "An agent is already running. Click STOP first.",
                })
                continue

            skill = data.get("skill")
            mode = data.get("mode", "interactive")
            run_type = data.get("run_type", "simulation")

            conv = get_conversation(cid)
            if not conv:
                await websocket.send_json({
                    "type": "error",
                    "content": f"Conversation {cid} not found",
                })
                continue

            if not is_api_configured():
                await websocket.send_json({
                    "type": "error",
                    "content": "Anthropic API is not configured. Set ANTHROPIC_API_KEY or gateway credentials.",
                })
                continue

            add_message(cid, "user", user_text)

            existing_messages = get_messages(cid)
            api_messages = []
            for m in existing_messages:
                if m["role"] in ("user", "assistant"):
                    api_messages.append({
                        "role": m["role"],
                        "content": m["content"],
                    })

            # Launch agent in a background task (keeps WebSocket loop free for stop/ping)
            task = asyncio.create_task(
                _run_agent_task(cid, api_messages, skill or conv.get("skill"), mode, run_type)
            )
            _active_tasks[cid] = task

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("WebSocket error for conversation %s", cid)
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass
    finally:
        if websocket in _active_sockets[cid]:
            _active_sockets[cid].remove(websocket)
        if not _active_sockets[cid]:
            del _active_sockets[cid]
            if cid in _docker_containers:
                asyncio.create_task(_cleanup_containers(cid))


@router.websocket("/ws/hyperloom/{sid}")
async def ws_hyperloom(websocket: WebSocket, sid: str):
    await websocket.accept()
    try:
        await websocket.send_json({
            "type": "info",
            "content": f"HyperLoom session {sid} event stream -- not yet implemented.",
        })
        while True:
            await websocket.receive_text()
            await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/fleet")
async def ws_fleet(websocket: WebSocket):
    await websocket.accept()
    try:
        await websocket.send_json({
            "type": "info",
            "content": "Fleet telemetry stream -- not yet implemented.",
        })
        while True:
            await websocket.receive_text()
            await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass


def _update_state_from_metrics(metrics: dict) -> None:
    state_updates = {}
    mapping = {
        "gpu_platform": "gpu_model",
        "gpu_count": "gpu_count",
        "model_name": "model_name",
        "model_params_b": "model_params_b",
        "framework": "framework",
        "tp": "tp",
        "pp": "pp",
        "dp": "dp",
        "weight_dtype": "weight_dtype",
        "throughput_tps": "throughput_tps",
        "ttft_p50": "ttft_p50",
        "ttft_p99": "ttft_p99",
        "tpot_p50": "tpot_p50",
        "hbm_used_gb": "hbm_used_gb",
        "run_mode": "run_type",
    }
    for src_key, dst_key in mapping.items():
        if src_key in metrics and metrics[src_key] is not None:
            state_updates[dst_key] = metrics[src_key]
    if state_updates:
        update_inference_state(state_updates)
