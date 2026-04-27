"""转化漏斗服务 — Sprint G4

每日转化漏斗: 曝光 → 到店 → 消费 → 加会员 → 复购。
提供漏斗计算、分析、行业对标和改善建议。
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 餐饮行业平均转化率（用于对标）
_INDUSTRY_BENCHMARK: dict[str, float] = {
    "visit_rate": 15.0,    # 曝光 → 到店 15%
    "order_rate": 90.0,    # 到店 → 消费 90%
    "member_rate": 25.0,   # 消费 → 加会员 25%
    "repeat_rate": 35.0,   # 会员 → 复购 35%
}


class ConversionFunnelService:
    """转化漏斗服务。"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  compute_daily_funnel — 计算每日转化漏斗
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def compute_daily_funnel(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        target_date: date,
    ) -> dict[str, Any]:
        """计算每日转化漏斗。

        - exposure: 从 wifi_visit_logs 统计（MAC 去重）
        - visit: 从 orders 表去重 customer_id（当日有订单 = 到店）
        - order: 从 orders 表 COUNT
        - member: 从 members 表当日新增
        - repeat: 从 orders 表 30 日内二次消费
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 1) 曝光: WiFi 探针去重
        exposure_count = await self._count_exposure(db, store_id, tenant_id, target_date)

        # 2) 到店: 当日有订单的独立客户数
        visit_result = await db.execute(
            text("""
                SELECT COUNT(DISTINCT customer_id) AS cnt
                FROM orders
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND biz_date = :target_date
                  AND customer_id IS NOT NULL
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "target_date": target_date,
            },
        )
        visit_count = int(visit_result.scalar() or 0)

        # 3) 订单数
        order_result = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM orders
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND biz_date = :target_date
                  AND status IN ('paid', 'completed')
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "target_date": target_date,
            },
        )
        order_count = int(order_result.scalar() or 0)

        # 4) 当日新增会员
        member_result = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM members
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND DATE(created_at) = :target_date
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "target_date": target_date,
            },
        )
        member_count = int(member_result.scalar() or 0)

        # 5) 30 日内复购（当日消费且 30 日前也消费过的客户数）
        repeat_result = await db.execute(
            text("""
                SELECT COUNT(DISTINCT o1.customer_id) AS cnt
                FROM orders o1
                WHERE o1.store_id = :store_id
                  AND o1.tenant_id = :tenant_id
                  AND o1.biz_date = :target_date
                  AND o1.customer_id IS NOT NULL
                  AND o1.status IN ('paid', 'completed')
                  AND o1.is_deleted = FALSE
                  AND EXISTS (
                      SELECT 1 FROM orders o2
                      WHERE o2.customer_id = o1.customer_id
                        AND o2.store_id = o1.store_id
                        AND o2.tenant_id = o1.tenant_id
                        AND o2.biz_date < :target_date
                        AND o2.biz_date >= :repeat_start
                        AND o2.status IN ('paid', 'completed')
                        AND o2.is_deleted = FALSE
                  )
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "target_date": target_date,
                "repeat_start": target_date - timedelta(days=30),
            },
        )
        repeat_count = int(repeat_result.scalar() or 0)

        # UPSERT 到 conversion_funnel_daily
        await db.execute(
            text("""
                INSERT INTO conversion_funnel_daily
                    (tenant_id, store_id, funnel_date,
                     exposure_count, visit_count, order_count,
                     member_count, repeat_count)
                VALUES
                    (:tenant_id, :store_id, :funnel_date,
                     :exposure, :visit, :order_cnt,
                     :member, :repeat_cnt)
                ON CONFLICT (tenant_id, store_id, funnel_date)
                DO UPDATE SET
                    exposure_count = EXCLUDED.exposure_count,
                    visit_count    = EXCLUDED.visit_count,
                    order_count    = EXCLUDED.order_count,
                    member_count   = EXCLUDED.member_count,
                    repeat_count   = EXCLUDED.repeat_count,
                    updated_at     = NOW()
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "funnel_date": target_date,
                "exposure": exposure_count,
                "visit": visit_count,
                "order_cnt": order_count,
                "member": member_count,
                "repeat_cnt": repeat_count,
            },
        )
        await db.commit()

        # 读回含 GENERATED 列的完整数据
        funnel_result = await db.execute(
            text("""
                SELECT
                    exposure_count, visit_count, order_count,
                    member_count, repeat_count,
                    visit_rate, order_rate, member_rate, repeat_rate
                FROM conversion_funnel_daily
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND funnel_date = :funnel_date
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "funnel_date": target_date,
            },
        )
        f = funnel_result.mappings().first()

        # 上月同期对比
        last_month_date = target_date - timedelta(days=30)
        lm_result = await db.execute(
            text("""
                SELECT
                    exposure_count, visit_count, order_count,
                    member_count, repeat_count,
                    visit_rate, order_rate, member_rate, repeat_rate
                FROM conversion_funnel_daily
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND funnel_date = :funnel_date
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "funnel_date": last_month_date,
            },
        )
        lm = lm_result.mappings().first()

        def _mom_change(current: int, prev_row: Any, field: str) -> Optional[float]:
            """计算环比变化百分比。"""
            if prev_row is None:
                return None
            prev = int(prev_row[field] or 0)
            if prev == 0:
                return None
            return round((current - prev) * 100.0 / prev, 1)

        funnel_data = {
            "date": str(target_date),
            "stages": [
                {
                    "stage": "exposure",
                    "label": "曝光",
                    "count": int(f["exposure_count"]),
                    "rate": None,
                    "mom_change": _mom_change(int(f["exposure_count"]), lm, "exposure_count"),
                },
                {
                    "stage": "visit",
                    "label": "到店",
                    "count": int(f["visit_count"]),
                    "rate": float(f["visit_rate"]) if f["visit_rate"] else 0.0,
                    "mom_change": _mom_change(int(f["visit_count"]), lm, "visit_count"),
                },
                {
                    "stage": "order",
                    "label": "消费",
                    "count": int(f["order_count"]),
                    "rate": float(f["order_rate"]) if f["order_rate"] else 0.0,
                    "mom_change": _mom_change(int(f["order_count"]), lm, "order_count"),
                },
                {
                    "stage": "member",
                    "label": "加会员",
                    "count": int(f["member_count"]),
                    "rate": float(f["member_rate"]) if f["member_rate"] else 0.0,
                    "mom_change": _mom_change(int(f["member_count"]), lm, "member_count"),
                },
                {
                    "stage": "repeat",
                    "label": "复购",
                    "count": int(f["repeat_count"]),
                    "rate": float(f["repeat_rate"]) if f["repeat_rate"] else 0.0,
                    "mom_change": _mom_change(int(f["repeat_count"]), lm, "repeat_count"),
                },
            ],
        }

        log.info(
            "daily_funnel_computed",
            store_id=str(store_id),
            date=str(target_date),
            exposure=exposure_count,
            visit=visit_count,
            order=order_count,
            member=member_count,
            repeat=repeat_count,
        )

        return funnel_data

    async def _count_exposure(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        target_date: date,
    ) -> int:
        """统计曝光数（WiFi 探针去重 MAC）。"""
        try:
            result = await db.execute(
                text("""
                    SELECT COUNT(DISTINCT mac_hash) AS cnt
                    FROM wifi_visit_logs
                    WHERE store_id = :store_id
                      AND tenant_id = :tenant_id
                      AND visit_date = :target_date
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "target_date": target_date,
                },
            )
            return int(result.scalar() or 0)
        except SQLAlchemyError:
            # wifi_visit_logs 表可能不存在
            log.warning(
                "wifi_visit_logs_unavailable",
                store_id=str(store_id),
                note="WiFi探针数据不可用，曝光数回退为0",
            )
            return 0

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  get_funnel_analysis — 漏斗分析
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_funnel_analysis(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        date_from: date,
        date_to: date,
    ) -> dict[str, Any]:
        """漏斗分析。

        - 5 环节数据 + 转化率
        - 最大漏损环节定位
        - 行业对标
        - 改善建议
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 聚合期间数据
        agg_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(exposure_count), 0)  AS total_exposure,
                    COALESCE(SUM(visit_count), 0)     AS total_visit,
                    COALESCE(SUM(order_count), 0)     AS total_order,
                    COALESCE(SUM(member_count), 0)    AS total_member,
                    COALESCE(SUM(repeat_count), 0)    AS total_repeat,
                    COUNT(*)                           AS days_count
                FROM conversion_funnel_daily
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND funnel_date BETWEEN :date_from AND :date_to
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        a = agg_result.mappings().first()

        exposure = int(a["total_exposure"])
        visit = int(a["total_visit"])
        order = int(a["total_order"])
        member = int(a["total_member"])
        repeat = int(a["total_repeat"])

        def _calc_rate(numerator: int, denominator: int) -> float:
            return round(numerator * 100.0 / denominator, 2) if denominator > 0 else 0.0

        visit_rate = _calc_rate(visit, exposure)
        order_rate = _calc_rate(order, visit)
        member_rate = _calc_rate(member, order)
        repeat_rate = _calc_rate(repeat, member)

        # 漏损分析：找出与行业对标差距最大的环节
        gaps: list[dict[str, Any]] = []
        stage_rates = [
            ("visit_rate", "曝光→到店", visit_rate),
            ("order_rate", "到店→消费", order_rate),
            ("member_rate", "消费→会员", member_rate),
            ("repeat_rate", "会员→复购", repeat_rate),
        ]
        for key, label, actual in stage_rates:
            benchmark = _INDUSTRY_BENCHMARK[key]
            gap = round(benchmark - actual, 2)
            gaps.append({
                "stage": key,
                "label": label,
                "actual_rate": actual,
                "benchmark_rate": benchmark,
                "gap": gap,
                "status": "below" if gap > 5 else ("at" if gap > -5 else "above"),
            })

        # 最大漏损环节
        max_gap = max(gaps, key=lambda x: x["gap"])

        # 改善建议
        suggestions = self._generate_suggestions(gaps, max_gap)

        # 每日趋势
        trend_result = await db.execute(
            text("""
                SELECT
                    funnel_date,
                    exposure_count, visit_count, order_count,
                    member_count, repeat_count,
                    visit_rate, order_rate, member_rate, repeat_rate
                FROM conversion_funnel_daily
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND funnel_date BETWEEN :date_from AND :date_to
                  AND is_deleted = FALSE
                ORDER BY funnel_date
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        trends = [
            {
                "date": str(row["funnel_date"]),
                "exposure": int(row["exposure_count"]),
                "visit": int(row["visit_count"]),
                "order": int(row["order_count"]),
                "member": int(row["member_count"]),
                "repeat": int(row["repeat_count"]),
                "visit_rate": float(row["visit_rate"]) if row["visit_rate"] else 0.0,
                "order_rate": float(row["order_rate"]) if row["order_rate"] else 0.0,
                "member_rate": float(row["member_rate"]) if row["member_rate"] else 0.0,
                "repeat_rate": float(row["repeat_rate"]) if row["repeat_rate"] else 0.0,
            }
            for row in trend_result.mappings().all()
        ]

        log.info(
            "funnel_analysis_computed",
            store_id=str(store_id),
            date_range=[str(date_from), str(date_to)],
            max_gap_stage=max_gap["stage"],
        )

        return {
            "date_range": [str(date_from), str(date_to)],
            "days_count": int(a["days_count"]),
            "summary": {
                "exposure": exposure,
                "visit": visit,
                "order": order,
                "member": member,
                "repeat": repeat,
            },
            "rates": {
                "visit_rate": visit_rate,
                "order_rate": order_rate,
                "member_rate": member_rate,
                "repeat_rate": repeat_rate,
            },
            "benchmark": _INDUSTRY_BENCHMARK,
            "gap_analysis": gaps,
            "max_gap_stage": {
                "stage": max_gap["stage"],
                "label": max_gap["label"],
                "gap": max_gap["gap"],
            },
            "suggestions": suggestions,
            "trends": trends,
        }

    @staticmethod
    def _generate_suggestions(
        gaps: list[dict[str, Any]],
        max_gap: dict[str, Any],
    ) -> list[dict[str, str]]:
        """基于漏损分析生成改善建议。"""
        suggestions: list[dict[str, str]] = []

        suggestion_map: dict[str, list[dict[str, str]]] = {
            "visit_rate": [
                {"title": "增加线上曝光", "action": "投放大众点评/抖音/小红书探店内容，提升到店转化"},
                {"title": "优化门头引流", "action": "升级门头灯箱、增设LED屏展示招牌菜，吸引路过客流"},
                {"title": "推出引流套餐", "action": "设计低价引流套餐(如19.9元双人餐)，降低首次到店门槛"},
            ],
            "order_rate": [
                {"title": "优化排队体验", "action": "缩短等位时间至15分钟内，提供等位小食/饮品"},
                {"title": "升级菜单展示", "action": "优化菜单设计，突出招牌菜和套餐，降低点单决策成本"},
                {"title": "服务员主动引导", "action": "培训服务员主动推荐，提高点单转化率"},
            ],
            "member_rate": [
                {"title": "结账即入会", "action": "POS结账时自动弹出入会引导，扫码即注册，送首单优惠券"},
                {"title": "会员专享权益", "action": "设计差异化会员权益(免排队/专属折扣/生日礼)，提升入会意愿"},
                {"title": "服务员话术培训", "action": "培训标准入会话术:'注册会员立省XX元，还送生日免费菜'"},
            ],
            "repeat_rate": [
                {"title": "离店即推券", "action": "结账后自动推送7天有效回头券，刺激二次到店"},
                {"title": "会员分层运营", "action": "基于RFM分层精准推送，沉默会员发唤醒券，活跃会员推升单"},
                {"title": "定期会员日", "action": "设定每月固定会员日，双倍积分+专属折扣，培养消费习惯"},
            ],
        }

        # 按差距大小排序，优先给出最大漏损环节的建议
        sorted_gaps = sorted(gaps, key=lambda x: x["gap"], reverse=True)
        for gap_item in sorted_gaps:
            if gap_item["gap"] > 0:
                stage_suggestions = suggestion_map.get(gap_item["stage"], [])
                for s in stage_suggestions[:2]:  # 每个环节最多 2 条
                    suggestions.append({
                        "stage": gap_item["label"],
                        "priority": "high" if gap_item["gap"] > 10 else "medium",
                        **s,
                    })

        return suggestions[:6]  # 最多返回 6 条建议
