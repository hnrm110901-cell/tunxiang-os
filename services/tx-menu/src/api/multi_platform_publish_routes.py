"""菜单一键多平台发布 API

端点概览:
  POST /api/v1/menu/publish/all           — 一键发布全平台
  POST /api/v1/menu/publish/{platform}    — 发布到指定平台
  GET  /api/v1/menu/publish/status        — 同步状态
  POST /api/v1/menu/publish/retry/{platform} — 重试失败项

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.multi_platform_publish_service import MultiPlatformPublishService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/menu/publish", tags=["multi-platform-publish"])


# ─── 辅助 ───


def _err(status: int, msg: str) -> None:
    raise HTTPException(
        status_code=status,
        detail={"ok": False, "error": {"message": msg}},
    )


def _svc(db: AsyncSession, tenant_id: str) -> MultiPlatformPublishService:
    return MultiPlatformPublishService(db=db, tenant_id=tenant_id)


# ─── 请求模型 ───


class PublishAllReq(BaseModel):
    store_id: str
    dish_ids: Optional[list[str]] = Field(
        None, description="菜品ID列表, null时发布全部active菜品"
    )


class PublishPlatformReq(BaseModel):
    store_id: str
    dish_ids: Optional[list[str]] = Field(
        None, description="菜品ID列表, null时发布全部"
    )


# ─── 端点 ───


@router.post("/all")
async def publish_to_all(
    req: PublishAllReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """一键发布到所有平台(美团/饿了么/抖音)。

    dish_ids=null 时发布全部active菜品。
    """
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.publish_to_all(
            store_id=req.store_id,
            dish_ids=req.dish_ids,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    except SQLAlchemyError:
        log.exception("multi_platform_publish.all_api_error")
        _err(500, "发布失败，请稍后重试")
    return {"ok": False, "error": {"message": "未知错误"}}


@router.post("/{platform}")
async def publish_to_platform(
    platform: str,
    req: PublishPlatformReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发布到指定平台。

    platform: meituan / eleme / douyin
    """
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.publish_to_platform(
            store_id=req.store_id,
            platform=platform,
            dish_ids=req.dish_ids,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    except SQLAlchemyError:
        log.exception("multi_platform_publish.platform_api_error", platform=platform)
        _err(500, f"发布到 {platform} 失败，请稍后重试")
    return {"ok": False, "error": {"message": "未知错误"}}


@router.get("/status")
async def get_sync_status(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """各平台同步状态概览。"""
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.get_sync_status(store_id=store_id)
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    except SQLAlchemyError:
        log.exception("multi_platform_publish.status_api_error")
        _err(500, "查询同步状态失败")
    return {"ok": False, "error": {"message": "未知错误"}}


@router.post("/retry/{platform}")
async def retry_failed(
    platform: str,
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重试失败项。"""
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.retry_failed(
            store_id=store_id,
            platform=platform,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    except SQLAlchemyError:
        log.exception("multi_platform_publish.retry_api_error", platform=platform)
        _err(500, f"重试 {platform} 失败项失败")
    return {"ok": False, "error": {"message": "未知错误"}}
