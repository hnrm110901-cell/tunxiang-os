"""OperationPlanNotifier — 高风险操作计划通知服务

创建 OperationPlan 后，通过以下渠道通知操作者需要确认：
1. 企业微信 Webhook（主渠道）
2. 系统内部消息（备用，写入 Redis 供前端 WebSocket 推送）
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import structlog

from .operation_planner import OperationPlan, RiskLevel

logger = structlog.get_logger()

# 企微 Webhook URL（从环境变量读取，按门店/品牌分组）
WECOM_WEBHOOK_URL = os.getenv("WECOM_OPS_WEBHOOK_URL", "")
WECOM_TIMEOUT_SECONDS = 5


class OperationPlanNotifier:
    """操作计划通知器"""

    @staticmethod
    async def notify(plan: OperationPlan) -> None:
        """发送操作计划通知（非阻塞，失败不抛异常）"""
        tasks = [
            OperationPlanNotifier._notify_wecom(plan),
            OperationPlanNotifier._notify_redis_pubsub(plan),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "plan_notification_failed",
                    channel=["wecom", "redis"][i],
                    plan_id=plan.plan_id,
                    error=str(result),
                )

    @staticmethod
    async def _notify_wecom(plan: OperationPlan) -> None:
        """发送企微 Webhook 消息"""
        if not WECOM_WEBHOOK_URL:
            logger.debug("wecom_webhook_not_configured", plan_id=plan.plan_id)
            return

        # 风险等级 → 颜色
        color_map = {
            RiskLevel.LOW: "info",
            RiskLevel.MEDIUM: "warning",
            RiskLevel.HIGH: "warning",
            RiskLevel.CRITICAL: "comment",
        }
        color = color_map.get(plan.impact.risk_level, "info")

        # 财务影响格式化
        impact_yuan = plan.impact.financial_impact_fen / 100 if plan.impact.financial_impact_fen else 0
        impact_text = f"¥{impact_yuan:,.0f}" if impact_yuan > 0 else "待评估"

        # 企微卡片消息（markdown 格式）
        message = {
            "msgtype": "markdown",
            "markdown": {
                "content": (
                    f"## ⚠️ 高风险操作待确认\n\n"
                    f"> **操作类型**：{plan.operation_type}\n"
                    f'> **风险等级**：<font color="{color}">{plan.impact.risk_level.upper()}</font>\n'
                    f"> **影响范围**：{plan.impact.impact_summary}\n"
                    f"> **财务影响**：{impact_text}\n"
                    f"> **注意事项**：{'；'.join(plan.impact.warnings) if plan.impact.warnings else '无'}\n\n"
                    f"**请在30分钟内确认或取消：**\n"
                    f"计划ID：`{plan.plan_id[:8]}...`\n\n"
                    f"请前往管理后台 → 待处理操作 → 确认执行"
                )
            },
        }

        async with httpx.AsyncClient(timeout=WECOM_TIMEOUT_SECONDS) as client:
            resp = await client.post(WECOM_WEBHOOK_URL, json=message)
            resp.raise_for_status()
            logger.info("wecom_notification_sent", plan_id=plan.plan_id, status=resp.status_code)

    @staticmethod
    async def _notify_redis_pubsub(plan: OperationPlan) -> None:
        """写入 Redis，供前端 WebSocket 轮询"""
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        try:
            import redis.asyncio as aioredis

            redis = await aioredis.from_url(redis_url, decode_responses=True, socket_timeout=3)

            notification = {
                "type": "operation_plan_created",
                "plan_id": plan.plan_id,
                "operation_type": plan.operation_type,
                "risk_level": plan.impact.risk_level,
                "operator_id": plan.operator_id,
                "tenant_id": plan.tenant_id,
                "expires_at": plan.expires_at.isoformat() if plan.expires_at else None,
                "impact_summary": plan.impact.impact_summary,
            }

            # 写入 operator 专属列表（前端轮询用）
            key = f"pending_plans:{plan.tenant_id}:{plan.operator_id}"
            await redis.lpush(key, json.dumps(notification, ensure_ascii=False))
            await redis.expire(key, 1800)  # 30分钟过期

            # 也发布到 Pub/Sub（WebSocket 订阅用）
            channel = f"ops_notifications:{plan.tenant_id}"
            await redis.publish(channel, json.dumps(notification, ensure_ascii=False))

            await redis.aclose()
            logger.info("redis_notification_sent", plan_id=plan.plan_id)

        except (OSError, RuntimeError) as exc:
            logger.warning("redis_notification_failed", plan_id=plan.plan_id, error=str(exc))
