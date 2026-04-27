"""Application CRUD 路由 (/api/v1/devforge/applications)。"""

from __future__ import annotations

import asyncio
from typing import Annotated, AsyncGenerator
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import DevForgeApplicationEventType

from ..db import get_db_with_tenant, validate_tenant_id
from ..repositories.application import ApplicationAlreadyExists, ApplicationRepository
from ..schemas.application import (
    ApplicationCreate,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationUpdate,
)

SOURCE_SERVICE = "tx-devforge"

router = APIRouter(prefix="/api/v1/devforge/applications", tags=["applications"])
logger = structlog.get_logger(__name__)

TenantHeader = Annotated[
    str,
    Header(
        alias="X-Tenant-ID",
        description="租户 UUID（RLS 隔离）",
    ),
]


async def _tenant_session(
    x_tenant_id: TenantHeader,
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency：解析 X-Tenant-ID 并返回带 RLS 的 session。

    通过 async for + yield 完整消费 inner generator，
    让 get_db_with_tenant 的 commit/rollback/close 在 FastAPI
    响应结束后正确触发，避免连接池泄漏与未提交事务。
    """

    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _ok(data: object) -> dict[str, object]:
    return {"ok": True, "data": data, "error": {}}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_application(
    body: ApplicationCreate,
    x_tenant_id: TenantHeader,
    session: AsyncSession = Depends(_tenant_session),
) -> dict[str, object]:
    tenant_uuid = UUID(validate_tenant_id(x_tenant_id))
    repo = ApplicationRepository(session)
    try:
        created = await repo.create(tenant_uuid, body.model_dump())
    except ApplicationAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "duplicate_code", "message": str(exc)},
        ) from exc

    payload = ApplicationResponse.model_validate(created).model_dump(mode="json")
    # 旁路写入事件总线（CLAUDE.md §15，v147 规范）— 失败不阻塞业务响应
    asyncio.create_task(
        emit_event(
            event_type=DevForgeApplicationEventType.CREATED,
            tenant_id=tenant_uuid,
            stream_id=str(created.id),
            payload={
                "code": created.code,
                "name": created.name,
                "resource_type": created.resource_type,
                "owner": created.owner,
                "tech_stack": created.tech_stack,
            },
            source_service=SOURCE_SERVICE,
        )
    )
    return _ok(payload)


@router.get("", response_model=None)
async def list_applications(
    x_tenant_id: TenantHeader,
    resource_type: str | None = Query(default=None, description="按资源类型过滤"),
    code: str | None = Query(default=None, description="按 code 精确匹配（用于 upsert 路径反查 id）"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(_tenant_session),
) -> dict[str, object]:
    tenant_uuid = UUID(validate_tenant_id(x_tenant_id))
    repo = ApplicationRepository(session)
    items, total = await repo.list(
        tenant_uuid,
        resource_type=resource_type,
        code=code,
        page=page,
        size=size,
    )
    payload = ApplicationListResponse(
        items=[ApplicationResponse.model_validate(it) for it in items],
        total=total,
        page=page,
        size=size,
    ).model_dump(mode="json")
    return _ok(payload)


@router.get("/{application_id}", response_model=None)
async def get_application(
    application_id: UUID,
    x_tenant_id: TenantHeader,
    session: AsyncSession = Depends(_tenant_session),
) -> dict[str, object]:
    tenant_uuid = UUID(validate_tenant_id(x_tenant_id))
    repo = ApplicationRepository(session)
    found = await repo.get_by_id(tenant_uuid, application_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "application not found"},
        )
    payload = ApplicationResponse.model_validate(found).model_dump(mode="json")
    return _ok(payload)


@router.patch("/{application_id}", response_model=None)
async def update_application(
    application_id: UUID,
    body: ApplicationUpdate,
    x_tenant_id: TenantHeader,
    session: AsyncSession = Depends(_tenant_session),
) -> dict[str, object]:
    tenant_uuid = UUID(validate_tenant_id(x_tenant_id))
    patch = body.model_dump(exclude_unset=True)
    repo = ApplicationRepository(session)
    try:
        updated = await repo.update(tenant_uuid, application_id, patch)
    except ApplicationAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "duplicate_code", "message": str(exc)},
        ) from exc

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "application not found"},
        )

    payload = ApplicationResponse.model_validate(updated).model_dump(mode="json")
    asyncio.create_task(
        emit_event(
            event_type=DevForgeApplicationEventType.UPDATED,
            tenant_id=tenant_uuid,
            stream_id=str(updated.id),
            payload={
                "code": updated.code,
                "patched_fields": list(patch.keys()),
            },
            source_service=SOURCE_SERVICE,
        )
    )
    return _ok(payload)


@router.delete("/{application_id}", response_model=None)
async def delete_application(
    application_id: UUID,
    x_tenant_id: TenantHeader,
    session: AsyncSession = Depends(_tenant_session),
) -> dict[str, object]:
    tenant_uuid = UUID(validate_tenant_id(x_tenant_id))
    repo = ApplicationRepository(session)
    deleted = await repo.soft_delete(tenant_uuid, application_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "application not found"},
        )
    asyncio.create_task(
        emit_event(
            event_type=DevForgeApplicationEventType.DELETED,
            tenant_id=tenant_uuid,
            stream_id=str(application_id),
            payload={"soft_delete": True},
            source_service=SOURCE_SERVICE,
        )
    )
    return _ok({"id": str(application_id), "is_deleted": True})
