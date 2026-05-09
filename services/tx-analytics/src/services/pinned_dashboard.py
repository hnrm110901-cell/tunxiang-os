"""驾驶舱 Pin 洞察 service 层 — S4-04 Issue #291 / Tier 3（RLS 路径全局 Tier 1）。

PR2.B：把 PR1 in-memory `_PINNED_STORE` dict 持久化到 PG（v403 dashboard_pinned 表）。

调用约定（路由层负责）：
  - 用 `get_db_with_tenant(tenant_id)` 注入 `app.tenant_id`（RLS 强制）
  - 服务层假设 session 已开启事务 + 已注入 tenant
  - SELECT/UPDATE 走 RLS USING 自动 tenant 过滤；INSERT 显式带 tenant_id（WITH CHECK 校验）

PR2 后续：
  - PR2.C：HTTP 路由 + main.py 注册（POST /append / GET /list / DELETE /{pin_id}）
  - PR2.D：web-admin AgentConsole Pin 按钮 + 驾驶舱 Feed
  - PR2.B-2：integration test 真 PG fixture（验证 FIFO 行为 + RLS 跨租户隔离）

本 PR2.B 单测是 mock-session SQL-shape 验证 — 不连真 DB；
真行为校验（FIFO 21 条第一条挤掉、tenant=A pin 不出现在 tenant=B）留 PR2.B-2。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Pin 数量上限（每 tenant），超出 FIFO 软删最旧项
PIN_LIMIT_PER_TENANT = 20


@dataclass
class PinnedItem:
    pin_id: str
    tenant_id: str
    pinner_user_id: str
    pinned_at: datetime
    surface_snapshot: dict[str, Any]  # A2UI v0.8 declaration
    source_query_id: Optional[str] = None
    source_natural_query: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin_id": self.pin_id,
            "tenant_id": self.tenant_id,
            "pinner_user_id": self.pinner_user_id,
            "pinned_at": self.pinned_at.isoformat(),
            "surface_snapshot": self.surface_snapshot,
            "source_query_id": self.source_query_id,
            "source_natural_query": self.source_natural_query,
        }


def _row_to_item(row: Mapping[str, Any]) -> PinnedItem:
    """SQLAlchemy mapping 行 → PinnedItem（UUID/JSONB 类型转换）。"""
    return PinnedItem(
        pin_id=str(row["pin_id"]),
        tenant_id=str(row["tenant_id"]),
        pinner_user_id=str(row["pinner_user_id"]),
        pinned_at=row["pinned_at"],
        surface_snapshot=row["surface_snapshot"],
        source_query_id=row["source_query_id"],
        source_natural_query=row["source_natural_query"],
    )


async def add_pin(
    session: AsyncSession,
    *,
    tenant_id: str,
    pinner_user_id: str,
    surface_snapshot: dict[str, Any],
    source_query_id: Optional[str] = None,
    source_natural_query: Optional[str] = None,
) -> PinnedItem:
    """新增 Pin。INSERT 后跑 FIFO 软删 SQL，把 tenant 上限外的最旧记录置 is_deleted=TRUE。

    tenant_id 必填非空 — service 层早拒减少 DB roundtrip（v403 RLS WITH CHECK 也会拒）。
    pinner_user_id 必填 — §9 Agent 决策留痕强制。
    surface_snapshot 序列化为 JSON 字符串再 ::jsonb cast（asyncpg 不直传 dict 给 text()）。

    Returns:
        新插入的 PinnedItem（pin_id / pinned_at 由 DB 默认值生成）。

    Raises:
        ValueError: tenant_id / pinner_user_id 为空
        sqlalchemy.exc.IntegrityError: WITH CHECK 失败（tenant_id != app.tenant_id）
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id 必填非空（防 RLS 绕过）")
    if not pinner_user_id or not pinner_user_id.strip():
        raise ValueError("pinner_user_id 必填非空（决策留痕）")

    # 1. INSERT — pin_id / pinned_at / created_at / updated_at 走 v403 DB 默认
    insert_result = await session.execute(
        text(
            """
            INSERT INTO dashboard_pinned (
                tenant_id, pinner_user_id, surface_snapshot,
                source_query_id, source_natural_query
            )
            VALUES (
                :tenant_id::uuid, :pinner_user_id::uuid, :surface_snapshot::jsonb,
                :source_query_id, :source_natural_query
            )
            RETURNING pin_id, tenant_id, pinner_user_id, pinned_at,
                      surface_snapshot, source_query_id, source_natural_query
            """
        ),
        {
            "tenant_id": tenant_id,
            "pinner_user_id": pinner_user_id,
            "surface_snapshot": json.dumps(surface_snapshot, ensure_ascii=False),
            "source_query_id": source_query_id,
            "source_natural_query": source_natural_query,
        },
    )
    new_row = insert_result.mappings().one()

    # 2. FIFO 软删 — 超 PIN_LIMIT_PER_TENANT 的最旧记录置 is_deleted=TRUE
    # RLS USING 已 implicit 把 tenant 过滤加上（current_setting('app.tenant_id')），
    # 因此此处无需显式 WHERE tenant_id = X
    await session.execute(
        text(
            """
            UPDATE dashboard_pinned
            SET is_deleted = TRUE, updated_at = NOW()
            WHERE pin_id NOT IN (
                SELECT pin_id FROM dashboard_pinned
                WHERE is_deleted = FALSE
                ORDER BY pinned_at DESC
                LIMIT :limit
            )
            AND is_deleted = FALSE
            """
        ),
        {"limit": PIN_LIMIT_PER_TENANT},
    )

    return _row_to_item(new_row)


async def list_pins(session: AsyncSession, tenant_id: str) -> list[PinnedItem]:
    """列出当前 tenant 的 active pinned items（最新在前，软删行不返）。

    RLS USING 自动 tenant 过滤；tenant_id 参数仅做 NULL 校验 + 调用方契约清晰。
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id 必填非空（防 RLS 绕过）")

    result = await session.execute(
        text(
            """
            SELECT pin_id, tenant_id, pinner_user_id, pinned_at,
                   surface_snapshot, source_query_id, source_natural_query
            FROM dashboard_pinned
            WHERE is_deleted = FALSE
            ORDER BY pinned_at DESC
            LIMIT :limit
            """
        ),
        {"limit": PIN_LIMIT_PER_TENANT},
    )
    return [_row_to_item(row) for row in result.mappings()]


async def remove_pin(
    session: AsyncSession,
    *,
    tenant_id: str,
    pin_id: str,
) -> bool:
    """软删 Pin。返回 True 表示找到并删，False 表示无此 pin_id（含跨 tenant 情况）。

    跨 tenant remove：RLS USING 阻挡可见性 → UPDATE 影响 0 行 → False（不抛异常）。
    is_deleted=TRUE 的行重复 remove：影响 0 行 → False（幂等）。
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id 必填非空（防 RLS 绕过）")
    if not pin_id or not pin_id.strip():
        raise ValueError("pin_id 必填非空")

    result = await session.execute(
        text(
            """
            UPDATE dashboard_pinned
            SET is_deleted = TRUE, updated_at = NOW()
            WHERE pin_id = :pin_id::uuid
              AND is_deleted = FALSE
            """
        ),
        {"pin_id": pin_id},
    )
    return (result.rowcount or 0) > 0
