"""Conversation CRUD routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inferforge.db import (
    create_conversation,
    get_conversation,
    list_conversations,
    update_conversation,
    delete_conversation,
    get_messages,
)

router = APIRouter(prefix="/api", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    skill: str | None = None
    mode: str = "interactive"


class ConversationPatch(BaseModel):
    title: str


@router.get("/conversations")
def api_list_conversations():
    convs = list_conversations()
    return {"conversations": convs, "total": len(convs)}


@router.post("/conversations", status_code=201)
def api_create_conversation(body: ConversationCreate):
    cid = create_conversation(
        title=body.title,
        skill=body.skill,
        mode=body.mode,
    )
    return {"id": cid, "title": body.title, "skill": body.skill, "mode": body.mode}


@router.get("/conversations/{cid}")
def api_get_conversation(cid: str):
    conv = get_conversation(cid)
    if not conv:
        raise HTTPException(404, f"Conversation {cid} not found")
    conv["messages"] = get_messages(cid)
    return conv


@router.patch("/conversations/{cid}")
def api_patch_conversation(cid: str, body: ConversationPatch):
    conv = get_conversation(cid)
    if not conv:
        raise HTTPException(404, f"Conversation {cid} not found")
    update_conversation(cid, title=body.title)
    return {"id": cid, "title": body.title}


@router.delete("/conversations/{cid}", status_code=204)
def api_delete_conversation(cid: str):
    conv = get_conversation(cid)
    if not conv:
        raise HTTPException(404, f"Conversation {cid} not found")
    delete_conversation(cid)
