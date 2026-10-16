"""Authentication routes -- JWT-based login and registration."""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from inferforge.config import INFERFORGE_JWT_SECRET
from inferforge.db.connection import get_connection

router = APIRouter(prefix="/api/auth", tags=["auth"])

_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = 24


def _short_id() -> str:
    return str(uuid.uuid4())[:12]


def _get_secret() -> str:
    secret = INFERFORGE_JWT_SECRET
    if not secret:
        secret = "inferforge-dev-secret-change-me"
    return secret


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def _create_token(user_id: str, username: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_secret(), algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _get_secret(), algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = auth_header[7:]
    return decode_token(token)


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None


@router.post("/login")
def api_login(body: LoginRequest):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    if not row:
        raise HTTPException(401, "Invalid username or password")
    user = dict(row)
    if not _check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid username or password")
    with conn:
        conn.execute(
            "UPDATE users SET last_login = datetime('now') WHERE id = ?",
            (user["id"],),
        )
    token = _create_token(user["id"], user["username"], user["role"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
        },
    }


@router.post("/register", status_code=201)
def api_register(body: RegisterRequest):
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    if existing:
        raise HTTPException(409, f"Username '{body.username}' already taken")
    uid = _short_id()
    pw_hash = _hash_password(body.password)
    with conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, display_name, role) "
            "VALUES (?,?,?,?,?)",
            (uid, body.username, pw_hash, body.display_name or body.username, "user"),
        )
    token = _create_token(uid, body.username, "user")
    return {
        "token": token,
        "user": {
            "id": uid,
            "username": body.username,
            "display_name": body.display_name or body.username,
            "role": "user",
        },
    }


@router.get("/me")
def api_me(user: dict = Depends(get_current_user)):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, username, display_name, role, created_at, last_login "
        "FROM users WHERE id = ?",
        (user["sub"],),
    ).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    return dict(row)
