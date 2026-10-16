"""Pydantic models for fleet management -- GPU node inventory and reservations."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class NodeStatus(str, Enum):
    online = "online"
    offline = "offline"
    reserved = "reserved"
    maintenance = "maintenance"
    unknown = "unknown"


class FleetNodeCreate(BaseModel):
    hostname: str = Field(min_length=1, max_length=256)
    ip_address: str | None = Field(default=None, max_length=45)
    ssh_user: str | None = Field(default=None, max_length=64)
    ssh_key_path: str | None = Field(default=None, max_length=512)
    gpu_platform: str | None = Field(default=None, max_length=64)
    gpu_count: int = Field(default=0, ge=0, le=512)
    hbm_per_gpu_gb: float = Field(default=0, ge=0)
    rocm_version: str | None = Field(default=None, max_length=32)

    @field_validator("hostname")
    @classmethod
    def hostname_no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("Hostname must not contain spaces")
        return v.strip()


class FleetNodeResponse(BaseModel):
    id: str
    hostname: str
    ip_address: str | None = None
    ssh_user: str | None = None
    ssh_key_path: str | None = None
    gpu_platform: str | None = None
    gpu_count: int = 0
    hbm_per_gpu_gb: float = 0
    rocm_version: str | None = None
    status: NodeStatus = NodeStatus.unknown
    last_probed: str | None = None
    metadata_json: dict | None = None


class FleetReservationCreate(BaseModel):
    node_id: str = Field(min_length=1, max_length=36)
    gpu_start: int = Field(default=0, ge=0)
    gpu_count: int = Field(default=1, ge=1, le=512)
    campaign_id: str | None = Field(default=None, max_length=36)
    conversation_id: str | None = Field(default=None, max_length=36)
    expires_hours: float | None = Field(default=None, gt=0, le=720)

    @field_validator("gpu_count")
    @classmethod
    def gpu_count_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("gpu_count must be >= 1")
        return v


class FleetReservationResponse(BaseModel):
    id: str
    node_id: str
    campaign_id: str | None = None
    conversation_id: str | None = None
    gpu_start: int = 0
    gpu_count: int = 1
    reserved_at: str | None = None
    expires_at: str | None = None
    released_at: str | None = None


class NodeProbeResult(BaseModel):
    """Result from SSH-probing a fleet node via amd-smi."""

    hostname: str
    reachable: bool = False
    ssh_key_used: str | None = None
    gpu_platform: str | None = None
    gpu_count: int = 0
    hbm_per_gpu_gb: float = 0
    rocm_version: str | None = None
    driver_version: str | None = None
    docker_available: bool = False
    error: str | None = None
    probed_at: str | None = None

    @property
    def total_hbm_gb(self) -> float:
        return self.gpu_count * self.hbm_per_gpu_gb
