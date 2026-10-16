"""Pydantic models for user authentication and management."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class UserRole(str, Enum):
    user = "user"
    admin = "admin"
    viewer = "viewer"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    role: UserRole = UserRole.user

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not all(c.isalnum() or c in ("_", "-", ".") for c in cleaned):
            raise ValueError(
                "Username must contain only alphanumeric characters, "
                "underscores, hyphens, or dots"
            )
        return cleaned

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if v.isalpha():
            raise ValueError("Password must contain at least one digit or symbol")
        if v.isdigit():
            raise ValueError("Password must contain at least one letter")
        return v


class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    role: UserRole = UserRole.user
    created_at: str | None = None
    last_login: str | None = None


class TokenPayload(BaseModel):
    sub: str
    username: str
    role: str
    exp: float
    iat: float


class TokenResponse(BaseModel):
    token: str = Field(description="JWT bearer token")
    user: UserResponse

    @property
    def authorization_header(self) -> str:
        return f"Bearer {self.token}"


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    role: UserRole | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
