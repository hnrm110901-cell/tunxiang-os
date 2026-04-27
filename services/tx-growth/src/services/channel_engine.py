"""渠道触达引擎 — 统一渠道配置、发送能力和合规频控

统一管理企微、短信、小程序、App Push 等渠道的消息发送，
强制频率限制防止用户骚扰，记录发送日志用于归因。

v144 DB 化：移除内存存储，改为 async SQLAlchemy
  - channel_configs 表存储渠道配置（替换 _channel_configs dict）
  - message_send_logs 表存储发送日志（替换 _send_logs + _daily_send_counts）
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

_logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# ChannelEngine
# ---------------------------------------------------------------------------


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

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ------------------------------------------------------------------
    # 渠道配置
    # ------------------------------------------------------------------

    async def get_channel_config(
        self,
        channel_name: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """查询渠道配置，SELECT from channel_configs

        若 DB 中无配置则返回内置默认值。
        """
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)

        result = await db.execute(
            text("""
                SELECT id, channel, max_daily_per_user, settings, is_enabled,
                       created_at, updated_at
                FROM channel_configs
                WHERE tenant_id = :tid AND channel = :channel AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tid, "channel": channel_name},
        )
        row = result.fetchone()

        channel_defaults = self.CHANNELS.get(channel_name, {})

        if not row:
            return {
                "channel": channel_name,
                "channel_name": channel_defaults.get("name", channel_name),
                "max_daily_per_user": channel_defaults.get("max_daily", 3),
                "settings": {},
                "is_enabled": True,
                "source": "default",
            }

        return {
            "channel": row.channel,
            "channel_name": channel_defaults.get("name", row.channel),
            "max_daily_per_user": row.max_daily_per_user,
            "settings": row.settings if isinstance(row.settings, dict) else {},
            "is_enabled": row.is_enabled,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "source": "db",
        }

    async def update_channel_config(
        self,
        channel_name: str,
        updates: dict,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """更新渠道配置，UPSERT into channel_configs

        Args:
            channel_name: 渠道名称
            updates: 更新内容，支持 max_daily_per_user / settings / is_enabled
            tenant_id: 租户ID
            db: 数据库会话
        """
        if channel_name not in self.CHANNELS:
            return {"error": f"不支持的渠道: {channel_name}"}

        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        now = datetime.now(timezone.utc)

        channel_defaults = self.CHANNELS[channel_name]
        max_daily = updates.get("max_daily_per_user", channel_defaults.get("max_daily", 3))
        settings = updates.get("settings", {})
        is_enabled = updates.get("is_enabled", True)

        await db.execute(
            text("""
                INSERT INTO channel_configs
                    (id, tenant_id, channel, max_daily_per_user, settings, is_enabled, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :tid, :channel, :max_daily, :settings::jsonb, :is_enabled, :now, :now)
                ON CONFLICT ON CONSTRAINT uq_channel_configs_tenant_channel DO UPDATE
                SET max_daily_per_user = EXCLUDED.max_daily_per_user,
                    settings = EXCLUDED.settings,
                    is_enabled = EXCLUDED.is_enabled,
                    updated_at = EXCLUDED.updated_at
            """),
            {
                "tid": tid,
                "channel": channel_name,
                "max_daily": max_daily,
                "settings": json.dumps(settings),
                "is_enabled": is_enabled,
                "now": now,
            },
        )
        await db.commit()

        _logger.info(
            "channel_engine.update_channel_config",
            channel=channel_name,
            max_daily=max_daily,
            tenant_id=tenant_id,
        )
        return {
            "channel": channel_name,
            "channel_name": channel_defaults.get("name", channel_name),
            "max_daily_per_user": max_daily,
            "settings": settings,
            "is_enabled": is_enabled,
            "updated_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # 消息发送
    # ------------------------------------------------------------------

    async def send_message(
        self,
        channel: str,
        recipient_id: str,
        content: str,
        message_type: str = "notification",
        *,
        tenant_id: str,
        db: AsyncSession,
        offer_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> dict:
        """模拟发送消息，记录到 message_send_logs

        核心逻辑：
        1. 从 channel_configs 查询该渠道今日频率配置
        2. 检查今日已发送次数（频率控制）
        3. 未超限则 INSERT into message_send_logs（模拟发送）

        Args:
            channel: 渠道名称
            recipient_id: 外部 user_id（企微 external_userid 或手机号）
            content: 消息内容
            message_type: 消息类型（notification/promotion/transactional）
            tenant_id: 租户ID
            db: 数据库会话
            offer_id: 关联优惠 ID（可选）
            campaign_id: 关联活动 ID（可选）
            customer_id: 内部 customer UUID（可选）
        """
        if channel not in self.CHANNELS:
            return {"success": False, "error": f"不支持的渠道: {channel}"}

        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)

        # 查询渠道频率配置（DB 优先，fallback 使用内置默认）
        max_daily = self.CHANNELS[channel]["max_daily"]
        try:
            cfg_result = await db.execute(
                text("""
                    SELECT max_daily_per_user, is_enabled FROM channel_configs
                    WHERE tenant_id = :tid AND channel = :channel AND is_deleted = false
                    LIMIT 1
                """),
                {"tid": tid, "channel": channel},
            )
            cfg = cfg_result.fetchone()
            if cfg:
                max_daily = cfg.max_daily_per_user
                if not cfg.is_enabled:
                    return {
                        "success": False,
                        "error": f"渠道 {channel} 已禁用",
                        "channel": channel,
                        "status": "blocked",
                    }
        except SQLAlchemyError:
            pass  # 表不存在时使用默认值

        # 频率检查：查今日已发送数
        today = datetime.now(timezone.utc).date()
        sent_today = 0
        try:
            count_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM message_send_logs
                    WHERE tenant_id = :tid
                      AND channel = :channel
                      AND external_user_id = :uid
                      AND sent_at::date = :today
                      AND status = 'sent'
                      AND is_deleted = false
                """),
                {"tid": tid, "channel": channel, "uid": recipient_id, "today": today},
            )
            sent_today = count_result.scalar() or 0
        except SQLAlchemyError:
            sent_today = 0

        if sent_today >= max_daily:
            return {
                "success": False,
                "error": f"频率限制：今日已发送 {sent_today} 次，上限 {max_daily} 次",
                "channel": channel,
                "status": "blocked",
                "sent_today": int(sent_today),
                "daily_limit": max_daily,
            }

        # 解析可选 UUID 参数
        customer_uuid: Optional[uuid.UUID] = None
        if customer_id:
            try:
                customer_uuid = uuid.UUID(customer_id)
            except ValueError:
                pass

        offer_uuid: Optional[uuid.UUID] = None
        if offer_id:
            try:
                offer_uuid = uuid.UUID(offer_id)
            except ValueError:
                pass

        campaign_uuid: Optional[uuid.UUID] = None
        if campaign_id:
            try:
                campaign_uuid = uuid.UUID(campaign_id)
            except ValueError:
                pass

        now = datetime.now(timezone.utc)
        log_id = uuid.uuid4()

        await db.execute(
            text("""
                INSERT INTO message_send_logs
                    (id, tenant_id, channel, customer_id, external_user_id,
                     content_summary, offer_id, campaign_id, status, sent_at, created_at)
                VALUES
                    (:id, :tid, :channel, :customer_id, :uid,
                     :content, :offer_id, :campaign_id, 'sent', :now, :now)
            """),
            {
                "id": log_id,
                "tid": tid,
                "channel": channel,
                "customer_id": customer_uuid,
                "uid": recipient_id,
                "content": content[:200],
                "offer_id": offer_uuid,
                "campaign_id": campaign_uuid,
                "now": now,
            },
        )
        await db.commit()

        _logger.info(
            "channel_engine.send_message",
            log_id=str(log_id),
            channel=channel,
            recipient_id=recipient_id,
            message_type=message_type,
            tenant_id=tenant_id,
        )
        return {
            "success": True,
            "log_id": str(log_id),
            "channel": channel,
            "status": "sent",
            "sent_at": now.isoformat(),
            "sent_today_after": int(sent_today) + 1,
            "daily_limit": max_daily,
        }

    # ------------------------------------------------------------------
    # 统计查询
    # ------------------------------------------------------------------

    async def get_send_stats(
        self,
        channel: Optional[str] = None,
        days: int = 7,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """聚合统计消息发送效果，SELECT from message_send_logs

        Args:
            channel: 按渠道过滤（None 表示全渠道）
            days: 统计最近 N 天（默认7天）
            tenant_id: 租户ID
            db: 数据库会话
        """
        await self._set_tenant(db, tenant_id)
        tid = uuid.UUID(tenant_id)
        today = datetime.now(timezone.utc).date()

        where_parts = [
            "tenant_id = :tid",
            "sent_at::date > (CURRENT_DATE - :days)",
            "is_deleted = false",
        ]
        params: dict = {"tid": tid, "days": days}

        if channel:
            if channel not in self.CHANNELS:
                return {"error": f"不支持的渠道: {channel}"}
            where_parts.append("channel = :channel")
            params["channel"] = channel

        where_clause = " AND ".join(where_parts)

        try:
            result = await db.execute(
                text(f"""
                    SELECT
                        channel,
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'sent')    AS sent_count,
                        COUNT(*) FILTER (WHERE status = 'failed')  AS failed_count,
                        COUNT(*) FILTER (WHERE status = 'blocked') AS blocked_count,
                        COUNT(DISTINCT external_user_id)           AS unique_users
                    FROM message_send_logs
                    WHERE {where_clause}
                    GROUP BY channel
                    ORDER BY total DESC
                """),
                params,
            )
            rows = result.fetchall()
        except SQLAlchemyError as exc:
            _logger.warning("channel_engine.get_send_stats_db_error", error=str(exc))
            return {
                "channel": channel,
                "days": days,
                "stats": [],
                "_note": "DB_ERROR",
            }

        channel_stats = [
            {
                "channel": r.channel,
                "channel_name": self.CHANNELS.get(r.channel, {}).get("name", r.channel),
                "total": int(r.total),
                "sent_count": int(r.sent_count),
                "failed_count": int(r.failed_count),
                "blocked_count": int(r.blocked_count),
                "unique_users": int(r.unique_users),
                "daily_avg": round(int(r.total) / max(1, days), 1),
            }
            for r in rows
        ]

        return {
            "channel": channel,
            "days": days,
            "period_start": str(today),
            "stats": channel_stats,
            "total_sent": sum(s["sent_count"] for s in channel_stats),
        }

    # ------------------------------------------------------------------
    # 企微专用发送（保留原有外部服务调用逻辑）
    # ------------------------------------------------------------------

    async def send_wecom_message(
        self,
        user_id: str,
        content: dict,
        tenant_id: UUID,
        offer_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """通过 gateway 内部 API 向企微用户发送个性化消息

        通过 POST /internal/wecom/send 调用 gateway 服务，
        gateway 再调用 WecomSDK 完成实际发送。

        Args:
            user_id:   企微 external_userid
            content:   {"title", "description", "url"(可选), "btntxt"(可选)}
            tenant_id: 租户 UUID（用于 X-Tenant-ID header）
            offer_id:  关联优惠 ID（可选，用于发送日志）
            db:        数据库会话（可选；传入则记录发送日志）
        """
        log = _logger.bind(channel="wecom", user_id=user_id, tenant_id=str(tenant_id))

        # 若有 db，先做频控检查
        if db:
            tid_str = str(tenant_id)
            freq_result = await self.send_message(
                channel="wecom",
                recipient_id=user_id,
                content=f"{content.get('title', '')} | {content.get('description', '')}",
                message_type="notification",
                tenant_id=tid_str,
                db=db,
                offer_id=offer_id,
            )
            if not freq_result.get("success"):
                log.warning("wecom_send_frequency_limited", reason=freq_result.get("error"))
                return {
                    "channel": "wecom",
                    "status": "blocked",
                    "reason": freq_result.get("error"),
                }

        # 判断消息类型
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
            log.warning("wecom_send_gateway_http_error", status_code=exc.response.status_code)
            return {"channel": "wecom", "status": "failed", "error": f"http_{exc.response.status_code}"}
        except httpx.RequestError as exc:
            log.warning("wecom_send_gateway_request_error", error=str(exc))
            return {"channel": "wecom", "status": "failed", "error": str(exc)}

        log.info("wecom_send_success", message_type=message_type)
        return {"channel": "wecom", "status": "sent"}

    # ------------------------------------------------------------------
    # 纯计算（不读写 DB，保留原有业务逻辑）
    # ------------------------------------------------------------------

    def check_frequency_limit_sync(
        self,
        sent_today: int,
        channel: str,
        max_daily_override: Optional[int] = None,
    ) -> dict:
        """同步频率限制检查（纯计算，已从 DB 取出 sent_today）

        Args:
            sent_today: 今日已发送次数（从 DB 查出）
            channel: 渠道名称
            max_daily_override: DB 中配置的日上限（None 则使用内置默认）
        """
        if channel not in self.CHANNELS:
            return {"allowed": False, "reason": f"不支持的渠道: {channel}", "current_count": 0, "max_daily": 0}

        max_daily = max_daily_override if max_daily_override is not None else self.CHANNELS[channel]["max_daily"]
        allowed = sent_today < max_daily
        reason = "" if allowed else f"今日已发送 {sent_today} 次，上限 {max_daily} 次"

        return {
            "allowed": allowed,
            "reason": reason,
            "current_count": sent_today,
            "max_daily": max_daily,
            "channel": channel,
            "channel_name": self.CHANNELS[channel]["name"],
        }

    # ------------------------------------------------------------------
    # 企微深度协同（Sprint C）
    # ------------------------------------------------------------------

    async def send_wecom_group_message(
        self,
        group_chat_id: str,
        content: str,
        content_type: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """企微群发消息 -- 发送到企微客户群"""
        _logger.info("wecom_group_send", group_chat_id=group_chat_id, tenant_id=tenant_id)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/internal/wecom/group-send",
                    json={
                        "chat_id": group_chat_id,
                        "content": content,
                        "msg_type": content_type,
                    },
                    headers={"X-Tenant-ID": tenant_id},
                    timeout=10.0,
                )
                result = resp.json()
                # 记录发送日志
                await db.execute(
                    text("""
                    INSERT INTO message_send_logs
                        (tenant_id, channel, external_user_id, content_summary, status, sent_at)
                    VALUES (:tid, 'wecom_group', :gid, :content, :status, NOW())
                """),
                    {
                        "tid": tenant_id,
                        "gid": group_chat_id,
                        "content": content[:200],
                        "status": "sent" if result.get("ok") else "failed",
                    },
                )
                return result
        except (httpx.HTTPError, OSError) as exc:
            _logger.error("wecom_group_send_error", error=str(exc), exc_info=True)
            return {"ok": False, "error": str(exc)}

    async def create_store_manager_task(
        self,
        store_id: str,
        customer_id: str,
        task_type: str,
        task_title: str,
        task_description: str,
        due_hours: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """创建门店店长待办任务 -- 用于服务修复/高价值客户跟进"""
        _logger.info("create_store_task", store_id=store_id, task_type=task_type, tenant_id=tenant_id)
        result = await db.execute(
            text("""
            INSERT INTO message_send_logs
                (tenant_id, channel, external_user_id, content_summary, status, sent_at)
            VALUES (:tid, 'store_task', :store_id, :summary, 'pending', NOW())
            RETURNING id
        """),
            {
                "tid": tenant_id,
                "store_id": store_id,
                "summary": f"[{task_type}] {task_title}: {task_description[:100]}",
            },
        )
        row = result.fetchone()
        task_id = str(row[0]) if row else None

        # 同时通过企微通知店长
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.GATEWAY_URL}/internal/wecom/send",
                    json={
                        "store_id": store_id,
                        "role": "store_manager",
                        "content": f"新待办: {task_title}\n{task_description}\n请在{due_hours}小时内处理",
                    },
                    headers={"X-Tenant-ID": tenant_id},
                    timeout=10.0,
                )
        except (httpx.HTTPError, OSError) as exc:
            _logger.warning("store_task_notify_failed", error=str(exc))

        return {"ok": True, "task_id": task_id}

    async def send_department_targeted(
        self,
        department_id: str,
        content: str,
        target_role: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """企微部门定向消息 -- 按部门+角色发送"""
        _logger.info("wecom_dept_send", department_id=department_id, role=target_role, tenant_id=tenant_id)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/internal/wecom/department-send",
                    json={
                        "department_id": department_id,
                        "target_role": target_role,
                        "content": content,
                    },
                    headers={"X-Tenant-ID": tenant_id},
                    timeout=10.0,
                )
                return resp.json()
        except (httpx.HTTPError, OSError) as exc:
            _logger.error("wecom_dept_send_error", error=str(exc), exc_info=True)
            return {"ok": False, "error": str(exc)}
