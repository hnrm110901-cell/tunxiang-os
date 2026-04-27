"""Pydantic V2 请求 / 响应 schema 集合。"""

from .application import (
    ApplicationCreate,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationUpdate,
)

__all__ = [
    "ApplicationCreate",
    "ApplicationUpdate",
    "ApplicationResponse",
    "ApplicationListResponse",
]
