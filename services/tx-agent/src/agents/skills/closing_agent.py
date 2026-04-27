"""闭店Agent — 闭店预检、未结单提醒、日结数据校验、闭店检查单驱动

职责：
- 闭店前自动预检（未结单/未闭班/现金差异/待开票）
- 检查单状态追踪与催促
- 日结数据校验（营收=支付合计、订单数=各渠道合计）
- 异常数据自动上报（给区域经理）
- 闭店完成后自动触发日结流程(E5-E6)

事件驱动：
- SCHEDULE.CLOSING_TIME_APPROACHING → 闭店前30分钟触发预检
- CHECKLIST.SUBMITTED → 检查单提交后校验
- SETTLEMENT.DAILY_CLOSED → 日结完成后数据核验
"""

from typing import Any

import structlog

from ..base import ActionConfig, AgentResult, SkillAgent

logger = structlog.get_logger()


class ClosingAgent(SkillAgent):
    agent_id = "closing_ops"
    agent_name = "闭店守护"
    description = "闭店预检、未结单提醒、日结数据校验、检查单驱动、异常上报"
    priority = "P1"
    run_location = "edge"
    agent_level = 2  # 自动发提醒 + 可撤回

    # Sprint D1 / PR G 批次 1：闭店流程触碰食安（当日剩余食材处理）+ 毛利（日结金额）
    # 不涉及出餐时长，experience 维度留空
    constraint_scope = {"margin", "safety"}

    def get_supported_actions(self) -> list[str]:
        return [
            "pre_closing_check",
            "validate_daily_settlement",
            "remind_unsettled_orders",
            "check_checklist_status",
            "generate_closing_report",
            "escalate_anomaly",
        ]

    def get_action_config(self, action: str) -> ActionConfig:
        """闭店 Agent 的 action 级会话策略"""
        configs = {
            # 日结校验失败需要人工确认是否强制闭店
            "validate_daily_settlement": ActionConfig(
                requires_human_confirm=True,
                max_retries=1,
                risk_level="high",
            ),
            # 异常上报需要人工确认上报内容
            "escalate_anomaly": ActionConfig(
                requires_human_confirm=True,
                max_retries=0,
                risk_level="critical",
            ),
            # 预检可自动重试（网络抖动等）
            "pre_closing_check": ActionConfig(
                max_retries=2,
                risk_level="medium",
            ),
            # 生成报告可重试
            "generate_closing_report": ActionConfig(
                max_retries=1,
                risk_level="low",
            ),
        }
        return configs.get(action, ActionConfig())

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "pre_closing_check": self._pre_closing_check,
            "validate_daily_settlement": self._validate_settlement,
            "remind_unsettled_orders": self._remind_unsettled,
            "check_checklist_status": self._check_checklist,
            "generate_closing_report": self._generate_report,
            "escalate_anomaly": self._escalate_anomaly,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported action: {action}")
        return await handler(params)

    async def _pre_closing_check(self, params: dict) -> AgentResult:
        """闭店前综合预检"""
        unsettled_count = params.get("unsettled_order_count", 0)
        pending_invoices = params.get("pending_invoice_count", 0)
        shift_closed = params.get("shift_closed", False)
        cash_variance_fen = params.get("cash_variance_fen", 0)
        checklist_completed = params.get("checklist_completed", False)
        occupied_tables = params.get("occupied_table_count", 0)

        blockers = []
        warnings = []

        # 阻断项（必须处理才能闭店）
        if unsettled_count > 0:
            blockers.append(
                {
                    "type": "unsettled_orders",
                    "message": f"有 {unsettled_count} 笔未结单",
                    "action": "settle_or_void",
                }
            )
        if occupied_tables > 0:
            blockers.append(
                {
                    "type": "occupied_tables",
                    "message": f"有 {occupied_tables} 张桌台仍在使用",
                    "action": "wait_or_force_close",
                }
            )
        if not shift_closed:
            blockers.append(
                {
                    "type": "shift_not_closed",
                    "message": "当班尚未交接",
                    "action": "close_shift",
                }
            )

        # 警告项（可以闭店但需关注）
        if pending_invoices > 0:
            warnings.append(f"{pending_invoices} 张待开发票")
        if abs(cash_variance_fen) >= 500:  # ≥5元差异
            warnings.append(f"现金差异 ¥{cash_variance_fen / 100:.2f}")
        if not checklist_completed:
            warnings.append("闭店检查单未完成")

        can_close = len(blockers) == 0
        status = "ready" if can_close and not warnings else "blocked" if not can_close else "warning"

        return AgentResult(
            success=True,
            action="pre_closing_check",
            data={
                "can_close": can_close,
                "status": status,
                "blockers": blockers,
                "warnings": warnings,
                "summary": {
                    "unsettled_orders": unsettled_count,
                    "occupied_tables": occupied_tables,
                    "pending_invoices": pending_invoices,
                    "shift_closed": shift_closed,
                    "cash_variance_fen": cash_variance_fen,
                    "checklist_completed": checklist_completed,
                },
            },
            reasoning=f"闭店预检: {'可以闭店' if can_close else f'{len(blockers)}项阻断'}，{len(warnings)}项警告",
            confidence=0.95,
            inference_layer="edge",
        )

    async def _validate_settlement(self, params: dict) -> AgentResult:
        """日结数据校验"""
        total_revenue_fen = params.get("total_revenue_fen", 0)
        payment_sum_fen = params.get("payment_sum_fen", 0)
        order_count = params.get("order_count", 0)
        channel_order_sum = params.get("channel_order_sum", 0)
        refund_total_fen = params.get("refund_total_fen", 0)

        discrepancies = []

        # 校验1: 营收 = 支付合计
        revenue_diff = abs(total_revenue_fen - payment_sum_fen + refund_total_fen)
        if revenue_diff > 100:  # 允许1元误差
            discrepancies.append(
                {
                    "type": "revenue_payment_mismatch",
                    "detail": f"营收¥{total_revenue_fen / 100:.2f} ≠ 支付¥{payment_sum_fen / 100:.2f} - 退款¥{refund_total_fen / 100:.2f}，差异¥{revenue_diff / 100:.2f}",
                    "severity": "high" if revenue_diff > 10000 else "medium",
                }
            )

        # 校验2: 订单数 = 各渠道合计
        if channel_order_sum > 0 and order_count != channel_order_sum:
            discrepancies.append(
                {
                    "type": "order_count_mismatch",
                    "detail": f"订单总数{order_count} ≠ 渠道合计{channel_order_sum}",
                    "severity": "medium",
                }
            )

        passed = len(discrepancies) == 0

        return AgentResult(
            success=True,
            action="validate_daily_settlement",
            data={
                "passed": passed,
                "discrepancies": discrepancies,
                "total_revenue_fen": total_revenue_fen,
                "payment_sum_fen": payment_sum_fen,
                "order_count": order_count,
            },
            reasoning=f"日结校验{'通过' if passed else f'不通过({len(discrepancies)}项差异)'}",
            confidence=0.95,
            inference_layer="edge",
        )

    async def _remind_unsettled(self, params: dict) -> AgentResult:
        """未结单提醒"""
        unsettled = params.get("unsettled_orders", [])

        if not unsettled:
            return AgentResult(
                success=True,
                action="remind_unsettled_orders",
                data={"count": 0, "message": "无未结单"},
                reasoning="所有订单已结算",
                confidence=1.0,
                inference_layer="edge",
            )

        total_fen = sum(o.get("total_fen", 0) for o in unsettled)

        return AgentResult(
            success=True,
            action="remind_unsettled_orders",
            data={
                "count": len(unsettled),
                "total_fen": total_fen,
                "orders": unsettled[:10],
                "notification": {
                    "type": "push",
                    "target": "store_manager",
                    "message": f"闭店提醒: {len(unsettled)}笔未结单（合计¥{total_fen / 100:.2f}），请尽快处理",
                },
            },
            reasoning=f"发送未结单提醒: {len(unsettled)}笔，合计¥{total_fen / 100:.2f}",
            confidence=0.95,
            inference_layer="edge",
        )

    async def _check_checklist(self, params: dict) -> AgentResult:
        """检查单状态追踪"""
        checklist_type = params.get("type", "closing")
        total_items = params.get("total_items", 0)
        checked_items = params.get("checked_items", 0)
        failed_items = params.get("failed_items", 0)

        progress = (checked_items / max(total_items, 1)) * 100

        return AgentResult(
            success=True,
            action="check_checklist_status",
            data={
                "type": checklist_type,
                "progress": progress,
                "total": total_items,
                "checked": checked_items,
                "failed": failed_items,
                "completed": progress >= 100,
            },
            reasoning=f"{checklist_type}检查单进度: {progress:.0f}% ({checked_items}/{total_items})"
            f"{'，异常' + str(failed_items) + '项' if failed_items else ''}",
            confidence=0.95,
            inference_layer="edge",
        )

    async def _generate_report(self, params: dict) -> AgentResult:
        """生成闭店报告"""
        store_name = params.get("store_name", "")
        date = params.get("date", "")
        revenue_fen = params.get("revenue_fen", 0)
        order_count = params.get("order_count", 0)
        guest_count = params.get("guest_count", 0)
        anomaly_count = params.get("anomaly_count", 0)
        checklist_pass_rate = params.get("checklist_pass_rate", 1.0)

        # 云端生成摘要
        ai_summary = None
        if self._router:
            try:
                resp = await self._router.complete(
                    prompt=f"请为{store_name} {date}生成一句闭店总结（30字以内）。"
                    f"营收¥{revenue_fen / 100:.0f}，{order_count}单，{guest_count}客，"
                    f"异常{anomaly_count}项，检查通过率{checklist_pass_rate:.0%}。",
                    max_tokens=60,
                )
                if resp:
                    ai_summary = resp.strip()
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                pass

        return AgentResult(
            success=True,
            action="generate_closing_report",
            data={
                "store_name": store_name,
                "date": date,
                "revenue_fen": revenue_fen,
                "order_count": order_count,
                "guest_count": guest_count,
                "anomaly_count": anomaly_count,
                "checklist_pass_rate": checklist_pass_rate,
                "ai_summary": ai_summary or f"{store_name} {date}营收¥{revenue_fen / 100:.0f}，{order_count}单",
            },
            reasoning="闭店报告已生成",
            confidence=0.9,
            inference_layer="edge+cloud" if ai_summary else "edge",
        )

    async def _escalate_anomaly(self, params: dict) -> AgentResult:
        """异常上报区域经理"""
        anomaly_type = params.get("anomaly_type", "")
        detail = params.get("detail", "")
        store_name = params.get("store_name", "")

        logger.warning("closing_anomaly_escalated", store=store_name, type=anomaly_type, detail=detail)

        return AgentResult(
            success=True,
            action="escalate_anomaly",
            data={
                "escalated": True,
                "target": "regional_manager",
                "anomaly_type": anomaly_type,
                "notification": {
                    "type": "push",
                    "message": f"[{store_name}] 闭店异常: {detail}",
                },
            },
            reasoning=f"闭店异常已上报区域经理: {anomaly_type}",
            confidence=1.0,
            inference_layer="edge",
        )
