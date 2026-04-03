"""渠道触达引擎 — 统一渠道配置、发送能力和合规频控

统一管理企微、短信、小程序、App Push 等渠道的消息发送，
强制频率限制防止用户骚扰，记录发送日志用于归因。
"""
import os
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
import structlog

# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_channel_configs: dict[str, dict] = {}
_send_logs: list[dict] = []
_daily_send_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
# _daily_send_counts[user_id][channel] = count_today


# ---------------------------------------------------------------------------
# ChannelEngine
# ---------------------------------------------------------------------------

_logger = structlog.get_logger(__name__)


class ChannelEngine:
    """渠道触达引擎 — 统一渠道配置、发送能力和合规频控"""

    GATEWAY_URL: str = os.getenv("GATEWAY_SERVICE_URL", "http://gateway:8000")

    CHANNELS = {
        "wecom": {"name": "企业微信", "max_daily": 3},
        "sms": {"name": "短信", "max_daily": 2},
        "miniapp": {"name": "小程序订阅消息", "max_daily": 5},
        "app_push": {"name": "App Push", "max_daily": 3},
        "pos_receipt": {"name": "POS小票二维码", "max_daily": 999},
        "reservation_page": {"name": "预订确认页", "max_daily": 1},
        "store_task": {"name": "门店人工任务", "max_daily": 1},
    }

    async def send_wecom_message(
        self,
        user_id: str,
        content: dict,
        tenant_id: UUID,
        offer_id: Optional[str] = None,
    ) -> dict:
        """通过 gateway 内部 API 向企微用户发送个性化消息

        通过 POST /internal/wecom/send 调用 gateway 服务，
        gateway 再调用 WecomSDK 完成实际发送。

        Args:
            user_id:   企微 external_userid
            content:   {"title", "description", "url"(可选), "btntxt"(可选)}
            tenant_id: 租户 UUID（用于 X-Tenant-ID header）
            offer_id:  关联优惠 ID（可选，用于发送日志）

        Returns:
            {"channel": "wecom", "status": "sent"|"placeholder", ...}
        """
        log = _logger.bind(channel="wecom", user_id=user_id, tenant_id=str(tenant_id))

        # 频控检查（用 user_id 作为频控 key）
        freq_check = self.check_frequency_limit(user_id, "wecom")
        if not freq_check["allowed"]:
            log.warning("wecom_send_frequency_limited", reason=freq_check["reason"])
            return {
                "channel": "wecom",
                "status": "blocked",
                "reason": freq_check["reason"],
            }

        # 判断消息类型：有 url 则发 text_card，否则发 text
        message_type = "text_card" if content.get("url") else "text"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/internal/wecom/send",
                    headers={"X-Tenant-ID": str(tenant_id)},
                    json={
                        "user_id": user_id,
                        "message_type": message_type,
                        "title": content.get("title", ""),
                        "description": content.get("description", ""),
                        "url": content.get("url", ""),
                        "btntxt": content.get("btntxt", "查看详情"),
                    },
                )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.warning(
                "wecom_send_gateway_http_error",
                status_code=exc.response.status_code,
            )
            return {"channel": "wecom", "status": "failed", "error": f"http_{exc.response.status_code}"}
        except httpx.RequestError as exc:
            log.warning("wecom_send_gateway_request_error", error=str(exc))
            return {"channel": "wecom", "status": "failed", "error": str(exc)}

        # 更新频控计数 + 发送日志
        message_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        today = date.today().isoformat()

        log_entry = {
            "message_id": message_id,
            "channel": "wecom",
            "user_id": user_id,
            "content": f"{content.get('title', '')} | {content.get('description', '')}",
            "offer_id": offer_id,
            "status": "sent",
            "sent_at": now,
            "date": today,
        }
        _send_logs.append(log_entry)
        _daily_send_counts[user_id]["wecom"] += 1

        log.info("wecom_send_success", message_id=message_id, message_type=message_type)
        return {"channel": "wecom", "status": "sent", "message_id": message_id}

    def send_message(
        self,
        channel: str,
        user_id: str,
        content: str,
        offer_id: Optional[str] = None,
    ) -> dict:
        """发送消息

        Args:
            channel: 渠道名称
            user_id: 用户ID
            content: 消息内容
            offer_id: 关联优惠ID（可选）

        Returns:
            发送结果
        """
        if channel not in self.CHANNELS:
            return {"success": False, "error": f"不支持的渠道: {channel}"}

        # 频控检查
        freq_check = self.check_frequency_limit(user_id, channel)
        if not freq_check["allowed"]:
            return {
                "success": False,
                "error": f"频率限制：{freq_check['reason']}",
                "channel": channel,
                "user_id": user_id,
            }

        # 模拟发送
        message_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        today = date.today().isoformat()

        log_entry = {
            "message_id": message_id,
            "channel": channel,
            "user_id": user_id,
            "content": content[:200],  # 截断存储
            "offer_id": offer_id,
            "status": "sent",
            "sent_at": now,
            "date": today,
        }
        _send_logs.append(log_entry)

        # 更新每日计数
        _daily_send_counts[user_id][channel] += 1

        return {
            "success": True,
            "message_id": message_id,
            "channel": channel,
            "user_id": user_id,
            "sent_at": now,
        }

    def check_frequency_limit(self, user_id: str, channel: str) -> dict:
        """检查频率限制

        Returns:
            {"allowed": bool, "reason": str, "current_count": int, "max_daily": int}
        """
        if channel not in self.CHANNELS:
            return {"allowed": False, "reason": f"不支持的渠道: {channel}", "current_count": 0, "max_daily": 0}

        max_daily = self.CHANNELS[channel]["max_daily"]
        current_count = _daily_send_counts.get(user_id, {}).get(channel, 0)

        allowed = current_count < max_daily
        reason = "" if allowed else f"今日已发送 {current_count} 次，上限 {max_daily} 次"

        return {
            "allowed": allowed,
            "reason": reason,
            "current_count": current_count,
            "max_daily": max_daily,
            "channel": channel,
            "channel_name": self.CHANNELS[channel]["name"],
        }

    def get_channel_stats(self, channel: str, date_range: dict) -> dict:
        """获取渠道统计

        Args:
            channel: 渠道名称
            date_range: {"start": "2026-03-01", "end": "2026-03-26"}
        """
        if channel not in self.CHANNELS:
            return {"error": f"不支持的渠道: {channel}"}

        start = date_range.get("start", "")
        end = date_range.get("end", "")

        channel_logs = [
            log for log in _send_logs
            if log["channel"] == channel
            and (not start or log.get("date", "") >= start)
            and (not end or log.get("date", "") <= end)
        ]

        total_sent = len(channel_logs)
        unique_users = len(set(log["user_id"] for log in channel_logs))
        with_offer = sum(1 for log in channel_logs if log.get("offer_id"))

        return {
            "channel": channel,
            "channel_name": self.CHANNELS[channel]["name"],
            "date_range": date_range,
            "total_sent": total_sent,
            "unique_users": unique_users,
            "with_offer_count": with_offer,
            "avg_per_user": round(total_sent / max(1, unique_users), 2),
        }

    def configure_channel(self, channel: str, settings: dict) -> dict:
        """配置渠道参数

        Args:
            channel: 渠道名称
            settings: 配置项
                {"max_daily": 5, "enabled": True, "template_id": "..."}
        """
        if channel not in self.CHANNELS:
            return {"error": f"不支持的渠道: {channel}"}

        config = _channel_configs.get(channel, {})
        config.update(settings)
        config["channel"] = channel
        config["updated_at"] = datetime.now(timezone.utc).isoformat()

        # 更新全局频率限制
        if "max_daily" in settings:
            self.CHANNELS[channel]["max_daily"] = settings["max_daily"]

        _channel_configs[channel] = config
        return config

    def get_send_log(
        self,
        user_id: Optional[str] = None,
        channel: Optional[str] = None,
        date_range: Optional[dict] = None,
    ) -> list[dict]:
        """查询发送日志

        Args:
            user_id: 按用户过滤（可选）
            channel: 按渠道过滤（可选）
            date_range: 按日期过滤（可选）
        """
        logs = _send_logs.copy()

        if user_id:
            logs = [l for l in logs if l["user_id"] == user_id]
        if channel:
            logs = [l for l in logs if l["channel"] == channel]
        if date_range:
            start = date_range.get("start", "")
            end = date_range.get("end", "")
            if start:
                logs = [l for l in logs if l.get("date", "") >= start]
            if end:
                logs = [l for l in logs if l.get("date", "") <= end]

        return logs


def reset_daily_counts() -> None:
    """重置每日发送计数（辅助函数，用于测试）"""
    _daily_send_counts.clear()


def clear_all_channel_data() -> None:
    """清空所有渠道数据（仅测试用）"""
    _channel_configs.clear()
    _send_logs.clear()
    _daily_send_counts.clear()
