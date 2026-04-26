"""SOP <-> IM双向桥接服务（Phase S2: IM全闭环）

职责：
1. 向IM推送SOP卡片（任务卡/教练卡/预警卡/纠正卡）
2. 解析IM回调（快捷操作/回复/照片上传）
3. 记录所有IM交互（审计日志）

设计原则：
- IM推送失败不阻塞主流程（catch具体异常，记录日志，标记失败）
- 所有交互必须记录到sop_im_interactions
- webhook URL从环境变量读取
- 通过httpx异步POST，3次重试，5秒超时
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import structlog
from services.tx_agent.src.models.im_interaction import (
    SOPIMInteraction,
    SOPQuickAction,
)
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 常量 ──

VALID_CHANNELS = {"wecom", "dingtalk", "feishu"}
VALID_DIRECTIONS = {"outbound", "inbound"}
VALID_MESSAGE_TYPES = {
    "task_card",
    "quick_reply",
    "photo_upload",
    "voice_cmd",
    "coaching_card",
    "alert_card",
}
VALID_ACTION_TYPES = {"confirm", "photo", "flag", "escalate", "data_entry"}

# 系统级tenant_id（种子数据）
SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"

# httpx 配置
HTTP_TIMEOUT = 5.0
HTTP_MAX_RETRIES = 3


class IMSOPBridgeService:
    """SOP <-> IM双向桥接

    支持企业微信、钉钉、飞书三个IM通道。
    所有推送和回调都记录到sop_im_interactions表。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ══════════════════════════════════════════════
    # 推送（Outbound）
    # ══════════════════════════════════════════════

    async def push_task_card(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        slot_name: str,
        tasks: list[dict],
        *,
        ai_insight: str | None = None,
        channel: str = "wecom",
    ) -> dict:
        """推送SOP任务卡到IM

        生成结构化任务卡片，包含任务列表和快捷操作按钮，
        通过指定IM通道推送给门店员工。

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            user_id: 接收人ID
            slot_name: 时段名称（如"午市高峰"）
            tasks: 任务列表 [{task_name, status, due_at, priority, ...}]
            ai_insight: Agent生成的智能洞察
            channel: IM通道（wecom/dingtalk/feishu）

        Returns:
            {ok, message_id, channel, card_type}
        """
        log = logger.bind(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            channel=channel,
        )

        # 1. 获取快捷操作
        quick_actions = await self._get_available_quick_actions(tenant_id)

        # 2. 构建卡片
        card_payload = self._build_task_card_payload(
            channel=channel,
            slot_name=slot_name,
            tasks=tasks,
            quick_actions=quick_actions,
            ai_insight=ai_insight,
        )

        # 3. 推送到IM
        send_ok = await self._send_to_channel_safe(
            channel=channel,
            message=card_payload,
            log=log,
        )

        # 4. 记录交互日志
        interaction_id = await self._log_interaction(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            direction="outbound",
            message_type="task_card",
            content={
                "card_type": "task_card",
                "slot_name": slot_name,
                "task_count": len(tasks),
                "tasks": tasks,
                "ai_insight": ai_insight,
                "quick_actions": quick_actions,
                "send_ok": send_ok,
            },
        )

        log.info(
            "task_card_pushed",
            interaction_id=interaction_id,
            task_count=len(tasks),
            send_ok=send_ok,
        )

        return {
            "ok": send_ok,
            "message_id": interaction_id,
            "channel": channel,
            "card_type": "task_card",
            "task_count": len(tasks),
        }

    async def push_alert_card(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        alert_type: str,
        anomalies: list[dict],
        *,
        analysis: str | None = None,
        channel: str = "wecom",
    ) -> dict:
        """推送异常预警卡到IM

        当SOP执行检测到异常（超时/违规/指标异常）时，
        向负责人推送预警卡片。

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            user_id: 接收人ID
            alert_type: 预警类型（overdue/violation/anomaly/threshold）
            anomalies: 异常列表 [{title, description, severity, ...}]
            analysis: AI分析结论
            channel: IM通道

        Returns:
            {ok, message_id, channel, card_type}
        """
        log = logger.bind(
            tenant_id=tenant_id,
            store_id=store_id,
            alert_type=alert_type,
        )

        card_payload = self._build_alert_card_payload(
            channel=channel,
            alert_type=alert_type,
            anomalies=anomalies,
            analysis=analysis,
        )

        send_ok = await self._send_to_channel_safe(
            channel=channel,
            message=card_payload,
            log=log,
        )

        interaction_id = await self._log_interaction(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            direction="outbound",
            message_type="alert_card",
            content={
                "card_type": "alert_card",
                "alert_type": alert_type,
                "anomaly_count": len(anomalies),
                "anomalies": anomalies,
                "analysis": analysis,
                "send_ok": send_ok,
            },
        )

        log.info(
            "alert_card_pushed",
            interaction_id=interaction_id,
            anomaly_count=len(anomalies),
            send_ok=send_ok,
        )

        return {
            "ok": send_ok,
            "message_id": interaction_id,
            "channel": channel,
            "card_type": "alert_card",
            "anomaly_count": len(anomalies),
        }

    async def push_coaching_card(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        coaching_type: str,
        content: dict,
        *,
        channel: str = "wecom",
    ) -> dict:
        """推送AI教练卡到IM

        推送智能教练内容，包含晨报摘要、时段复盘、日报总结等。

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            user_id: 接收人ID
            coaching_type: 教练类型（morning_brief/slot_review/daily_report/tip）
            content: 教练内容 {title, summary, metrics, suggestions, ...}
            channel: IM通道

        Returns:
            {ok, message_id, channel, card_type}
        """
        log = logger.bind(
            tenant_id=tenant_id,
            store_id=store_id,
            coaching_type=coaching_type,
        )

        card_payload = self._build_coaching_card_payload(
            channel=channel,
            coaching_type=coaching_type,
            content=content,
        )

        send_ok = await self._send_to_channel_safe(
            channel=channel,
            message=card_payload,
            log=log,
        )

        interaction_id = await self._log_interaction(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            direction="outbound",
            message_type="coaching_card",
            content={
                "card_type": "coaching_card",
                "coaching_type": coaching_type,
                "content": content,
                "send_ok": send_ok,
            },
        )

        log.info(
            "coaching_card_pushed",
            interaction_id=interaction_id,
            coaching_type=coaching_type,
            send_ok=send_ok,
        )

        return {
            "ok": send_ok,
            "message_id": interaction_id,
            "channel": channel,
            "card_type": "coaching_card",
            "coaching_type": coaching_type,
        }

    async def push_corrective_card(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        action: dict,
        *,
        channel: str = "wecom",
    ) -> dict:
        """推送纠正动作卡到IM

        当SOP任务不合规并创建纠正动作后，向责任人推送纠正卡片，
        包含问题描述、截止时间和快捷操作按钮。

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            user_id: 责任人ID
            action: 纠正动作详情 {id, title, description, severity, due_at, ...}
            channel: IM通道

        Returns:
            {ok, message_id, channel, card_type}
        """
        log = logger.bind(
            tenant_id=tenant_id,
            store_id=store_id,
            action_id=action.get("id"),
        )

        card_payload = self._build_corrective_card_payload(
            channel=channel,
            action=action,
        )

        send_ok = await self._send_to_channel_safe(
            channel=channel,
            message=card_payload,
            log=log,
        )

        interaction_id = await self._log_interaction(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            direction="outbound",
            message_type="task_card",
            content={
                "card_type": "corrective_card",
                "action": action,
                "send_ok": send_ok,
            },
            action_id=action.get("id"),
        )

        log.info(
            "corrective_card_pushed",
            interaction_id=interaction_id,
            severity=action.get("severity"),
            send_ok=send_ok,
        )

        return {
            "ok": send_ok,
            "message_id": interaction_id,
            "channel": channel,
            "card_type": "corrective_card",
            "action_id": action.get("id"),
        }

    # ══════════════════════════════════════════════
    # 回调处理（Inbound）
    # ══════════════════════════════════════════════

    async def handle_im_callback(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        callback_data: dict,
    ) -> dict:
        """处理IM回调（快捷操作按钮点击）

        解析回调数据中的action_code，查找快捷操作定义，
        执行对应操作并记录交互日志。

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            user_id: 操作人ID
            callback_data: 回调数据 {
                action_code: str,
                instance_id?: str,
                action_id?: str,
                reply_to?: str,
                note?: str,
                extra?: dict
            }

        Returns:
            {ok, action_code, action_name, result}
        """
        log = logger.bind(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
        )

        action_code = callback_data.get("action_code", "")
        instance_id = callback_data.get("instance_id")
        action_id = callback_data.get("action_id")
        reply_to = callback_data.get("reply_to")
        note = callback_data.get("note")

        # 1. 查找快捷操作定义
        quick_action = await self._find_quick_action(tenant_id, action_code)
        if not quick_action:
            log.warning("unknown_action_code", action_code=action_code)
            return {
                "ok": False,
                "action_code": action_code,
                "error": f"未知的操作代码: {action_code}",
            }

        # 2. 执行对应操作
        result = await self._execute_quick_action(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            quick_action=quick_action,
            instance_id=instance_id,
            action_id=action_id,
            note=note,
            extra=callback_data.get("extra", {}),
        )

        # 3. 记录inbound交互日志
        interaction_id = await self._log_interaction(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            direction="inbound",
            message_type="quick_reply",
            content={
                "action_code": action_code,
                "action_name": quick_action["action_name"],
                "action_type": quick_action["action_type"],
                "callback_data": callback_data,
                "result": result,
            },
            instance_id=instance_id,
            action_id=action_id,
            reply_to=reply_to,
        )

        log.info(
            "im_callback_handled",
            interaction_id=interaction_id,
            action_code=action_code,
            result_ok=result.get("ok", False),
        )

        return {
            "ok": result.get("ok", False),
            "action_code": action_code,
            "action_name": quick_action["action_name"],
            "result": result,
        }

    async def handle_photo_upload(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        instance_id: str,
        photo_url: str,
        *,
        note: str | None = None,
        channel: str = "wecom",
    ) -> dict:
        """处理IM照片上传（任务拍照确认）

        员工通过IM上传照片作为任务完成凭证。
        照片URL记录到交互日志，并关联到任务实例。

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            user_id: 上传人ID
            instance_id: 任务实例ID
            photo_url: 照片URL
            note: 备注说明
            channel: IM通道

        Returns:
            {ok, message_id, instance_id, photo_url}
        """
        log = logger.bind(
            tenant_id=tenant_id,
            store_id=store_id,
            instance_id=instance_id,
        )

        # 1. 记录照片上传交互
        interaction_id = await self._log_interaction(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            direction="inbound",
            message_type="photo_upload",
            content={
                "photo_url": photo_url,
                "note": note,
                "channel": channel,
            },
            instance_id=instance_id,
        )

        # 2. 更新任务实例的结果（追加照片记录）
        try:
            from sqlalchemy import text

            await self.db.execute(
                text("""
                    UPDATE sop_task_instances
                    SET result = COALESCE(result, '{}'::jsonb)
                        || jsonb_build_object(
                            'photos',
                            COALESCE(result->'photos', '[]'::jsonb)
                                || jsonb_build_array(
                                    jsonb_build_object(
                                        'url', :photo_url,
                                        'uploaded_by', :user_id,
                                        'uploaded_at', :now,
                                        'note', :note
                                    )
                                )
                        ),
                        updated_at = NOW()
                    WHERE id = :instance_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "photo_url": photo_url,
                    "user_id": user_id,
                    "now": datetime.now(timezone.utc).isoformat(),
                    "note": note or "",
                    "instance_id": instance_id,
                    "tenant_id": tenant_id,
                },
            )
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001 — 最外层兜底
            log.error("photo_update_task_failed", exc_info=True, error=str(exc))
            await self.db.rollback()

        log.info(
            "photo_uploaded",
            interaction_id=interaction_id,
            photo_url=photo_url,
        )

        return {
            "ok": True,
            "message_id": interaction_id,
            "instance_id": instance_id,
            "photo_url": photo_url,
        }

    # ══════════════════════════════════════════════
    # 查询
    # ══════════════════════════════════════════════

    async def list_interactions(
        self,
        tenant_id: str,
        store_id: str,
        *,
        user_id: str | None = None,
        direction: str | None = None,
        message_type: str | None = None,
        instance_id: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """列出IM交互记录（分页）

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            user_id: 筛选用户
            direction: 筛选方向（outbound/inbound）
            message_type: 筛选消息类型
            instance_id: 筛选关联任务实例
            page: 页码
            size: 每页条数

        Returns:
            {items: [...], total: int, page: int, size: int}
        """
        conditions = [
            SOPIMInteraction.tenant_id == UUID(tenant_id),
            SOPIMInteraction.store_id == UUID(store_id),
            SOPIMInteraction.is_deleted.is_(False),
        ]

        if user_id:
            conditions.append(SOPIMInteraction.user_id == UUID(user_id))
        if direction:
            conditions.append(SOPIMInteraction.direction == direction)
        if message_type:
            conditions.append(SOPIMInteraction.message_type == message_type)
        if instance_id:
            conditions.append(SOPIMInteraction.instance_id == UUID(instance_id))

        # 总数
        count_stmt = select(func.count()).select_from(SOPIMInteraction).where(and_(*conditions))
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        # 分页查询
        offset = (page - 1) * size
        query_stmt = (
            select(SOPIMInteraction)
            .where(and_(*conditions))
            .order_by(SOPIMInteraction.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        result = await self.db.execute(query_stmt)
        rows = result.scalars().all()

        items = [
            {
                "id": str(r.id),
                "tenant_id": str(r.tenant_id),
                "store_id": str(r.store_id),
                "user_id": str(r.user_id),
                "instance_id": str(r.instance_id) if r.instance_id else None,
                "action_id": str(r.action_id) if r.action_id else None,
                "channel": r.channel,
                "direction": r.direction,
                "message_type": r.message_type,
                "content": r.content,
                "reply_to": str(r.reply_to) if r.reply_to else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    async def list_quick_actions(
        self,
        tenant_id: str,
        *,
        include_system: bool = True,
    ) -> list[dict]:
        """列出所有快捷操作定义

        Args:
            tenant_id: 租户ID
            include_system: 是否包含系统级通用操作

        Returns:
            [{id, action_code, action_name, action_type, ...}, ...]
        """
        tenant_ids = [UUID(tenant_id)]
        if include_system:
            tenant_ids.append(UUID(SYSTEM_TENANT_ID))

        stmt = (
            select(SOPQuickAction)
            .where(
                and_(
                    SOPQuickAction.tenant_id.in_(tenant_ids),
                    SOPQuickAction.is_active.is_(True),
                    SOPQuickAction.is_deleted.is_(False),
                )
            )
            .order_by(SOPQuickAction.action_code)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "id": str(r.id),
                "tenant_id": str(r.tenant_id),
                "action_code": r.action_code,
                "action_name": r.action_name,
                "action_type": r.action_type,
                "target_service": r.target_service,
                "target_endpoint": r.target_endpoint,
                "payload_template": r.payload_template,
                "requires_photo": r.requires_photo,
                "requires_note": r.requires_note,
                "is_active": r.is_active,
            }
            for r in rows
        ]

    # ══════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════

    async def _send_to_channel(
        self,
        channel: str,
        webhook_url: str,
        message: dict,
    ) -> bool:
        """发送消息到IM通道（企微/钉钉/飞书webhook）

        通过httpx异步POST，3次重试，5秒超时。

        Args:
            channel: IM通道
            webhook_url: webhook URL
            message: 消息JSON

        Returns:
            是否发送成功

        Raises:
            httpx.HTTPStatusError: HTTP状态码异常
            httpx.TimeoutException: 请求超时
        """
        for attempt in range(1, HTTP_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    resp = await client.post(
                        webhook_url,
                        json=message,
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()

                    # 企微/钉钉/飞书的成功判断
                    body = resp.json()
                    errcode = body.get("errcode", body.get("code", 0))
                    if errcode == 0:
                        return True

                    logger.warning(
                        "im_channel_api_error",
                        channel=channel,
                        attempt=attempt,
                        errcode=errcode,
                        errmsg=body.get("errmsg", body.get("msg", "")),
                    )

            except httpx.TimeoutException:
                logger.warning(
                    "im_channel_timeout",
                    channel=channel,
                    attempt=attempt,
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "im_channel_http_error",
                    channel=channel,
                    attempt=attempt,
                    status=exc.response.status_code,
                )

        return False

    async def _send_to_channel_safe(
        self,
        channel: str,
        message: dict,
        log: structlog.BoundLogger,
    ) -> bool:
        """安全包装：获取channel配置并发送，失败不抛异常"""
        try:
            config = self._get_channel_config(channel)
            webhook_url = config.get("webhook_url")
            if not webhook_url:
                log.warning("im_channel_no_webhook", channel=channel)
                return False

            return await self._send_to_channel(
                channel=channel,
                webhook_url=webhook_url,
                message=message,
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.error(
                "im_send_failed",
                channel=channel,
                error=str(exc),
                exc_info=True,
            )
            return False

    async def _log_interaction(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        direction: str,
        message_type: str,
        content: dict,
        *,
        instance_id: str | None = None,
        action_id: str | None = None,
        reply_to: str | None = None,
    ) -> str:
        """记录IM交互日志

        Returns:
            交互记录ID
        """
        interaction = SOPIMInteraction(
            id=uuid4(),
            tenant_id=UUID(tenant_id),
            store_id=UUID(store_id),
            user_id=UUID(user_id),
            direction=direction,
            message_type=message_type,
            content=content,
            instance_id=UUID(instance_id) if instance_id else None,
            action_id=UUID(action_id) if action_id else None,
            reply_to=UUID(reply_to) if reply_to else None,
        )
        self.db.add(interaction)
        try:
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001 — 日志写入最外层兜底
            logger.error(
                "interaction_log_failed",
                error=str(exc),
                exc_info=True,
            )
            await self.db.rollback()
            # 日志写入失败不应阻塞主流程
        return str(interaction.id)

    def _get_channel_config(self, channel: str) -> dict:
        """从环境变量获取IM通道配置

        环境变量命名：
        - EXPENSE_WECOM_WEBHOOK_URL
        - EXPENSE_DINGTALK_WEBHOOK_URL
        - EXPENSE_FEISHU_WEBHOOK_URL

        Returns:
            {webhook_url: str, channel: str}
        """
        env_map = {
            "wecom": "EXPENSE_WECOM_WEBHOOK_URL",
            "dingtalk": "EXPENSE_DINGTALK_WEBHOOK_URL",
            "feishu": "EXPENSE_FEISHU_WEBHOOK_URL",
        }

        env_key = env_map.get(channel)
        if not env_key:
            raise ValueError(f"不支持的IM通道: {channel}")

        return {
            "webhook_url": os.environ.get(env_key, ""),
            "channel": channel,
        }

    async def _get_available_quick_actions(self, tenant_id: str) -> list[dict]:
        """获取可用的快捷操作列表（用于卡片按钮）"""
        actions = await self.list_quick_actions(tenant_id)
        return [
            {
                "action_code": a["action_code"],
                "action_name": a["action_name"],
                "action_type": a["action_type"],
                "requires_photo": a["requires_photo"],
                "requires_note": a["requires_note"],
            }
            for a in actions
        ]

    async def _find_quick_action(self, tenant_id: str, action_code: str) -> dict | None:
        """查找指定的快捷操作定义"""
        tenant_ids = [UUID(tenant_id), UUID(SYSTEM_TENANT_ID)]
        stmt = (
            select(SOPQuickAction)
            .where(
                and_(
                    SOPQuickAction.tenant_id.in_(tenant_ids),
                    SOPQuickAction.action_code == action_code,
                    SOPQuickAction.is_active.is_(True),
                    SOPQuickAction.is_deleted.is_(False),
                )
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        return {
            "id": str(row.id),
            "action_code": row.action_code,
            "action_name": row.action_name,
            "action_type": row.action_type,
            "target_service": row.target_service,
            "target_endpoint": row.target_endpoint,
            "payload_template": row.payload_template,
            "requires_photo": row.requires_photo,
            "requires_note": row.requires_note,
        }

    async def _execute_quick_action(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        quick_action: dict,
        instance_id: str | None,
        action_id: str | None,
        note: str | None,
        extra: dict,
    ) -> dict:
        """执行快捷操作

        根据action_type分发到不同的处理逻辑：
        - confirm: 完成任务（更新sop_task_instances状态）
        - photo:   等待照片上传（标记需要照片）
        - flag:    标记异常（创建纠正动作）
        - escalate: 呼叫支援（升级通知）
        - data_entry: 记录备注
        """
        action_type = quick_action["action_type"]

        if action_type == "confirm":
            return await self._action_confirm_task(tenant_id, store_id, user_id, instance_id)
        elif action_type == "photo":
            return await self._action_request_photo(instance_id)
        elif action_type == "flag":
            return await self._action_flag_issue(tenant_id, store_id, user_id, instance_id, note)
        elif action_type == "escalate":
            return await self._action_escalate(tenant_id, store_id, user_id, instance_id, action_id)
        elif action_type == "data_entry":
            return await self._action_data_entry(tenant_id, store_id, user_id, instance_id, note)
        else:
            return {"ok": False, "error": f"未知操作类型: {action_type}"}

    async def _action_confirm_task(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        instance_id: str | None,
    ) -> dict:
        """一键确认：将任务实例标记为已完成"""
        if not instance_id:
            return {"ok": False, "error": "缺少instance_id"}

        from sqlalchemy import text

        try:
            result = await self.db.execute(
                text("""
                    UPDATE sop_task_instances
                    SET status = 'completed',
                        completed_at = NOW(),
                        result = COALESCE(result, '{}'::jsonb)
                            || '{"confirmed_via": "im_quick_action"}'::jsonb,
                        updated_at = NOW()
                    WHERE id = :instance_id
                      AND tenant_id = :tenant_id
                      AND status IN ('pending', 'in_progress')
                    RETURNING id
                """),
                {"instance_id": instance_id, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            await self.db.commit()

            if row:
                return {"ok": True, "instance_id": instance_id, "new_status": "completed"}
            else:
                return {"ok": False, "error": "任务不存在或已完成"}
        except Exception as exc:  # noqa: BLE001
            logger.error("confirm_task_failed", exc_info=True, error=str(exc))
            await self.db.rollback()
            return {"ok": False, "error": str(exc)}

    async def _action_request_photo(self, instance_id: str | None) -> dict:
        """拍照确认：返回需要上传照片的指示"""
        return {
            "ok": True,
            "requires_photo": True,
            "instance_id": instance_id,
            "message": "请拍照上传确认",
        }

    async def _action_flag_issue(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        instance_id: str | None,
        note: str | None,
    ) -> dict:
        """标记异常：创建纠正动作"""
        if not instance_id:
            return {"ok": False, "error": "缺少instance_id"}

        from sqlalchemy import text

        try:
            result = await self.db.execute(
                text("""
                    INSERT INTO sop_corrective_actions
                        (tenant_id, store_id, source_instance_id,
                         action_type, severity, title, description,
                         assignee_id, due_at)
                    VALUES
                        (:tenant_id, :store_id, :instance_id,
                         'immediate', 'warning',
                         '员工标记异常',
                         :description,
                         :user_id,
                         NOW() + INTERVAL '2 hours')
                    RETURNING id
                """),
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "instance_id": instance_id,
                    "description": note or "通过IM快捷操作标记的异常",
                    "user_id": user_id,
                },
            )
            row = result.fetchone()
            await self.db.commit()

            corrective_id = str(row[0]) if row else None
            return {
                "ok": True,
                "corrective_action_id": corrective_id,
                "instance_id": instance_id,
                "message": "异常已标记，纠正动作已创建",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("flag_issue_failed", exc_info=True, error=str(exc))
            await self.db.rollback()
            return {"ok": False, "error": str(exc)}

    async def _action_escalate(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        instance_id: str | None,
        action_id: str | None,
    ) -> dict:
        """呼叫支援：升级通知"""
        # 如果有纠正动作ID，更新其升级状态
        if action_id:
            from sqlalchemy import text

            try:
                await self.db.execute(
                    text("""
                        UPDATE sop_corrective_actions
                        SET status = 'escalated',
                            escalated_to = :user_id,
                            escalated_at = NOW(),
                            updated_at = NOW()
                        WHERE id = :action_id
                          AND tenant_id = :tenant_id
                    """),
                    {
                        "action_id": action_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                    },
                )
                await self.db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.error("escalate_failed", exc_info=True, error=str(exc))
                await self.db.rollback()

        return {
            "ok": True,
            "instance_id": instance_id,
            "action_id": action_id,
            "message": "支援请求已发送",
        }

    async def _action_data_entry(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        instance_id: str | None,
        note: str | None,
    ) -> dict:
        """快速备注：记录到任务实例的result中"""
        if not instance_id or not note:
            return {"ok": True, "message": "备注已记录（无关联任务）"}

        from sqlalchemy import text

        try:
            await self.db.execute(
                text("""
                    UPDATE sop_task_instances
                    SET result = COALESCE(result, '{}'::jsonb)
                        || jsonb_build_object(
                            'notes',
                            COALESCE(result->'notes', '[]'::jsonb)
                                || jsonb_build_array(
                                    jsonb_build_object(
                                        'text', :note,
                                        'by', :user_id,
                                        'at', :now
                                    )
                                )
                        ),
                        updated_at = NOW()
                    WHERE id = :instance_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "note": note,
                    "user_id": user_id,
                    "now": datetime.now(timezone.utc).isoformat(),
                    "instance_id": instance_id,
                    "tenant_id": tenant_id,
                },
            )
            await self.db.commit()
            return {"ok": True, "message": "备注已保存", "instance_id": instance_id}
        except Exception as exc:  # noqa: BLE001
            logger.error("data_entry_failed", exc_info=True, error=str(exc))
            await self.db.rollback()
            return {"ok": False, "error": str(exc)}

    # ══════════════════════════════════════════════
    # 卡片构建
    # ══════════════════════════════════════════════

    def _build_task_card_payload(
        self,
        channel: str,
        slot_name: str,
        tasks: list[dict],
        quick_actions: list[dict],
        ai_insight: str | None,
    ) -> dict:
        """构建任务卡片JSON（适配不同IM平台格式）

        企微使用interactive card格式，
        钉钉使用actionCard格式，
        飞书使用interactive格式。
        """
        # 通用卡片数据
        card_data = {
            "card_type": "task_card",
            "title": f"📋 {slot_name} — SOP任务提醒",
            "tasks": [
                {
                    "name": t.get("task_name", ""),
                    "status": t.get("status", "pending"),
                    "priority": t.get("priority", "normal"),
                    "due_at": t.get("due_at", ""),
                }
                for t in tasks
            ],
            "quick_actions": [
                {
                    "code": a["action_code"],
                    "name": a["action_name"],
                    "type": a["action_type"],
                }
                for a in quick_actions
            ],
            "task_count": len(tasks),
            "pending_count": sum(1 for t in tasks if t.get("status") == "pending"),
        }
        if ai_insight:
            card_data["ai_insight"] = ai_insight

        if channel == "wecom":
            return self._wrap_wecom_card(card_data)
        elif channel == "dingtalk":
            return self._wrap_dingtalk_card(card_data)
        elif channel == "feishu":
            return self._wrap_feishu_card(card_data)
        else:
            return card_data

    def _build_alert_card_payload(
        self,
        channel: str,
        alert_type: str,
        anomalies: list[dict],
        analysis: str | None,
    ) -> dict:
        """构建预警卡片JSON"""
        severity_emoji = {
            "critical": "🔴",
            "warning": "🟡",
            "info": "🔵",
        }

        card_data = {
            "card_type": "alert_card",
            "title": f"⚠️ SOP异常预警 — {alert_type}",
            "alert_type": alert_type,
            "anomalies": [
                {
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "severity": a.get("severity", "warning"),
                    "emoji": severity_emoji.get(a.get("severity", "warning"), "🟡"),
                }
                for a in anomalies
            ],
            "anomaly_count": len(anomalies),
        }
        if analysis:
            card_data["analysis"] = analysis

        if channel == "wecom":
            return self._wrap_wecom_card(card_data)
        elif channel == "dingtalk":
            return self._wrap_dingtalk_card(card_data)
        elif channel == "feishu":
            return self._wrap_feishu_card(card_data)
        else:
            return card_data

    def _build_coaching_card_payload(
        self,
        channel: str,
        coaching_type: str,
        content: dict,
    ) -> dict:
        """构建教练卡片JSON"""
        type_labels = {
            "morning_brief": "🌅 晨报摘要",
            "slot_review": "📊 时段复盘",
            "daily_report": "📈 日报总结",
            "tip": "💡 经营提示",
        }

        card_data = {
            "card_type": "coaching_card",
            "title": type_labels.get(coaching_type, f"🤖 AI教练 — {coaching_type}"),
            "coaching_type": coaching_type,
            "content": content,
        }

        if channel == "wecom":
            return self._wrap_wecom_card(card_data)
        elif channel == "dingtalk":
            return self._wrap_dingtalk_card(card_data)
        elif channel == "feishu":
            return self._wrap_feishu_card(card_data)
        else:
            return card_data

    def _build_corrective_card_payload(
        self,
        channel: str,
        action: dict,
    ) -> dict:
        """构建纠正动作卡片JSON"""
        severity_emoji = {
            "critical": "🔴 紧急",
            "warning": "🟡 警告",
            "info": "🔵 提示",
        }

        card_data = {
            "card_type": "corrective_card",
            "title": f"🔧 纠正动作 — {action.get('title', '')}",
            "severity": action.get("severity", "warning"),
            "severity_label": severity_emoji.get(action.get("severity", "warning"), "🟡 警告"),
            "description": action.get("description", ""),
            "due_at": action.get("due_at", ""),
            "action_id": action.get("id"),
            "quick_actions": [
                {"code": "confirm_task", "name": "已处理"},
                {"code": "flag_issue", "name": "标记异常"},
                {"code": "call_support", "name": "呼叫支援"},
            ],
        }

        if channel == "wecom":
            return self._wrap_wecom_card(card_data)
        elif channel == "dingtalk":
            return self._wrap_dingtalk_card(card_data)
        elif channel == "feishu":
            return self._wrap_feishu_card(card_data)
        else:
            return card_data

    # ── IM平台消息格式适配 ──

    def _wrap_wecom_card(self, card_data: dict) -> dict:
        """适配企业微信webhook消息格式"""
        # 构建markdown文本
        lines = [f"### {card_data.get('title', '')}"]

        if card_data.get("ai_insight"):
            lines.append(f"> 💡 {card_data['ai_insight']}")

        if card_data.get("analysis"):
            lines.append(f"> 🔍 {card_data['analysis']}")

        if card_data.get("tasks"):
            lines.append("")
            for t in card_data["tasks"]:
                status_icon = "✅" if t["status"] == "completed" else "⏳"
                lines.append(f"{status_icon} **{t['name']}** — {t.get('due_at', '')}")

        if card_data.get("anomalies"):
            lines.append("")
            for a in card_data["anomalies"]:
                lines.append(f"{a.get('emoji', '🟡')} **{a['title']}**: {a['description']}")

        if card_data.get("content"):
            content = card_data["content"]
            if isinstance(content, dict):
                if content.get("summary"):
                    lines.append(f"\n{content['summary']}")
                if content.get("suggestions"):
                    lines.append("")
                    for s in content["suggestions"]:
                        lines.append(f"- {s}")

        if card_data.get("quick_actions"):
            lines.append("")
            action_names = [a["name"] for a in card_data["quick_actions"]]
            lines.append(f"快捷操作: {' | '.join(action_names)}")

        return {
            "msgtype": "markdown",
            "markdown": {
                "content": "\n".join(lines),
            },
            "_card_data": card_data,
        }

    def _wrap_dingtalk_card(self, card_data: dict) -> dict:
        """适配钉钉webhook消息格式（actionCard）"""
        lines = [f"### {card_data.get('title', '')}"]

        if card_data.get("ai_insight"):
            lines.append(f"> 💡 {card_data['ai_insight']}")

        if card_data.get("tasks"):
            lines.append("")
            for t in card_data["tasks"]:
                status_icon = "✅" if t["status"] == "completed" else "⏳"
                lines.append(f"{status_icon} **{t['name']}**")

        if card_data.get("anomalies"):
            for a in card_data["anomalies"]:
                lines.append(f"{a.get('emoji', '🟡')} {a['title']}")

        btns = []
        if card_data.get("quick_actions"):
            for a in card_data["quick_actions"][:3]:
                btns.append(
                    {
                        "title": a["name"],
                        "actionURL": f"txos://action/{a['code']}",
                    }
                )

        return {
            "msgtype": "actionCard",
            "actionCard": {
                "title": card_data.get("title", ""),
                "text": "\n".join(lines),
                "btns": btns,
                "btnOrientation": "1",
            },
            "_card_data": card_data,
        }

    def _wrap_feishu_card(self, card_data: dict) -> dict:
        """适配飞书webhook消息格式（interactive）"""
        elements = []

        # 标题后的描述
        if card_data.get("ai_insight"):
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"💡 {card_data['ai_insight']}",
                    },
                }
            )

        if card_data.get("tasks"):
            for t in card_data["tasks"]:
                status_icon = "✅" if t["status"] == "completed" else "⏳"
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"{status_icon} **{t['name']}** — {t.get('due_at', '')}",
                        },
                    }
                )

        if card_data.get("anomalies"):
            for a in card_data["anomalies"]:
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"{a.get('emoji', '🟡')} **{a['title']}**: {a['description']}",
                        },
                    }
                )

        actions = []
        if card_data.get("quick_actions"):
            for a in card_data["quick_actions"][:4]:
                actions.append(
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": a["name"]},
                        "value": {"action_code": a["code"]},
                        "type": "primary" if a.get("type") == "confirm" else "default",
                    }
                )

        if actions:
            elements.append({"tag": "action", "actions": actions})

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": card_data.get("title", ""),
                    },
                },
                "elements": elements,
            },
            "_card_data": card_data,
        }
