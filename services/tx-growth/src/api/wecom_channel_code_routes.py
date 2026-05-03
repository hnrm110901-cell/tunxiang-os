"""渠道活码 API 路由

POST   /api/v1/growth/wecom/channel-codes              — 创建渠道活码
GET    /api/v1/growth/wecom/channel-codes              — 查询渠道活码列表
GET    /api/v1/growth/wecom/channel-codes/{id}          — 获取渠道活码详情
GET    /api/v1/growth/wecom/channel-codes/{id}/stats    — 渠道扫码统计
POST   /api/v1/growth/wecom/channel-codes/{id}/handle-scan — 处理扫码回调
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.wecom_channel_code_service import wecom_channel_code_service


# 懒加载 get_db 依赖，避免在 Python 3.9 环境中触发 shared 模块导入
async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：获取数据库 session"""
    from shared.ontology.src.database import get_db

    async for session in get_db():
        yield session


get_db = _get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/wecom", tags=["wecom-channel-code"])


# ─────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────


class CreateChannelCodeRequest(BaseModel):
    merchant_code: str = Field(..., min_length=1, max_length=100, description="商户编码")
    channel_name: str = Field(..., min_length=1, max_length=200, description='渠道名称，如"海报-店门口-2026Q2"')
    qrcode_url: str = Field(..., min_length=1, description="企微联系二维码URL")
    auto_tags: list[str] = Field(default_factory=list, description="自动打标签列表")
    auto_reply: str = Field(default="", description="自动回复文案")
    group_id: Optional[str] = Field(default=None, description="自动拉群ID")


class HandleScanRequest(BaseModel):
    external_userid: str = Field(..., min_length=1, description="企微外部联系人ID")


# ─────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────


@router.post("/channel-codes")
async def create_channel_code(
    req: CreateChannelCodeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建渠道活码"""
    logger.info(
        "create_channel_code",
        merchant_code=req.merchant_code,
        channel_name=req.channel_name,
        tenant_id=x_tenant_id,
    )

    code = await wecom_channel_code_service.create_channel_code(
        merchant_code=req.merchant_code,
        channel_name=req.channel_name,
        qrcode_url=req.qrcode_url,
        auto_tags=req.auto_tags,
        auto_reply=req.auto_reply,
        group_id=req.group_id,
        tenant_id=x_tenant_id,
        db=db,
    )

    return {"ok": True, "data": code.to_dict()}


@router.get("/channel-codes")
async def list_channel_codes(
    merchant_code: Optional[str] = Query(None, description="商户编码（可选筛选）"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询渠道活码列表（分页，可按商户编码筛选）"""
    logger.info(
        "list_channel_codes",
        merchant_code=merchant_code,
        page=page,
        size=size,
        tenant_id=x_tenant_id,
    )

    result = await wecom_channel_code_service.get_channel_codes(
        merchant_code=merchant_code,
        page=page,
        size=size,
        tenant_id=x_tenant_id,
        db=db,
    )

    return {"ok": True, "data": result}


@router.get("/channel-codes/{channel_id}")
async def get_channel_code_detail(
    channel_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取渠道活码详情"""
    logger.info(
        "get_channel_code_detail",
        channel_id=channel_id,
        tenant_id=x_tenant_id,
    )

    code = await wecom_channel_code_service.get_channel_code(
        channel_id=channel_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    if code is None:
        raise HTTPException(status_code=404, detail="渠道活码不存在")

    return {"ok": True, "data": code.to_dict()}


@router.get("/channel-codes/{channel_id}/stats")
async def get_channel_code_stats(
    channel_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """渠道扫码统计"""
    logger.info(
        "get_channel_code_stats",
        channel_id=channel_id,
        tenant_id=x_tenant_id,
    )

    stats = await wecom_channel_code_service.get_channel_stats(
        channel_id=channel_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    if "error" in stats:
        raise HTTPException(status_code=404, detail=stats["error"])

    return {"ok": True, "data": stats}


@router.post("/channel-codes/{channel_id}/handle-scan")
async def handle_channel_scan(
    channel_id: str,
    req: HandleScanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """处理扫码回调事件（自动打标签 + 自动回复 + 自动拉群）"""
    logger.info(
        "handle_channel_scan",
        channel_id=channel_id,
        external_userid=req.external_userid,
        tenant_id=x_tenant_id,
    )

    result = await wecom_channel_code_service.handle_scan(
        channel_id=channel_id,
        external_userid=req.external_userid,
        tenant_id=x_tenant_id,
        db=db,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "处理扫码事件失败"))

    return {"ok": True, "data": result}
