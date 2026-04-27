"""IM通知服务（企微/钉钉）

Agent Level 2/3 自动执行时，通过IM渠道通知相关人员。
当前实现：企微机器人Webhook（最简方案）
后续扩展：企微应用消息/钉钉/短信

使用方式：
    svc = IMNotificationService()
    msg = await svc.notify_shift_fill_request(...)
    await svc.send_wecom_bot(webhook_url, msg)
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog

log = structlog.get_logger(__name__)


class IMNotificationService:
    """IM消息推送服务

    当前支持企微群机器人Webhook推送。
    所有通知模板返回Markdown格式字符串。
    """

    async def send_wecom_bot(
        self,
        webhook_url: str,
        message: str,
        mentioned_list: Optional[list[str]] = None,
    ) -> bool:
        """发送企微群机器人消息

        Args:
            webhook_url: 企微机器人Webhook地址
            message: Markdown格式消息内容
            mentioned_list: 需要@的成员userid列表
        """
        content = message
        if mentioned_list:
            at_str = "".join(f"<@{uid}>" for uid in mentioned_list)
            content += f"\n{at_str}"

        payload: dict[str, Any] = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(webhook_url, json=payload, timeout=10)
                ok = resp.status_code == 200
                log.info(
                    "wecom_bot_sent",
                    status=resp.status_code,
                    success=ok,
                )
                return ok
            except httpx.TimeoutException as exc:
                log.error("wecom_bot_timeout", error=str(exc))
                return False
            except httpx.HTTPError as exc:
                log.error("wecom_bot_failed", error=str(exc))
                return False

    # ── 通知模板 ─────────────────────────────────────────────────────

    async def notify_shift_fill_request(
        self,
        employee_name: str,
        store_name: str,
        date_str: str,
        time_slot: str,
        position: str,
    ) -> str:
        """补位请求通知模板

        Agent Level 2 自动发送，员工30分钟内确认
        """
        return (
            f"### 补位请求\n"
            f"**门店**：{store_name}\n"
            f"**日期**：{date_str}\n"
            f"**时段**：{time_slot}\n"
            f"**岗位**：{position}\n\n"
            f"您被推荐为补位候选人，请在30分钟内确认是否可以到岗。\n"
            f'> 回复"接受"确认补位'
        )

    async def notify_compliance_alert(
        self,
        employee_name: str,
        alert_type: str,
        detail: str,
        due_date: str,
    ) -> str:
        """合规预警通知模板

        Agent Level 1 建议通知，HR确认后发送
        """
        severity = "CRITICAL" if alert_type == "expired" else "WARNING"
        return (
            f"### [{severity}] 合规预警\n"
            f"**员工**：{employee_name}\n"
            f"**类型**：{detail}\n"
            f"**到期日**：{due_date}\n\n"
            f"请尽快处理，逾期将影响排班资格。"
        )

    async def notify_turnover_risk(
        self,
        employee_name: str,
        risk_score: float,
        reasons: list[str],
        store_name: str,
    ) -> str:
        """离职风险预警通知

        Agent Level 1 建议通知，HR确认后发送
        """
        reasons_text = "\n".join(f"- {r}" for r in reasons)
        return (
            f"### 离职风险预警\n"
            f"**员工**：{employee_name}\n"
            f"**门店**：{store_name}\n"
            f"**风险评分**：{risk_score:.0f}/100\n"
            f"**风险信号**：\n{reasons_text}\n\n"
            f"建议尽快安排一对一沟通。"
        )

    async def notify_schedule_generated(
        self,
        store_name: str,
        week_start: str,
        savings_yuan: float,
    ) -> str:
        """排班方案生成通知

        Agent Level 2 自动执行后通知，30分钟回滚窗口
        """
        return (
            f"### 智能排班方案已生成\n"
            f"**门店**：{store_name}\n"
            f"**排班周期**：{week_start} 起\n"
            f"**预计节约**：{savings_yuan:.0f}元\n\n"
            f"排班方案已生成为草稿，请在30分钟内确认或回滚。\n"
            f"> 登录后台查看详情"
        )

    async def notify_contribution_update(
        self,
        employee_name: str,
        total_score: float,
        rank: int,
        total_employees: int,
        trend: str,
    ) -> str:
        """贡献度更新通知（员工端推送）

        Agent Level 3 完全自主执行，仅推送结果
        """
        trend_text = "上升" if trend == "up" else ("下降" if trend == "down" else "持平")
        grade = (
            "卓越"
            if total_score >= 90
            else ("优秀" if total_score >= 80 else ("良好" if total_score >= 60 else "加油"))
        )
        return (
            f"### 本周贡献度报告\n"
            f"**{employee_name}** 您好！\n"
            f"**综合得分**：{total_score:.1f}分（{grade}）\n"
            f"**门店排名**：第{rank}名/共{total_employees}人\n"
            f"**趋势**：{trend_text}\n\n"
            f"> 打开员工端查看详细分析"
        )
