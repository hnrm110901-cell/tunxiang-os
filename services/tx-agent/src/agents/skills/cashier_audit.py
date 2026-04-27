"""#27 收银稽核 Agent — P0 | 边缘+云端

守门员Agent：监控每笔收银操作，检测折扣异常、退款异常、挂账超额。
触发条件：每笔结账后实时检查 or 每小时批量检查。

检测维度：
- 同一收银员短时间内多次退款
- 大额折扣无审批
- 现金交易异常（现金占比过高、金额异常）
- 挂账超额
"""

from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()

# 默认阈值
DEFAULT_REFUND_COUNT_THRESHOLD = 3  # 短时间内退款次数上限
DEFAULT_REFUND_WINDOW_MINUTES = 60  # 退款检测时间窗口
DEFAULT_LARGE_DISCOUNT_FEN = 5000  # 大额折扣阈值（50元）
DEFAULT_CASH_RATIO_THRESHOLD = 0.8  # 现金交易占比异常阈值
DEFAULT_PENDING_LIMIT_FEN = 100000  # 挂账上限（1000元）


class CashierAuditAgent(SkillAgent):
    agent_id = "cashier_audit"
    agent_name = "收银稽核"
    description = "监控收银操作，检测折扣异常、退款异常、挂账超额、现金异常"
    priority = "P0"
    run_location = "edge+cloud"

    # Sprint D1 / PR Overflow：折扣异常/挂账超额检测直接关联毛利底线
    # （设计稿 §附录B "cashier_audit 状态复核" 决策点已被覆盖：P0 实装级别接入 margin）
    constraint_scope = {"margin"}

    def get_supported_actions(self) -> list[str]:
        return [
            "audit_transaction",
            "batch_audit",
            "detect_refund_anomaly",
            "detect_cash_anomaly",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "audit_transaction": self._audit_transaction,
            "batch_audit": self._batch_audit,
            "detect_refund_anomaly": self._detect_refund_anomaly,
            "detect_cash_anomaly": self._detect_cash_anomaly,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    # ─── 单笔结账稽核 ───

    async def _audit_transaction(self, params: dict) -> AgentResult:
        """单笔收银操作稽核 — 结账后实时触发"""
        txn = params.get("transaction", {})
        txn_id = txn.get("txn_id", "unknown")
        cashier_id = txn.get("cashier_id", "")
        total_fen = txn.get("total_amount_fen", 0)
        discount_fen = txn.get("discount_amount_fen", 0)
        refund_fen = txn.get("refund_amount_fen", 0)
        pending_fen = txn.get("pending_amount_fen", 0)
        has_approval = txn.get("discount_approved", False)
        payment_method = txn.get("payment_method", "")

        anomalies: list[dict] = []

        # 1. 大额折扣无审批
        discount_threshold = params.get("large_discount_fen", DEFAULT_LARGE_DISCOUNT_FEN)
        if discount_fen > discount_threshold and not has_approval:
            anomalies.append(
                {
                    "txn_id": txn_id,
                    "type": "unapproved_large_discount",
                    "detail": f"折扣 {discount_fen / 100:.2f} 元超阈值且未审批",
                    "severity": "high",
                }
            )

        # 2. 折扣率异常
        if total_fen > 0:
            discount_rate = discount_fen / total_fen
            if discount_rate > 0.5:
                anomalies.append(
                    {
                        "txn_id": txn_id,
                        "type": "excessive_discount_rate",
                        "detail": f"折扣率 {discount_rate:.1%} 超过 50%",
                        "severity": "high" if discount_rate > 0.7 else "medium",
                    }
                )

        # 3. 退款异常
        if refund_fen > 0 and total_fen > 0 and refund_fen > total_fen * 0.5:
            anomalies.append(
                {
                    "txn_id": txn_id,
                    "type": "large_refund",
                    "detail": f"退款 {refund_fen / 100:.2f} 元超过订单金额 50%",
                    "severity": "high",
                }
            )

        # 4. 挂账超额
        pending_limit = params.get("pending_limit_fen", DEFAULT_PENDING_LIMIT_FEN)
        if pending_fen > pending_limit:
            anomalies.append(
                {
                    "txn_id": txn_id,
                    "type": "pending_over_limit",
                    "detail": f"挂账 {pending_fen / 100:.2f} 元超上限 {pending_limit / 100:.2f} 元",
                    "severity": "medium",
                }
            )

        risk_level = "high" if any(a["severity"] == "high" for a in anomalies) else "medium" if anomalies else "low"

        return AgentResult(
            success=True,
            action="audit_transaction",
            data={
                "risk_level": risk_level,
                "transactions_checked": 1,
                "anomalies": anomalies,
                "txn_id": txn_id,
                "cashier_id": cashier_id,
                "price_fen": total_fen,
                "cost_fen": txn.get("cost_fen", 0),
            },
            reasoning=f"交易 {txn_id} 稽核完成，风险等级 {risk_level}，{len(anomalies)} 个异常",
            confidence=0.92,
            inference_layer="edge",
        )

    # ─── 批量稽核 ───

    async def _batch_audit(self, params: dict) -> AgentResult:
        """批量收银稽核 — 每小时定时触发"""
        transactions = params.get("transactions", [])
        if not transactions:
            return AgentResult(
                success=False,
                action="batch_audit",
                error="无交易数据",
                reasoning="批量稽核需要提供交易列表",
                confidence=1.0,
            )

        all_anomalies: list[dict] = []
        for txn in transactions:
            result = await self._audit_transaction({"transaction": txn})
            if result.data.get("anomalies"):
                all_anomalies.extend(result.data["anomalies"])

        high_count = sum(1 for a in all_anomalies if a["severity"] == "high")
        risk_level = "high" if high_count > 0 else "medium" if all_anomalies else "low"

        return AgentResult(
            success=True,
            action="batch_audit",
            data={
                "risk_level": risk_level,
                "transactions_checked": len(transactions),
                "anomalies": all_anomalies,
                "high_severity_count": high_count,
                "total_anomaly_count": len(all_anomalies),
            },
            reasoning=f"批量稽核 {len(transactions)} 笔交易，发现 {len(all_anomalies)} 个异常（{high_count} 个高危）",
            confidence=0.90,
        )

    # ─── 退款异常检测 ───

    async def _detect_refund_anomaly(self, params: dict) -> AgentResult:
        """检测同一收银员短时间内多次退款"""
        cashier_id = params.get("cashier_id", "")
        refund_records = params.get("refund_records", [])
        window_minutes = params.get("window_minutes", DEFAULT_REFUND_WINDOW_MINUTES)
        threshold = params.get("refund_count_threshold", DEFAULT_REFUND_COUNT_THRESHOLD)

        refund_count = len(refund_records)
        total_refund_fen = sum(r.get("amount_fen", 0) for r in refund_records)

        is_anomaly = refund_count >= threshold
        anomalies: list[dict] = []
        if is_anomaly:
            anomalies.append(
                {
                    "txn_id": f"refund_batch_{cashier_id}",
                    "type": "frequent_refund",
                    "detail": f"收银员 {cashier_id} 在 {window_minutes} 分钟内退款 {refund_count} 次，"
                    f"总计 {total_refund_fen / 100:.2f} 元",
                    "severity": "high" if refund_count >= threshold * 2 else "medium",
                }
            )

        risk_level = "high" if any(a["severity"] == "high" for a in anomalies) else "medium" if anomalies else "low"

        return AgentResult(
            success=True,
            action="detect_refund_anomaly",
            data={
                "risk_level": risk_level,
                "transactions_checked": refund_count,
                "anomalies": anomalies,
                "cashier_id": cashier_id,
                "refund_count": refund_count,
                "total_refund_fen": total_refund_fen,
                "window_minutes": window_minutes,
                "threshold": threshold,
            },
            reasoning=f"收银员 {cashier_id} 退款 {refund_count} 次/"
            f"{window_minutes}min，{'异常' if is_anomaly else '正常'}",
            confidence=0.88,
        )

    # ─── 现金交易异常 ───

    async def _detect_cash_anomaly(self, params: dict) -> AgentResult:
        """检测现金交易异常 — 现金占比过高"""
        transactions = params.get("transactions", [])
        if not transactions:
            return AgentResult(
                success=False,
                action="detect_cash_anomaly",
                error="无交易数据",
                reasoning="现金异常检测需要提供交易列表",
                confidence=1.0,
            )

        cash_threshold = params.get("cash_ratio_threshold", DEFAULT_CASH_RATIO_THRESHOLD)

        total_count = len(transactions)
        cash_count = sum(1 for t in transactions if t.get("payment_method") == "cash")
        cash_ratio = cash_count / total_count if total_count > 0 else 0

        total_cash_fen = sum(t.get("amount_fen", 0) for t in transactions if t.get("payment_method") == "cash")

        anomalies: list[dict] = []
        if cash_ratio > cash_threshold:
            anomalies.append(
                {
                    "txn_id": "cash_ratio_alert",
                    "type": "high_cash_ratio",
                    "detail": f"现金交易占比 {cash_ratio:.1%} 超阈值 {cash_threshold:.1%}，"
                    f"现金总额 {total_cash_fen / 100:.2f} 元",
                    "severity": "medium",
                }
            )

        risk_level = "medium" if anomalies else "low"

        return AgentResult(
            success=True,
            action="detect_cash_anomaly",
            data={
                "risk_level": risk_level,
                "transactions_checked": total_count,
                "anomalies": anomalies,
                "cash_count": cash_count,
                "cash_ratio": round(cash_ratio, 4),
                "total_cash_fen": total_cash_fen,
            },
            reasoning=f"现金交易 {cash_count}/{total_count}（{cash_ratio:.1%}），{'异常' if anomalies else '正常'}",
            confidence=0.85,
        )
