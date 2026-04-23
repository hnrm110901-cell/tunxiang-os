"""KDS 显示规则配置 API — 颜色 / 超时 / 渠道高亮

# ROUTER REGISTRATION:
# from .api.kds_display_rules_routes import router as kds_display_rules_router
# app.include_router(kds_display_rules_router, prefix="/api/v1/kds")

端点清单：
  GET  /display-rules/{store_id}   — 获取门店 KDS 显示规则配置
  PUT  /display-rules/{store_id}   — 更新门店 KDS 显示规则配置

所有端点需要 X-Tenant-ID header。
持久化方式：kds_display_rules 表（v210 迁移创建）。
"""

from __future__ import annotations

import json
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(tags=["kds-display-rules"])


# ─── 公共依赖 ───────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求 / 响应 Schemas ────────────────────────────────────────────────────


class ChannelColors(BaseModel):
    dine_in: str = "#2ECC71"
    meituan: str = "#FFD700"
    eleme: str = "#0088FF"
    douyin: str = "#000000"


class DisplayRulesPayload(BaseModel):
    timeout_warning_seconds: int = Field(default=600, ge=60, le=7200)
    timeout_warning_color: str = Field(default="#FFA500", max_length=20)
    timeout_critical_seconds: int = Field(default=900, ge=60, le=7200)
    timeout_critical_color: str = Field(default="#FF0000", max_length=20)
    rush_order_flash: bool = True
    rush_order_color: str = Field(default="#FF4444", max_length=20)
    gift_item_color: str = Field(default="#9B59B6", max_length=20)
    takeout_highlight_color: str = Field(default="#3498DB", max_length=20)
    channel_colors: ChannelColors = Field(default_factory=ChannelColors)


class DisplayRulesResponse(BaseModel):
    ok: bool
    data: Optional[Dict] = None  # noqa: UP007
    error: Optional[Dict] = None  # noqa: UP007


# ─── 默认配置 ────────────────────────────────────────────────────────────────

_DEFAULTS = DisplayRulesPayload()


# ─── GET /display-rules/{store_id} ──────────────────────────────────────────


@router.get("/display-rules/{store_id}")
async def get_display_rules(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取门店 KDS 显示规则配置。不存在则返回默认值。"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        text("""
            SELECT rules
            FROM kds_display_rules
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = false
            LIMIT 1
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()

    if row and row[0]:
        return {"ok": True, "data": row[0]}

    return {"ok": True, "data": _DEFAULTS.model_dump()}


# ─── PUT /display-rules/{store_id} ──────────────────────────────────────────


@router.put("/display-rules/{store_id}")
async def put_display_rules(
    store_id: str,
    payload: DisplayRulesPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建或更新门店 KDS 显示规则配置（UPSERT）。"""
    tenant_id = _get_tenant_id(request)
    rules_dict = payload.model_dump()
    rules_str = json.dumps(rules_dict, ensure_ascii=False)

    # 检查是否已有记录
    existing = await db.execute(
        text("""
            SELECT id
            FROM kds_display_rules
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = false
            LIMIT 1
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    row = existing.fetchone()

    if row:
        await db.execute(
            text("""
                UPDATE kds_display_rules
                SET rules = :rules::jsonb, updated_at = now()
                WHERE id = :id
            """),
            {"rules": rules_str, "id": str(row[0])},
        )
    else:
        new_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO kds_display_rules (id, tenant_id, store_id, rules)
                VALUES (:id, :tenant_id, :store_id, :rules::jsonb)
            """),
            {
                "id": new_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "rules": rules_str,
            },
        )

    await db.commit()
    return {"ok": True, "data": rules_dict}
