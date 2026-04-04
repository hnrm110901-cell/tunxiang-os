"""DiscountHealthProjector — 折扣健康物化视图投影器

消费事件：
  discount.applied         → 更新折扣率/折扣金额/泄漏类型
  discount.authorized      → 标记授权折扣（合法）
  discount.revoked         → 标记折扣撤销
  discount.threshold_exceeded → 超阈值计数+1
  discount.leak_detected   → Agent检测到泄漏，更新泄漏类型分布

维护视图：mv_discount_health
  - 按 (tenant_id, store_id, stat_date) 聚合
  - total_orders/discounted_orders/discount_rate/total_discount_fen
  - unauthorized_count/leak_types/top_operators/threshold_breaches

设计：
  每条 discount.applied 事件到达，更新当日统计，增量计算，不全量重扫
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

import structlog

from ..projector import ProjectorBase

logger = structlog.get_logger(__name__)


class DiscountHealthProjector(ProjectorBase):
    """折扣健康投影器 — 维护 mv_discount_health 视图"""

    name = "discount_health"
    event_types = {
        "discount.applied",
        "discount.authorized",
        "discount.revoked",
        "discount.threshold_exceeded",
        "discount.leak_detected",
        "order.paid",   # 用于分母（总订单数）
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        """处理单条事件，增量更新 mv_discount_health。"""
        event_type = event["event_type"]
        store_id = event.get("store_id")
        if not store_id:
            return  # 无门店事件跳过（品牌级事件不计入门店统计）

        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        stat_date = occurred_at.date()

        # 确保今日记录存在（UPSERT 行不存在则初始化为0）
        await conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO mv_discount_health
                (tenant_id, store_id, stat_date, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (tenant_id, store_id, stat_date) DO NOTHING
            """,
            self.tenant_id,
            UUID(str(store_id)),
            stat_date,
        )

        payload = event.get("payload") or {}

        if event_type == "order.paid":
            # 分母：订单总数 +1
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_discount_health
                SET total_orders = total_orders + 1,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                UUID(str(event["event_id"])),
            )

        elif event_type == "discount.applied":
            discount_fen = payload.get("discount_fen", 0)
            margin_passed = payload.get("margin_passed", True)
            has_approval = bool(payload.get("approval_id"))
            threshold_exceeded = not margin_passed

            # 折扣类型 → 泄漏类型分类
            leak_type = _classify_leak_type(payload)

            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_discount_health
                SET discounted_orders   = discounted_orders + 1,
                    total_discount_fen  = total_discount_fen + $4,
                    unauthorized_count  = unauthorized_count + $5,
                    threshold_breaches  = threshold_breaches + $6,
                    leak_types          = _merge_leak_types(leak_types, $7::jsonb),
                    last_event_id       = $8,
                    updated_at          = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                discount_fen,
                0 if has_approval else 1,
                1 if threshold_exceeded else 0,
                json.dumps({leak_type: 1}),
                UUID(str(event["event_id"])),
            )

            # 重新计算折扣率（折扣订单数/总订单数 的分子已更新，分母由 order.paid 维护）
            await _recalc_discount_rate(conn, self.tenant_id, UUID(str(store_id)), stat_date)

        elif event_type == "discount.authorized":
            # 有授权 → unauthorized_count - 1（不小于0）
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_discount_health
                SET unauthorized_count = GREATEST(0, unauthorized_count - 1),
                    last_event_id      = $4,
                    updated_at         = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                UUID(str(event["event_id"])),
            )

        elif event_type == "discount.threshold_exceeded":
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_discount_health
                SET threshold_breaches = threshold_breaches + 1,
                    last_event_id      = $4,
                    updated_at         = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                UUID(str(event["event_id"])),
            )

        elif event_type == "discount.leak_detected":
            leak_types = payload.get("leak_types", {})
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_discount_health
                SET leak_types    = _merge_leak_types(leak_types, $4::jsonb),
                    last_event_id = $5,
                    updated_at    = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                json.dumps(leak_types),
                UUID(str(event["event_id"])),
            )


# ──────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────

def _classify_leak_type(payload: dict) -> str:
    """根据折扣事件 payload 分类泄漏类型。"""
    discount_type = payload.get("discount_type", "unknown")
    has_approval = bool(payload.get("approval_id"))
    margin_passed = payload.get("margin_passed", True)

    if not has_approval and not margin_passed:
        return "unauthorized_margin_breach"  # 无授权且低于毛利底线
    if not has_approval:
        return "unauthorized_discount"        # 无授权折扣
    if not margin_passed:
        return "authorized_margin_breach"     # 有授权但低于毛利底线
    if discount_type == "free_item":
        return "free_item"
    if discount_type == "percent_off":
        return "percent_discount"
    return "normal_discount"


async def _recalc_discount_rate(
    conn: object,
    tenant_id: "UUID",
    store_id: "UUID",
    stat_date: "date",
) -> None:
    """重新计算折扣率 = discounted_orders / total_orders（防除零）。"""
    await conn.execute(  # type: ignore[union-attr]
        """
        UPDATE mv_discount_health
        SET discount_rate = CASE
            WHEN total_orders > 0
            THEN ROUND(discounted_orders::NUMERIC / total_orders, 4)
            ELSE 0
        END
        WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
        """,
        tenant_id,
        store_id,
        stat_date,
    )
