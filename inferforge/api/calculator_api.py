"""Memory calculator and model/GPU registry API routes."""

import json
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from inferforge.config import PROJECT_DIR

router = APIRouter(prefix="/api", tags=["calculator"])

_DATA_DIR = PROJECT_DIR / "inferforge" / "data"
_CALCULATOR_PATH = PROJECT_DIR / "inferforge" / "calculator" / "engine.py"


class CalculateRequest(BaseModel):
    model: str
    gpu: str = "MI300X"
    gpu_count: int = 8
    dtype: str = "bf16"
    seq_len: int = 4096
    kv_dtype: str | None = None
    extra_args: list[str] | None = None


@router.post("/calculate")
def api_calculate(body: CalculateRequest):
    if not _CALCULATOR_PATH.exists():
        raise HTTPException(
            503,
            f"engine.py not found at {_CALCULATOR_PATH}",
        )

    cmd = [
        sys.executable,
        str(_CALCULATOR_PATH),
        "--model", body.model,
        "--gpu", body.gpu,
        "--gpu-count", str(body.gpu_count),
        "--dtype", body.dtype,
        "--seq-len", str(body.seq_len),
        "--json",
    ]
    if body.kv_dtype:
        cmd.extend(["--kv-dtype", body.kv_dtype])
    if body.extra_args:
        cmd.extend(body.extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_DIR),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Calculator timed out")
    except Exception as e:
        raise HTTPException(500, f"Failed to run calculator: {e}")

    if result.returncode != 0:
        raise HTTPException(
            422,
            {
                "error": "Calculator returned non-zero exit code",
                "stderr": result.stderr.strip(),
                "stdout": result.stdout.strip(),
            },
        )

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(
            500,
            {
                "error": "Calculator output is not valid JSON",
                "raw_stdout": result.stdout[:2000],
            },
        )

    return output


@router.get("/models")
def api_list_models():
    registry_path = _DATA_DIR / "model_registry.json"
    if not registry_path.exists():
        return []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        raise HTTPException(500, "Failed to read model registry")
    if isinstance(data, dict):
        return [{"key": k, **v} for k, v in data.items()]
    return data


@router.get("/gpus")
def api_list_gpus():
    specs_path = _DATA_DIR / "gpu_specs.json"
    if not specs_path.exists():
        return []
    try:
        data = json.loads(specs_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        raise HTTPException(500, "Failed to read GPU specs")
    if isinstance(data, dict):
        return [{"key": k, **v} for k, v in data.items()]
    return data
