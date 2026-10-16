"""InferForge FastAPI application -- main entry point."""

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from inferforge import __version__
from inferforge.config import (
    HOST,
    PORT,
    AUTH_USER,
    AUTH_PASS,
    CREDENTIAL_SOURCE,
    API_CONNECTION,
    is_api_configured,
    is_api_connected,
)
from inferforge.db.schema import init_db
from inferforge.db.connection import close_all as close_db

# API route modules
from inferforge.api import (
    conversations,
    skills,
    benchmarks,
    inference_state,
    campaigns,
    fleet,
    hyperloom_sessions,
    recipes,
    deployments,
    auth,
    calculator_api,
    websocket,
)

logger = logging.getLogger("inferforge")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PACKAGE_DIR = Path(__file__).resolve().parent            # inferforge/
_PROJECT_DIR = _PACKAGE_DIR.parent                         # repo root
_FRONTEND_DIR = _PROJECT_DIR / "frontend"
_CLASSIC_DIR = _FRONTEND_DIR / "classic"
_NOVA_DIR = _FRONTEND_DIR / "nova"
_ERA_DIR = _FRONTEND_DIR / "era"
_COMMON_DIR = _FRONTEND_DIR / "common"


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("InferForge v%s starting up", __version__)
    init_db()
    logger.info("Database initialized")
    logger.info("API credentials: source=%s, configured=%s, connected=%s",
                CREDENTIAL_SOURCE, is_api_configured(), is_api_connected())
    if not is_api_configured():
        logger.warning("Anthropic API is NOT configured -- agent chat will not work")
    elif not is_api_connected():
        logger.warning("Anthropic API configured but connection check failed: %s",
                        API_CONNECTION.get("message", "unknown"))
    yield
    close_db()
    logger.info("InferForge shut down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="InferForge",
    version=__version__,
    description="AMD Unified LLM Inference Optimization Platform",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Optional Basic Auth middleware
# ---------------------------------------------------------------------------

if AUTH_USER:
    import base64

    @app.middleware("http")
    async def basic_auth_middleware(request: Request, call_next):
        if request.url.path.startswith("/ws/"):
            return await call_next(request)
        # Allow static assets through
        for prefix in ("/common/", "/classic/", "/nova/", "/era/"):
            if request.url.path.startswith(prefix):
                return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                user, _, password = decoded.partition(":")
                if secrets.compare_digest(user, AUTH_USER) and secrets.compare_digest(password, AUTH_PASS):
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="InferForge"'},
            content="Unauthorized",
        )

# ---------------------------------------------------------------------------
# Static files — mount at paths matching HTML <link>/<script> references
# ---------------------------------------------------------------------------

# HTML references: /common/css/..., /common/js/...
if _COMMON_DIR.is_dir():
    app.mount("/common", StaticFiles(directory=str(_COMMON_DIR)), name="common")

# HTML references: /classic/css/..., /classic/js/...
if (_CLASSIC_DIR / "css").is_dir():
    app.mount("/classic/css", StaticFiles(directory=str(_CLASSIC_DIR / "css")), name="classic-css")
if (_CLASSIC_DIR / "js").is_dir():
    app.mount("/classic/js", StaticFiles(directory=str(_CLASSIC_DIR / "js")), name="classic-js")

# HTML references: /nova/css/..., /nova/js/...
if (_NOVA_DIR / "css").is_dir():
    app.mount("/nova/css", StaticFiles(directory=str(_NOVA_DIR / "css")), name="nova-css")
if (_NOVA_DIR / "js").is_dir():
    app.mount("/nova/js", StaticFiles(directory=str(_NOVA_DIR / "js")), name="nova-js")

# HTML references: /era/css/..., /era/js/...
if (_ERA_DIR / "css").is_dir():
    app.mount("/era/css", StaticFiles(directory=str(_ERA_DIR / "css")), name="era-css")
if (_ERA_DIR / "js").is_dir():
    app.mount("/era/js", StaticFiles(directory=str(_ERA_DIR / "js")), name="era-js")


# ---------------------------------------------------------------------------
# Include API routers
# ---------------------------------------------------------------------------

app.include_router(conversations.router)
app.include_router(skills.router)
app.include_router(benchmarks.router)
app.include_router(inference_state.router)
app.include_router(campaigns.router)
app.include_router(fleet.router)
app.include_router(hyperloom_sessions.router)
app.include_router(recipes.router)
app.include_router(deployments.router)
app.include_router(auth.router)
app.include_router(calculator_api.router)
app.include_router(websocket.router)


# ---------------------------------------------------------------------------
# HTML routes — serve files directly (no Jinja2 needed)
# ---------------------------------------------------------------------------

def _serve_html(file_path: Path, fallback_name: str) -> HTMLResponse:
    """Read and return an HTML file, or a fallback page."""
    if file_path.exists():
        return HTMLResponse(file_path.read_text(encoding="utf-8", errors="replace"))
    return HTMLResponse(
        f"<html><body style='background:#0a0a14;color:#e0e0f0;font-family:sans-serif;padding:40px'>"
        f"<h1>InferForge {fallback_name}</h1>"
        f"<p>Frontend not found at {file_path}. API is available at <a href='/api/health'>/api/health</a></p>"
        f"</body></html>",
        status_code=200,
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _serve_html(_CLASSIC_DIR / "index.html", "Classic")


@app.get("/nova", response_class=HTMLResponse)
async def nova_ui(request: Request):
    return _serve_html(_NOVA_DIR / "index.html", "Nova")


@app.get("/era", response_class=HTMLResponse)
async def era_ui(request: Request):
    return _serve_html(_ERA_DIR / "index.html", "Era")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
@app.get("/api/status")
async def health():
    return {
        "status": "ok",
        "version": __version__,
        "api_configured": is_api_configured(),
        "api_connected": is_api_connected(),
        "credential_source": CREDENTIAL_SOURCE,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import uvicorn

    log_level = os.environ.get("INFERFORGE_LOG_LEVEL", "info").lower()
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = uvicorn.Config(
        "inferforge.server:app",
        host=HOST,
        port=PORT,
        reload=os.environ.get("INFERFORGE_RELOAD", "").lower() in ("1", "true"),
        log_level=log_level,
        timeout_graceful_shutdown=2,  # Force-kill after 2s on Ctrl+C
    )
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
