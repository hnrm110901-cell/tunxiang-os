"""绩效奖金计算服务

基于员工月度日KPI得分卡均分，按角色奖金规则阶梯系数计算月度绩效奖金。
奖金 = base_amount_fen x multiplier（由月均分匹配 tier_config 决定）

金额单位：分（fen）。RLS：每次 DB 操作前设置 app.tenant_id。
"""

from __future__ import annotations

import json
from datetime import date
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


class BonusCalculatorService:
    """月度绩效奖金计算引擎"""

    # ── 默认阶梯配置（bonus_rules 表无数据时降级使用）──────────────
    DEFAULT_TIER_CONFIG: list[dict[str, Any]] = [
        {"min_score": 90, "max_score": 100, "multiplier": 1.5},
        {"min_score": 80, "max_score": 89, "multiplier": 1.2},
        {"min_score": 70, "max_score": 79, "multiplier": 1.0},
        {"min_score": 0, "max_score": 69, "multiplier": 0.8},
    ]
    DEFAULT_BASE_AMOUNT_FEN = 200000  # 2000元

    # ── 计算月度奖金 ────────────────────────────────────────────────

    async def calculate_monthly_bonus(
        self,
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
        year: int,
        month: int,
    ) -> list[dict[str, Any]]:
        """计算月度绩效奖金

        1. 查询该员工当月所有daily_scorecards -> 月均分
        2. 查询该角色的bonus_rules -> 匹配tier -> multiplier
        3. 奖金 = base_amount_fen x multiplier
        4. 返回每个员工: {employee_id, role, avg_score, multiplier, bonus_fen, bonus_yuan}
        """
        await _set_tenant(db, tenant_id)

        # 月份范围
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1)
        else:
            month_end = date(year, month + 1, 1)

        # 1. 查询月均分
        rows = await db.execute(
            text("""
                SELECT employee_id, employee_name, role,
                       AVG(total_score)::NUMERIC(5,1) AS avg_score,
                       COUNT(*) AS score_days
                FROM daily_scorecards
                WHERE tenant_id = :tid AND store_id = :sid
                  AND score_date >= :d0 AND score_date < :d1
                  AND is_deleted = FALSE
                GROUP BY employee_id, employee_name, role
                ORDER BY avg_score DESC
            """),
            {"tid": tenant_id, "sid": store_id, "d0": month_start, "d1": month_end},
        )
        emp_scores = rows.mappings().fetchall()

        if not emp_scores:
            return []

        # 2. 查询奖金规则 (门店级优先 -> 品牌级)
        rules_map = await self._load_bonus_rules(db, tenant_id, store_id)

        # 3. 计算每个员工奖金
        results: list[dict[str, Any]] = []
        for emp in emp_scores:
            role = str(emp["role"] or "").strip().lower()
            avg_score = float(emp["avg_score"] or 0)

            rule = rules_map.get(role, {})
            base_fen = int(rule.get("base_amount_fen", self.DEFAULT_BASE_AMOUNT_FEN))
            tier_config = rule.get("tier_config", self.DEFAULT_TIER_CONFIG)

            multiplier = self._match_tier(avg_score, tier_config)
            bonus_fen = int(round(base_fen * multiplier))

            results.append({
                "employee_id": str(emp["employee_id"]),
                "employee_name": emp["employee_name"],
                "role": role,
                "avg_score": avg_score,
                "score_days": int(emp["score_days"] or 0),
                "base_amount_fen": base_fen,
                "multiplier": multiplier,
                "bonus_fen": bonus_fen,
                "bonus_yuan": round(bonus_fen / 100, 2),
            })

        log.info(
            "bonus.calculated",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            year=year,
            month=month,
            employee_count=len(results),
            total_bonus_fen=sum(r["bonus_fen"] for r in results),
        )
        return results

    async def preview_bonus(
        self,
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
        year: int,
        month: int,
    ) -> dict[str, Any]:
        """奖金预览（月末前预估）

        基于截至今日的得分预估月末奖金，含总金额汇总+按角色汇总
        """
        items = await self.calculate_monthly_bonus(db, store_id, tenant_id, year, month)

        total_bonus_fen = sum(i["bonus_fen"] for i in items)

        # 按角色汇总
        role_summary: dict[str, dict[str, Any]] = {}
        for item in items:
            role = item["role"]
            if role not in role_summary:
                role_summary[role] = {
                    "role": role,
                    "count": 0,
                    "total_bonus_fen": 0,
                    "avg_score": 0.0,
                    "scores_sum": 0.0,
                }
            rs = role_summary[role]
            rs["count"] += 1
            rs["total_bonus_fen"] += item["bonus_fen"]
            rs["scores_sum"] += item["avg_score"]

        for rs in role_summary.values():
            rs["avg_score"] = round(rs["scores_sum"] / max(rs["count"], 1), 1)
            rs["total_bonus_yuan"] = round(rs["total_bonus_fen"] / 100, 2)
            del rs["scores_sum"]

        return {
            "year": year,
            "month": month,
            "store_id": str(store_id),
            "total_employees": len(items),
            "total_bonus_fen": total_bonus_fen,
            "total_bonus_yuan": round(total_bonus_fen / 100, 2),
            "role_summary": list(role_summary.values()),
            "details": items,
            "is_preview": True,
            "note": "基于截至今日的日得分卡数据预估",
        }

    # ── 奖金规则管理 ────────────────────────────────────────────────

    async def get_bonus_rules(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """获取奖金规则列表"""
        await _set_tenant(db, tenant_id)

        conds = ["tenant_id = :tid", "is_deleted = FALSE"]
        params: dict[str, Any] = {"tid": tenant_id}

        if store_id is not None:
            conds.append("(store_id = :sid OR store_id IS NULL)")
            params["sid"] = store_id
        else:
            conds.append("store_id IS NULL")

        where = " AND ".join(conds)
        rows = await db.execute(
            text(f"""
                SELECT id, tenant_id, store_id, role, base_amount_fen,
                       tier_config, effective_from, effective_until,
                       is_active, created_at, updated_at
                FROM bonus_rules
                WHERE {where}
                ORDER BY role, store_id NULLS LAST
            """),
            params,
        )
        items: list[dict[str, Any]] = []
        for r in rows.mappings().fetchall():
            row = dict(r)
            row["id"] = str(row["id"])
            row["tenant_id"] = str(row["tenant_id"])
            row["store_id"] = str(row["store_id"]) if row["store_id"] else None
            tc = row.get("tier_config")
            if isinstance(tc, str):
                row["tier_config"] = json.loads(tc)
            for dt_field in ("effective_from", "effective_until", "created_at", "updated_at"):
                val = row.get(dt_field)
                if val is not None and hasattr(val, "isoformat"):
                    row[dt_field] = val.isoformat()
            items.append(row)
        return items

    async def manage_bonus_rules(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID | None,
        role: str,
        rules: dict[str, Any],
    ) -> dict[str, Any]:
        """新建或更新奖金规则"""
        await _set_tenant(db, tenant_id)

        base_amount_fen = int(rules.get("base_amount_fen", self.DEFAULT_BASE_AMOUNT_FEN))
        tier_config = rules.get("tier_config", self.DEFAULT_TIER_CONFIG)
        effective_from = rules.get("effective_from")
        effective_until = rules.get("effective_until")
        is_active = rules.get("is_active", True)

        tier_json = json.dumps(tier_config, ensure_ascii=False)
        rule_id = uuid4()

        # 先软删除该角色旧规则
        if store_id is not None:
            await db.execute(
                text("""
                    UPDATE bonus_rules
                    SET is_active = FALSE, is_deleted = TRUE, updated_at = NOW()
                    WHERE tenant_id = :tid AND store_id = :sid AND role = :role
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "sid": store_id, "role": role},
            )
        else:
            await db.execute(
                text("""
                    UPDATE bonus_rules
                    SET is_active = FALSE, is_deleted = TRUE, updated_at = NOW()
                    WHERE tenant_id = :tid AND store_id IS NULL AND role = :role
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "role": role},
            )

        # 插入新规则
        await db.execute(
            text("""
                INSERT INTO bonus_rules
                    (id, tenant_id, store_id, role, base_amount_fen, tier_config,
                     effective_from, effective_until, is_active)
                VALUES
                    (:id, :tid, :sid, :role, :base, CAST(:tiers AS jsonb),
                     :ef, :eu, :active)
            """),
            {
                "id": rule_id,
                "tid": tenant_id,
                "sid": store_id,
                "role": role,
                "base": base_amount_fen,
                "tiers": tier_json,
                "ef": effective_from,
                "eu": effective_until,
                "active": is_active,
            },
        )

        log.info(
            "bonus_rule.upserted",
            tenant_id=str(tenant_id),
            store_id=str(store_id) if store_id else None,
            role=role,
            base_amount_fen=base_amount_fen,
        )

        return {
            "id": str(rule_id),
            "role": role,
            "base_amount_fen": base_amount_fen,
            "tier_config": tier_config,
            "is_active": is_active,
        }

    # ── 内部辅助 ────────────────────────────────────────────────────

    async def _load_bonus_rules(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
    ) -> dict[str, dict[str, Any]]:
        """加载奖金规则。优先门店级，降级品牌级。"""
        try:
            rows = await db.execute(
                text("""
                    SELECT role, base_amount_fen, tier_config, store_id
                    FROM bonus_rules
                    WHERE tenant_id = :tid
                      AND (store_id = :sid OR store_id IS NULL)
                      AND is_active = TRUE AND is_deleted = FALSE
                    ORDER BY store_id NULLS LAST
                """),
                {"tid": tenant_id, "sid": store_id},
            )

            rules: dict[str, dict[str, Any]] = {}
            for r in rows.mappings().fetchall():
                role = str(r["role"]).strip().lower()
                # 门店级覆盖品牌级（先到先得，门店级排在前面）
                if role not in rules:
                    tc = r["tier_config"]
                    if isinstance(tc, str):
                        tc = json.loads(tc)
                    rules[role] = {
                        "base_amount_fen": int(r["base_amount_fen"]),
                        "tier_config": tc,
                    }
            return rules
        except (ProgrammingError, DBAPIError) as exc:
            log.warning("bonus.rules_load_failed", error=str(exc))
            return {}

    @staticmethod
    def _match_tier(
        avg_score: float,
        tier_config: list[dict[str, Any]],
    ) -> float:
        """根据月均分匹配阶梯系数"""
        score_int = int(round(avg_score))
        for tier in tier_config:
            min_s = int(tier.get("min_score", 0))
            max_s = int(tier.get("max_score", 100))
            if min_s <= score_int <= max_s:
                return float(tier.get("multiplier", 1.0))
        # 未匹配到任何阶梯，使用最低系数
        return 0.8
