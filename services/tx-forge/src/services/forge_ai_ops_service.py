"""Forge AI Ops 服务 — Agent 可观测性 & LLM 成本分析

跨服务只读查询 tx-agent 拥有的表（同一 PostgreSQL 实例）：
  - agent_decision_logs  — Agent 决策留痕
  - session_runs          — 会话执行记录
  - session_events        — 会话事件时间线
  - model_call_logs       — 模型调用日志
  - agent_memories         — Agent 记忆存储

职责：
  1. get_agent_observatory()   — 9 大 Agent 全景仪表盘
  2. get_agent_detail()        — 单 Agent 详情（分布 + 趋势）
  3. get_agent_traces()        — 会话追踪列表（分页）
  4. get_trace_detail()        — 单次会话事件时间线
  5. get_decision_feed()       — 决策流（实时 feed）
  6. get_model_registry()      — 模型注册表（成本 + 性能）
  7. get_llm_cost_dashboard()  — LLM 成本仪表盘
  8. get_llm_latency_stats()   — 延迟百分位统计
  9. get_agent_memory_browse() — Agent 记忆浏览
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import AGENT_REGISTRY

logger = structlog.get_logger(__name__)

# agent_id → 注册信息快查
_AGENT_MAP: dict[str, dict] = {a["agent_id"]: a for a in AGENT_REGISTRY}


class ForgeAIOpsService:
    """Agent 可观测性与 LLM 运维"""

    # ──────────────────────────────────────────────────────────
    #  Agent 全景
    # ──────────────────────────────────────────────────────────

    async def get_agent_observatory(
        self, db: AsyncSession, *, store_id: str | None = None
    ) -> dict:
        """9 大 Agent 全景仪表盘：决策量 / 置信度 / 延迟 / 约束违规。"""
        store_filter = "AND store_id = :store_id" if store_id else ""
        params: dict = {}
        if store_id:
            params["store_id"] = store_id

        # 每个 agent 近 7 天决策统计
        decision_result = await db.execute(
            text(f"""
                SELECT
                    agent_id,
                    COUNT(*)              AS decision_count,
                    AVG(confidence)       AS avg_confidence,
                    AVG(execution_ms)     AS avg_execution_ms,
                    MAX(decided_at)       AS last_decision_at
                FROM agent_decision_logs
                WHERE decided_at >= NOW() - INTERVAL '7 days'
                {store_filter}
                GROUP BY agent_id
            """),
            params,
        )
        decision_map: dict[str, dict] = {}
        for r in decision_result.mappings().all():
            decision_map[r["agent_id"]] = {
                "decision_count": r["decision_count"],
                "avg_confidence": round(float(r["avg_confidence"] or 0), 4),
                "avg_execution_ms": round(float(r["avg_execution_ms"] or 0), 1),
                "last_decision_at": r["last_decision_at"],
            }

        # 约束违规：constraints_check 中包含 false 值的记录
        violation_result = await db.execute(
            text(f"""
                SELECT
                    agent_id,
                    COUNT(*) AS violation_count
                FROM agent_decision_logs
                WHERE decided_at >= NOW() - INTERVAL '7 days'
                  AND constraints_check::text LIKE '%false%'
                {store_filter}
                GROUP BY agent_id
            """),
            params,
        )
        violation_map: dict[str, int] = {
            r["agent_id"]: r["violation_count"]
            for r in violation_result.mappings().all()
        }

        # 活跃会话
        active_result = await db.execute(
            text(f"""
                SELECT
                    agent_template_name AS agent_id,
                    COUNT(*)            AS active_sessions
                FROM session_runs
                WHERE status = 'running'
                {store_filter}
                GROUP BY agent_template_name
            """),
            params,
        )
        active_map: dict[str, int] = {
            r["agent_id"]: r["active_sessions"]
            for r in active_result.mappings().all()
        }

        # 组装 9 个 agent
        agents = []
        total_decisions = 0
        total_violations = 0
        for reg in AGENT_REGISTRY:
            aid = reg["agent_id"]
            stats = decision_map.get(aid, {})
            dc = stats.get("decision_count", 0)
            vc = violation_map.get(aid, 0)
            total_decisions += dc
            total_violations += vc
            agents.append({
                "agent_id": aid,
                "name": reg["name"],
                "priority": reg["priority"],
                "inference_layer": reg["inference_layer"],
                "decision_count_7d": dc,
                "avg_confidence": stats.get("avg_confidence", 0),
                "avg_execution_ms": stats.get("avg_execution_ms", 0),
                "last_decision_at": stats.get("last_decision_at"),
                "constraint_violations_7d": vc,
                "active_sessions": active_map.get(aid, 0),
            })

        summary = {
            "total_agents": len(AGENT_REGISTRY),
            "total_decisions_7d": total_decisions,
            "total_violations_7d": total_violations,
            "agents_with_activity": len(decision_map),
        }

        logger.info("agent_observatory_queried", **summary)
        return {"agents": agents, "summary": summary}

    # ──────────────────────────────────────────────────────────
    #  单 Agent 详情
    # ──────────────────────────────────────────────────────────

    async def get_agent_detail(
        self, db: AsyncSession, agent_id: str, *, days: int = 7
    ) -> dict:
        """单 Agent 决策分布、置信度直方图、约束明细、日趋势。"""
        params = {"agent_id": agent_id, "days": days}

        # 决策类型分布
        type_result = await db.execute(
            text("""
                SELECT decision_type, COUNT(*) AS cnt
                FROM agent_decision_logs
                WHERE agent_id = :agent_id
                  AND decided_at >= NOW() - MAKE_INTERVAL(days => :days)
                GROUP BY decision_type
                ORDER BY cnt DESC
            """),
            params,
        )
        decision_type_distribution = [dict(r) for r in type_result.mappings().all()]

        # 置信度直方图 (10 个桶: 0-0.1, 0.1-0.2, ..., 0.9-1.0)
        histogram_result = await db.execute(
            text("""
                SELECT
                    WIDTH_BUCKET(confidence, 0, 1, 10) AS bucket,
                    COUNT(*) AS cnt
                FROM agent_decision_logs
                WHERE agent_id = :agent_id
                  AND decided_at >= NOW() - MAKE_INTERVAL(days => :days)
                  AND confidence IS NOT NULL
                GROUP BY bucket
                ORDER BY bucket
            """),
            params,
        )
        confidence_histogram = [
            {
                "bucket": r["bucket"],
                "range": f"{max((r['bucket'] - 1) * 0.1, 0):.1f}-{min(r['bucket'] * 0.1, 1.0):.1f}",
                "count": r["cnt"],
            }
            for r in histogram_result.mappings().all()
        ]

        # 约束维度分解（哪些约束项 false 最多）
        constraint_result = await db.execute(
            text("""
                SELECT
                    key AS constraint_name,
                    COUNT(*) AS violation_count
                FROM agent_decision_logs,
                     LATERAL jsonb_each_text(constraints_check) AS kv(key, value)
                WHERE agent_id = :agent_id
                  AND decided_at >= NOW() - MAKE_INTERVAL(days => :days)
                  AND kv.value = 'false'
                GROUP BY key
                ORDER BY violation_count DESC
            """),
            params,
        )
        constraint_breakdown = [dict(r) for r in constraint_result.mappings().all()]

        # 最近 20 条决策
        recent_result = await db.execute(
            text("""
                SELECT
                    id, decision_type, input_context, reasoning,
                    output_action, constraints_check, confidence,
                    execution_ms, model_id, status, decided_at
                FROM agent_decision_logs
                WHERE agent_id = :agent_id
                ORDER BY decided_at DESC
                LIMIT 20
            """),
            {"agent_id": agent_id},
        )
        recent_decisions = [dict(r) for r in recent_result.mappings().all()]

        # 日趋势
        trend_result = await db.execute(
            text("""
                SELECT
                    DATE(decided_at) AS day,
                    COUNT(*)         AS decision_count,
                    AVG(confidence)  AS avg_confidence,
                    AVG(execution_ms) AS avg_execution_ms
                FROM agent_decision_logs
                WHERE agent_id = :agent_id
                  AND decided_at >= NOW() - MAKE_INTERVAL(days => :days)
                GROUP BY DATE(decided_at)
                ORDER BY day
            """),
            params,
        )
        daily_trend = [
            {
                **dict(r),
                "avg_confidence": round(float(r["avg_confidence"] or 0), 4),
                "avg_execution_ms": round(float(r["avg_execution_ms"] or 0), 1),
            }
            for r in trend_result.mappings().all()
        ]

        reg = _AGENT_MAP.get(agent_id, {})
        return {
            "agent_id": agent_id,
            "name": reg.get("name", agent_id),
            "priority": reg.get("priority", ""),
            "inference_layer": reg.get("inference_layer", ""),
            "days": days,
            "decision_type_distribution": decision_type_distribution,
            "confidence_histogram": confidence_histogram,
            "constraint_breakdown": constraint_breakdown,
            "recent_decisions": recent_decisions,
            "daily_trend": daily_trend,
        }

    # ──────────────────────────────────────────────────────────
    #  会话追踪
    # ──────────────────────────────────────────────────────────

    async def get_agent_traces(
        self,
        db: AsyncSession,
        *,
        agent_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询 session_runs。"""
        conditions = []
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if agent_id:
            conditions.append("agent_template_name = :agent_id")
            params["agent_id"] = agent_id
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM session_runs {where}"),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text(f"""
                SELECT
                    session_id, agent_template_name, store_id,
                    trigger_type, status, total_tokens, total_cost_fen,
                    started_at, finished_at
                FROM session_runs
                {where}
                ORDER BY started_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]

        return {"items": items, "total": total, "page": page, "size": size}

    async def get_trace_detail(
        self, db: AsyncSession, session_id: str
    ) -> dict:
        """单次会话：运行信息 + 事件时间线。"""
        # 会话主记录
        run_result = await db.execute(
            text("""
                SELECT
                    session_id, agent_template_name, store_id,
                    trigger_type, status, total_tokens, total_cost_fen,
                    started_at, finished_at
                FROM session_runs
                WHERE session_id = :session_id
            """),
            {"session_id": session_id},
        )
        run = run_result.mappings().first()
        if not run:
            return {"run": None, "events": []}

        # 事件时间线（用 session_runs 的 PK 关联 session_events）
        events_result = await db.execute(
            text("""
                SELECT
                    e.sequence_no, e.event_type, e.step_id, e.agent_id,
                    e.action, e.input_json, e.output_json, e.reasoning,
                    e.tokens_used, e.duration_ms, e.inference_layer
                FROM session_events e
                JOIN session_runs r ON r.id = e.session_id
                WHERE r.session_id = :session_id
                ORDER BY e.sequence_no
            """),
            {"session_id": session_id},
        )
        events = [dict(r) for r in events_result.mappings().all()]

        return {"run": dict(run), "events": events}

    # ──────────────────────────────────────────────────────────
    #  决策 Feed
    # ──────────────────────────────────────────────────────────

    async def get_decision_feed(
        self,
        db: AsyncSession,
        *,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """最新决策流，可按 agent 过滤。"""
        conditions = []
        params: dict = {"limit": limit}

        if agent_id:
            conditions.append("agent_id = :agent_id")
            params["agent_id"] = agent_id

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        result = await db.execute(
            text(f"""
                SELECT
                    id, agent_id, decision_type, input_context,
                    reasoning, output_action, constraints_check,
                    confidence, execution_ms, model_id, plan_id,
                    status, decided_at
                FROM agent_decision_logs
                {where}
                ORDER BY decided_at DESC
                LIMIT :limit
            """),
            params,
        )
        return [dict(r) for r in result.mappings().all()]

    # ──────────────────────────────────────────────────────────
    #  模型注册表 & LLM 成本
    # ──────────────────────────────────────────────────────────

    async def get_model_registry(
        self, db: AsyncSession, *, days: int = 30
    ) -> list[dict]:
        """模型调用汇总：调用量 / 延迟 / Token / 成本 / 成功率。"""
        result = await db.execute(
            text("""
                SELECT
                    model,
                    COUNT(*)                                    AS call_count,
                    ROUND(AVG(duration_ms)::numeric, 1)         AS avg_duration_ms,
                    SUM(input_tokens + output_tokens)            AS total_tokens,
                    SUM(cost_usd)                                AS total_cost_usd,
                    ROUND(
                        AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END)::numeric,
                        4
                    )                                           AS success_rate
                FROM model_call_logs
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
                GROUP BY model
                ORDER BY call_count DESC
            """),
            {"days": days},
        )
        return [
            {
                **dict(r),
                "total_cost_usd": float(r["total_cost_usd"] or 0),
                "success_rate": float(r["success_rate"] or 0),
            }
            for r in result.mappings().all()
        ]

    async def get_llm_cost_dashboard(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        group_by: str = "day",
    ) -> dict:
        """LLM 成本仪表盘：按天 / 按模型 / 按任务类型分组。"""
        group_col_map = {
            "day": "date_trunc('day', created_at)",
            "model": "model",
            "task_type": "task_type",
        }
        group_expr = group_col_map.get(group_by, group_col_map["day"])
        group_alias = "period" if group_by == "day" else group_by

        result = await db.execute(
            text(f"""
                SELECT
                    {group_expr}                            AS {group_alias},
                    COUNT(*)                                AS call_count,
                    SUM(input_tokens)                       AS input_tokens,
                    SUM(output_tokens)                      AS output_tokens,
                    SUM(cost_usd)                           AS cost_usd,
                    ROUND(AVG(duration_ms)::numeric, 1)     AS avg_duration_ms
                FROM model_call_logs
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
                GROUP BY {group_expr}
                ORDER BY {group_expr}
            """),
            {"days": days},
        )
        entries = [
            {
                **dict(r),
                "cost_usd": float(r["cost_usd"] or 0),
            }
            for r in result.mappings().all()
        ]

        # 合计
        totals_result = await db.execute(
            text("""
                SELECT
                    COUNT(*)               AS total_calls,
                    SUM(input_tokens)      AS total_input_tokens,
                    SUM(output_tokens)     AS total_output_tokens,
                    SUM(cost_usd)          AS total_cost_usd,
                    ROUND(AVG(duration_ms)::numeric, 1) AS avg_duration_ms
                FROM model_call_logs
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
            """),
            {"days": days},
        )
        totals = dict(totals_result.mappings().one())
        totals["total_cost_usd"] = float(totals["total_cost_usd"] or 0)

        return {
            "group_by": group_by,
            "days": days,
            "entries": entries,
            "totals": totals,
        }

    async def get_llm_latency_stats(
        self, db: AsyncSession, *, days: int = 7
    ) -> dict:
        """延迟百分位统计：全局 P50/P95/P99 + 按模型分解。"""
        # 全局百分位
        global_result = await db.execute(
            text("""
                SELECT
                    percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
                    percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99,
                    COUNT(*)  AS total_calls,
                    AVG(duration_ms) AS avg_ms
                FROM model_call_logs
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
            """),
            {"days": days},
        )
        global_stats = dict(global_result.mappings().one())
        for k in ("p50", "p95", "p99", "avg_ms"):
            global_stats[k] = round(float(global_stats[k] or 0), 1)

        # 按模型分解
        model_result = await db.execute(
            text("""
                SELECT
                    model,
                    COUNT(*)  AS call_count,
                    percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
                    percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99,
                    AVG(duration_ms) AS avg_ms
                FROM model_call_logs
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
                GROUP BY model
                ORDER BY call_count DESC
            """),
            {"days": days},
        )
        per_model = [
            {
                **dict(r),
                "p50": round(float(r["p50"] or 0), 1),
                "p95": round(float(r["p95"] or 0), 1),
                "p99": round(float(r["p99"] or 0), 1),
                "avg_ms": round(float(r["avg_ms"] or 0), 1),
            }
            for r in model_result.mappings().all()
        ]

        return {
            "days": days,
            "global": global_stats,
            "per_model": per_model,
        }

    # ──────────────────────────────────────────────────────────
    #  Agent 记忆浏览
    # ──────────────────────────────────────────────────────────

    async def get_agent_memory_browse(
        self,
        db: AsyncSession,
        *,
        agent_id: str | None = None,
        memory_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """浏览 Agent 记忆条目，支持按 agent / 类型过滤。"""
        conditions = []
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if agent_id:
            conditions.append("agent_id = :agent_id")
            params["agent_id"] = agent_id
        if memory_type:
            conditions.append("memory_type = :memory_type")
            params["memory_type"] = memory_type

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM agent_memories {where}"),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text(f"""
                SELECT
                    id, agent_id, memory_type, memory_key,
                    content, confidence, access_count,
                    last_accessed_at, created_at
                FROM agent_memories
                {where}
                ORDER BY last_accessed_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]

        return {"items": items, "total": total, "page": page, "size": size}
