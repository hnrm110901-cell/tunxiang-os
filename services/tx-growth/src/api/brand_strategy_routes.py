"""品牌策略中枢 API

端点：
  GET  /api/v1/brand/profile                     当前激活的品牌档案
  POST /api/v1/brand/profile                     创建品牌档案
  PUT  /api/v1/brand/profile/{id}                更新品牌档案（version +1）

  GET  /api/v1/brand/calendar                    营销日历列表
  POST /api/v1/brand/calendar                    添加营销节点

  GET  /api/v1/brand/constraints                 内容约束规则列表
  POST /api/v1/brand/constraints                 添加内容约束

  GET  /api/v1/brand/content-brief               生成内容简报
       ?channel=wechat&segment=高价值常客&purpose=复购召回
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from models.brand_strategy import (
    BrandContentConstraintsCreate,
    BrandProfileCreate,
    BrandProfileUpdate,
    BrandSeasonalCalendarCreate,
)
from services.brand_strategy_db_service import BrandStrategyDbService

from shared.ontology.src.database import get_db_with_tenant

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/brand", tags=["brand-strategy"])

_svc = BrandStrategyDbService()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


def _parse_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    """从 Header 解析租户 UUID，校验格式"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID header")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {x_tenant_id!r}")


async def get_tenant_db(
    x_tenant_id: Optional[str] = Header(default=None),
) -> Any:
    """FastAPI 依赖：解析租户 ID 并返回 (tenant_id, db) 元组"""
    tenant_id = _parse_tenant(x_tenant_id)
    async for db in get_db_with_tenant(str(tenant_id)):
        yield tenant_id, db


# ---------------------------------------------------------------------------
# 品牌档案
# ---------------------------------------------------------------------------


@router.get("/profile")
async def get_active_profile(
    ctx: tuple = Depends(get_tenant_db),
) -> dict:
    """获取当前激活的品牌档案"""
    tenant_id, db = ctx
    profile = await _svc.get_active_profile(tenant_id, db)
    if profile is None:
        raise HTTPException(status_code=404, detail="尚未配置品牌档案")
    return ok_response(profile)


@router.post("/profile", status_code=201)
async def create_profile(
    body: BrandProfileCreate,
    ctx: tuple = Depends(get_tenant_db),
) -> dict:
    """创建品牌档案

    若 is_active=True（默认），会将同租户其他档案设为非激活。
    """
    tenant_id, db = ctx
    try:
        profile = await _svc.create_profile(tenant_id, body, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok_response(profile)


@router.put("/profile/{profile_id}")
async def update_profile(
    profile_id: uuid.UUID,
    body: BrandProfileUpdate,
    ctx: tuple = Depends(get_tenant_db),
) -> dict:
    """更新品牌档案，version 自动 +1"""
    tenant_id, db = ctx
    try:
        profile = await _svc.update_profile(tenant_id, profile_id, body, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if profile is None:
        raise HTTPException(status_code=404, detail=f"品牌档案不存在: {profile_id}")
    return ok_response(profile)


# ---------------------------------------------------------------------------
# 营销日历
# ---------------------------------------------------------------------------


@router.get("/calendar")
async def list_calendar(
    brand_profile_id: Optional[uuid.UUID] = Query(default=None, description="按品牌档案 ID 过滤"),
    ctx: tuple = Depends(get_tenant_db),
) -> dict:
    """获取营销日历列表"""
    tenant_id, db = ctx
    entries = await _svc.list_calendar(tenant_id, db, brand_profile_id=brand_profile_id)
    return ok_response({"items": entries, "total": len(entries)})


@router.post("/calendar", status_code=201)
async def add_calendar_entry(
    body: BrandSeasonalCalendarCreate,
    ctx: tuple = Depends(get_tenant_db),
) -> dict:
    """添加营销日历节点（节气/节日/自定义）"""
    tenant_id, db = ctx
    try:
        entry = await _svc.create_calendar_entry(tenant_id, body, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok_response(entry)


# ---------------------------------------------------------------------------
# 内容约束规则
# ---------------------------------------------------------------------------


@router.get("/constraints")
async def list_constraints(
    brand_profile_id: Optional[uuid.UUID] = Query(default=None, description="按品牌档案 ID 过滤"),
    ctx: tuple = Depends(get_tenant_db),
) -> dict:
    """获取所有内容约束规则列表"""
    tenant_id, db = ctx
    constraints = await _svc.list_constraints(tenant_id, db, brand_profile_id=brand_profile_id)
    return ok_response({"items": constraints, "total": len(constraints)})


@router.post("/constraints", status_code=201)
async def add_constraint(
    body: BrandContentConstraintsCreate,
    ctx: tuple = Depends(get_tenant_db),
) -> dict:
    """添加内容约束规则"""
    tenant_id, db = ctx
    try:
        constraint = await _svc.create_constraint(tenant_id, body, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok_response(constraint)


# ---------------------------------------------------------------------------
# 内容简报（核心端点）
# ---------------------------------------------------------------------------


@router.get("/content-brief")
async def get_content_brief(
    channel: str = Query(..., description="渠道：wechat/miniapp/sms/poster/wecom/douyin/xiaohongshu"),
    segment: str = Query(..., description="目标客群名称，如「高价值常客」"),
    purpose: str = Query(..., description="内容目的，如「复购召回」「节日祝福」「新品推介」"),
    ctx: tuple = Depends(get_tenant_db),
) -> dict:
    """生成完整内容简报，供 content_generation agent 消费

    返回的 system_prompt 字段可直接注入 LLM 的 system message，
    涵盖品牌约束、渠道规则、节气上下文、目标客群描述。

    示例：
      GET /api/v1/brand/content-brief?channel=wechat&segment=高价值常客&purpose=复购召回
    """
    tenant_id, db = ctx
    try:
        brief = await _svc.build_content_brief(tenant_id, channel, segment, purpose, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok_response(brief.model_dump(mode="json"))
