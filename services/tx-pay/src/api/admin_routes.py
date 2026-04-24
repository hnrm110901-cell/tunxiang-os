"""支付管理 API — 渠道配置、路由管理

端点：
  GET  /api/v1/pay/admin/channels              — 列出已注册渠道
  GET  /api/v1/pay/admin/configs               — 查询渠道配置
  POST /api/v1/pay/admin/configs               — 创建/更新渠道配置
  POST /api/v1/pay/admin/cache/invalidate      — 清除路由缓存
"""
from __future__ import annotations

import json
from typing import Optional

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..channels.base import PayMethod

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/pay/admin", tags=["支付管理"])


class ChannelConfigReq(BaseModel):
    """渠道配置请求"""
    brand_id: Optional[str] = None
    store_id: Optional[str] = None
    method: PayMethod
    channel_name: str
    priority: int = 0
    is_active: bool = True
    config_data: dict = Field(default_factory=dict)


class CacheInvalidateReq(BaseModel):
    tenant_id: Optional[str] = None
    store_id: Optional[str] = None


# ─── 端点 ───────────────────────────────────────────────────────────

@router.get("/channels")
async def list_channels():
    """列出所有已注册的支付渠道"""
    from ..deps import get_channel_registry

    registry = await get_channel_registry()
    return {"ok": True, "data": registry.list_channels()}


@router.get("/configs")
async def list_configs(
    store_id: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询渠道配置"""
    from ..deps import get_db

    db = await get_db()
    from sqlalchemy import text
    query = """
        SELECT id, tenant_id, brand_id, store_id, method, channel_name,
               priority, is_active, config_data, created_at
        FROM payment_channel_configs
        WHERE tenant_id = :tenant_id::UUID
    """
    params: dict = {"tenant_id": x_tenant_id}
    if store_id:
        query += " AND (store_id = :store_id::UUID OR store_id IS NULL)"
        params["store_id"] = store_id
    query += " ORDER BY priority DESC"

    result = await db.execute(text(query), params)
    rows = result.fetchall()
    configs = [
        {
            "id": str(r[0]),
            "tenant_id": str(r[1]),
            "brand_id": str(r[2]) if r[2] else None,
            "store_id": str(r[3]) if r[3] else None,
            "method": r[4],
            "channel_name": r[5],
            "priority": r[6],
            "is_active": r[7],
            "config_data": r[8] or {},
        }
        for r in rows
    ]
    return {"ok": True, "data": configs}


@router.post("/configs")
async def upsert_config(
    req: ChannelConfigReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建或更新渠道配置"""
    from ..deps import get_db, get_routing_engine

    db = await get_db()
    from sqlalchemy import text
    await db.execute(
        text("""
            INSERT INTO payment_channel_configs (
                tenant_id, brand_id, store_id, method,
                channel_name, priority, is_active, config_data
            ) VALUES (
                :tenant_id::UUID,
                CASE WHEN :brand_id = '' THEN NULL ELSE :brand_id::UUID END,
                CASE WHEN :store_id = '' THEN NULL ELSE :store_id::UUID END,
                :method, :channel_name, :priority, :is_active, :config_data::JSONB
            )
            ON CONFLICT (tenant_id, COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::UUID), method)
            DO UPDATE SET
                channel_name = EXCLUDED.channel_name,
                priority = EXCLUDED.priority,
                is_active = EXCLUDED.is_active,
                config_data = EXCLUDED.config_data,
                updated_at = NOW()
        """),
        {
            "tenant_id": x_tenant_id,
            "brand_id": req.brand_id or "",
            "store_id": req.store_id or "",
            "method": req.method.value,
            "channel_name": req.channel_name,
            "priority": req.priority,
            "is_active": req.is_active,
            "config_data": json.dumps(req.config_data, ensure_ascii=False),
        },
    )
    await db.commit()

    # 清除缓存
    engine = await get_routing_engine()
    engine.invalidate_cache(tenant_id=x_tenant_id, store_id=req.store_id)

    return {"ok": True, "data": {"message": "配置已保存"}}


@router.post("/cache/invalidate")
async def invalidate_cache(req: CacheInvalidateReq):
    """手动清除路由缓存"""
    from ..deps import get_routing_engine

    engine = await get_routing_engine()
    cleared = engine.invalidate_cache(
        tenant_id=req.tenant_id,
        store_id=req.store_id,
    )
    return {"ok": True, "data": {"cleared": cleared}}
