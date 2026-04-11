"""收银异常Agent — 反结账检测、漏单检测、支付异常、挂账超期

职责：
- 监控反结账频率（异常高频→可能舞弊）
- 检测漏单（有桌台占用但无订单）
- 支付方式异常（大额现金、频繁小额退款）
- 挂账/赊账超期提醒
- 班次收银差异检测

事件驱动：
- ORDER.REVERSE_SETTLED → 反结账触发审查
- PAYMENT.CONFIRMED → 支付完成后异常扫描
- SHIFT.CLOSED → 班结时现金差异检测
"""
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()


class BillingAnomalyAgent(SkillAgent):
    agent_id = "billing_anomaly"
    agent_name = "收银异常检测"
    description = "反结账检测、漏单检测、支付异常、挂账超期、班次差异"
    priority = "P1"
    run_location = "edge+cloud"
    agent_level = 1  # 仅建议，不自动执行（涉及资金安全）

    def get_supported_actions(self) -> list[str]:
        return [
            "detect_reverse_settle_anomaly",
            "scan_missing_orders",
            "detect_payment_anomaly",
            "check_overdue_credit",
            "analyze_shift_variance",
            "get_risk_summary",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "detect_reverse_settle_anomaly": self._detect_reverse_settle,
            "scan_missing_orders": self._scan_missing_orders,
            "detect_payment_anomaly": self._detect_payment_anomaly,
            "check_overdue_credit": self._check_overdue_credit,
            "analyze_shift_variance": self._analyze_shift_variance,
            "get_risk_summary": self._get_risk_summary,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported action: {action}")
        return await handler(params)

    async def _detect_reverse_settle(self, params: dict) -> AgentResult:
        """反结账异常检测"""
        operator_id = params.get("operator_id", "")
        order_id = params.get("order_id", "")
        reverse_count_today = params.get("reverse_count_today", 0)
        reverse_amount_fen = params.get("reverse_amount_fen", 0)

        risk_level = "low"
        alerts = []

        # 规则：单人单日反结账≥3次 → 高风险
        if reverse_count_today >= 3:
            risk_level = "high"
            alerts.append(f"收银员今日反结账{reverse_count_today}次，超过阈值(3次)")
        elif reverse_count_today >= 2:
            risk_level = "medium"
            alerts.append(f"收银员今日反结账{reverse_count_today}次，接近阈值")

        # 规则：单笔反结账金额≥500元 → 需要审批
        if reverse_amount_fen >= 50000:
            risk_level = "high"
            alerts.append(f"反结账金额¥{reverse_amount_fen / 100:.2f}，超过审批阈值(¥500)")

        # 云端深度分析
        ai_analysis = None
        if self._router and risk_level == "high":
            try:
                resp = await self._router.complete(
                    prompt=f"收银员反结账异常：今日第{reverse_count_today}次反结账，金额¥{reverse_amount_fen / 100:.2f}。"
                           f"请分析可能的原因和建议措施（50字以内）。",
                    max_tokens=80,
                )
                if resp:
                    ai_analysis = resp.strip()
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                pass

        if risk_level == "high":
            logger.warning("billing_anomaly_detected",
                          operator=operator_id, order=order_id, risk=risk_level,
                          count=reverse_count_today, amount_fen=reverse_amount_fen)

        return AgentResult(
            success=True, action="detect_reverse_settle_anomaly",
            data={
                "risk_level": risk_level,
                "alerts": alerts,
                "operator_id": operator_id,
                "order_id": order_id,
                "reverse_count_today": reverse_count_today,
                "reverse_amount_fen": reverse_amount_fen,
                "ai_analysis": ai_analysis,
                "requires_approval": risk_level == "high",
            },
            reasoning=f"反结账风险评级: {risk_level}，{'; '.join(alerts) if alerts else '无异常'}",
            confidence=0.9,
            inference_layer="edge+cloud" if ai_analysis else "edge",
        )

    async def _scan_missing_orders(self, params: dict) -> AgentResult:
        """漏单检测：有桌台占用但无活跃订单"""
        occupied_tables = params.get("occupied_tables", [])
        active_orders = params.get("active_order_table_nos", [])

        missing = [t for t in occupied_tables if t.get("table_no") not in active_orders
                   and t.get("status") in ("opened", "dining", "serving")]

        return AgentResult(
            success=True, action="scan_missing_orders",
            data={
                "missing_count": len(missing),
                "missing_tables": missing,
                "total_occupied": len(occupied_tables),
            },
            reasoning=f"{len(occupied_tables)}张桌台占用中，{len(missing)}张疑似漏单",
            confidence=0.85,
            inference_layer="edge",
        )

    async def _detect_payment_anomaly(self, params: dict) -> AgentResult:
        """支付异常检测"""
        payment = params.get("payment", {})
        method = payment.get("method", "")
        amount_fen = payment.get("amount_fen", 0)
        order_total_fen = payment.get("order_total_fen", 0)

        anomalies = []

        # 大额现金（≥1000元）
        if method == "cash" and amount_fen >= 100000:
            anomalies.append({"type": "large_cash", "detail": f"现金支付¥{amount_fen / 100:.0f}，建议引导扫码支付"})

        # 支付金额与订单金额严重不符
        if order_total_fen > 0 and amount_fen > 0:
            ratio = amount_fen / order_total_fen
            if ratio < 0.5:
                anomalies.append({"type": "underpayment", "detail": f"实付仅为应付的{ratio:.0%}，可能存在未授权折扣"})
            elif ratio > 1.5:
                anomalies.append({"type": "overpayment", "detail": f"实付超过应付{ratio:.0%}，请核实"})

        return AgentResult(
            success=True, action="detect_payment_anomaly",
            data={
                "anomaly_count": len(anomalies),
                "anomalies": anomalies,
                "payment": payment,
            },
            reasoning=f"支付¥{amount_fen / 100:.2f}({method})，{'发现' + str(len(anomalies)) + '项异常' if anomalies else '无异常'}",
            confidence=0.85,
            inference_layer="edge",
        )

    async def _check_overdue_credit(self, params: dict) -> AgentResult:
        """挂账超期检查"""
        credit_orders = params.get("credit_orders", [])
        overdue_days_threshold = params.get("overdue_days_threshold", 30)

        overdue = [o for o in credit_orders if o.get("days_outstanding", 0) > overdue_days_threshold]
        total_overdue_fen = sum(o.get("outstanding_fen", 0) for o in overdue)

        return AgentResult(
            success=True, action="check_overdue_credit",
            data={
                "overdue_count": len(overdue),
                "total_overdue_fen": total_overdue_fen,
                "overdue_orders": overdue[:20],  # 最多返回20条
                "threshold_days": overdue_days_threshold,
            },
            reasoning=f"挂账超{overdue_days_threshold}天: {len(overdue)}笔，合计¥{total_overdue_fen / 100:.2f}",
            confidence=0.95,
            inference_layer="edge",
        )

    async def _analyze_shift_variance(self, params: dict) -> AgentResult:
        """班次收银差异分析"""
        expected_cash_fen = params.get("expected_cash_fen", 0)
        actual_cash_fen = params.get("actual_cash_fen", 0)
        operator_name = params.get("operator_name", "")

        variance_fen = actual_cash_fen - expected_cash_fen
        variance_rate = abs(variance_fen) / max(expected_cash_fen, 1)

        risk_level = "low"
        if abs(variance_fen) >= 10000:  # ≥100元差异
            risk_level = "high"
        elif abs(variance_fen) >= 2000:  # ≥20元
            risk_level = "medium"

        return AgentResult(
            success=True, action="analyze_shift_variance",
            data={
                "expected_cash_fen": expected_cash_fen,
                "actual_cash_fen": actual_cash_fen,
                "variance_fen": variance_fen,
                "variance_rate": variance_rate,
                "risk_level": risk_level,
                "operator_name": operator_name,
            },
            reasoning=f"{operator_name}班次现金差异: {'+'if variance_fen > 0 else ''}¥{variance_fen / 100:.2f} "
                      f"(差异率{variance_rate:.1%})，风险等级: {risk_level}",
            confidence=0.95,
            inference_layer="edge",
        )

    async def _get_risk_summary(self, params: dict) -> AgentResult:
        """获取今日收银风险汇总"""
        return AgentResult(
            success=True, action="get_risk_summary",
            data={
                "date": params.get("date", ""),
                "reverse_settle_count": params.get("reverse_settle_count", 0),
                "missing_order_count": params.get("missing_order_count", 0),
                "overdue_credit_count": params.get("overdue_credit_count", 0),
                "cash_variance_fen": params.get("cash_variance_fen", 0),
                "high_risk_alerts": params.get("high_risk_alerts", 0),
                "risk_score": params.get("risk_score", 15),  # 0-100
            },
            reasoning="收银风险日报汇总",
            confidence=0.9,
            inference_layer="edge",
        )
