"""KDS 多维标识与颜色规则配置化 API — 模块2.1（对标天财智能出品）

# ROUTER REGISTRATION:
# from .api.kds_rules_routes import router as kds_rules_router
# app.include_router(kds_rules_router, prefix="/api/v1/kds-rules")

端点清单：
  GET  /{store_id}   — 获取门店KDS规则配置
  PUT  /{store_id}   — 保存KDS规则配置

功能：
  - 超时预警：warn_minutes / urgent_minutes + 颜色
  - 渠道标识色：堂食 / 外卖 / 自取
  - 标识开关：客位 / 备注 / 做法 / 渠道标识
  - 特殊标识：赠菜角标 / 退菜角标颜色

所有端点需要 X-Tenant-ID header。
持久化方式：kds_rules_config 表（JSON存储）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(tags=["kds-rules"])


# ─── 公共依赖 ───────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求 / 响应 Schemas ────────────────────────────────────────────────────


class KDSRuleConfig(BaseModel):
    """KDS多维标识与颜色规则配置（门店级别）"""

    # 超时预警
    warn_minutes: int = Field(default=15, ge=1, le=120, description="超时预警时长（分钟）")
    warn_color: str = Field(default="#FFA500", max_length=20, description="预警颜色（橙）")
    urgent_minutes: int = Field(default=25, ge=1, le=120, description="催单阈值（分钟）")
    urgent_color: str = Field(default="#FF0000", max_length=20, description="催单颜色（红）")
    # 渠道标识色
    channel_colors: dict[str, Any] = Field(
        default_factory=lambda: {
            "dine_in": "#4CAF50",
            "takeout": "#2196F3",
            "pickup": "#9C27B0",
        },
        description="渠道标识色：堂食/外卖/自取",
    )
    # 标识开关
    show_guest_seat: bool = Field(default=True, description="显示客位")
    show_remark: bool = Field(default=True, description="显示备注")
    show_cooking_method: bool = Field(default=True, description="显示做法")
    show_channel_badge: bool = Field(default=True, description="显示渠道标识")
    # 特殊标识颜色
    gift_badge_color: str = Field(default="#FFD700", max_length=20, description="赠菜标识颜色（金）")
    return_badge_color: str = Field(default="#607D8B", max_length=20, description="退菜标识颜色（灰）")


_DEFAULTS = KDSRuleConfig()


# ─── GET /{store_id} ─────────────────────────────────────────────────────────


@router.get("/{store_id}")
async def get_kds_rules(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取门店KDS规则配置。不存在则返回默认值。"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        text("""
            SELECT config
            FROM kds_rules_config
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


# ─── PUT /{store_id} ─────────────────────────────────────────────────────────


@router.put("/{store_id}")
async def put_kds_rules(
    store_id: str,
    payload: KDSRuleConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建或更新门店KDS规则配置（UPSERT）。"""
    tenant_id = _get_tenant_id(request)
    config_dict = payload.model_dump()
    config_str = json.dumps(config_dict, ensure_ascii=False)

    # 检查是否已有记录
    existing = await db.execute(
        text("""
            SELECT id
            FROM kds_rules_config
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
                UPDATE kds_rules_config
                SET config = :config::jsonb, updated_at = now()
                WHERE id = :id
            """),
            {"config": config_str, "id": str(row[0])},
        )
    else:
        new_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO kds_rules_config (id, tenant_id, store_id, config)
                VALUES (:id, :tenant_id, :store_id, :config::jsonb)
            """),
            {
                "id": new_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "config": config_str,
            },
        )

    await db.commit()
    return {"ok": True, "data": config_dict}
