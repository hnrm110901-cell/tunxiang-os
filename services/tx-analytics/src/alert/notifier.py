"""预警通知 — 多渠道推送

支持渠道：
  - in_app: 应用内通知（写入 notification 表）
  - wechat: 企业微信消息
  - sms:    短信通知（P0 告警）
  - email:  邮件通知
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Alert, AlertSeverity

log = structlog.get_logger(__name__)


class AlertNotifier:
    """预警通知器

    根据告警的 notify_channels 配置，将告警推送到指定渠道。
    支持按角色（notify_roles）筛选接收人。
    """

    async def notify(self, db: AsyncSession, alert: Alert,
                     channels: list[str] | None = None,
                     recipients: list[str] | None = None) -> dict[str, bool]:
        """发送通知到指定渠道

        Returns:
            {"in_app": True, "wechat": False, ...} — 每个渠道的发送结果
        """
        channels = channels or ["in_app"]
        results: dict[str, bool] = {}

        for channel in channels:
            try:
                if channel == "in_app":
                    results[channel] = await self._notify_in_app(db, alert, recipients)
                elif channel == "wechat":
                    results[channel] = await self._notify_wechat(alert, recipients)
                elif channel == "sms":
                    results[channel] = await self._notify_sms(alert, recipients)
                elif channel == "email":
                    results[channel] = await self._notify_email(alert, recipients)
                else:
                    log.warning("alert_notify_unknown_channel", channel=channel)
                    results[channel] = False
            except (OperationalError, SQLAlchemyError) as exc:
                log.error("alert_notify_failed", channel=channel, alert_id=alert.alert_id, error=str(exc), exc_info=True)
                results[channel] = False

        return results

    async def _notify_in_app(self, db: AsyncSession, alert: Alert, recipients: list[str] | None) -> bool:
        """应用内通知 — 为每个接收人写入 notifications 表

        前端通过轮询或 WebSocket 拉取未读通知。
        """
        try:
            title = f"[{alert.severity.label_cn}] {alert.title}"
            body = alert.description or alert.title
            recips = recipients if recipients else [""]

            for user_id in recips:
                await db.execute(
                    text("""
                        INSERT INTO notifications (tenant_id, user_id, store_id, title, body,
                            alert_id, severity, category, is_read, created_at)
                        VALUES (:tenant_id, :user_id, :store_id, :title, :body,
                            :alert_id, :severity, 'alert', FALSE, NOW())
                    """),
                    {
                        "tenant_id": alert.tenant_id,
                        "user_id": user_id,
                        "store_id": alert.store_id,
                        "title": title,
                        "body": body,
                        "alert_id": alert.alert_id,
                        "severity": alert.severity.value,
                    },
                )
            await db.commit()
            return True
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("alert_notify_in_app_failed", alert_id=alert.alert_id, error=str(exc))
            await db.rollback()
            return False

    async def _notify_wechat(self, alert: Alert, recipients: list[str] | None) -> bool:
        """企业微信通知 — 通过企业微信 API 发送卡片消息

        Phase 1: 打印日志，后续接入企业微信 Webhook。
        """
        log.info("alert_notify_wechat",
            alert_id=alert.alert_id,
            severity=alert.severity.value,
            title=alert.title,
            recipients=recipients or [],
        )
        return True

    async def _notify_sms(self, alert: Alert, recipients: list[str] | None) -> bool:
        """短信通知 — P0 告警时通过短信平台发送

        Phase 1: 打印日志，后续接入短信网关。
        """
        if alert.severity != AlertSeverity.P0_CRITICAL:
            log.debug("alert_notify_sms_skipped_non_p0", alert_id=alert.alert_id)
            return False

        log.info("alert_notify_sms",
            alert_id=alert.alert_id,
            severity=alert.severity.value,
            title=alert.title,
            recipients=recipients or [],
        )
        return True

    async def _notify_email(self, alert: Alert, recipients: list[str] | None) -> bool:
        """邮件通知 — 通过 SMTP 发送

        Phase 1: 打印日志，后续接入邮件服务。
        """
        log.info("alert_notify_email",
            alert_id=alert.alert_id,
            severity=alert.severity.value,
            title=alert.title,
            recipients=recipients or [],
        )
        return True
