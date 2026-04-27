"""多渠道统一发送调度器

协调 SMS / WeChat / WeCom 三大渠道的发送节奏：
  - 频次限制: 每位客户每天最多收到N条营销消息(可配置)
  - 时段优化: 不同渠道在不同时段的打开率不同，自动选最佳时段
  - 去重: 同一客户同一Campaign不会在多个渠道收到重复内容
  - 优先级: 高优先级消息(流失召回/生日关怀)可突破部分限制

集成点：
  - channel_engine (tx-growth) — 实际消息发送
  - notification_tasks 表 — 异步任务队列
  - 营销冷却规则 — 参考ai_marketing_orchestrator的MARKETING_COOLDOWN_RULES
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 渠道配置
# ---------------------------------------------------------------------------

CHANNEL_CONFIG: dict[str, dict[str, Any]] = {
    "sms": {
        "daily_limit_per_customer": 2,
        "best_hours": (10, 12, 17, 19),  # 10-12点, 17-19点
        "cost_fen_per_msg": 5,  # 约0.05元/条
        "priority_order": 3,  # 成本最高，优先级最低
    },
    "wechat_subscribe": {
        "daily_limit_per_customer": 3,
        "best_hours": (8, 10, 12, 14, 18, 21),
        "cost_fen_per_msg": 0,
        "priority_order": 1,  # 免费+高打开率，优先
    },
    "wecom_chat": {
        "daily_limit_per_customer": 5,
        "best_hours": (9, 12, 14, 18, 20),
        "cost_fen_per_msg": 0,
        "priority_order": 2,  # 免费但触达率略低
    },
}

# 高优先级场景可突破频次限制(+N条)
HIGH_PRIORITY_EXTRA_ALLOWANCE = 2

# 全局营销冷却(小时): 同一客户两次营销消息的最小间隔
GLOBAL_COOLDOWN_HOURS = 4


class UnifiedSendScheduler:
    """多渠道统一发送调度器"""

    async def schedule_send(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        campaign_id: uuid.UUID,
        db: Any,
        *,
        channels: list[str],
        content_by_channel: dict[str, dict[str, Any]],
        priority: str = "normal",  # normal / high / critical
        preferred_send_at: Optional[datetime] = None,
    ) -> dict:
        """为单个客户调度多渠道发送

        流程：
        1. 检查每个渠道的频次限制
        2. 去重：该客户该Campaign已发送的渠道跳过
        3. 选择最优渠道+时段
        4. 写入notification_tasks异步执行
        """
        available_channels: list[dict[str, Any]] = []
        skipped_channels: list[dict[str, str]] = []

        for ch in channels:
            if ch not in CHANNEL_CONFIG:
                skipped_channels.append({"channel": ch, "reason": "未知渠道"})
                continue

            # 检查去重
            is_dup = await self._check_dedup(db, tenant_id, customer_id, campaign_id, ch)
            if is_dup:
                skipped_channels.append({"channel": ch, "reason": "已发送"})
                continue

            # 检查频次限制
            can_send = await self._check_frequency_limit(db, tenant_id, customer_id, ch, priority)
            if not can_send:
                skipped_channels.append({"channel": ch, "reason": "频次已达上限"})
                continue

            # 检查冷却期
            in_cooldown = await self._check_cooldown(db, tenant_id, customer_id)
            if in_cooldown and priority == "normal":
                skipped_channels.append({"channel": ch, "reason": "冷却期内"})
                continue

            config = CHANNEL_CONFIG[ch]
            send_time = self._optimize_send_time(ch, preferred_send_at)

            available_channels.append(
                {
                    "channel": ch,
                    "send_at": send_time,
                    "cost_fen": config["cost_fen_per_msg"],
                    "priority_order": config["priority_order"],
                }
            )

        if not available_channels:
            log.info(
                "send_all_channels_skipped",
                customer_id=str(customer_id),
                campaign_id=str(campaign_id),
                skipped=skipped_channels,
            )
            return {
                "scheduled": [],
                "skipped": skipped_channels,
                "total_cost_fen": 0,
            }

        # 按优先级排序，选择最优渠道(仅发1条，避免骚扰)
        available_channels.sort(key=lambda c: c["priority_order"])
        selected = available_channels[0]

        # 写入notification_tasks
        task_id = uuid.uuid4()
        ch_name = selected["channel"]
        content = content_by_channel.get(ch_name, {})

        await db.execute(
            text("""
                INSERT INTO notification_tasks (
                    id, tenant_id, customer_id, campaign_id,
                    channel, content, scheduled_at, priority, status
                ) VALUES (
                    :id, :tenant_id, :customer_id, :campaign_id,
                    :channel, :content::jsonb, :scheduled_at, :priority, 'pending'
                )
            """),
            {
                "id": str(task_id),
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
                "campaign_id": str(campaign_id),
                "channel": ch_name,
                "content": json.dumps(content),
                "scheduled_at": selected["send_at"],
                "priority": priority,
            },
        )

        log.info(
            "send_scheduled",
            task_id=str(task_id),
            customer_id=str(customer_id),
            channel=ch_name,
            send_at=str(selected["send_at"]),
        )

        return {
            "scheduled": [
                {
                    "task_id": str(task_id),
                    "channel": ch_name,
                    "send_at": selected["send_at"].isoformat() if selected["send_at"] else None,
                    "cost_fen": selected["cost_fen"],
                }
            ],
            "skipped": skipped_channels,
            "total_cost_fen": selected["cost_fen"],
        }

    async def schedule_batch(
        self,
        tenant_id: uuid.UUID,
        customer_ids: list[uuid.UUID],
        campaign_id: uuid.UUID,
        db: Any,
        *,
        channels: list[str],
        content_by_channel: dict[str, dict[str, Any]],
        priority: str = "normal",
    ) -> dict:
        """批量调度：为一组客户调度发送"""
        total_scheduled = 0
        total_skipped = 0
        total_cost_fen = 0

        for cid in customer_ids:
            result = await self.schedule_send(
                tenant_id,
                cid,
                campaign_id,
                db,
                channels=channels,
                content_by_channel=content_by_channel,
                priority=priority,
            )
            total_scheduled += len(result["scheduled"])
            total_skipped += len(result["skipped"])
            total_cost_fen += result["total_cost_fen"]

        log.info(
            "batch_send_scheduled",
            campaign_id=str(campaign_id),
            total_customers=len(customer_ids),
            scheduled=total_scheduled,
            skipped=total_skipped,
            cost_fen=total_cost_fen,
        )

        return {
            "total_customers": len(customer_ids),
            "scheduled": total_scheduled,
            "skipped": total_skipped,
            "total_cost_fen": total_cost_fen,
        }

    # ===================================================================
    # 私有方法
    # ===================================================================

    async def _check_dedup(
        self,
        db: Any,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        campaign_id: uuid.UUID,
        channel: str,
    ) -> bool:
        """检查该客户该Campaign该渠道是否已发送"""
        result = await db.execute(
            text("""
                SELECT 1 FROM notification_tasks
                WHERE tenant_id = :tenant_id
                  AND customer_id = :customer_id
                  AND campaign_id = :campaign_id
                  AND channel = :channel
                  AND status != 'failed'
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
                "campaign_id": str(campaign_id),
                "channel": channel,
            },
        )
        return result.first() is not None

    async def _check_frequency_limit(
        self,
        db: Any,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        channel: str,
        priority: str,
    ) -> bool:
        """检查渠道每日频次限制"""
        config = CHANNEL_CONFIG.get(channel, {})
        daily_limit = config.get("daily_limit_per_customer", 3)
        if priority in ("high", "critical"):
            daily_limit += HIGH_PRIORITY_EXTRA_ALLOWANCE

        result = await db.execute(
            text("""
                SELECT COUNT(*) FROM notification_tasks
                WHERE tenant_id = :tenant_id
                  AND customer_id = :customer_id
                  AND channel = :channel
                  AND scheduled_at::date = CURRENT_DATE
                  AND status != 'failed'
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
                "channel": channel,
            },
        )
        count = result.scalar() or 0
        return count < daily_limit

    async def _check_cooldown(
        self,
        db: Any,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
    ) -> bool:
        """检查全局营销冷却期"""
        result = await db.execute(
            text(
                """
                SELECT 1 FROM notification_tasks
                WHERE tenant_id = :tenant_id
                  AND customer_id = :customer_id
                  AND scheduled_at > NOW() - INTERVAL ':hours hours'
                  AND status NOT IN ('failed', 'cancelled')
                  AND is_deleted = FALSE
                LIMIT 1
            """.replace(":hours", str(GLOBAL_COOLDOWN_HOURS))
            ),
            {
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
            },
        )
        return result.first() is not None

    @staticmethod
    def _optimize_send_time(
        channel: str,
        preferred: Optional[datetime] = None,
    ) -> datetime:
        """选择最优发送时间

        如果preferred在渠道最佳时段内，直接使用；
        否则推迟到下一个最佳时段。
        """
        now = datetime.now(timezone.utc)
        if preferred and preferred > now:
            return preferred

        config = CHANNEL_CONFIG.get(channel, {})
        best_hours = config.get("best_hours", (10, 18))

        current_hour = now.hour
        # 找到下一个最佳小时
        for h in sorted(best_hours):
            if h > current_hour:
                return now.replace(hour=h, minute=0, second=0, microsecond=0)

        # 今天已过最佳时段，推到明天第一个最佳时段
        tomorrow = now.replace(hour=sorted(best_hours)[0], minute=0, second=0, microsecond=0)
        from datetime import timedelta

        return tomorrow + timedelta(days=1)
