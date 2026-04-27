"""Application Pydantic schemas（V2 风格）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.application import VALID_RESOURCE_TYPES


class ApplicationCreate(BaseModel):
    """创建应用请求体。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=100, description="租户内唯一标识")
    name: str = Field(..., min_length=1, max_length=200)
    resource_type: str = Field(
        ...,
        description=(
            "资源类型：backend_service / frontend_app / edge_image / adapter / data_asset"
        ),
    )
    owner: str | None = Field(default=None, max_length=200)
    repo_path: str | None = Field(default=None, max_length=500)
    tech_stack: str | None = Field(default=None, max_length=50)
    description: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("resource_type")
    @classmethod
    def _check_resource_type(cls, value: str) -> str:
        if value not in VALID_RESOURCE_TYPES:
            raise ValueError(
                f"resource_type must be one of {VALID_RESOURCE_TYPES}, got {value!r}"
            )
        return value


class ApplicationUpdate(BaseModel):
    """更新应用请求体（PATCH 部分字段）。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    resource_type: str | None = None
    owner: str | None = Field(default=None, max_length=200)
    repo_path: str | None = Field(default=None, max_length=500)
    tech_stack: str | None = Field(default=None, max_length=50)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("resource_type")
    @classmethod
    def _check_resource_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in VALID_RESOURCE_TYPES:
            raise ValueError(
                f"resource_type must be one of {VALID_RESOURCE_TYPES}, got {value!r}"
            )
        return value


class ApplicationResponse(BaseModel):
    """应用详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    resource_type: str
    owner: str | None
    repo_path: str | None
    tech_stack: str | None
    description: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class ApplicationListResponse(BaseModel):
    """分页列表响应。"""

    items: list[ApplicationResponse]
    total: int
    page: int
    size: int
