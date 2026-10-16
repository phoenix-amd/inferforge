"""Pydantic models for optimized serving recipes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KernelPatch(BaseModel):
    """A single kernel-level optimization patch."""

    name: str = Field(max_length=256)
    category: str = Field(default="kernel", max_length=64)
    description: str = Field(default="", max_length=1024)
    file_path: str | None = Field(default=None, max_length=512)
    env_vars: dict[str, str] = Field(default_factory=dict)
    triton_config: dict | None = None
    hipblaslt_config: dict | None = None


class OptimizationItem(BaseModel):
    """A single optimization in the recipe's optimization stack."""

    category: str = Field(max_length=64)
    name: str = Field(max_length=256)
    description: str = Field(default="", max_length=1024)
    value: str | None = None
    delta_pct: float | None = None


class RecipeCreate(BaseModel):
    model_name: str = Field(min_length=1, max_length=256)
    gpu_type: str = Field(min_length=1, max_length=64)
    framework: str = Field(default="vllm", max_length=32)

    model_family: str | None = Field(default=None, max_length=64)
    optimizations_json: list[OptimizationItem] | None = None
    server_args: str | None = Field(default=None, max_length=4096)
    kernel_patches_json: list[KernelPatch] | None = None

    baseline_tps: float | None = Field(default=None, ge=0)
    optimized_tps: float | None = Field(default=None, ge=0)
    gain_pct: float | None = None

    source: str | None = Field(default=None, max_length=64)
    source_session_id: str | None = Field(default=None, max_length=36)
    kb_record_id: str | None = Field(default=None, max_length=64)


class RecipeResponse(BaseModel):
    id: str
    model_family: str | None = None
    model_name: str
    gpu_type: str
    framework: str = "vllm"

    optimizations_json: list[dict] | None = None
    server_args: str | None = None
    kernel_patches_json: list[dict] | None = None

    baseline_tps: float | None = None
    optimized_tps: float | None = None
    gain_pct: float | None = None

    source: str | None = None
    source_session_id: str | None = None
    kb_record_id: str | None = None

    created_at: str | None = None
    updated_at: str | None = None

    @property
    def has_kernel_patches(self) -> bool:
        return bool(self.kernel_patches_json)

    @property
    def optimization_count(self) -> int:
        return len(self.optimizations_json) if self.optimizations_json else 0
