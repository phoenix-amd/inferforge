"""Central configuration -- reads environment variables and discovers project layout."""

import json
import os
import re
from pathlib import Path

# --- Paths ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent                     # inferforge package -> inferforge root
CLAUDE_MD = PROJECT_DIR / "CLAUDE.md"
SKILLS_DIR = SCRIPT_DIR / "skills"                  # inferforge/skills/
SETTINGS_JSON = PROJECT_DIR / ".claude" / "settings.json"
DB_PATH = SCRIPT_DIR / "inferforge.db"
ENV_FILE = PROJECT_DIR / ".env"

ANTHROPIC_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_CUSTOM_HEADERS",
)

CLAUDE_SETTINGS_CANDIDATES = (
    (Path.home() / ".claude" / "settings.json", "~/.claude/settings.json"),
    (Path.home() / ".claude" / "settings.local.json", "~/.claude/settings.local.json"),
    (PROJECT_DIR / ".claude" / "settings.local.json", "project .claude/settings.local.json"),
    (PROJECT_DIR / ".claude" / "settings.json", "project .claude/settings.json"),
)

# --- HyperLoom integration ---
HYPERLOOM_KB_URL = os.environ.get("HYPERLOOM_KB_URL", "")
HYPERLOOM_KB_TOKEN = os.environ.get("HYPERLOOM_KB_TOKEN", "")
HYPERLOOM_INSTALL_DIR = os.environ.get(
    "HYPERLOOM_INSTALL_DIR",
    str(Path.home() / "hyperloom"),
)

# --- JWT ---
INFERFORGE_JWT_SECRET = os.environ.get("INFERFORGE_JWT_SECRET", "")


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (existing vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def extract_settings_env(data: dict) -> dict[str, str]:
    """Pull ANTHROPIC_* values from a Claude settings.json (top-level or env block)."""
    result: dict[str, str] = {}
    env_block = data.get("env", {})
    if isinstance(env_block, dict):
        for key in ANTHROPIC_ENV_KEYS:
            val = env_block.get(key)
            if val is not None and str(val).strip():
                result[key] = str(val).strip()

    for key in ANTHROPIC_ENV_KEYS:
        if key in result:
            continue
        val = data.get(key)
        if val is not None and str(val).strip() and not isinstance(val, (dict, list)):
            result[key] = str(val).strip()
    return result


def apply_env_dict(values: dict[str, str], only_missing: bool = True) -> list[str]:
    """Apply values to os.environ. Returns keys that were set."""
    applied: list[str] = []
    for key, value in values.items():
        if only_missing and key in os.environ:
            continue
        os.environ[key] = value
        applied.append(key)
    return applied


def detect_amd_gateway_key(key: str) -> bool:
    """Detect AMD LLM Gateway keys by prefix pattern."""
    if not key:
        return False
    key = key.strip()
    if key.startswith("llm_"):
        return True
    if len(key) == 32 and all(c in "0123456789abcdefABCDEF" for c in key):
        return True
    return False


def _auto_configure_amd_gateway() -> bool:
    """If the API key looks like an AMD Gateway key, auto-set gateway env vars."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not detect_amd_gateway_key(key):
        return False
    if os.environ.get("ANTHROPIC_CUSTOM_HEADERS", ""):
        return False
    os.environ["ANTHROPIC_CUSTOM_HEADERS"] = f"Ocp-Apim-Subscription-Key: {key}"
    if not os.environ.get("ANTHROPIC_BASE_URL") or os.environ["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com":
        os.environ["ANTHROPIC_BASE_URL"] = "https://llm.amd.com/Anthropic"
    os.environ["ANTHROPIC_API_KEY"] = "dummy"
    return True


def _configured_from_environ() -> bool:
    _auto_configure_amd_gateway()

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key and key != "dummy":
        return True
    if key == "dummy":
        raw = os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "")
        for part in re.split(r"[,\n]", raw):
            part = part.strip()
            if ":" not in part:
                continue
            header_key = part.split(":", 1)[0].strip().lower()
            if header_key in ("ocp-apim-subscription-key", "x-api-key", "authorization"):
                return True
    return False


def load_credentials() -> str:
    """Load API credentials. Priority: shell env > .env > Claude settings files."""
    if _configured_from_environ():
        return "environment"

    load_dotenv(ENV_FILE)
    if _configured_from_environ():
        return ".env"

    contributed: list[str] = []
    for path, label in CLAUDE_SETTINGS_CANDIDATES:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        applied = apply_env_dict(extract_settings_env(data), only_missing=True)
        if applied:
            contributed.append(label)

    if _configured_from_environ():
        return contributed[0] if contributed else "claude settings"
    return "none"


def _reload_hyperloom_env() -> None:
    """Re-read HyperLoom env vars after dotenv / settings loading."""
    global HYPERLOOM_KB_URL, HYPERLOOM_KB_TOKEN, HYPERLOOM_INSTALL_DIR, INFERFORGE_JWT_SECRET
    HYPERLOOM_KB_URL = os.environ.get("HYPERLOOM_KB_URL", HYPERLOOM_KB_URL)
    HYPERLOOM_KB_TOKEN = os.environ.get("HYPERLOOM_KB_TOKEN", HYPERLOOM_KB_TOKEN)
    HYPERLOOM_INSTALL_DIR = os.environ.get("HYPERLOOM_INSTALL_DIR", HYPERLOOM_INSTALL_DIR)
    INFERFORGE_JWT_SECRET = os.environ.get("INFERFORGE_JWT_SECRET", INFERFORGE_JWT_SECRET)


CREDENTIAL_SOURCE = load_credentials()
_reload_hyperloom_env()

# --- Claude API ---
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def parse_custom_headers() -> dict:
    raw = os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "")
    headers = {}
    if not raw:
        return headers
    for part in re.split(r"[,\n]", raw):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            headers[k.strip()] = v.strip()
    return headers


CUSTOM_HEADERS = parse_custom_headers()


def is_api_configured() -> bool:
    """True when a direct API key or AMD gateway subscription header is present."""
    if API_KEY and API_KEY != "dummy":
        return True
    if API_KEY == "dummy" and any(
        k.lower() in ("ocp-apim-subscription-key", "x-api-key", "authorization")
        for k in CUSTOM_HEADERS
    ):
        return True
    return False


def api_config_error_message() -> str:
    return (
        "Anthropic API credentials are not configured.\n\n"
        "Set credentials via one of:\n"
        "  * Environment variables (ANTHROPIC_API_KEY, etc.)\n"
        "  * .env file in the InferForge root\n"
        "  * ~/.claude/settings.json (env block)\n\n"
        "AMD internal gateway example:\n"
        "  ANTHROPIC_API_KEY=dummy\n"
        "  ANTHROPIC_BASE_URL=https://llm-api.your-domain.com/Anthropic\n"
        "  ANTHROPIC_CUSTOM_HEADERS=Ocp-Apim-Subscription-Key: YOUR_SUBSCRIPTION_KEY"
    )


def verify_api_connection(timeout: float = 15.0) -> dict:
    """Probe the Anthropic API with a minimal request. Returns {ok, message}."""
    if not is_api_configured():
        return {"ok": False, "message": api_config_error_message()}

    if os.environ.get("INFERFORGE_SKIP_API_VERIFY", "").lower() in ("1", "true", "yes"):
        return {"ok": True, "message": "Skipped (INFERFORGE_SKIP_API_VERIFY)"}

    try:
        import anthropic
    except ImportError:
        return {
            "ok": False,
            "message": "Could not verify API -- install anthropic (pip install anthropic)",
        }

    try:
        client = anthropic.Anthropic(
            api_key=API_KEY,
            base_url=BASE_URL,
            default_headers=CUSTOM_HEADERS if CUSTOM_HEADERS else None,
            timeout=timeout,
        )
        client.messages.create(
            model=MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return {"ok": True, "message": "Connected"}
    except Exception as exc:
        return {
            "ok": False,
            "message": (
                "Could not connect to the Anthropic API. Check ANTHROPIC_API_KEY, "
                "ANTHROPIC_BASE_URL, and network, then restart the server. "
                f"({exc})"
            ),
        }


API_CONNECTION = verify_api_connection()


def is_api_connected() -> bool:
    """True when credentials exist and a live API probe succeeded."""
    return API_CONNECTION.get("ok", False)


def api_connection_error_message() -> str:
    msg = API_CONNECTION.get("message", "")
    if msg:
        return msg
    return (
        "Anthropic API credentials are present but the connection check failed. "
        "Verify your key or subscription header and restart the server."
    )


# --- Server ---
HOST = os.environ.get("INFERFORGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("INFERFORGE_PORT", "7801"))
AUTH_USER = os.environ.get("INFERFORGE_AUTH_USER", "")
AUTH_PASS = os.environ.get("INFERFORGE_AUTH_PASS", "")

# --- Safety deny patterns ---
BLOCKED_PATTERNS = [
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -fr /",
    "rm -rf --no-preserve-root", "mkfs", "fdisk", "dd if=",
    "reboot", "shutdown", "poweroff", "halt", "init 0", "init 6",
    "systemctl reboot", "systemctl poweroff",
    "git push --force", "git push -f",
    "chmod -R 777 /", "chown -R",
]

# --- Skill discovery ---
def discover_skills() -> dict:
    skills = {}
    if not SKILLS_DIR.is_dir():
        return skills
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        name = skill_dir.name
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        lines = content.strip().split("\n")
        desc = ""
        for line in lines:
            if line.startswith("#"):
                continue
            if line.strip():
                desc = line.strip()[:120]
                break
        skills[name] = {
            "name": name,
            "description": desc,
            "skill_file": str(skill_md),
            "content_length": len(content),
        }
    return skills

SKILLS = discover_skills()

# --- Load CLAUDE.md ---
def load_claude_md() -> str:
    if CLAUDE_MD.exists():
        return CLAUDE_MD.read_text(encoding="utf-8", errors="replace")
    return ""

def load_skill_content(skill_name: str) -> str:
    skill = SKILLS.get(skill_name)
    if not skill:
        return ""
    try:
        return Path(skill["skill_file"]).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
