"""HTTP client for the Hyperloom Experience Knowledge Base (KB).

Provides async methods to search, retrieve, and sync optimization recipes
from the centralized KB into InferForge's local SQLite database.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

import httpx

from ..db.connection import get_connection

logger = logging.getLogger(__name__)

# Default timeout for KB API requests
_DEFAULT_TIMEOUT = 30.0


class RecipeClient:
    """Async HTTP client for the Hyperloom Experience KB API."""

    def __init__(self, kb_url: str, kb_token: str, timeout: float = _DEFAULT_TIMEOUT):
        """Initialize the recipe client.

        Parameters
        ----------
        kb_url:
            Base URL of the Experience KB API (e.g. ``https://kb.hyperloom.example.com``).
        kb_token:
            Bearer token for KB API authentication.
        timeout:
            HTTP request timeout in seconds.
        """
        self._base_url = kb_url.rstrip("/")
        self._token = kb_token
        self._timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {kb_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def search_recipes(
        self,
        model_family: str,
        gpu_type: str,
        framework: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search the KB for optimization recipes matching the criteria.

        Parameters
        ----------
        model_family:
            Model family to search for (e.g. ``llama``, ``qwen``).
        gpu_type:
            Target GPU type (e.g. ``mi300x``).
        framework:
            Optional framework filter (``vllm``, ``sglang``).
        limit:
            Maximum number of results to return.

        Returns
        -------
        list[dict]
            List of recipe dicts from the KB.
        """
        params: dict[str, Any] = {
            "model_family": model_family,
            "gpu_type": gpu_type,
            "limit": limit,
        }
        if framework:
            params["framework"] = framework

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/recipes/search",
                    params=params,
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()

                # Handle both {"recipes": [...]} and bare list responses
                if isinstance(data, list):
                    return data
                return data.get("recipes", data.get("results", []))

        except httpx.HTTPStatusError as exc:
            logger.error(
                "KB search failed: %d %s", exc.response.status_code, exc.response.text[:200]
            )
            return []
        except httpx.RequestError as exc:
            logger.error("KB request error: %s", exc)
            return []

    async def get_recipe(self, recipe_id: str) -> dict | None:
        """Retrieve a single recipe by ID from the KB.

        Returns None if the recipe is not found or the request fails.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/recipes/{recipe_id}",
                    headers=self._headers,
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()

        except httpx.HTTPStatusError as exc:
            logger.error(
                "KB get recipe failed: %d %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return None
        except httpx.RequestError as exc:
            logger.error("KB request error: %s", exc)
            return None

    async def list_recipes(
        self,
        gpu_type: str | None = None,
        framework: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """List recipes from the KB with optional filters."""
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if gpu_type:
            params["gpu_type"] = gpu_type
        if framework:
            params["framework"] = framework

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/recipes",
                    params=params,
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return data
                return data.get("recipes", data.get("results", []))

        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.error("KB list recipes failed: %s", exc)
            return []

    async def sync_to_db(self, db_path: str | None = None) -> int:
        """Sync recipes from the KB to the local SQLite database.

        Fetches all recipes from the KB and upserts them into the local
        ``recipes`` table. Existing recipes (matched by ``kb_record_id``)
        are updated; new ones are inserted.

        Returns the count of new or updated recipes.
        """
        conn = get_connection(db_path)

        # Fetch all recipes from KB (paginated)
        all_recipes: list[dict] = []
        offset = 0
        page_size = 100

        while True:
            page = await self.list_recipes(offset=offset, limit=page_size)
            if not page:
                break
            all_recipes.extend(page)
            if len(page) < page_size:
                break
            offset += page_size

        if not all_recipes:
            logger.info("No recipes found in KB to sync")
            return 0

        count = 0
        for kb_recipe in all_recipes:
            try:
                upserted = _upsert_recipe_from_kb(conn, kb_recipe)
                if upserted:
                    count += 1
            except Exception as exc:
                logger.error("Failed to upsert recipe %s: %s", kb_recipe.get("id", "?"), exc)

        conn.commit()
        logger.info("Synced %d recipes from KB", count)
        return count

    async def health_check(self) -> dict:
        """Check KB API connectivity. Returns ``{ok: bool, message: str}``."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/health",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "Connected"}
                return {
                    "ok": False,
                    "message": f"HTTP {resp.status_code}: {resp.text[:100]}",
                }
        except httpx.RequestError as exc:
            return {"ok": False, "message": str(exc)}


# ---------------------------------------------------------------------------
# Local DB helpers
# ---------------------------------------------------------------------------

def _upsert_recipe_from_kb(conn, kb_recipe: dict) -> bool:
    """Upsert a KB recipe into the local recipes table. Returns True if modified."""
    kb_id = kb_recipe.get("id", kb_recipe.get("record_id", ""))
    if not kb_id:
        return False

    # Check if already exists
    existing = conn.execute(
        "SELECT id, updated_at FROM recipes WHERE kb_record_id = ?", (kb_id,)
    ).fetchone()

    local_row = _kb_to_local_recipe(kb_recipe)

    if existing:
        # Update if KB version is newer
        kb_updated = kb_recipe.get("updated_at", "")
        local_updated = dict(existing).get("updated_at", "")
        if kb_updated and local_updated and kb_updated <= local_updated:
            return False  # Already up to date

        local_id = dict(existing)["id"]
        _update_recipe(conn, local_id, local_row)
        return True
    else:
        _insert_recipe(conn, local_row)
        return True


def _kb_to_local_recipe(kb_recipe: dict) -> dict:
    """Map a KB recipe response to the local recipes table schema."""
    return {
        "id": str(uuid.uuid4())[:12],
        "model_family": kb_recipe.get("model_family", ""),
        "model_name": kb_recipe.get("model_name", ""),
        "gpu_type": kb_recipe.get("gpu_type", ""),
        "framework": kb_recipe.get("framework", "vllm"),
        "optimizations_json": json.dumps(kb_recipe.get("optimizations", [])),
        "server_args": kb_recipe.get("server_args", ""),
        "kernel_patches_json": json.dumps(kb_recipe.get("kernel_patches", [])),
        "baseline_tps": kb_recipe.get("baseline_tps"),
        "optimized_tps": kb_recipe.get("optimized_tps"),
        "gain_pct": kb_recipe.get("gain_pct"),
        "source": "kb",
        "source_session_id": kb_recipe.get("source_session_id"),
        "kb_record_id": kb_recipe.get("id", kb_recipe.get("record_id")),
        "updated_at": datetime.utcnow().isoformat(),
    }


def _insert_recipe(conn, row: dict) -> None:
    cols = [k for k in row.keys() if row[k] is not None]
    vals = [row[k] for k in cols]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    with conn:
        conn.execute(
            f"INSERT INTO recipes ({col_names}) VALUES ({placeholders})", vals
        )


def _update_recipe(conn, recipe_id: str, row: dict) -> None:
    skip = {"id"}
    updates = []
    vals = []
    for col, val in row.items():
        if col in skip or val is None:
            continue
        updates.append(f"{col} = ?")
        vals.append(val)
    if not updates:
        return
    vals.append(recipe_id)
    with conn:
        conn.execute(
            f"UPDATE recipes SET {', '.join(updates)} WHERE id = ?", vals
        )
