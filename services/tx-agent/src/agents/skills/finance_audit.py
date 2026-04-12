"""#6 财务稽核 Agent — P1 | 云端

来源：FctAgent + DecisionAgent + business_intel(5子Agent)
能力：财务报表、营收异常、KPI分析、订单预测、经营洞察

迁移自 tunxiang V2.x decision_agent.py + business_intel/agent.py
"""
import statistics
from typing import Any, Optional

import structlog

from ..base import ActionConfig, AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


# 场景优先级（从 scenario_matcher.py 迁移）
SCENARIO_PRIORITY = [
    "high_cost", "high_waste", "holiday_peak", "revenue_down",
    "weekend", "new_dish", "weekday_normal",
]


class FinanceAuditAgent(SkillAgent):
    agent_id = "finance_audit"
    agent_name = "财务稽核"
    description = "财务报表、营收异常分析、KPI快照、经营洞察、场景识别"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "get_financial_report",
            "detect_revenue_anomaly",
            "snapshot_kpi",
            "forecast_orders",
            "generate_biz_insight",
            "match_scenario",
            "analyze_order_trend",
            "cost_analysis",
            "daily_reconciliation",
            "update_daily_revenue",
            "flag_discount_anomaly",
            "generate_shift_summary",
            "flag_receiving_variance",
            "process_approval_result",
            "root_cause_analysis",
            "check_pl_anomaly",
            "get_settlement_snapshot",  # Phase 3: 读 mv_daily_settlement
            "get_pnl_snapshot",         # Phase 3: 读 mv_store_pnl
        ]

    def get_action_config(self, action: str) -> ActionConfig:
        """财务稽核 Agent 的 action 级会话策略"""
        configs = {
            # 折扣异常标记 — 最高风险，需人工确认
            "flag_discount_anomaly": ActionConfig(
                risk_level="critical",
                requires_human_confirm=True,
                max_retries=0,
            ),
            # 营收异常检测 — 最高风险
            "detect_revenue_anomaly": ActionConfig(
                risk_level="critical",
                requires_human_confirm=True,
                max_retries=0,
            ),
            # P&L 异常检查
            "check_pl_anomaly": ActionConfig(
                risk_level="critical",
                requires_human_confirm=True,
                max_retries=0,
            ),
            # 根因分析
            "root_cause_analysis": ActionConfig(
                risk_level="high",
                requires_human_confirm=True,
                max_retries=1,
            ),
            # 日结对账需人工确认
            "daily_reconciliation": ActionConfig(
                risk_level="high",
                requires_human_confirm=True,
                max_retries=1,
            ),
            # 营收更新
            "update_daily_revenue": ActionConfig(
                risk_level="high",
                requires_human_confirm=True,
                max_retries=1,
            ),
            # 收货差异标记
            "flag_receiving_variance": ActionConfig(
                risk_level="high",
                requires_human_confirm=True,
                max_retries=1,
            ),
            # 审批结果处理
            "process_approval_result": ActionConfig(
                risk_level="high",
                requires_human_confirm=True,
                max_retries=1,
            ),
            # 以下为中等风险操作
            "get_financial_report": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "snapshot_kpi": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "forecast_orders": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "generate_biz_insight": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "match_scenario": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "analyze_order_trend": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "cost_analysis": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "generate_shift_summary": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "get_settlement_snapshot": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            "get_pnl_snapshot": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
        }
        return configs.get(action, ActionConfig())

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "detect_revenue_anomaly": self._detect_revenue_anomaly,
            "snapshot_kpi": self._snapshot_kpi,
            "forecast_orders": self._forecast_orders,
            "match_scenario": self._match_scenario,
            "analyze_order_trend": self._analyze_order_trend,
            "get_financial_report": self._get_report,
            "generate_biz_insight": self._biz_insight,
            "cost_analysis": self._cost_analysis,
            "daily_reconciliation": self._daily_reconciliation,
            "update_daily_revenue": self._update_daily_revenue,
            "flag_discount_anomaly": self._flag_discount_anomaly,
            "generate_shift_summary": self._generate_shift_summary,
            "flag_receiving_variance": self._flag_receiving_variance,
            "process_approval_result": self._process_approval_result,
            "root_cause_analysis": self._root_cause_analysis,
            "check_pl_anomaly": self._check_pl_anomaly,
            "get_settlement_snapshot": self._get_settlement_snapshot,
            "get_pnl_snapshot": self._get_pnl_snapshot,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"Unsupported: {action}")

    # ─── 营收异常检测 ───

    async def _detect_revenue_anomaly(self, params: dict) -> AgentResult:
        """检测营收异常 — 对比历史基线"""
        actual_fen = params.get("actual_revenue_fen", 0)
        history_fen = params.get("history_daily_fen", [])

        if not history_fen:
            return AgentResult(success=False, action="detect_revenue_anomaly", error="无历史数据")

        avg = statistics.mean(history_fen)
        std = statistics.stdev(history_fen) if len(history_fen) >= 2 else avg * 0.1

        # Z-score 异常检测
        z_score = (actual_fen - avg) / std if std > 0 else 0
        is_anomaly = abs(z_score) > 2.0
        severity = "critical" if abs(z_score) > 3 else "warning" if abs(z_score) > 2 else "normal"
        direction = "above" if z_score > 0 else "below"

        deviation_pct = round((actual_fen - avg) / avg * 100, 1) if avg > 0 else 0

        return AgentResult(
            success=True,
            action="detect_revenue_anomaly",
            data={
                "is_anomaly": is_anomaly,
                "severity": severity,
                "direction": direction,
                "actual_yuan": round(actual_fen / 100, 2),
                "expected_yuan": round(avg / 100, 2),
                "deviation_pct": deviation_pct,
                "z_score": round(z_score, 2),
            },
            reasoning=f"今日营收 ¥{actual_fen/100:.0f}，历史均值 ¥{avg/100:.0f}，"
                      f"偏差 {deviation_pct:+.1f}%（{severity}）",
            confidence=0.85 if len(history_fen) >= 14 else 0.65,
        )

    # ─── KPI 快照 ───

    async def _snapshot_kpi(self, params: dict) -> AgentResult:
        """KPI 健康度快照"""
        kpis = params.get("kpis", {})
        targets = params.get("targets", {})

        scores = {}
        for kpi_name, actual in kpis.items():
            target = targets.get(kpi_name)
            if target and target > 0:
                completion = min(100, actual / target * 100)
                scores[kpi_name] = {
                    "actual": actual,
                    "target": target,
                    "completion_pct": round(completion, 1),
                    "status": "good" if completion >= 90 else "warning" if completion >= 70 else "critical",
                }

        overall = statistics.mean([s["completion_pct"] for s in scores.values()]) if scores else 0

        return AgentResult(
            success=True,
            action="snapshot_kpi",
            data={
                "kpi_scores": scores,
                "overall_completion_pct": round(overall, 1),
                "status": "good" if overall >= 90 else "warning" if overall >= 70 else "critical",
            },
            reasoning=f"KPI 综合达成率 {overall:.0f}%",
            confidence=0.9,
        )

    # ─── 订单量预测 ───

    async def _forecast_orders(self, params: dict) -> AgentResult:
        """预测未来 N 天订单量"""
        history = params.get("daily_orders", [])
        days_ahead = params.get("days_ahead", 7)

        if len(history) < 7:
            return AgentResult(success=False, action="forecast_orders", error="至少需要7天历史数据")

        # 基于周期性（7天）+ 趋势
        weekly_pattern = [statistics.mean(history[i::7]) for i in range(7)]
        recent_avg = statistics.mean(history[-7:])
        overall_avg = statistics.mean(history)
        trend = (recent_avg - overall_avg) / overall_avg if overall_avg > 0 else 0

        predictions = []
        for d in range(days_ahead):
            base = weekly_pattern[d % 7]
            adjusted = base * (1 + trend * 0.5)  # 趋势衰减
            predictions.append(round(max(0, adjusted)))

        return AgentResult(
            success=True,
            action="forecast_orders",
            data={
                "daily_forecast": predictions,
                "total_forecast": sum(predictions),
                "trend_pct": round(trend * 100, 1),
                "avg_daily": round(statistics.mean(predictions)),
            },
            reasoning=f"预测 {days_ahead} 天总订单 {sum(predictions)}，"
                      f"趋势 {trend*100:+.1f}%",
            confidence=0.75,
        )

    # ─── 场景识别 ───

    async def _match_scenario(self, params: dict) -> AgentResult:
        """识别当前经营场景"""
        cost_rate = params.get("cost_rate_pct", 30)
        waste_rate = params.get("waste_rate_pct", 2)
        is_holiday = params.get("is_holiday", False)
        is_weekend = params.get("is_weekend", False)
        revenue_change_pct = params.get("revenue_change_pct", 0)
        has_new_dish = params.get("has_new_dish", False)

        # 按优先级匹配场景
        if cost_rate >= 40:
            scenario = "high_cost"
            label = "成本超标"
        elif waste_rate >= 5:
            scenario = "high_waste"
            label = "损耗异常"
        elif is_holiday:
            scenario = "holiday_peak"
            label = "节假日高峰"
        elif revenue_change_pct < -15:
            scenario = "revenue_down"
            label = "营收下滑"
        elif is_weekend:
            scenario = "weekend"
            label = "周末经营"
        elif has_new_dish:
            scenario = "new_dish"
            label = "新菜上市"
        else:
            scenario = "weekday_normal"
            label = "工作日常态"

        return AgentResult(
            success=True,
            action="match_scenario",
            data={
                "scenario": scenario,
                "label": label,
                "priority": SCENARIO_PRIORITY.index(scenario),
                "inputs": {
                    "cost_rate_pct": cost_rate,
                    "waste_rate_pct": waste_rate,
                    "is_holiday": is_holiday,
                    "revenue_change_pct": revenue_change_pct,
                },
            },
            reasoning=f"当前场景：{label}",
            confidence=0.85,
        )

    # ─── 订单趋势分析 ───

    async def _analyze_order_trend(self, params: dict) -> AgentResult:
        """分析订单趋势"""
        daily_orders = params.get("daily_orders", [])
        daily_revenue_fen = params.get("daily_revenue_fen", [])

        if len(daily_orders) < 2:
            return AgentResult(success=False, action="analyze_order_trend", error="至少需要2天数据")

        order_trend = "up" if daily_orders[-1] > daily_orders[0] else "down" if daily_orders[-1] < daily_orders[0] else "flat"
        avg_orders = round(statistics.mean(daily_orders))
        avg_ticket_fen = 0
        if daily_orders and daily_revenue_fen and sum(daily_orders) > 0:
            avg_ticket_fen = round(sum(daily_revenue_fen) / sum(daily_orders))

        return AgentResult(
            success=True,
            action="analyze_order_trend",
            data={
                "order_trend": order_trend,
                "avg_daily_orders": avg_orders,
                "avg_ticket_fen": avg_ticket_fen,
                "avg_ticket_yuan": round(avg_ticket_fen / 100, 2),
                "total_orders": sum(daily_orders),
                "period_days": len(daily_orders),
            },
            reasoning=f"订单趋势 {order_trend}，日均 {avg_orders} 单，客单价 ¥{avg_ticket_fen/100:.0f}",
            confidence=0.8,
        )

    async def _get_report(self, params: dict) -> AgentResult:
        report_type = params.get("report_type", "period_summary")
        return AgentResult(success=True, action="get_financial_report",
                         data={"report_type": report_type, "generated": True},
                         reasoning=f"生成 {report_type} 报表", confidence=0.9)

    async def _biz_insight(self, params: dict) -> AgentResult:
        metrics = params.get("metrics", {})
        insights = []
        if metrics.get("cost_rate_pct", 0) > 35:
            insights.append({"type": "cost_alert", "detail": "成本率偏高，建议核查食材采购", "priority": 1})
        if metrics.get("revenue_change_pct", 0) < -10:
            insights.append({"type": "revenue_drop", "detail": "营收下滑，关注客流变化", "priority": 1})
        if not insights:
            insights.append({"type": "stable", "detail": "经营稳定，维持当前策略", "priority": 3})
        return AgentResult(success=True, action="generate_biz_insight",
                         data={"insights": insights, "total": len(insights)},
                         reasoning=f"生成 {len(insights)} 条经营洞察", confidence=0.8)

    # ─── 成本分析（真实DB） ───

    async def _cost_analysis(self, params: dict) -> AgentResult:
        store_id = params.get("store_id") or self.store_id
        date_from = params.get("date_from")  # YYYY-MM-DD
        date_to = params.get("date_to")

        if self._db:
            from datetime import datetime, timedelta, timezone

            from sqlalchemy import text

            if not date_from:
                date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
            if not date_to:
                date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # 查询实际营收
            rev_row = await self._db.execute(text("""
                SELECT
                    COALESCE(SUM(final_amount_fen), 0) as revenue_fen,
                    COUNT(*) as order_count
                FROM orders
                WHERE tenant_id = :tenant_id
                  AND (:store_id::UUID IS NULL OR store_id = :store_id::UUID)
                  AND status = 'completed'
                  AND created_at >= :date_from::date
                  AND created_at < :date_to::date + INTERVAL '1 day'
            """), {"tenant_id": self.tenant_id, "store_id": store_id,
                   "date_from": date_from, "date_to": date_to})
            rev = dict(rev_row.mappings().first() or {})

            # 查询成本（从BOM计算，如无BOM则用营收*行业均值估算）
            cost_row = await self._db.execute(text("""
                SELECT COALESCE(SUM(oi.quantity * COALESCE(d.cost_price_fen, oi.unit_price_fen * 0.35)), 0) as cost_fen
                FROM order_items oi
                JOIN orders o ON oi.order_id = o.id
                LEFT JOIN dishes d ON oi.dish_id = d.id
                WHERE o.tenant_id = :tenant_id
                  AND (:store_id::UUID IS NULL OR o.store_id = :store_id::UUID)
                  AND o.status = 'completed'
                  AND o.created_at >= :date_from::date
                  AND o.created_at < :date_to::date + INTERVAL '1 day'
            """), {"tenant_id": self.tenant_id, "store_id": store_id,
                   "date_from": date_from, "date_to": date_to})
            cost = dict(cost_row.mappings().first() or {})

            revenue_fen = int(rev.get("revenue_fen") or 0)
            cost_fen = int(cost.get("cost_fen") or 0)
            order_count = int(rev.get("order_count") or 0)
            gross_profit_fen = revenue_fen - cost_fen
            gross_margin = gross_profit_fen / revenue_fen if revenue_fen > 0 else 0

            # Claude深度分析
            analysis = ""
            if self._router and revenue_fen > 0:
                try:
                    analysis = await self._router.complete(
                        tenant_id=self.tenant_id,
                        task_type="cost_analysis",
                        system="你是餐饮财务顾问，根据成本数据给出简洁的经营建议，100字内，中文。",
                        messages=[{"role": "user", "content":
                            f"营收{revenue_fen/100:.0f}元，成本{cost_fen/100:.0f}元，"
                            f"毛利率{gross_margin:.1%}，订单数{order_count}，"
                            f"统计区间{date_from}至{date_to}。请评估并给出改善建议。"}],
                        max_tokens=200,
                        db=self._db,
                    )
                except Exception as exc:  # noqa: BLE001 — Claude不可用时降级为规则分析
                    logger.warning("finance_audit_llm_fallback", error=str(exc))

            return AgentResult(
                success=True, action="cost_analysis",
                data={
                    "revenue_fen": revenue_fen,
                    "cost_fen": cost_fen,
                    "gross_profit_fen": gross_profit_fen,
                    "gross_margin": round(gross_margin, 4),
                    "order_count": order_count,
                    "avg_order_value_fen": revenue_fen // order_count if order_count else 0,
                    "date_from": date_from,
                    "date_to": date_to,
                    "analysis": analysis,
                },
                reasoning=f"营收{revenue_fen/100:.0f}元，毛利率{gross_margin:.1%}，{analysis[:40] if analysis else '规则计算'}",
                confidence=0.95 if analysis else 0.85,
                inference_layer="cloud" if analysis else "edge",
            )

        # 降级：使用params传入的数据
        revenue = params.get("revenue_fen", 0)
        costs = params.get("costs", {})
        total_cost = sum(costs.values()) if isinstance(costs, dict) else params.get("total_cost_fen", 0)
        gross = revenue - total_cost
        margin = gross / revenue if revenue > 0 else 0
        return AgentResult(
            success=True, action="cost_analysis",
            data={"revenue_fen": revenue, "cost_fen": total_cost,
                  "gross_profit_fen": gross, "gross_margin": round(margin, 4)},
            reasoning=f"毛利率{margin:.1%}",
            confidence=0.8,
        )

    # ─── 日结对账（真实DB） ───

    async def _daily_reconciliation(self, params: dict) -> AgentResult:
        store_id = params.get("store_id") or self.store_id
        date = params.get("date")  # YYYY-MM-DD，默认今天

        if self._db:
            from datetime import datetime, timezone

            from sqlalchemy import text

            if not date:
                date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            rows = await self._db.execute(text("""
                SELECT
                    p.method,
                    COUNT(*) as txn_count,
                    COALESCE(SUM(p.amount_fen), 0) as total_fen,
                    COALESCE(SUM(CASE WHEN p.status = 'paid' THEN p.amount_fen ELSE 0 END), 0) as paid_fen,
                    COALESCE(SUM(CASE WHEN p.status = 'refunded' THEN p.amount_fen ELSE 0 END), 0) as refunded_fen
                FROM payments p
                JOIN orders o ON p.order_id = o.id
                WHERE o.tenant_id = :tenant_id
                  AND (:store_id::UUID IS NULL OR o.store_id = :store_id::UUID)
                  AND DATE(p.created_at) = :date::date
                GROUP BY p.method
            """), {"tenant_id": self.tenant_id, "store_id": store_id, "date": date})

            by_method = [dict(r) for r in rows.mappings()]
            total_paid = sum(r["paid_fen"] for r in by_method)
            total_refunded = sum(r["refunded_fen"] for r in by_method)

            return AgentResult(
                success=True, action="daily_reconciliation",
                data={
                    "date": date,
                    "by_method": by_method,
                    "total_paid_fen": total_paid,
                    "total_refunded_fen": total_refunded,
                    "net_fen": total_paid - total_refunded,
                    "discrepancies": [],  # 需接入第三方平台数据才能对比
                },
                reasoning=f"{date}实收{total_paid/100:.0f}元，退款{total_refunded/100:.0f}元，净收{(total_paid-total_refunded)/100:.0f}元",
                confidence=1.0,
                inference_layer="edge",
            )

        # 降级
        return AgentResult(
            success=True, action="daily_reconciliation",
            data={"date": params.get("date", ""), "discrepancies": [], "total_paid_fen": 0},
            reasoning="无DB连接，无法查询真实对账数据",
            confidence=0.3,
        )

    # ─── 事件驱动：累加日营收 ───

    async def _update_daily_revenue(self, params: dict) -> AgentResult:
        """order_completed / trade.order.paid 触发：更新当日营收累计，并检测是否偏离基线

        不直接写 DB；计算偏差供上层决定是否触发异常告警。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        order_amount_fen = params.get("total_fen") or event_data.get("total_fen", 0)
        current_daily_total_fen = params.get("current_daily_total_fen", 0)
        daily_target_fen = params.get("daily_target_fen", 0)

        # 累加本单后的日营收
        new_daily_total_fen = current_daily_total_fen + order_amount_fen

        # 目标达成率
        achievement_pct = (
            round(new_daily_total_fen / daily_target_fen * 100, 1)
            if daily_target_fen > 0 else None
        )

        # 若有 DB，从 orders 表实时聚合今日营收
        actual_daily_fen: Optional[int] = None
        if self._db and store_id:
            from datetime import datetime, timezone

            from sqlalchemy import text
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            row = await self._db.execute(text("""
                SELECT COALESCE(SUM(final_amount_fen), 0) as daily_revenue
                FROM orders
                WHERE tenant_id = :tenant_id
                  AND (:store_id::UUID IS NULL OR store_id = :store_id::UUID)
                  AND status = 'completed'
                  AND DATE(completed_at) = :today::date
            """), {"tenant_id": self.tenant_id, "store_id": store_id, "today": today})
            r = dict(row.mappings().first() or {})
            actual_daily_fen = int(r.get("daily_revenue") or 0)

        report_total = actual_daily_fen if actual_daily_fen is not None else new_daily_total_fen

        logger.info(
            "daily_revenue_updated",
            store_id=store_id,
            order_amount_fen=order_amount_fen,
            daily_total_fen=report_total,
            achievement_pct=achievement_pct,
        )

        return AgentResult(
            success=True,
            action="update_daily_revenue",
            data={
                "store_id": store_id,
                "order_amount_fen": order_amount_fen,
                "daily_total_fen": report_total,
                "daily_total_yuan": round(report_total / 100, 2),
                "daily_target_fen": daily_target_fen,
                "achievement_pct": achievement_pct,
                "data_source": "db_realtime" if actual_daily_fen is not None else "incremental",
            },
            reasoning=(
                f"日营收更新：今日累计¥{report_total/100:.0f}"
                + (f"，目标达成{achievement_pct}%" if achievement_pct is not None else "")
            ),
            confidence=0.95 if actual_daily_fen is not None else 0.8,
        )

    # ─── 事件驱动：标记折扣异常 ───

    async def _flag_discount_anomaly(self, params: dict) -> AgentResult:
        """discount_violation / trade.discount.blocked 触发：财务视角标记折扣异常

        与 discount_guard.log_violation 互补：
        - discount_guard 负责合规视角（是否违规、操作员归因）
        - finance_audit 负责财务视角（对毛利的影响、是否触发财务复核）
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        order_id = params.get("order_id") or event_data.get("order_id")
        discount_amount_fen = params.get("discount_amount_fen") or event_data.get("discount_amount_fen", 0)
        order_total_fen = params.get("total_fen") or event_data.get("total_fen", 0)
        cost_fen = params.get("cost_fen") or event_data.get("cost_fen", 0)

        discount_rate = discount_amount_fen / order_total_fen if order_total_fen > 0 else 0
        # 折后实收
        net_revenue_fen = order_total_fen - discount_amount_fen
        # 折后毛利
        gross_profit_fen = net_revenue_fen - cost_fen
        gross_margin = gross_profit_fen / net_revenue_fen if net_revenue_fen > 0 else 0

        # 毛利是否跌破底线（阈值 15%）
        margin_breached = gross_margin < 0.15

        # 是否需要财务复核
        needs_finance_review = (
            discount_amount_fen > 20000 or   # 单笔折扣超200元
            discount_rate > 0.5 or           # 折扣率超50%
            margin_breached                  # 毛利跌穿底线
        )

        logger.info(
            "discount_anomaly_flagged",
            store_id=store_id,
            order_id=order_id,
            discount_rate=round(discount_rate, 4),
            gross_margin=round(gross_margin, 4),
            needs_finance_review=needs_finance_review,
        )

        return AgentResult(
            success=True,
            action="flag_discount_anomaly",
            data={
                "store_id": store_id,
                "order_id": order_id,
                "discount_amount_fen": discount_amount_fen,
                "discount_rate": round(discount_rate, 4),
                "net_revenue_fen": net_revenue_fen,
                "gross_profit_fen": gross_profit_fen,
                "gross_margin": round(gross_margin, 4),
                "margin_breached": margin_breached,
                "needs_finance_review": needs_finance_review,
                "impact_level": "high" if needs_finance_review else "low",
            },
            reasoning=(
                f"折扣财务影响：折扣率{discount_rate:.1%}，折后毛利率{gross_margin:.1%}"
                + ("，毛利跌穿底线！" if margin_breached else "")
                + ("，需财务复核" if needs_finance_review else "")
            ),
            confidence=0.9,
        )

    # ─── 事件驱动：生成班次财务摘要 ───

    async def _generate_shift_summary(self, params: dict) -> AgentResult:
        """shift_handover / trade.daily_settlement.completed 触发：生成班次财务快照

        汇总该班次的营收、折扣、退款、毛利数据，
        供班组长交接和夜间财务归档使用。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        shift_id = params.get("shift_id") or event_data.get("shift_id", "")
        shift_date = params.get("shift_date") or event_data.get("shift_date", "")
        shift_type = params.get("shift_type") or event_data.get("shift_type", "day")  # day/night

        # 优先从 DB 聚合班次数据
        summary: dict = {}
        if self._db and store_id and shift_date:
            from sqlalchemy import text
            row = await self._db.execute(text("""
                SELECT
                    COUNT(*) as order_count,
                    COALESCE(SUM(final_amount_fen), 0) as revenue_fen,
                    COALESCE(SUM(discount_amount_fen), 0) as discount_fen,
                    COALESCE(SUM(refund_amount_fen), 0) as refund_fen,
                    COUNT(DISTINCT customer_id) as unique_customers
                FROM orders
                WHERE tenant_id = :tenant_id
                  AND (:store_id::UUID IS NULL OR store_id = :store_id::UUID)
                  AND status = 'completed'
                  AND DATE(completed_at) = :shift_date::date
                  AND (:shift_type = 'all'
                       OR (:shift_type = 'day' AND EXTRACT(HOUR FROM completed_at) BETWEEN 6 AND 17)
                       OR (:shift_type = 'night' AND (EXTRACT(HOUR FROM completed_at) >= 18
                                                       OR EXTRACT(HOUR FROM completed_at) < 6)))
            """), {
                "tenant_id": self.tenant_id,
                "store_id": store_id,
                "shift_date": shift_date,
                "shift_type": shift_type,
            })
            r = dict(row.mappings().first() or {})
            order_count = int(r.get("order_count") or 0)
            revenue_fen = int(r.get("revenue_fen") or 0)
            discount_fen = int(r.get("discount_fen") or 0)
            refund_fen = int(r.get("refund_fen") or 0)
            unique_customers = int(r.get("unique_customers") or 0)
        else:
            # 降级：使用 params 传入的数据
            order_count = params.get("order_count", 0)
            revenue_fen = params.get("revenue_fen", 0)
            discount_fen = params.get("discount_fen", 0)
            refund_fen = params.get("refund_fen", 0)
            unique_customers = params.get("unique_customers", 0)

        net_revenue_fen = revenue_fen - refund_fen
        avg_order_value_fen = net_revenue_fen // order_count if order_count > 0 else 0
        discount_rate = discount_fen / (revenue_fen + discount_fen) if (revenue_fen + discount_fen) > 0 else 0

        summary = {
            "shift_id": shift_id,
            "shift_date": shift_date,
            "shift_type": shift_type,
            "store_id": store_id,
            "order_count": order_count,
            "unique_customers": unique_customers,
            "revenue_fen": revenue_fen,
            "revenue_yuan": round(revenue_fen / 100, 2),
            "discount_fen": discount_fen,
            "discount_rate": round(discount_rate, 4),
            "refund_fen": refund_fen,
            "net_revenue_fen": net_revenue_fen,
            "net_revenue_yuan": round(net_revenue_fen / 100, 2),
            "avg_order_value_fen": avg_order_value_fen,
            "avg_order_value_yuan": round(avg_order_value_fen / 100, 2),
        }

        # 使用 Claude 生成班次财务点评
        commentary = ""
        if self._router and order_count > 0:
            try:
                commentary = await self._router.complete(
                    tenant_id=self.tenant_id,
                    task_type="standard_analysis",
                    system="你是餐饮财务助理，根据班次数据给出一句话简短点评（30字内），重点关注异常数据。",
                    messages=[{"role": "user", "content":
                        f"{shift_date} {shift_type}班：{order_count}单，"
                        f"净营收¥{net_revenue_fen/100:.0f}，"
                        f"折扣率{discount_rate:.1%}，客单价¥{avg_order_value_fen/100:.0f}。"}],
                    max_tokens=80,
                    db=self._db,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("finance_shift_summary_llm_fallback", error=str(exc))

        summary["commentary"] = commentary

        return AgentResult(
            success=True,
            action="generate_shift_summary",
            data=summary,
            reasoning=(
                f"{shift_date} {shift_type}班摘要：{order_count}单，"
                f"净营收¥{net_revenue_fen/100:.0f}"
                + (f"，{commentary}" if commentary else "")
            ),
            confidence=0.95 if self._db else 0.8,
            inference_layer="cloud" if commentary else "edge",
        )

    # ─── 事件驱动：标记收货差异 ───

    async def _flag_receiving_variance(self, params: dict) -> AgentResult:
        """supply.receiving.variance 触发：财务角度标记进货差异，评估损失金额

        收货数量与采购单不符时触发，财务需核实是否存在以下问题：
        - 供应商短斤少两
        - 收货员操作失误
        - 采购单录入错误
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        purchase_order_id = params.get("purchase_order_id") or event_data.get("purchase_order_id")
        ingredient_name = params.get("ingredient_name") or event_data.get("ingredient_name", "")
        ordered_qty = params.get("ordered_qty") or event_data.get("ordered_qty", 0)
        received_qty = params.get("received_qty") or event_data.get("received_qty", 0)
        unit_price_fen = params.get("unit_price_fen") or event_data.get("unit_price_fen", 0)
        supplier_id = params.get("supplier_id") or event_data.get("supplier_id")

        variance_qty = received_qty - ordered_qty
        variance_pct = variance_qty / ordered_qty if ordered_qty > 0 else 0
        variance_amount_fen = int(abs(variance_qty) * unit_price_fen)

        # 差异类型
        variance_type = (
            "short_delivery" if variance_qty < 0 else
            "over_delivery" if variance_qty > 0 else
            "matched"
        )

        # 是否需要财务介入（差异金额>100元 或 差异率>5%）
        needs_finance_action = (
            variance_amount_fen > 10000 or abs(variance_pct) > 0.05
        )

        recommended_action = []
        if variance_type == "short_delivery" and needs_finance_action:
            recommended_action.append("向供应商发起差异索赔")
            recommended_action.append("在采购付款时扣减差额")
        elif variance_type == "over_delivery":
            recommended_action.append("确认是否退回多余货品或补付款")
        if abs(variance_pct) > 0.1:
            recommended_action.append("评估供应商信用评级")

        logger.info(
            "receiving_variance_flagged",
            store_id=store_id,
            purchase_order_id=purchase_order_id,
            ingredient_name=ingredient_name,
            variance_type=variance_type,
            variance_amount_fen=variance_amount_fen,
        )

        return AgentResult(
            success=True,
            action="flag_receiving_variance",
            data={
                "store_id": store_id,
                "purchase_order_id": purchase_order_id,
                "supplier_id": supplier_id,
                "ingredient_name": ingredient_name,
                "ordered_qty": ordered_qty,
                "received_qty": received_qty,
                "variance_qty": variance_qty,
                "variance_pct": round(variance_pct, 4),
                "variance_type": variance_type,
                "variance_amount_fen": variance_amount_fen,
                "variance_amount_yuan": round(variance_amount_fen / 100, 2),
                "needs_finance_action": needs_finance_action,
                "recommended_action": recommended_action,
            },
            reasoning=(
                f"收货差异：{ingredient_name} {variance_type}，"
                f"差异{variance_qty:+.2f}（{variance_pct:+.1%}），"
                f"涉及金额¥{variance_amount_fen/100:.0f}"
            ),
            confidence=0.9,
        )

    # ─── 事件驱动：处理审批完成 ───

    async def _process_approval_result(self, params: dict) -> AgentResult:
        """org.approval.completed 触发：审批完成后财务联动处理

        根据审批类型执行对应财务动作：
        - 采购审批通过 → 解锁采购预算
        - 报销审批通过 → 生成付款指令
        - 折扣审批通过 → 更新折扣授权记录
        - 预算调整通过 → 更新预算台账
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        approval_id = params.get("approval_id") or event_data.get("approval_id")
        approval_type = params.get("approval_type") or event_data.get("approval_type", "unknown")
        approved = params.get("approved") if params.get("approved") is not None else event_data.get("approved", True)
        amount_fen = params.get("amount_fen") or event_data.get("amount_fen", 0)
        applicant_id = params.get("applicant_id") or event_data.get("applicant_id")

        # 按审批类型派生财务动作
        finance_action_map = {
            "purchase": "解锁采购预算，更新应付账款",
            "reimbursement": "生成付款指令，扣减费用预算",
            "discount": "更新折扣授权记录，同步折扣守护规则",
            "budget_adjustment": "更新门店预算台账",
            "write_off": "记录核销凭证，更新库存台账",
        }
        finance_action = finance_action_map.get(approval_type, "归档审批记录")

        # 拒绝时的财务处理
        if not approved:
            finance_action = f"审批拒绝：冻结对应{approval_type}申请，退回预算占用"

        impact_assessment = {
            "budget_impact_fen": amount_fen if approved else 0,
            "requires_payment": approved and approval_type in ("reimbursement", "purchase"),
            "requires_rule_update": approved and approval_type == "discount",
        }

        logger.info(
            "approval_result_processed",
            store_id=store_id,
            approval_id=approval_id,
            approval_type=approval_type,
            approved=approved,
            amount_fen=amount_fen,
        )

        return AgentResult(
            success=True,
            action="process_approval_result",
            data={
                "store_id": store_id,
                "approval_id": approval_id,
                "approval_type": approval_type,
                "approved": approved,
                "amount_fen": amount_fen,
                "amount_yuan": round(amount_fen / 100, 2),
                "applicant_id": applicant_id,
                "finance_action": finance_action,
                "impact_assessment": impact_assessment,
            },
            reasoning=(
                f"审批{'通过' if approved else '拒绝'}：{approval_type}，"
                f"金额¥{amount_fen/100:.0f}，财务动作={finance_action}"
            ),
            confidence=0.9,
        )

    # ─── 事件驱动：成本超标根因分析 ───

    async def _root_cause_analysis(self, params: dict) -> AgentResult:
        """finance.cost_rate.exceeded 触发：分析成本率超标根因

        从多个维度拆解成本超标原因，并给出优先级最高的改善建议。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        actual_cost_rate = params.get("actual_cost_rate") or event_data.get("actual_cost_rate", 0)
        target_cost_rate = params.get("target_cost_rate") or event_data.get("target_cost_rate", 0.35)
        over_rate = actual_cost_rate - target_cost_rate
        date_range = params.get("date_range") or event_data.get("date_range", "近7天")

        # 从 params 或 event_data 获取拆解数据
        breakdown = params.get("cost_breakdown") or event_data.get("cost_breakdown", {})
        waste_rate = breakdown.get("waste_rate", 0)
        purchasing_variance = breakdown.get("purchasing_variance", 0)
        discount_rate = breakdown.get("discount_rate", 0)
        portion_over = breakdown.get("portion_over_standard", False)

        # 根因推断规则
        hypotheses: list[dict] = []

        if waste_rate > 0.05:
            hypotheses.append({
                "cause": "食材损耗偏高",
                "evidence": f"损耗率 {waste_rate:.1%}（阈值5%）",
                "impact_pct": round(waste_rate * actual_cost_rate * 100, 1),
                "suggested_action": "核查库存管理规范，减少备货量，优化先进先出",
                "priority": 1,
            })

        if purchasing_variance > 0.08:
            hypotheses.append({
                "cause": "采购价格偏高",
                "evidence": f"采购差异率 {purchasing_variance:.1%}",
                "impact_pct": round(purchasing_variance * 10, 1),
                "suggested_action": "重新议价或启动比价采购",
                "priority": 2,
            })

        if discount_rate > 0.15:
            hypotheses.append({
                "cause": "折扣过度导致毛利侵蚀",
                "evidence": f"折扣率 {discount_rate:.1%}（偏高）",
                "impact_pct": round(discount_rate * 5, 1),
                "suggested_action": "收紧折扣授权，重审折扣政策",
                "priority": 3,
            })

        if portion_over:
            hypotheses.append({
                "cause": "出品份量超标准",
                "evidence": "多门店报告份量超出SOP标准",
                "impact_pct": 3.0,
                "suggested_action": "加强厨房SOP培训，使用标准量器",
                "priority": 4,
            })

        if not hypotheses:
            hypotheses.append({
                "cause": "原因待查",
                "evidence": f"成本率{actual_cost_rate:.1%} 超目标{over_rate:.1%}，但各分项指标正常",
                "impact_pct": round(over_rate * 100, 1),
                "suggested_action": "人工抽查近期采购单和出库记录",
                "priority": 1,
            })

        # 按优先级排序
        hypotheses.sort(key=lambda h: h["priority"])
        top_cause = hypotheses[0]

        # Claude 深度分析
        llm_analysis = ""
        if self._router and hypotheses:
            try:
                hypothesis_text = "\n".join([
                    f"- {h['cause']}: {h['evidence']}，建议{h['suggested_action']}"
                    for h in hypotheses[:3]
                ])
                llm_analysis = await self._router.complete(
                    tenant_id=self.tenant_id,
                    task_type="cost_analysis",
                    system="你是餐饮运营顾问，根据成本超标分析给出最优先的一个改善建议，50字内，中文。",
                    messages=[{"role": "user", "content":
                        f"{date_range}成本率{actual_cost_rate:.1%}，目标{target_cost_rate:.1%}，"
                        f"超出{over_rate:.1%}。根因假设：\n{hypothesis_text}"}],
                    max_tokens=120,
                    db=self._db,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("finance_root_cause_llm_fallback", error=str(exc))

        return AgentResult(
            success=True,
            action="root_cause_analysis",
            data={
                "store_id": store_id,
                "actual_cost_rate": round(actual_cost_rate, 4),
                "target_cost_rate": round(target_cost_rate, 4),
                "over_rate": round(over_rate, 4),
                "date_range": date_range,
                "hypotheses": hypotheses,
                "top_cause": top_cause,
                "llm_analysis": llm_analysis,
            },
            reasoning=(
                f"成本超标根因：{top_cause['cause']}，"
                f"建议{top_cause['suggested_action']}"
                + (f"。AI补充: {llm_analysis[:30]}" if llm_analysis else "")
            ),
            confidence=0.8 if not llm_analysis else 0.88,
            inference_layer="cloud" if llm_analysis else "edge",
        )

    # ─── 事件驱动：P&L 异常检测 ───

    async def _check_pl_anomaly(self, params: dict) -> AgentResult:
        """finance.daily_pl.generated 触发：对日 P&L 数据进行多维异常检测

        检测维度：
        1. 营收同比/环比偏差
        2. 成本率是否超阈值
        3. 毛利润绝对值是否低于预警线
        4. 客单价异常波动
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})

        revenue_fen = params.get("revenue_fen") or event_data.get("revenue_fen", 0)
        cost_fen = params.get("cost_fen") or event_data.get("cost_fen", 0)
        gross_profit_fen = revenue_fen - cost_fen
        gross_margin = gross_profit_fen / revenue_fen if revenue_fen > 0 else 0

        order_count = params.get("order_count") or event_data.get("order_count", 0)
        avg_ticket_fen = revenue_fen // order_count if order_count > 0 else 0

        # 历史基线对比数据（可选）
        history_revenue_fen = params.get("history_revenue_fen", [])
        history_margin = params.get("history_gross_margin", [])
        history_ticket = params.get("history_avg_ticket_fen", [])

        anomalies: list[dict] = []

        # 检测1：营收偏差
        if history_revenue_fen and len(history_revenue_fen) >= 3:
            avg_rev = statistics.mean(history_revenue_fen)
            std_rev = statistics.stdev(history_revenue_fen) if len(history_revenue_fen) >= 2 else avg_rev * 0.1
            z_rev = (revenue_fen - avg_rev) / std_rev if std_rev > 0 else 0
            if abs(z_rev) > 2.0:
                anomalies.append({
                    "dimension": "revenue",
                    "severity": "critical" if abs(z_rev) > 3 else "warning",
                    "detail": f"营收¥{revenue_fen/100:.0f}，偏离均值{z_rev:+.1f}个标准差",
                    "z_score": round(z_rev, 2),
                })

        # 检测2：毛利率
        if gross_margin < 0.25:
            anomalies.append({
                "dimension": "gross_margin",
                "severity": "critical" if gross_margin < 0.15 else "warning",
                "detail": f"毛利率{gross_margin:.1%}，低于警戒线25%",
                "value": round(gross_margin, 4),
            })

        # 检测3：毛利润绝对值（低于1000元触发）
        if 0 < revenue_fen > 0 and gross_profit_fen < 100000:
            anomalies.append({
                "dimension": "gross_profit_absolute",
                "severity": "warning",
                "detail": f"毛利润¥{gross_profit_fen/100:.0f}，绝对值偏低",
                "value": gross_profit_fen,
            })

        # 检测4：客单价异常
        if history_ticket and len(history_ticket) >= 3 and avg_ticket_fen > 0:
            avg_t = statistics.mean(history_ticket)
            if avg_t > 0:
                ticket_deviation = abs(avg_ticket_fen - avg_t) / avg_t
                if ticket_deviation > 0.2:
                    anomalies.append({
                        "dimension": "avg_ticket",
                        "severity": "warning",
                        "detail": f"客单价¥{avg_ticket_fen/100:.0f}，偏离均值{ticket_deviation:.1%}",
                        "deviation_pct": round(ticket_deviation, 4),
                    })

        overall_status = (
            "critical" if any(a["severity"] == "critical" for a in anomalies) else
            "warning" if anomalies else
            "normal"
        )

        return AgentResult(
            success=True,
            action="check_pl_anomaly",
            data={
                "store_id": store_id,
                "revenue_fen": revenue_fen,
                "cost_fen": cost_fen,
                "gross_profit_fen": gross_profit_fen,
                "gross_margin": round(gross_margin, 4),
                "order_count": order_count,
                "avg_ticket_fen": avg_ticket_fen,
                "anomalies": anomalies,
                "anomaly_count": len(anomalies),
                "overall_status": overall_status,
            },
            reasoning=(
                f"P&L异常检测：{overall_status}，发现{len(anomalies)}个异常项"
                + (f"（{anomalies[0]['detail']}）" if anomalies else "，各项正常")
            ),
            confidence=0.85 if history_revenue_fen else 0.7,
        )

    # ─── Phase 3: 读物化视图（< 5ms，替代跨服务查询） ───

    async def _get_settlement_snapshot(self, params: dict) -> AgentResult:
        """从 mv_daily_settlement 读取日结快照（Phase 3）。

        响应时间 < 5ms，替代原来 tx-ops + tx-finance 双服务查询模式。
        """
        from datetime import date
        from typing import Optional

        from sqlalchemy import text

        store_id: str = params.get("store_id") or self.store_id or ""
        stat_date: Optional[date] = params.get("stat_date") or date.today()

        if not store_id:
            return AgentResult(
                success=False, action="get_settlement_snapshot",
                error="缺少 store_id",
            )

        if not self._db:
            return AgentResult(
                success=False, action="get_settlement_snapshot",
                error="无DB连接，无法读取物化视图",
            )

        row = await self._db.execute(text("""
            SELECT
                status, total_orders, total_revenue_fen,
                cash_declared_fen, pos_system_fen, gap_fen,
                member_consume_fen, channel_revenue_fen,
                discount_total_fen, refund_total_fen,
                closed_at, updated_at
            FROM mv_daily_settlement
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id::UUID
              AND stat_date = :stat_date
        """), {
            "tenant_id": self.tenant_id,
            "store_id": store_id,
            "stat_date": stat_date,
        })

        r = row.mappings().first()
        if not r:
            return AgentResult(
                success=True, action="get_settlement_snapshot",
                data={
                    "store_id": store_id,
                    "stat_date": stat_date.isoformat() if hasattr(stat_date, "isoformat") else str(stat_date),
                    "message": "当日暂无结算数据",
                    "source": "mv_daily_settlement",
                },
                confidence=0.5,
            )

        data = dict(r)
        for key in ("closed_at", "updated_at"):
            if data.get(key):
                data[key] = data[key].isoformat()
        data["stat_date"] = stat_date.isoformat() if hasattr(stat_date, "isoformat") else str(stat_date)
        data["store_id"] = store_id
        data["total_revenue_yuan"] = round(int(data.get("total_revenue_fen") or 0) / 100, 2)
        data["gap_yuan"] = round(int(data.get("gap_fen") or 0) / 100, 2)
        data["source"] = "mv_daily_settlement"

        gap_fen = int(data.get("gap_fen") or 0)
        status = data.get("status", "open")
        risk = "high" if abs(gap_fen) > 10000 or status == "discrepancy" else "low"

        return AgentResult(
            success=True, action="get_settlement_snapshot",
            data=data,
            reasoning=(
                f"日结快照（{stat_date}）：状态={status}，"
                f"营收¥{data['total_revenue_yuan']}，"
                f"差额¥{data['gap_yuan']}，风险={risk}"
            ),
            confidence=0.95,
            inference_layer="cloud",
        )

    async def _get_pnl_snapshot(self, params: dict) -> AgentResult:
        """从 mv_store_pnl 读取门店P&L快照（Phase 3）。

        替代原来 tx-finance 多表聚合模式，Agent决策速度提升 20x。
        """
        from datetime import date
        from typing import Optional

        from sqlalchemy import text

        store_id: str = params.get("store_id") or self.store_id or ""
        stat_date: Optional[date] = params.get("stat_date") or date.today()

        if not store_id:
            return AgentResult(
                success=False, action="get_pnl_snapshot",
                error="缺少 store_id",
            )

        if not self._db:
            return AgentResult(
                success=False, action="get_pnl_snapshot",
                error="无DB连接，无法读取物化视图",
            )

        row = await self._db.execute(text("""
            SELECT
                brand_id, revenue_fen, cost_fen, gross_profit_fen,
                gross_margin, order_count, avg_ticket_fen,
                discount_fen, refund_fen, channel_fee_fen,
                updated_at
            FROM mv_store_pnl
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id::UUID
              AND stat_date = :stat_date
        """), {
            "tenant_id": self.tenant_id,
            "store_id": store_id,
            "stat_date": stat_date,
        })

        r = row.mappings().first()
        if not r:
            return AgentResult(
                success=True, action="get_pnl_snapshot",
                data={
                    "store_id": store_id,
                    "stat_date": stat_date.isoformat() if hasattr(stat_date, "isoformat") else str(stat_date),
                    "message": "当日暂无P&L数据",
                    "source": "mv_store_pnl",
                },
                confidence=0.5,
            )

        data = dict(r)
        if data.get("updated_at"):
            data["updated_at"] = data["updated_at"].isoformat()
        data["stat_date"] = stat_date.isoformat() if hasattr(stat_date, "isoformat") else str(stat_date)
        data["store_id"] = store_id
        data["revenue_yuan"] = round(int(data.get("revenue_fen") or 0) / 100, 2)
        data["gross_profit_yuan"] = round(int(data.get("gross_profit_fen") or 0) / 100, 2)
        data["source"] = "mv_store_pnl"

        gross_margin = float(data.get("gross_margin") or 0)
        margin_status = "healthy" if gross_margin >= 0.6 else ("warning" if gross_margin >= 0.5 else "critical")

        return AgentResult(
            success=True, action="get_pnl_snapshot",
            data=data,
            reasoning=(
                f"P&L快照（{stat_date}）：营收¥{data['revenue_yuan']}，"
                f"毛利率{gross_margin*100:.1f}%（{margin_status}），"
                f"均客单¥{int(data.get('avg_ticket_fen') or 0)/100:.0f}"
            ),
            confidence=0.95,
            inference_layer="cloud",
        )
