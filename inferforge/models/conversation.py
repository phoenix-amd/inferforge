"""Pydantic models for conversations and messages."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ExecutionMode(str, Enum):
    interactive = "interactive"
    autonomous = "autonomous"
    batch = "batch"


class ConversationCreate(BaseModel):
    title: str = Field(default="New Conversation", min_length=1, max_length=256)
    skill: str | None = Field(default=None, max_length=64)
    mode: ExecutionMode = ExecutionMode.interactive
    project_id: str | None = Field(default=None, max_length=36)
    user_id: str | None = Field(default=None, max_length=36)


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    skill: str | None = None
    mode: ExecutionMode | None = None


class ConversationResponse(BaseModel):
    id: str
    title: str
    skill: str | None = None
    mode: str = "interactive"
    project_id: str | None = None
    user_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    messages: list[MessageResponse] = Field(default_factory=list)


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


class MessageResponse(BaseModel):
    id: int
    conversation_id: str
    role: MessageRole
    content: str = ""
    tool_calls: list[dict] | str | None = None
    tool_results: list[dict] | str | None = None
    metadata: dict | str | None = None
    created_at: str | None = None


class MessageCreate(BaseModel):
    role: MessageRole
    content: str = Field(default="", max_length=1_000_000)
    tool_calls: list[dict] | None = None
    tool_results: list[dict] | None = None
    metadata: dict | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    skill: str | None = None
    mode: ExecutionMode = ExecutionMode.interactive
