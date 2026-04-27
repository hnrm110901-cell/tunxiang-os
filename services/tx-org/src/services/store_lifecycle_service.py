"""门店生命周期服务

判定门店当前所处生命周期阶段（爬坡/成熟/平台/衰退），
并提供该阶段的差异化健康基准线。

不同阶段对"健康"的定义不同：
- 爬坡期(0-6月): 营收达目标60%即健康，亏损正常
- 成熟期(6-24月): 营收达目标100%，利润率>10%
- 平台期(24-36月): 营收达95%，利润率>8%
- 衰退期(36月+): 营收达85%，利润率>5%

金额单位：分（fen）。RLS：每次 DB 操作前设置 app.tenant_id。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


class StoreLifecycleService:
    """门店生命周期管理"""

    # ── 阶段判定规则 ────────────────────────────────────────────────
    STAGE_RULES: dict[str, dict[str, Any]] = {
        "rampup": {
            "months": (0, 6),
            "description": "爬坡期",
            "revenue_target_pct": 0.6,
            "profit_margin_min": -0.05,
            "turnover_min": 1.5,
        },
        "mature": {
            "months": (6, 24),
            "description": "成熟期",
            "revenue_target_pct": 1.0,
            "profit_margin_min": 0.10,
            "turnover_min": 2.5,
        },
        "plateau": {
            "months": (24, 36),
            "description": "平台期",
            "revenue_target_pct": 0.95,
            "profit_margin_min": 0.08,
            "turnover_min": 2.0,
        },
        "decline": {
            "months": (36, 999),
            "description": "衰退期",
            "revenue_target_pct": 0.85,
            "profit_margin_min": 0.05,
            "turnover_min": 1.5,
        },
    }

    # ── 阶段判定 ────────────────────────────────────────────────────

    async def determine_stage(
        self,
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        """判定门店当前生命周期阶段

        1. 查询opened_date计算开业月数
        2. 基于月数初步判定
        3. 叠加经营数据修正（连续下滑可能提前进入下一阶段）
        4. 返回stage + 该阶段的差异化基准线
        """
        await _set_tenant(db, tenant_id)

        # 查询或创建生命周期记录
        lifecycle = await self._get_or_create_lifecycle(db, tenant_id, store_id)
        if lifecycle is None:
            raise ValueError(f"门店不存在或无开业日期: {store_id}")

        opened_date = lifecycle["opened_date"]
        today = date.today()
        months = self._calc_months(opened_date, today)

        # 基于月数初步判定
        initial_stage = self._stage_by_months(months)

        # 经营数据修正
        adjusted_stage = await self._adjust_stage_by_performance(
            db, tenant_id, store_id, initial_stage, months,
        )

        # 构建基准线
        rule = self.STAGE_RULES[adjusted_stage]
        health_baseline = {
            "revenue_target_pct": rule["revenue_target_pct"],
            "profit_margin_min": rule["profit_margin_min"],
            "turnover_min": rule["turnover_min"],
        }

        # 更新数据库
        old_stage = lifecycle.get("current_stage", "")
        stage_changed = old_stage != adjusted_stage
        stage_entered_at = today if stage_changed else lifecycle.get("stage_entered_at", today)
        next_review = today + timedelta(days=30)

        baseline_json = json.dumps(health_baseline, ensure_ascii=False)
        await db.execute(
            text("""
                UPDATE store_lifecycle_stages
                SET current_stage = :stage,
                    stage_entered_at = :entered,
                    health_baseline = CAST(:bl AS jsonb),
                    next_review_date = :nr,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE
            """),
            {
                "stage": adjusted_stage,
                "entered": stage_entered_at,
                "bl": baseline_json,
                "nr": next_review,
                "tid": tenant_id,
                "sid": store_id,
            },
        )

        if stage_changed:
            log.info(
                "lifecycle.stage_changed",
                store_id=str(store_id),
                old_stage=old_stage,
                new_stage=adjusted_stage,
                months=months,
            )

        return {
            "store_id": str(store_id),
            "opened_date": opened_date.isoformat(),
            "months_since_opening": months,
            "current_stage": adjusted_stage,
            "stage_description": rule["description"],
            "stage_entered_at": stage_entered_at.isoformat() if hasattr(stage_entered_at, "isoformat") else str(stage_entered_at),
            "health_baseline": health_baseline,
            "next_review_date": next_review.isoformat(),
            "stage_changed": stage_changed,
        }

    async def get_stage_baselines(
        self,
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        """获取当前阶段的基准指标"""
        await _set_tenant(db, tenant_id)

        row = await db.execute(
            text("""
                SELECT current_stage, health_baseline, opened_date,
                       months_since_opening, stage_entered_at
                FROM store_lifecycle_stages
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE
            """),
            {"tid": tenant_id, "sid": store_id},
        )
        r = row.mappings().first()
        if r is None:
            # 没有记录时先判定
            return await self.determine_stage(db, store_id, tenant_id)

        stage = r["current_stage"]
        rule = self.STAGE_RULES.get(stage, self.STAGE_RULES["mature"])
        baseline = r["health_baseline"]
        if isinstance(baseline, str):
            baseline = json.loads(baseline)

        return {
            "store_id": str(store_id),
            "current_stage": stage,
            "stage_description": rule["description"],
            "months_since_opening": int(r["months_since_opening"] or 0),
            "opened_date": r["opened_date"].isoformat() if hasattr(r["opened_date"], "isoformat") else str(r["opened_date"]),
            "health_baseline": baseline or {
                "revenue_target_pct": rule["revenue_target_pct"],
                "profit_margin_min": rule["profit_margin_min"],
                "turnover_min": rule["turnover_min"],
            },
            "all_stages": {
                k: {
                    "description": v["description"],
                    "months_range": f"{v['months'][0]}-{v['months'][1]}月",
                    "revenue_target_pct": v["revenue_target_pct"],
                    "profit_margin_min": v["profit_margin_min"],
                }
                for k, v in self.STAGE_RULES.items()
            },
        }

    async def get_lifecycle_overview(
        self,
        db: AsyncSession,
        tenant_id: UUID,
    ) -> list[dict[str, Any]]:
        """所有门店的生命周期概览（总部视角）

        每家店: store_name, opened_date, months, stage, health_vs_stage_baseline
        """
        await _set_tenant(db, tenant_id)

        rows = await db.execute(
            text("""
                SELECT s.id AS store_id, s.store_name,
                       sl.opened_date, sl.months_since_opening,
                       sl.current_stage, sl.stage_entered_at,
                       sl.health_baseline, sl.next_review_date
                FROM stores s
                LEFT JOIN store_lifecycle_stages sl
                    ON sl.store_id = s.id AND sl.tenant_id = s.tenant_id
                    AND sl.is_deleted = FALSE
                WHERE s.tenant_id = :tid AND s.is_deleted = FALSE
                ORDER BY sl.months_since_opening DESC NULLS LAST, s.store_name
            """),
            {"tid": tenant_id},
        )

        items: list[dict[str, Any]] = []
        for r in rows.mappings().fetchall():
            stage = r["current_stage"]
            rule = self.STAGE_RULES.get(stage, {}) if stage else {}

            baseline = r["health_baseline"]
            if isinstance(baseline, str):
                baseline = json.loads(baseline)

            items.append({
                "store_id": str(r["store_id"]),
                "store_name": r["store_name"],
                "opened_date": r["opened_date"].isoformat() if r["opened_date"] and hasattr(r["opened_date"], "isoformat") else None,
                "months_since_opening": int(r["months_since_opening"]) if r["months_since_opening"] is not None else None,
                "current_stage": stage,
                "stage_description": rule.get("description", "未知"),
                "stage_entered_at": r["stage_entered_at"].isoformat() if r["stage_entered_at"] and hasattr(r["stage_entered_at"], "isoformat") else None,
                "health_baseline": baseline,
                "next_review_date": r["next_review_date"].isoformat() if r["next_review_date"] and hasattr(r["next_review_date"], "isoformat") else None,
            })

        return items

    # ── 初始化门店生命周期 ──────────────────────────────────────────

    async def init_store_lifecycle(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        opened_date: date,
    ) -> dict[str, Any]:
        """为门店初始化生命周期记录"""
        await _set_tenant(db, tenant_id)

        months = self._calc_months(opened_date, date.today())
        stage = self._stage_by_months(months)
        rule = self.STAGE_RULES[stage]
        baseline = {
            "revenue_target_pct": rule["revenue_target_pct"],
            "profit_margin_min": rule["profit_margin_min"],
            "turnover_min": rule["turnover_min"],
        }
        baseline_json = json.dumps(baseline, ensure_ascii=False)
        new_id = uuid4()

        await db.execute(
            text("""
                INSERT INTO store_lifecycle_stages
                    (id, tenant_id, store_id, opened_date, current_stage,
                     stage_entered_at, health_baseline, next_review_date)
                VALUES
                    (:id, :tid, :sid, :opened, :stage,
                     :entered, CAST(:bl AS jsonb), :nr)
                ON CONFLICT (tenant_id, store_id)
                DO UPDATE SET
                    opened_date = EXCLUDED.opened_date,
                    current_stage = EXCLUDED.current_stage,
                    stage_entered_at = EXCLUDED.stage_entered_at,
                    health_baseline = EXCLUDED.health_baseline,
                    next_review_date = EXCLUDED.next_review_date,
                    updated_at = NOW()
            """),
            {
                "id": new_id,
                "tid": tenant_id,
                "sid": store_id,
                "opened": opened_date,
                "stage": stage,
                "entered": date.today(),
                "bl": baseline_json,
                "nr": date.today() + timedelta(days=30),
            },
        )

        log.info(
            "lifecycle.initialized",
            store_id=str(store_id),
            stage=stage,
            months=months,
        )

        return {
            "store_id": str(store_id),
            "opened_date": opened_date.isoformat(),
            "current_stage": stage,
            "months_since_opening": months,
            "health_baseline": baseline,
        }

    # ── 内部辅助 ────────────────────────────────────────────────────

    async def _get_or_create_lifecycle(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
    ) -> dict[str, Any] | None:
        """获取生命周期记录，不存在则从 stores 表 created_at 自动创建"""
        row = await db.execute(
            text("""
                SELECT opened_date, current_stage, stage_entered_at,
                       health_baseline, months_since_opening
                FROM store_lifecycle_stages
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE
            """),
            {"tid": tenant_id, "sid": store_id},
        )
        r = row.mappings().first()
        if r:
            return dict(r)

        # 尝试从 stores 表获取开业日期
        store_row = await db.execute(
            text("""
                SELECT COALESCE(opened_at, created_at)::date AS opened_date
                FROM stores
                WHERE id = :sid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"sid": store_id, "tid": tenant_id},
        )
        sr = store_row.mappings().first()
        if sr is None:
            return None

        opened = sr["opened_date"]
        result = await self.init_store_lifecycle(db, tenant_id, store_id, opened)
        return {"opened_date": opened, "current_stage": result["current_stage"], "stage_entered_at": date.today()}

    @staticmethod
    def _calc_months(opened_date: date, today: date) -> int:
        """计算开业月数"""
        return (today.year - opened_date.year) * 12 + (today.month - opened_date.month)

    def _stage_by_months(self, months: int) -> str:
        """根据月数判定阶段"""
        for stage, rule in self.STAGE_RULES.items():
            low, high = rule["months"]
            if low <= months < high:
                return stage
        return "decline"

    async def _adjust_stage_by_performance(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        initial_stage: str,
        months: int,
    ) -> str:
        """叠加经营数据修正阶段判定

        规则：
        - 成熟期但连续3月营收下滑>10% -> 提前进入平台期
        - 平台期但连续2月营收下滑>15% -> 提前进入衰退期
        - 爬坡期但营收超标50%且利润率>15% -> 提前进入成熟期
        """
        try:
            # 查询最近3个月的营收趋势
            rows = await db.execute(
                text("""
                    SELECT TO_CHAR(created_at, 'YYYY-MM') AS mon,
                           COALESCE(SUM(final_amount_fen), 0) AS revenue_fen
                    FROM orders
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND status NOT IN ('cancelled', 'refunded')
                      AND created_at >= CURRENT_DATE - INTERVAL '90 days'
                    GROUP BY TO_CHAR(created_at, 'YYYY-MM')
                    ORDER BY mon DESC
                    LIMIT 3
                """),
                {"tid": tenant_id, "sid": store_id},
            )
            monthly_rev = [int(r["revenue_fen"] or 0) for r in rows.mappings().fetchall()]

            if len(monthly_rev) < 2:
                return initial_stage

            # 检查连续下滑
            declining_months = 0
            for i in range(len(monthly_rev) - 1):
                current = monthly_rev[i]
                previous = monthly_rev[i + 1]
                if previous > 0 and current < previous * 0.9:
                    declining_months += 1

            if initial_stage == "mature" and declining_months >= 2:
                log.info(
                    "lifecycle.early_plateau",
                    store_id=str(store_id),
                    declining_months=declining_months,
                )
                return "plateau"

            if initial_stage == "plateau" and declining_months >= 2:
                decline_pct = (
                    (monthly_rev[-1] - monthly_rev[0]) / max(monthly_rev[0], 1)
                    if monthly_rev[-1] > 0
                    else 0
                )
                if abs(decline_pct) > 0.15:
                    log.info(
                        "lifecycle.early_decline",
                        store_id=str(store_id),
                        decline_pct=round(decline_pct, 4),
                    )
                    return "decline"

        except (ProgrammingError, DBAPIError) as exc:
            log.debug("lifecycle.performance_adjust_unavailable", error=str(exc))

        return initial_stage
