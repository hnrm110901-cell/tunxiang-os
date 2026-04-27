"""试点验证闭环服务 — PilotService

负责：
  - 创建/激活/暂停/完成试点计划
  - 生成 AI 复盘报告（Claude API）
  - 执行复盘建议（rollout / abort / extend）
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

import anthropic
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Pydantic 数据模型
# ---------------------------------------------------------------------------
from pydantic import BaseModel, ConfigDict, Field


class SuccessCriterion(BaseModel):
    metric: str
    operator: Literal["gt", "gte", "lt", "lte", "eq"]
    threshold: float
    description: str = ""


class StoreRef(BaseModel):
    store_id: str
    store_name: str


class PilotProgramCreate(BaseModel):
    name: str
    description: str | None = None
    pilot_type: Literal["new_dish", "new_ingredient", "new_combo", "price_change", "menu_restructure"]
    recommendation_source: Literal["intel_report", "competitor_watch", "trend_signal", "manual"] = "manual"
    source_ref_id: uuid.UUID | None = None
    hypothesis: str | None = None
    target_stores: list[StoreRef]
    control_stores: list[StoreRef] | None = None
    start_date: date
    end_date: date
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    items: list["PilotItemCreate"] = Field(default_factory=list)


class PilotItemCreate(BaseModel):
    item_type: Literal["dish", "ingredient", "price"]
    item_ref_id: uuid.UUID | None = None
    item_name: str
    action: Literal["add", "remove", "modify", "price_change"]
    action_config: dict[str, Any] = Field(default_factory=dict)


class PilotProgram(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    pilot_type: str
    recommendation_source: str
    source_ref_id: uuid.UUID | None
    hypothesis: str | None
    target_stores: list[dict]
    control_stores: list[dict] | None
    start_date: date
    end_date: date
    status: str
    success_criteria: list[dict]
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PilotReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    pilot_program_id: uuid.UUID
    review_type: str
    overall_verdict: str
    key_findings: list[dict]
    recommendations: list[dict]
    metrics_summary: dict
    ai_analysis: str | None
    reviewed_at: datetime
    created_at: datetime


# ---------------------------------------------------------------------------
# PilotService
# ---------------------------------------------------------------------------


class PilotService:
    """试点验证闭环核心服务"""

    def __init__(self, db_session: Any, anthropic_client: anthropic.AsyncAnthropic | None = None):
        self._db = db_session
        self._ai = anthropic_client or anthropic.AsyncAnthropic()

    # ------------------------------------------------------------------
    # 创建试点
    # ------------------------------------------------------------------
    async def create_pilot(
        self,
        tenant_id: uuid.UUID,
        pilot_data: PilotProgramCreate,
        created_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """创建试点计划，包含成功标准定义"""
        now = datetime.now(timezone.utc)
        pilot_id = uuid.uuid4()

        program_row = {
            "id": str(pilot_id),
            "tenant_id": str(tenant_id),
            "name": pilot_data.name,
            "description": pilot_data.description,
            "pilot_type": pilot_data.pilot_type,
            "recommendation_source": pilot_data.recommendation_source,
            "source_ref_id": str(pilot_data.source_ref_id) if pilot_data.source_ref_id else None,
            "hypothesis": pilot_data.hypothesis,
            "target_stores": [s.model_dump() for s in pilot_data.target_stores],
            "control_stores": [s.model_dump() for s in pilot_data.control_stores]
            if pilot_data.control_stores
            else None,
            "start_date": pilot_data.start_date.isoformat(),
            "end_date": pilot_data.end_date.isoformat(),
            "status": "draft",
            "success_criteria": [c.model_dump() for c in pilot_data.success_criteria],
            "created_by": str(created_by) if created_by else None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        await self._db.execute(
            """
            INSERT INTO pilot_programs
              (id, tenant_id, name, description, pilot_type, recommendation_source,
               source_ref_id, hypothesis, target_stores, control_stores,
               start_date, end_date, status, success_criteria, created_by,
               created_at, updated_at)
            VALUES
              (:id, :tenant_id, :name, :description, :pilot_type, :recommendation_source,
               :source_ref_id, :hypothesis, :target_stores::jsonb, :control_stores::jsonb,
               :start_date, :end_date, :status, :success_criteria::jsonb, :created_by,
               :created_at, :updated_at)
            """,
            {
                **program_row,
                "target_stores": json.dumps(program_row["target_stores"]),
                "control_stores": json.dumps(program_row["control_stores"]) if program_row["control_stores"] else None,
                "success_criteria": json.dumps(program_row["success_criteria"]),
            },
        )

        # 写入 pilot_items
        for item in pilot_data.items:
            await self._db.execute(
                """
                INSERT INTO pilot_items
                  (id, tenant_id, pilot_program_id, item_type, item_ref_id,
                   item_name, action, action_config, is_active, created_at)
                VALUES
                  (:id, :tenant_id, :pilot_program_id, :item_type, :item_ref_id,
                   :item_name, :action, :action_config::jsonb, TRUE, NOW())
                """,
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_id),
                    "pilot_program_id": str(pilot_id),
                    "item_type": item.item_type,
                    "item_ref_id": str(item.item_ref_id) if item.item_ref_id else None,
                    "item_name": item.item_name,
                    "action": item.action,
                    "action_config": json.dumps(item.action_config),
                },
            )

        logger.info("pilot_created", tenant_id=str(tenant_id), pilot_id=str(pilot_id), name=pilot_data.name)
        return {**program_row, "items_count": len(pilot_data.items)}

    # ------------------------------------------------------------------
    # 激活试点
    # ------------------------------------------------------------------
    async def activate_pilot(self, tenant_id: uuid.UUID, pilot_id: uuid.UUID) -> dict[str, Any]:
        """激活试点：状态变更为 active，记录激活时间"""
        row = await self._get_program(tenant_id, pilot_id)
        if row is None:
            raise ValueError(f"试点 {pilot_id} 不存在")
        if row["status"] not in ("draft", "paused"):
            raise ValueError(f"试点当前状态 '{row['status']}' 不可激活")

        await self._db.execute(
            """
            UPDATE pilot_programs
            SET status = 'active', updated_at = NOW()
            WHERE id = :id AND tenant_id = :tenant_id
            """,
            {"id": str(pilot_id), "tenant_id": str(tenant_id)},
        )

        logger.info("pilot_activated", tenant_id=str(tenant_id), pilot_id=str(pilot_id))
        return {**row, "status": "active"}

    # ------------------------------------------------------------------
    # 暂停试点
    # ------------------------------------------------------------------
    async def pause_pilot(self, tenant_id: uuid.UUID, pilot_id: uuid.UUID) -> dict[str, Any]:
        """暂停试点"""
        row = await self._get_program(tenant_id, pilot_id)
        if row is None:
            raise ValueError(f"试点 {pilot_id} 不存在")
        if row["status"] != "active":
            raise ValueError(f"只有 active 状态的试点可暂停，当前: {row['status']}")

        await self._db.execute(
            "UPDATE pilot_programs SET status = 'paused', updated_at = NOW() WHERE id = :id AND tenant_id = :tenant_id",
            {"id": str(pilot_id), "tenant_id": str(tenant_id)},
        )
        logger.info("pilot_paused", pilot_id=str(pilot_id))
        return {**row, "status": "paused"}

    # ------------------------------------------------------------------
    # 获取指标时序数据
    # ------------------------------------------------------------------
    async def get_metrics_timeseries(
        self,
        tenant_id: uuid.UUID,
        pilot_id: uuid.UUID,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        """返回每日指标时序数据，拆分试验组 / 对照组"""
        rows = await self._db.fetch_all(
            """
            SELECT store_id, is_control_store, metric_date,
                   dish_sales_count, dish_revenue, avg_order_value,
                   customer_satisfaction_score, repeat_purchase_rate, raw_metrics
            FROM pilot_metrics
            WHERE tenant_id = :tenant_id
              AND pilot_program_id = :pilot_id
              {date_filter}
            ORDER BY metric_date ASC, is_control_store ASC
            """.format(
                date_filter=("AND metric_date BETWEEN :start_date AND :end_date" if start_date and end_date else "")
            ),
            {
                "tenant_id": str(tenant_id),
                "pilot_id": str(pilot_id),
                **(
                    {}
                    if not (start_date and end_date)
                    else {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    }
                ),
            },
        )

        pilot_data: list[dict] = []
        control_data: list[dict] = []
        for r in rows:
            item = dict(r)
            if item.get("is_control_store"):
                control_data.append(item)
            else:
                pilot_data.append(item)

        return {"pilot_stores": pilot_data, "control_stores": control_data}

    # ------------------------------------------------------------------
    # AI 生成复盘报告
    # ------------------------------------------------------------------
    async def generate_pilot_review(
        self,
        tenant_id: uuid.UUID,
        pilot_id: uuid.UUID,
        review_type: Literal["interim", "final"] = "interim",
    ) -> dict[str, Any]:
        """AI 生成复盘报告：汇总指标 → 调用 Claude API → 写入 pilot_reviews"""
        program = await self._get_program(tenant_id, pilot_id)
        if program is None:
            raise ValueError(f"试点 {pilot_id} 不存在")

        # 1. 汇总 pilot_metrics 数据
        metrics_summary = await self._compute_metrics_summary(tenant_id, pilot_id)

        # 2. 计算基线对比
        baseline = await self._compute_baseline_summary(tenant_id, pilot_id)

        # 3. 调用 Claude API 生成分析文字
        ai_analysis = await self._generate_ai_analysis(program, metrics_summary, baseline, review_type)

        # 4. 推断 verdict 和 recommendations
        verdict, key_findings, recommendations = self._derive_verdict(program, metrics_summary, baseline)

        review_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await self._db.execute(
            """
            INSERT INTO pilot_reviews
              (id, tenant_id, pilot_program_id, review_type, overall_verdict,
               key_findings, recommendations, metrics_summary, ai_analysis,
               reviewed_at, created_at)
            VALUES
              (:id, :tenant_id, :pilot_program_id, :review_type, :overall_verdict,
               :key_findings::jsonb, :recommendations::jsonb, :metrics_summary::jsonb,
               :ai_analysis, :reviewed_at, :created_at)
            """,
            {
                "id": str(review_id),
                "tenant_id": str(tenant_id),
                "pilot_program_id": str(pilot_id),
                "review_type": review_type,
                "overall_verdict": verdict,
                "key_findings": json.dumps(key_findings),
                "recommendations": json.dumps(recommendations),
                "metrics_summary": json.dumps(metrics_summary),
                "ai_analysis": ai_analysis,
                "reviewed_at": now.isoformat(),
                "created_at": now.isoformat(),
            },
        )

        logger.info("pilot_review_generated", pilot_id=str(pilot_id), verdict=verdict, review_type=review_type)
        return {
            "id": str(review_id),
            "pilot_program_id": str(pilot_id),
            "review_type": review_type,
            "overall_verdict": verdict,
            "key_findings": key_findings,
            "recommendations": recommendations,
            "metrics_summary": metrics_summary,
            "ai_analysis": ai_analysis,
            "reviewed_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # 执行复盘建议
    # ------------------------------------------------------------------
    async def execute_recommendation(
        self,
        tenant_id: uuid.UUID,
        pilot_id: uuid.UUID,
        recommendation: Literal["rollout", "abort", "extend"],
        extend_days: int = 14,
    ) -> dict[str, Any]:
        """
        执行复盘建议：
          rollout — 标记完成，记录推广意向
          abort   — 标记取消，写入失败教训
          extend  — 延长试点时间，状态保持 active
        """
        program = await self._get_program(tenant_id, pilot_id)
        if program is None:
            raise ValueError(f"试点 {pilot_id} 不存在")

        result: dict[str, Any]

        if recommendation == "rollout":
            await self._db.execute(
                "UPDATE pilot_programs SET status = 'completed', updated_at = NOW() WHERE id = :id AND tenant_id = :tenant_id",
                {"id": str(pilot_id), "tenant_id": str(tenant_id)},
            )
            result = {
                "action": "rollout",
                "status": "completed",
                "message": f"试点「{program['name']}」已标记完成，请在 tx-menu 中将试点菜品推广至全部门店",
                "next_step": "在 tx-menu 创建菜品推广任务，选择目标门店",
            }
            logger.info("pilot_rollout_decided", pilot_id=str(pilot_id))

        elif recommendation == "abort":
            await self._db.execute(
                "UPDATE pilot_programs SET status = 'cancelled', updated_at = NOW() WHERE id = :id AND tenant_id = :tenant_id",
                {"id": str(pilot_id), "tenant_id": str(tenant_id)},
            )
            result = {
                "action": "abort",
                "status": "cancelled",
                "message": f"试点「{program['name']}」已取消，失败原因已记录在复盘报告中",
                "lesson": "本次试点数据已保留，可供后续类似决策参考",
            }
            logger.info("pilot_aborted", pilot_id=str(pilot_id))

        elif recommendation == "extend":
            from datetime import timedelta

            current_end = date.fromisoformat(str(program["end_date"]))
            new_end = current_end + timedelta(days=extend_days)
            await self._db.execute(
                "UPDATE pilot_programs SET end_date = :new_end, updated_at = NOW() WHERE id = :id AND tenant_id = :tenant_id",
                {"id": str(pilot_id), "tenant_id": str(tenant_id), "new_end": new_end.isoformat()},
            )
            result = {
                "action": "extend",
                "status": "active",
                "original_end_date": current_end.isoformat(),
                "new_end_date": new_end.isoformat(),
                "extended_days": extend_days,
                "message": f"试点「{program['name']}」已延长 {extend_days} 天，新截止日期：{new_end}",
            }
            logger.info("pilot_extended", pilot_id=str(pilot_id), new_end=str(new_end))

        else:
            raise ValueError(f"不支持的建议类型: {recommendation}")

        return result

    # ------------------------------------------------------------------
    # 获取最新复盘报告
    # ------------------------------------------------------------------
    async def get_latest_review(self, tenant_id: uuid.UUID, pilot_id: uuid.UUID) -> dict[str, Any] | None:
        """获取最新的复盘报告"""
        row = await self._db.fetch_one(
            """
            SELECT * FROM pilot_reviews
            WHERE tenant_id = :tenant_id AND pilot_program_id = :pilot_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"tenant_id": str(tenant_id), "pilot_id": str(pilot_id)},
        )
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # 列出试点
    # ------------------------------------------------------------------
    async def list_pilots(
        self,
        tenant_id: uuid.UUID,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        where = "WHERE tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if status:
            where += " AND status = :status"
            params["status"] = status

        total = await self._db.fetch_val(f"SELECT COUNT(*) FROM pilot_programs {where}", params)
        rows = await self._db.fetch_all(
            f"""
            SELECT * FROM pilot_programs {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": size, "offset": (page - 1) * size},
        )
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "size": size}

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _get_program(self, tenant_id: uuid.UUID, pilot_id: uuid.UUID) -> dict | None:
        row = await self._db.fetch_one(
            "SELECT * FROM pilot_programs WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE",
            {"id": str(pilot_id), "tenant_id": str(tenant_id)},
        )
        return dict(row) if row else None

    async def _compute_metrics_summary(self, tenant_id: uuid.UUID, pilot_id: uuid.UUID) -> dict:
        """汇总试点期间各门店的指标均值"""
        rows = await self._db.fetch_all(
            """
            SELECT
                is_control_store,
                COUNT(DISTINCT store_id)            AS store_count,
                SUM(dish_sales_count)               AS total_sales,
                SUM(dish_revenue)                   AS total_revenue,
                AVG(avg_order_value)                AS avg_order_value,
                AVG(customer_satisfaction_score)    AS avg_satisfaction,
                AVG(repeat_purchase_rate)           AS avg_repeat_rate,
                COUNT(metric_date)                  AS data_days
            FROM pilot_metrics
            WHERE tenant_id = :tenant_id AND pilot_program_id = :pilot_id
            GROUP BY is_control_store
            """,
            {"tenant_id": str(tenant_id), "pilot_id": str(pilot_id)},
        )

        summary: dict = {"pilot": {}, "control": {}}
        for r in rows:
            d = dict(r)
            key = "control" if d.get("is_control_store") else "pilot"
            summary[key] = {
                "store_count": d.get("store_count", 0),
                "total_sales": d.get("total_sales", 0),
                "total_revenue": float(d.get("total_revenue") or 0),
                "avg_order_value": float(d.get("avg_order_value") or 0),
                "avg_satisfaction": float(d.get("avg_satisfaction") or 0),
                "avg_repeat_rate": float(d.get("avg_repeat_rate") or 0),
                "data_days": d.get("data_days", 0),
            }

        # 计算提升率（试验组 vs 对照组）
        if summary["pilot"] and summary["control"]:
            pilot = summary["pilot"]
            control = summary["control"]
            for metric in ("total_sales", "total_revenue", "avg_order_value", "avg_satisfaction", "avg_repeat_rate"):
                p_val = pilot.get(metric, 0)
                c_val = control.get(metric, 0)
                if c_val and c_val != 0:
                    lift = round((p_val - c_val) / abs(c_val) * 100, 2)
                else:
                    lift = None
                summary.setdefault("lift", {})[metric] = lift

        return summary

    async def _compute_baseline_summary(self, tenant_id: uuid.UUID, pilot_id: uuid.UUID) -> dict:
        """基线：试点前14天均值（仅试验组门店）"""
        program = await self._get_program(tenant_id, pilot_id)
        if not program:
            return {}

        try:
            start = date.fromisoformat(str(program["start_date"]))
        except (ValueError, TypeError):
            return {}

        from datetime import timedelta

        baseline_end = (start - timedelta(days=1)).isoformat()
        baseline_start = (start - timedelta(days=15)).isoformat()

        # 注意：baseline 数据依赖 orders 表，此处返回占位结构
        # 实际生产中应从 tx-analytics 的 dish_sales 视图查询
        return {
            "baseline_period": {"start": baseline_start, "end": baseline_end},
            "note": "基线数据需从 tx-analytics orders 视图聚合",
        }

    def _derive_verdict(
        self,
        program: dict,
        metrics_summary: dict,
        baseline: dict,
    ) -> tuple[str, list[dict], list[dict]]:
        """根据成功标准 + 指标结果推断 verdict"""
        success_criteria = program.get("success_criteria") or []
        lift_data = metrics_summary.get("lift", {})
        pilot_data = metrics_summary.get("pilot", {})

        passed = 0
        total_criteria = len(success_criteria)
        key_findings: list[dict] = []
        recommendations: list[dict] = []

        for criterion in success_criteria:
            metric = criterion.get("metric", "")
            operator = criterion.get("operator", "gt")
            threshold = float(criterion.get("threshold", 0))

            # 从 lift 或 pilot 数据中取指标值
            actual_value = lift_data.get(metric) if metric in lift_data else pilot_data.get(metric)
            if actual_value is None:
                key_findings.append({"metric": metric, "status": "no_data", "message": f"{metric} 暂无数据"})
                continue

            ops = {
                "gt": actual_value > threshold,
                "gte": actual_value >= threshold,
                "lt": actual_value < threshold,
                "lte": actual_value <= threshold,
                "eq": actual_value == threshold,
            }
            met = ops.get(operator, False)
            passed += 1 if met else 0
            key_findings.append(
                {
                    "metric": metric,
                    "actual": actual_value,
                    "threshold": threshold,
                    "operator": operator,
                    "met": met,
                    "status": "pass" if met else "fail",
                }
            )

        # 总体 verdict
        if total_criteria == 0:
            verdict = "inconclusive"
        elif passed == total_criteria:
            verdict = "success"
        elif passed >= total_criteria * 0.6:
            verdict = "partial_success"
        elif passed >= total_criteria * 0.3:
            verdict = "failed"
        else:
            verdict = "failed"

        # 默认 recommendations
        rec_map = {
            "success": [{"action": "rollout", "priority": "high", "reason": "全部成功标准达成，建议推广至全门店"}],
            "partial_success": [
                {"action": "modify", "priority": "medium", "reason": "部分指标未达标，建议优化后扩大试点"},
                {"action": "extend", "priority": "low", "reason": "也可延长观察期"},
            ],
            "failed": [{"action": "abort", "priority": "high", "reason": "指标未达预期，建议取消并总结教训"}],
            "inconclusive": [{"action": "extend", "priority": "medium", "reason": "数据不足，建议延长观察期"}],
        }
        recommendations = rec_map.get(verdict, [])

        return verdict, key_findings, recommendations

    async def _generate_ai_analysis(
        self,
        program: dict,
        metrics_summary: dict,
        baseline: dict,
        review_type: str,
    ) -> str:
        """调用 Claude API 生成结构化复盘分析文字"""
        system_prompt = """你是屯象OS的资深餐饮经营分析专家，负责对门店试点实验进行复盘分析。

分析框架（必须按此结构输出）：
1. 试点背景摘要（1-2句）
2. 关键指标表现（列表，含实际数据 vs 对照组）
3. 成功或失败的核心原因分析（3-5点）
4. 对品牌/门店经营的潜在影响
5. 具体行动建议（按优先级排序）

要求：
- 语言简洁专业，避免废话
- 数据引用精确到小数点后1位
- 建议具体可执行，避免空泛
- 总字数控制在400字以内"""

        user_content = f"""试点计划复盘请求

试点名称：{program.get("name", "")}
试点类型：{program.get("pilot_type", "")}
试点假设：{program.get("hypothesis", "未设定")}
复盘类型：{"期中" if review_type == "interim" else "最终"}
目标门店数：{len(program.get("target_stores") or [])}
对照门店数：{len(program.get("control_stores") or [])}

指标汇总数据：
{json.dumps(metrics_summary, ensure_ascii=False, indent=2)}

成功标准：
{json.dumps(program.get("success_criteria", []), ensure_ascii=False, indent=2)}

请按分析框架生成复盘报告。"""

        try:
            response = await self._ai.messages.create(
                model="claude-opus-4-5",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            return response.content[0].text
        except anthropic.APIError as e:
            logger.error("ai_analysis_failed", error=str(e), pilot_id=str(program.get("id", "")))
            return f"AI 分析暂时不可用（{type(e).__name__}）。指标汇总：试验组销量 {metrics_summary.get('pilot', {}).get('total_sales', 0)}，对照组销量 {metrics_summary.get('control', {}).get('total_sales', 0)}。"
