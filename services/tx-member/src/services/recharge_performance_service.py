"""储值绩效服务 — 绩效记录 + 汇总 + 排名 + 提成计算

员工储值绩效 UPSERT（日/月），多维度汇总，3种提成模式（flat/percentage/tiered）。
金额单位：分（fen）。
"""

import json
import uuid
from datetime import date
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class RechargePerformanceService:
    """储值绩效服务"""

    # ── 记录绩效（UPSERT） ───────────────────────────────────

    @staticmethod
    async def record_performance(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        employee_id: str,
        period_date: date,
        period_type: str = "daily",
        recharge_count: int = 1,
        recharge_amount_fen: int = 0,
        bonus_amount_fen: int = 0,
        is_smart: bool = False,
    ) -> dict:
        """UPSERT 员工储值绩效。

        基于 UNIQUE(tenant_id, store_id, employee_id, period_date, period_type) 幂等累加。
        """
        perf_id = str(uuid.uuid4())
        result = await db.execute(
            text("""
                INSERT INTO recharge_performance (
                    tenant_id, id, store_id, employee_id,
                    period_date, period_type,
                    total_recharge_count, total_recharge_amount_fen,
                    total_bonus_amount_fen,
                    smart_recharge_count, smart_recharge_amount_fen
                ) VALUES (
                    :tenant_id, :id, :store_id, :employee_id,
                    :period_date, :period_type,
                    :recharge_count, :recharge_amount_fen,
                    :bonus_amount_fen,
                    :smart_count, :smart_amount
                )
                ON CONFLICT (tenant_id, store_id, employee_id, period_date, period_type)
                DO UPDATE SET
                    total_recharge_count      = recharge_performance.total_recharge_count + EXCLUDED.total_recharge_count,
                    total_recharge_amount_fen = recharge_performance.total_recharge_amount_fen + EXCLUDED.total_recharge_amount_fen,
                    total_bonus_amount_fen    = recharge_performance.total_bonus_amount_fen + EXCLUDED.total_bonus_amount_fen,
                    smart_recharge_count      = recharge_performance.smart_recharge_count + EXCLUDED.smart_recharge_count,
                    smart_recharge_amount_fen = recharge_performance.smart_recharge_amount_fen + EXCLUDED.smart_recharge_amount_fen,
                    conversion_rate           = CASE
                        WHEN (recharge_performance.total_recharge_count + EXCLUDED.total_recharge_count) > 0
                        THEN ROUND(
                            (recharge_performance.smart_recharge_count + EXCLUDED.smart_recharge_count)::NUMERIC /
                            (recharge_performance.total_recharge_count + EXCLUDED.total_recharge_count) * 100, 2
                        )
                        ELSE 0
                    END,
                    updated_at = now()
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "id": perf_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "period_date": period_date,
                "period_type": period_type,
                "recharge_count": recharge_count,
                "recharge_amount_fen": recharge_amount_fen,
                "bonus_amount_fen": bonus_amount_fen,
                "smart_count": recharge_count if is_smart else 0,
                "smart_amount": recharge_amount_fen if is_smart else 0,
            },
        )
        row = result.fetchone()
        await db.commit()

        final_id = str(row.id) if row else perf_id
        logger.info(
            "recharge_performance_recorded",
            perf_id=final_id,
            employee_id=employee_id,
            period_date=str(period_date),
        )
        return {"id": final_id, "upserted": True}

    # ── 日汇总 ───────────────────────────────────────────────

    @staticmethod
    async def get_daily_summary(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        period_date: date,
    ) -> dict:
        """获取门店某日的储值绩效汇总"""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(DISTINCT employee_id)                    AS active_employees,
                    COALESCE(SUM(total_recharge_count), 0)         AS total_count,
                    COALESCE(SUM(total_recharge_amount_fen), 0)    AS total_amount_fen,
                    COALESCE(SUM(total_bonus_amount_fen), 0)       AS total_bonus_fen,
                    COALESCE(SUM(smart_recharge_count), 0)         AS smart_count,
                    COALESCE(SUM(smart_recharge_amount_fen), 0)    AS smart_amount_fen
                FROM recharge_performance
                WHERE tenant_id   = :tenant_id
                  AND store_id    = :store_id
                  AND period_date = :period_date
                  AND period_type = 'daily'
                  AND is_deleted  = FALSE
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "period_date": period_date},
        )
        row = result.fetchone()
        total = row.total_count if row else 0
        smart = row.smart_count if row else 0
        conversion = round(smart / total * 100, 2) if total > 0 else 0

        return {
            "store_id": store_id,
            "period_date": str(period_date),
            "active_employees": row.active_employees if row else 0,
            "total_count": total,
            "total_amount_fen": row.total_amount_fen if row else 0,
            "total_bonus_fen": row.total_bonus_fen if row else 0,
            "smart_count": smart,
            "smart_amount_fen": row.smart_amount_fen if row else 0,
            "conversion_rate": conversion,
        }

    # ── 月汇总 ───────────────────────────────────────────────

    @staticmethod
    async def get_monthly_summary(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        year: int,
        month: int,
    ) -> dict:
        """获取门店某月的储值绩效汇总（从 daily 聚合）"""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)

        result = await db.execute(
            text("""
                SELECT
                    COUNT(DISTINCT employee_id)                    AS active_employees,
                    COALESCE(SUM(total_recharge_count), 0)         AS total_count,
                    COALESCE(SUM(total_recharge_amount_fen), 0)    AS total_amount_fen,
                    COALESCE(SUM(total_bonus_amount_fen), 0)       AS total_bonus_fen,
                    COALESCE(SUM(smart_recharge_count), 0)         AS smart_count,
                    COALESCE(SUM(smart_recharge_amount_fen), 0)    AS smart_amount_fen
                FROM recharge_performance
                WHERE tenant_id   = :tenant_id
                  AND store_id    = :store_id
                  AND period_date >= :start_date
                  AND period_date <  :end_date
                  AND period_type = 'daily'
                  AND is_deleted  = FALSE
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.fetchone()
        total = row.total_count if row else 0
        smart = row.smart_count if row else 0
        conversion = round(smart / total * 100, 2) if total > 0 else 0

        return {
            "store_id": store_id,
            "year": year,
            "month": month,
            "active_employees": row.active_employees if row else 0,
            "total_count": total,
            "total_amount_fen": row.total_amount_fen if row else 0,
            "total_bonus_fen": row.total_bonus_fen if row else 0,
            "smart_count": smart,
            "smart_amount_fen": row.smart_amount_fen if row else 0,
            "conversion_rate": conversion,
        }

    # ── 排名 ─────────────────────────────────────────────────

    @staticmethod
    async def get_ranking(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        start_date: date,
        end_date: date,
        sort_by: str = "total_recharge_amount_fen",
        limit: int = 20,
    ) -> list[dict]:
        """员工储值绩效排名"""
        valid_sorts = {
            "total_recharge_amount_fen",
            "total_recharge_count",
            "smart_recharge_count",
            "conversion_rate",
        }
        if sort_by not in valid_sorts:
            sort_by = "total_recharge_amount_fen"

        result = await db.execute(
            text(f"""
                SELECT
                    employee_id,
                    SUM(total_recharge_count)       AS total_count,
                    SUM(total_recharge_amount_fen)  AS total_amount_fen,
                    SUM(total_bonus_amount_fen)     AS total_bonus_fen,
                    SUM(smart_recharge_count)        AS smart_count,
                    SUM(smart_recharge_amount_fen)   AS smart_amount_fen,
                    CASE WHEN SUM(total_recharge_count) > 0
                        THEN ROUND(SUM(smart_recharge_count)::NUMERIC / SUM(total_recharge_count) * 100, 2)
                        ELSE 0
                    END AS conversion_rate
                FROM recharge_performance
                WHERE tenant_id   = :tenant_id
                  AND store_id    = :store_id
                  AND period_date BETWEEN :start_date AND :end_date
                  AND period_type = 'daily'
                  AND is_deleted  = FALSE
                GROUP BY employee_id
                ORDER BY {sort_by} DESC
                LIMIT :limit
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
            },
        )
        rows = result.fetchall()
        return [
            {
                "rank": idx + 1,
                "employee_id": str(r.employee_id),
                "total_count": r.total_count,
                "total_amount_fen": r.total_amount_fen,
                "total_bonus_fen": r.total_bonus_fen,
                "smart_count": r.smart_count,
                "smart_amount_fen": r.smart_amount_fen,
                "conversion_rate": float(r.conversion_rate),
            }
            for idx, r in enumerate(rows)
        ]

    # ── 提成计算 ─────────────────────────────────────────────

    @staticmethod
    async def calculate_commission(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        employee_id: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        """计算员工储值提成（3种模式：flat_per_card / percentage / tiered）"""
        # 1) 获取提成规则
        today = date.today()
        rule_result = await db.execute(
            text("""
                SELECT id, rule_name, commission_type, commission_value, tiers
                FROM recharge_commission_rules
                WHERE tenant_id = :tenant_id
                  AND (store_id = :store_id OR store_id IS NULL)
                  AND is_active = TRUE
                  AND effective_from <= :today
                  AND (effective_until IS NULL OR effective_until >= :today)
                  AND is_deleted = FALSE
                ORDER BY store_id NULLS LAST
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "today": today},
        )
        rule = rule_result.fetchone()

        # 2) 获取员工绩效
        perf_result = await db.execute(
            text("""
                SELECT
                    SUM(total_recharge_count)       AS total_count,
                    SUM(total_recharge_amount_fen)  AS total_amount_fen
                FROM recharge_performance
                WHERE tenant_id   = :tenant_id
                  AND store_id    = :store_id
                  AND employee_id = :employee_id
                  AND period_date BETWEEN :start_date AND :end_date
                  AND period_type = 'daily'
                  AND is_deleted  = FALSE
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        perf = perf_result.fetchone()
        total_count = perf.total_count if perf and perf.total_count else 0
        total_amount_fen = perf.total_amount_fen if perf and perf.total_amount_fen else 0

        if not rule:
            return {
                "employee_id": employee_id,
                "commission_fen": 0,
                "commission_type": "none",
                "rule_name": None,
                "total_count": total_count,
                "total_amount_fen": total_amount_fen,
            }

        # 3) 计算提成
        commission_fen = _calc_commission(
            commission_type=rule.commission_type,
            commission_value=float(rule.commission_value) if rule.commission_value else 0,
            tiers=rule.tiers,
            total_count=total_count,
            total_amount_fen=total_amount_fen,
        )

        return {
            "employee_id": employee_id,
            "commission_fen": commission_fen,
            "commission_type": rule.commission_type,
            "rule_name": rule.rule_name,
            "rule_id": str(rule.id),
            "total_count": total_count,
            "total_amount_fen": total_amount_fen,
        }

    # ── 提成规则 CRUD ────────────────────────────────────────

    @staticmethod
    async def create_commission_rule(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: Optional[str] = None,
        rule_name: str,
        commission_type: str,
        commission_value: float = 0,
        tiers: Optional[list] = None,
        effective_from: date = None,
        effective_until: Optional[date] = None,
    ) -> dict:
        """创建提成规则"""
        rule_id = str(uuid.uuid4())
        if effective_from is None:
            effective_from = date.today()

        await db.execute(
            text("""
                INSERT INTO recharge_commission_rules (
                    tenant_id, id, store_id, rule_name,
                    commission_type, commission_value, tiers,
                    effective_from, effective_until
                ) VALUES (
                    :tenant_id, :id, :store_id, :rule_name,
                    :commission_type, :commission_value, :tiers::JSONB,
                    :effective_from, :effective_until
                )
            """),
            {
                "tenant_id": tenant_id,
                "id": rule_id,
                "store_id": store_id,
                "rule_name": rule_name,
                "commission_type": commission_type,
                "commission_value": commission_value,
                "tiers": json.dumps(tiers) if tiers else None,
                "effective_from": effective_from,
                "effective_until": effective_until,
            },
        )
        await db.commit()
        logger.info("recharge_commission_rule_created", rule_id=rule_id, name=rule_name)
        return {"id": rule_id, "rule_name": rule_name}

    @staticmethod
    async def list_commission_rules(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """列出提成规则"""
        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: dict = {"tenant_id": tenant_id}

        if store_id:
            conditions.append("(store_id = :store_id OR store_id IS NULL)")
            params["store_id"] = store_id

        where = " AND ".join(conditions)

        count_result = await db.execute(text(f"SELECT COUNT(*) FROM recharge_commission_rules WHERE {where}"), params)
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset
        items_result = await db.execute(
            text(f"""
                SELECT id, store_id, rule_name, commission_type,
                       commission_value, is_active,
                       effective_from, effective_until, created_at
                FROM recharge_commission_rules
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = items_result.fetchall()
        items = [
            {
                "id": str(r.id),
                "store_id": str(r.store_id) if r.store_id else None,
                "rule_name": r.rule_name,
                "commission_type": r.commission_type,
                "commission_value": float(r.commission_value) if r.commission_value else 0,
                "is_active": r.is_active,
                "effective_from": str(r.effective_from),
                "effective_until": str(r.effective_until) if r.effective_until else None,
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    @staticmethod
    async def delete_commission_rule(db: AsyncSession, tenant_id: str, rule_id: str) -> dict:
        """软删除提成规则"""
        await db.execute(
            text("""
                UPDATE recharge_commission_rules
                SET is_deleted = TRUE, updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :rule_id
            """),
            {"tenant_id": tenant_id, "rule_id": rule_id},
        )
        await db.commit()
        logger.info("recharge_commission_rule_deleted", rule_id=rule_id)
        return {"id": rule_id, "deleted": True}


# ── 内部辅助 ─────────────────────────────────────────────────


def _calc_commission(
    *,
    commission_type: str,
    commission_value: float,
    tiers: Optional[list],
    total_count: int,
    total_amount_fen: int,
) -> int:
    """计算提成金额（分）"""
    if commission_type == "flat_per_card":
        # 每张卡固定金额（commission_value 单位：分）
        return int(commission_value * total_count)

    if commission_type == "percentage":
        # 按充值金额百分比（commission_value 单位：百分比）
        return int(total_amount_fen * commission_value / 100)

    if commission_type == "tiered" and tiers:
        # 阶梯提成：按充值金额落入区间计算
        # tiers 格式: [{"min_fen": 0, "max_fen": 100000, "rate_pct": 1}, ...]
        commission = 0
        for tier in sorted(tiers, key=lambda t: t.get("min_fen", 0)):
            tier_min = tier.get("min_fen", 0)
            tier_max = tier.get("max_fen", float("inf"))
            rate = tier.get("rate_pct", 0)

            if total_amount_fen <= tier_min:
                break
            applicable = min(total_amount_fen, tier_max) - tier_min
            if applicable > 0:
                commission += int(applicable * rate / 100)
        return commission

    return 0
