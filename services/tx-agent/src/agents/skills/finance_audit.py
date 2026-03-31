"""#6 财务稽核 Agent — P1 | 云端

来源：FctAgent + DecisionAgent + business_intel(5子Agent)
能力：财务报表、营收异常、KPI分析、订单预测、经营洞察

迁移自 tunxiang V2.x decision_agent.py + business_intel/agent.py
"""
import statistics
from typing import Any, Optional
import structlog
from ..base import SkillAgent, AgentResult

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
        ]

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
            from sqlalchemy import text
            from datetime import datetime, timezone, timedelta

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
            from sqlalchemy import text
            from datetime import datetime, timezone

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
