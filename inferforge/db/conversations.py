"""Conversation and message CRUD operations."""

import json
import sqlite3
import uuid

from .connection import get_connection


def _short_id() -> str:
    return str(uuid.uuid4())[:12]


def create_conversation(
    title: str = "New Conversation",
    skill: str | None = None,
    mode: str = "interactive",
    project_id: str | None = None,
    user_id: str | None = None,
) -> str:
    cid = _short_id()
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO conversations (id, title, skill, mode, project_id, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, title, skill, mode, project_id, user_id),
        )
    return cid


def get_conversation(cid: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else None


def list_conversations(
    project_id: str | None = None,
    user_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    conn = get_connection()
    clauses: list[str] = []
    params: list = []
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM conversations {where} ORDER BY updated_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def update_conversation(cid: str, **kwargs) -> None:
    allowed = {"title", "skill", "mode", "project_id", "user_id"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = "datetime('now')"
    set_parts: list[str] = []
    params: list = []
    for k, v in fields.items():
        if v == "datetime('now')":
            set_parts.append(f"{k} = datetime('now')")
        else:
            set_parts.append(f"{k} = ?")
            params.append(v)
    params.append(cid)
    conn = get_connection()
    with conn:
        conn.execute(
            f"UPDATE conversations SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )


def delete_conversation(cid: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    tool_calls: list | None = None,
    tool_results: list | None = None,
    metadata: dict | None = None,
) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO messages "
            "(conversation_id, role, content, tool_calls, tool_results, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                json.dumps(tool_results) if tool_results else None,
                json.dumps(metadata) if metadata else None,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        return cur.lastrowid


def get_messages(conversation_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for key in ("tool_calls", "tool_results", "metadata"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except json.JSONDecodeError:
                    pass
        result.append(d)
    return result
