"""Forge 结果计价引擎 — 对标 Intercom $0.99/resolution

职责：
  1. create_outcome_definition()  — 定义可计费的结果类型
  2. list_outcome_definitions()   — 列出结果定义
  3. record_outcome_event()       — 记录结果事件 + 自动计收入
  4. verify_outcome()             — 人工/自动验证结果
  5. attribute_outcome()          — 多 Agent 归因分润
  6. get_outcome_dashboard()      — 结果仪表盘
  7. get_outcome_events()         — 分页查询结果事件
"""

from __future__ import annotations

import json
import math
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import PRICING_MODELS

logger = structlog.get_logger(__name__)

# ── 允许值枚举 ────────────────────────────────────────────────
OUTCOME_TYPES = {
    "resolution",       # 问题解决（客服场景）
    "conversion",       # 转化（营销场景）
    "retention",        # 留存（会员场景）
    "cost_saving",      # 降本（运营场景）
    "compliance_pass",  # 合规通过（食安/财务）
    "custom",           # 自定义
}

MEASUREMENT_METHODS = {"event_count", "duration", "value_delta", "manual"}

VERIFICATION_METHODS = {"auto", "manual", "dual"}


class ForgeOutcomeService:
    """结果计价引擎 — 对标 Intercom $0.99/resolution"""

    # ── 1. 创建结果定义 ─────────────────────────────────────────
    async def create_outcome_definition(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        outcome_type: str,
        outcome_name: str,
        description: str = "",
        measurement_method: str = "event_count",
        price_fen_per_outcome: int = 0,
        attribution_window_hours: int = 24,
        verification_method: str = "auto",
    ) -> dict:
        """定义一种可计费的结果类型。"""
        if outcome_type not in OUTCOME_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"无效 outcome_type: {outcome_type}，可选: {sorted(OUTCOME_TYPES)}",
            )
        if measurement_method not in MEASUREMENT_METHODS:
            raise HTTPException(
                status_code=422,
                detail=f"无效 measurement_method: {measurement_method}，可选: {sorted(MEASUREMENT_METHODS)}",
            )
        if verification_method not in VERIFICATION_METHODS:
            raise HTTPException(
                status_code=422,
                detail=f"无效 verification_method: {verification_method}，可选: {sorted(VERIFICATION_METHODS)}",
            )

        outcome_id = f"oc_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_outcome_definitions
                    (outcome_id, app_id, outcome_type, outcome_name, description,
                     measurement_method, price_fen_per_outcome,
                     attribution_window_hours, verification_method)
                VALUES
                    (:outcome_id, :app_id, :outcome_type, :outcome_name, :description,
                     :measurement_method, :price_fen_per_outcome,
                     :attribution_window_hours, :verification_method)
                RETURNING outcome_id, app_id, outcome_type, outcome_name, description,
                          measurement_method, price_fen_per_outcome,
                          attribution_window_hours, verification_method,
                          is_active, created_at
            """),
            {
                "outcome_id": outcome_id,
                "app_id": app_id,
                "outcome_type": outcome_type,
                "outcome_name": outcome_name,
                "description": description,
                "measurement_method": measurement_method,
                "price_fen_per_outcome": price_fen_per_outcome,
                "attribution_window_hours": attribution_window_hours,
                "verification_method": verification_method,
            },
        )
        row = dict(result.mappings().one())

        logger.info(
            "outcome_definition_created",
            outcome_id=outcome_id,
            app_id=app_id,
            outcome_type=outcome_type,
            price_fen=price_fen_per_outcome,
        )
        await db.commit()
        return row

    # ── 2. 列出结果定义 ─────────────────────────────────────────
    async def list_outcome_definitions(
        self,
        db: AsyncSession,
        *,
        app_id: str | None = None,
        outcome_type: str | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        """按条件筛选结果定义列表。"""
        clauses: list[str] = []
        params: dict = {}

        if app_id:
            clauses.append("app_id = :app_id")
            params["app_id"] = app_id
        if outcome_type:
            clauses.append("outcome_type = :outcome_type")
            params["outcome_type"] = outcome_type
        if active_only:
            clauses.append("is_active = true")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        result = await db.execute(
            text(f"""
                SELECT outcome_id, app_id, outcome_type, outcome_name, description,
                       measurement_method, price_fen_per_outcome,
                       attribution_window_hours, verification_method,
                       is_active, created_at
                FROM forge_outcome_definitions
                {where}
                ORDER BY created_at DESC
            """),
            params,
        )
        return [dict(r) for r in result.mappings().all()]

    # ── 3. 记录结果事件 ─────────────────────────────────────────
    async def record_outcome_event(
        self,
        db: AsyncSession,
        *,
        outcome_id: str,
        app_id: str,
        store_id: str | None = None,
        agent_id: str | None = None,
        decision_log_id: str | None = None,
        outcome_data: dict | None = None,
    ) -> dict:
        """记录一次结果事件，自动查询价格并计收入。"""
        if outcome_data is None:
            outcome_data = {}

        # 查定义获取单价
        def_result = await db.execute(
            text("""
                SELECT outcome_id, app_id, outcome_type, price_fen_per_outcome,
                       verification_method
                FROM forge_outcome_definitions
                WHERE outcome_id = :outcome_id AND is_active = true
            """),
            {"outcome_id": outcome_id},
        )
        definition = def_result.mappings().first()
        if not definition:
            raise HTTPException(status_code=404, detail=f"结果定义不存在或已停用: {outcome_id}")

        price_fen = definition["price_fen_per_outcome"]
        auto_verified = definition["verification_method"] == "auto"

        event_id = f"oev_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_outcome_events
                    (event_id, outcome_id, app_id, store_id, agent_id,
                     decision_log_id, outcome_data, revenue_fen,
                     verified, verified_at)
                VALUES
                    (:event_id, :outcome_id, :app_id, :store_id, :agent_id,
                     :decision_log_id, :outcome_data::jsonb, :revenue_fen,
                     :verified, CASE WHEN :verified THEN NOW() ELSE NULL END)
                RETURNING event_id, outcome_id, app_id, store_id, agent_id,
                          decision_log_id, outcome_data, revenue_fen,
                          verified, verified_at, created_at
            """),
            {
                "event_id": event_id,
                "outcome_id": outcome_id,
                "app_id": app_id,
                "store_id": store_id,
                "agent_id": agent_id,
                "decision_log_id": decision_log_id,
                "outcome_data": json.dumps(outcome_data, ensure_ascii=False),
                "revenue_fen": price_fen,
                "verified": auto_verified,
            },
        )
        event_row = dict(result.mappings().one())

        # 自动验证时直接记录收入
        if auto_verified and price_fen > 0:
            await db.execute(
                text("""
                    INSERT INTO forge_revenue_entries
                        (app_id, payer_tenant_id, amount_fen, platform_fee_fen,
                         developer_payout_fen, fee_rate, pricing_model)
                    VALUES
                        (:app_id, :store_id, :amount_fen, :platform_fee_fen,
                         :developer_payout_fen, :fee_rate, 'usage_based')
                """),
                {
                    "app_id": app_id,
                    "store_id": store_id or "platform",
                    "amount_fen": price_fen,
                    "platform_fee_fen": int(price_fen * PRICING_MODELS["usage_based"]["platform_fee_rate"]),
                    "developer_payout_fen": price_fen - int(price_fen * PRICING_MODELS["usage_based"]["platform_fee_rate"]),
                    "fee_rate": PRICING_MODELS["usage_based"]["platform_fee_rate"],
                },
            )

        await db.commit()

        logger.info(
            "outcome_event_recorded",
            event_id=event_id,
            outcome_id=outcome_id,
            app_id=app_id,
            revenue_fen=price_fen,
            auto_verified=auto_verified,
        )
        return event_row

    # ── 4. 验证结果 ─────────────────────────────────────────────
    async def verify_outcome(
        self,
        db: AsyncSession,
        event_id: str,
        *,
        verified: bool,
        verified_by: str,
    ) -> dict:
        """人工验证结果事件，验证失败时冲销收入。"""
        result = await db.execute(
            text("""
                UPDATE forge_outcome_events
                SET verified = :verified,
                    verified_at = NOW(),
                    verified_by = :verified_by
                WHERE event_id = :event_id
                RETURNING event_id, outcome_id, app_id, store_id,
                          revenue_fen, verified, verified_at, verified_by
            """),
            {
                "event_id": event_id,
                "verified": verified,
                "verified_by": verified_by,
            },
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"结果事件不存在: {event_id}")

        row_dict = dict(row)

        # 验证失败 → 冲销收入（插入负数流水）
        if not verified and row_dict["revenue_fen"] > 0:
            await db.execute(
                text("""
                    INSERT INTO forge_revenue_entries
                        (app_id, payer_tenant_id, amount_fen, platform_fee_fen,
                         developer_payout_fen, fee_rate, pricing_model)
                    VALUES
                        (:app_id, :store_id, :neg_amount, :neg_fee,
                         :neg_payout, :fee_rate, 'usage_based')
                """),
                {
                    "app_id": row_dict["app_id"],
                    "store_id": row_dict["store_id"] or "platform",
                    "neg_amount": -row_dict["revenue_fen"],
                    "neg_fee": -int(row_dict["revenue_fen"] * PRICING_MODELS["usage_based"]["platform_fee_rate"]),
                    "neg_payout": -(row_dict["revenue_fen"] - int(row_dict["revenue_fen"] * PRICING_MODELS["usage_based"]["platform_fee_rate"])),
                    "fee_rate": PRICING_MODELS["usage_based"]["platform_fee_rate"],
                },
            )
            logger.info(
                "outcome_revenue_reversed",
                event_id=event_id,
                reversed_fen=row_dict["revenue_fen"],
            )

        await db.commit()

        logger.info(
            "outcome_verified",
            event_id=event_id,
            verified=verified,
            verified_by=verified_by,
        )
        return row_dict

    # ── 5. 多 Agent 归因 ────────────────────────────────────────
    async def attribute_outcome(
        self,
        db: AsyncSession,
        *,
        outcome_id: str,
        app_id: str,
        store_id: str,
        outcome_data: dict | None = None,
    ) -> dict:
        """多 Agent 归因：按时间衰减 + 因果权重拆分功劳。"""
        if outcome_data is None:
            outcome_data = {}

        # 查定义
        def_result = await db.execute(
            text("""
                SELECT outcome_id, outcome_type, price_fen_per_outcome,
                       attribution_window_hours
                FROM forge_outcome_definitions
                WHERE outcome_id = :outcome_id AND is_active = true
            """),
            {"outcome_id": outcome_id},
        )
        definition = def_result.mappings().first()
        if not definition:
            raise HTTPException(status_code=404, detail=f"结果定义不存在: {outcome_id}")

        window_hours = definition["attribution_window_hours"]
        price_fen = definition["price_fen_per_outcome"]

        # 查归因窗口内的 Agent 决策日志
        logs_result = await db.execute(
            text("""
                SELECT id, agent_id, decision_type, confidence, created_at
                FROM agent_decision_logs
                WHERE store_id = :store_id
                  AND created_at >= NOW() - MAKE_INTERVAL(hours => :window_hours)
                ORDER BY created_at DESC
            """),
            {"store_id": store_id, "window_hours": window_hours},
        )
        decision_logs = [dict(r) for r in logs_result.mappings().all()]

        # 计算归因权重（时间衰减 + 置信度）
        attributed_agents: list[dict] = []
        total_raw_weight = 0.0

        for log_entry in decision_logs:
            # 时间衰减：越近越大，半衰期 = window / 2
            # 简化：线性衰减
            hours_ago = 0.0  # 由 DB 端计算时差，此处用序号近似
            idx = decision_logs.index(log_entry)
            time_factor = max(0.1, 1.0 - (idx / max(len(decision_logs), 1)))
            confidence = float(log_entry.get("confidence") or 0.5)
            raw_weight = time_factor * confidence
            total_raw_weight += raw_weight
            attributed_agents.append({
                "agent_id": log_entry["agent_id"],
                "decision_id": str(log_entry["id"]),
                "decision_type": log_entry["decision_type"],
                "raw_weight": raw_weight,
                "weight": 0.0,  # 归一化后填充
            })

        # 归一化权重
        for agent in attributed_agents:
            agent["weight"] = round(
                agent["raw_weight"] / total_raw_weight, 4
            ) if total_raw_weight > 0 else 0.0
            del agent["raw_weight"]

        # 记录结果事件
        event_id = f"oev_{uuid4().hex[:12]}"
        attributed_data = {
            **outcome_data,
            "attributed_agents": attributed_agents,
        }

        await db.execute(
            text("""
                INSERT INTO forge_outcome_events
                    (event_id, outcome_id, app_id, store_id,
                     outcome_data, revenue_fen, verified)
                VALUES
                    (:event_id, :outcome_id, :app_id, :store_id,
                     :outcome_data::jsonb, :revenue_fen, true)
            """),
            {
                "event_id": event_id,
                "outcome_id": outcome_id,
                "app_id": app_id,
                "store_id": store_id,
                "outcome_data": json.dumps(attributed_data, ensure_ascii=False),
                "revenue_fen": price_fen,
            },
        )
        await db.commit()

        logger.info(
            "outcome_attributed",
            event_id=event_id,
            outcome_id=outcome_id,
            agent_count=len(attributed_agents),
            total_revenue_fen=price_fen,
        )

        return {
            "outcome_event_id": event_id,
            "outcome_id": outcome_id,
            "app_id": app_id,
            "store_id": store_id,
            "attributed_agents": attributed_agents,
            "total_revenue_fen": price_fen,
        }

    # ── 6. 结果仪表盘 ──────────────────────────────────────────
    async def get_outcome_dashboard(
        self,
        db: AsyncSession,
        *,
        app_id: str | None = None,
        days: int = 30,
    ) -> dict:
        """汇总结果事件：总量、验证率、收入、按类型拆分、趋势。"""
        app_filter = "AND e.app_id = :app_id" if app_id else ""
        params: dict = {"days": days}
        if app_id:
            params["app_id"] = app_id

        # 总量统计
        summary_result = await db.execute(
            text(f"""
                SELECT
                    COUNT(*)                                    AS total_outcomes,
                    COUNT(*) FILTER (WHERE e.verified = true)   AS verified_outcomes,
                    COALESCE(SUM(e.revenue_fen), 0)             AS total_revenue_fen
                FROM forge_outcome_events e
                WHERE e.created_at >= NOW() - MAKE_INTERVAL(days => :days)
                  {app_filter}
            """),
            params,
        )
        summary = dict(summary_result.mappings().one())

        # 按类型拆分
        type_result = await db.execute(
            text(f"""
                SELECT
                    d.outcome_type,
                    COUNT(*)                        AS event_count,
                    COALESCE(SUM(e.revenue_fen), 0) AS revenue_fen
                FROM forge_outcome_events e
                JOIN forge_outcome_definitions d ON d.outcome_id = e.outcome_id
                WHERE e.created_at >= NOW() - MAKE_INTERVAL(days => :days)
                  {app_filter}
                GROUP BY d.outcome_type
                ORDER BY revenue_fen DESC
            """),
            params,
        )
        by_type = [dict(r) for r in type_result.mappings().all()]

        # 按日趋势
        trend_result = await db.execute(
            text(f"""
                SELECT
                    e.created_at::date              AS day,
                    COUNT(*)                        AS event_count,
                    COALESCE(SUM(e.revenue_fen), 0) AS revenue_fen
                FROM forge_outcome_events e
                WHERE e.created_at >= NOW() - MAKE_INTERVAL(days => :days)
                  {app_filter}
                GROUP BY e.created_at::date
                ORDER BY day ASC
            """),
            params,
        )
        daily_trend = [dict(r) for r in trend_result.mappings().all()]

        # Top Agent 归因排行
        top_agents_result = await db.execute(
            text(f"""
                SELECT
                    e.agent_id,
                    COUNT(*)                        AS outcome_count,
                    COALESCE(SUM(e.revenue_fen), 0) AS revenue_fen
                FROM forge_outcome_events e
                WHERE e.created_at >= NOW() - MAKE_INTERVAL(days => :days)
                  AND e.agent_id IS NOT NULL
                  {app_filter}
                GROUP BY e.agent_id
                ORDER BY revenue_fen DESC
                LIMIT 10
            """),
            params,
        )
        top_agents = [dict(r) for r in top_agents_result.mappings().all()]

        return {
            **summary,
            "days": days,
            "by_type": by_type,
            "daily_trend": daily_trend,
            "top_agents": top_agents,
        }

    # ── 7. 分页查询结果事件 ─────────────────────────────────────
    async def get_outcome_events(
        self,
        db: AsyncSession,
        *,
        app_id: str | None = None,
        outcome_id: str | None = None,
        verified: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询结果事件列表。"""
        clauses: list[str] = []
        params: dict = {}

        if app_id:
            clauses.append("e.app_id = :app_id")
            params["app_id"] = app_id
        if outcome_id:
            clauses.append("e.outcome_id = :outcome_id")
            params["outcome_id"] = outcome_id
        if verified is not None:
            clauses.append("e.verified = :verified")
            params["verified"] = verified

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        # 总数
        count_result = await db.execute(
            text(f"""
                SELECT COUNT(*) FROM forge_outcome_events e {where}
            """),
            params,
        )
        total = count_result.scalar_one()

        # 数据
        result = await db.execute(
            text(f"""
                SELECT e.event_id, e.outcome_id, e.app_id, e.store_id,
                       e.agent_id, e.decision_log_id, e.outcome_data,
                       e.revenue_fen, e.verified, e.verified_at,
                       e.verified_by, e.created_at
                FROM forge_outcome_events e
                {where}
                ORDER BY e.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]

        return {"items": items, "total": total, "page": page, "size": size}
