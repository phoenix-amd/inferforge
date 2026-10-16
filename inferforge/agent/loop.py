"""Core agentic loop — streams Claude API responses, executes tools, iterates."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

import anthropic

from inferforge.agent.system_prompt import build_system_prompt
from inferforge.agent.tools import (
    TOOLS,
    execute_bash,
    execute_read_file,
    execute_report_metrics,
    execute_write_file,
)

# Maximum tool-use iterations before forced stop
MAX_ITERATIONS = 100

# Transient error codes eligible for exponential backoff
_TRANSIENT_CODES = (429, 529)
_MAX_RETRIES = 5


async def run_agent(
    messages: list[dict],
    skill: str | None = None,
    mode: str = "interactive",
    run_type: str = "simulation",
    conversation_id: str | None = None,
    *,
    api_key: str = "",
    base_url: str = "https://api.anthropic.com",
    model: str = "claude-sonnet-4-6",
    custom_headers: dict[str, str] | None = None,
    max_tokens: int = 8192,
    skills_dir: str | None = None,
    project_dir: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Run the agentic loop. Yields streaming events for the WebSocket / SSE layer.

    Event types emitted
    -------------------
    - ``text_delta``        incremental assistant text
    - ``tool_use_start``    tool invocation begins
    - ``tool_output_line``  streaming line from bash
    - ``tool_use_end``      tool invocation complete
    - ``metrics_reported``  structured metrics from report_metrics tool
    - ``message_complete``  agent finished
    - ``error``             unrecoverable error
    """
    if not api_key:
        yield {
            "type": "error",
            "content": "Anthropic API key is not configured.",
        }
        return

    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url,
        default_headers=custom_headers if custom_headers else None,
    )

    # Resolve the last user message text for skill auto-loading
    last_user_text = _extract_last_user_text(messages)

    system_prompt = build_system_prompt(
        message_text=last_user_text,
        skill=skill,
        mode=mode,
        run_type=run_type,
        skills_dir=skills_dir,
        project_dir=project_dir,
    )

    # Convert to API format (only user/assistant roles)
    api_messages: list[dict] = []
    for msg in messages:
        if msg.get("role") in ("user", "assistant"):
            api_messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

    overload_retries = 0

    for iteration in range(MAX_ITERATIONS):
        try:
            assistant_content: list[dict] = []
            current_text = ""
            tool_uses: list[dict] = []
            stop_reason: str | None = None

            with client.messages.stream(
                model=model,
                system=system_prompt,
                messages=api_messages,
                tools=TOOLS,
                max_tokens=max_tokens,
            ) as stream:
                for event in stream:
                    if not hasattr(event, "type"):
                        continue

                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "text":
                            current_text = ""
                        elif block.type == "tool_use":
                            tool_uses.append({
                                "id": block.id,
                                "name": block.name,
                                "input": {},
                                "_input_json": "",
                            })

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "text"):
                            current_text += delta.text
                            yield {
                                "type": "text_delta",
                                "content": delta.text,
                            }
                        elif hasattr(delta, "partial_json"):
                            if tool_uses:
                                tool_uses[-1]["_input_json"] += delta.partial_json

                    elif event.type == "content_block_stop":
                        if current_text:
                            assistant_content.append({
                                "type": "text",
                                "text": current_text,
                            })
                        if tool_uses and tool_uses[-1].get("_input_json"):
                            try:
                                tool_uses[-1]["input"] = json.loads(
                                    tool_uses[-1]["_input_json"]
                                )
                            except json.JSONDecodeError:
                                tool_uses[-1]["input"] = {}
                            del tool_uses[-1]["_input_json"]
                            assistant_content.append({
                                "type": "tool_use",
                                "id": tool_uses[-1]["id"],
                                "name": tool_uses[-1]["name"],
                                "input": tool_uses[-1]["input"],
                            })

                response = stream.get_final_message()
                stop_reason = response.stop_reason

        except anthropic.APIError as e:
            is_transient = (
                getattr(e, "status_code", 0) in _TRANSIENT_CODES
                or "overloaded_error" in str(e)
                or "rate_limit" in str(e)
            )
            if is_transient and overload_retries < _MAX_RETRIES:
                overload_retries += 1
                wait = 2 ** overload_retries
                yield {
                    "type": "text_delta",
                    "content": (
                        f"\nAPI temporarily overloaded -- waiting {wait}s "
                        f"before retry {overload_retries}/{_MAX_RETRIES}...\n"
                    ),
                }
                await asyncio.sleep(wait)
                continue

            msg = (
                "API temporarily overloaded after 5 retries. "
                "Please wait a moment and resend your message."
                if is_transient
                else f"API Error: {e}"
            )
            yield {"type": "error", "content": msg}
            return

        except Exception as e:
            yield {"type": "error", "content": f"Error: {e}"}
            return

        # Reset retry counter on success
        overload_retries = 0

        # No tool use -> agent is done
        if stop_reason != "tool_use" or not tool_uses:
            yield {"type": "message_complete"}
            return

        # Execute tools and collect results
        api_messages.append({
            "role": "assistant",
            "content": assistant_content,
        })
        tool_results: list[dict] = []

        for tool in tool_uses:
            tool_name = tool["name"]
            tool_input = tool["input"]
            tool_id = tool["id"]

            yield {
                "type": "tool_use_start",
                "tool_id": tool_id,
                "tool_name": tool_name,
                "input": tool_input,
            }

            result_content = ""

            if tool_name == "bash":
                output_parts: list[str] = []
                async for ev in execute_bash(tool_input.get("command", "")):
                    if ev["type"] == "tool_output":
                        yield {
                            "type": "tool_output_line",
                            "tool_id": tool_id,
                            "content": ev["content"],
                        }
                        output_parts.append(ev["content"])
                    elif ev["type"] == "tool_done":
                        result_content = ev.get(
                            "full_output", "".join(output_parts)
                        )
                        yield {
                            "type": "tool_use_end",
                            "tool_id": tool_id,
                            "exit_code": ev.get("exit_code", -1),
                        }
                    elif ev["type"] == "tool_error":
                        result_content = ev["content"]
                        yield {
                            "type": "tool_use_end",
                            "tool_id": tool_id,
                            "exit_code": -1,
                            "error": ev["content"],
                        }

            elif tool_name == "read_file":
                rf_exit = 1
                async for ev in execute_read_file(tool_input.get("path", "")):
                    result_content = ev.get("content", "")
                    rf_exit = 0 if ev["type"] == "tool_done" else 1
                yield {
                    "type": "tool_use_end",
                    "tool_id": tool_id,
                    "exit_code": rf_exit,
                }

            elif tool_name == "write_file":
                wf_exit = 1
                async for ev in execute_write_file(
                    tool_input.get("path", ""),
                    tool_input.get("content", ""),
                ):
                    result_content = ev.get("content", "")
                    wf_exit = 0 if ev["type"] == "tool_done" else 1
                yield {
                    "type": "tool_use_end",
                    "tool_id": tool_id,
                    "exit_code": wf_exit,
                }

            elif tool_name == "report_metrics":
                metrics_data = tool_input.get("metrics", {})
                async for ev in execute_report_metrics(metrics_data):
                    if ev["type"] == "metrics_reported":
                        yield {
                            "type": "metrics_reported",
                            "data": ev["data"],
                            "conversation_id": conversation_id,
                        }
                    elif ev["type"] == "tool_done":
                        result_content = ev.get("content", "")
                        yield {
                            "type": "tool_use_end",
                            "tool_id": tool_id,
                            "exit_code": 0,
                        }
                    elif ev["type"] == "tool_error":
                        result_content = ev["content"]
                        yield {
                            "type": "tool_use_end",
                            "tool_id": tool_id,
                            "exit_code": 1,
                            "error": ev["content"],
                        }

            else:
                result_content = f"Unknown tool: {tool_name}"
                yield {
                    "type": "tool_use_end",
                    "tool_id": tool_id,
                    "exit_code": 1,
                }

            # Truncate very large outputs
            if len(result_content) > 50_000:
                result_content = (
                    result_content[:50_000] + "\n... [truncated at 50KB]"
                )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result_content,
            })

        # Feed tool results back to the conversation
        api_messages.append({"role": "user", "content": tool_results})
        tool_uses = []

    yield {
        "type": "error",
        "content": f"Max tool iterations ({MAX_ITERATIONS}) reached.",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_last_user_text(messages: list[dict]) -> str:
    """Pull the text of the most recent user message."""
    for m in reversed(messages):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict)
            )
    return ""


