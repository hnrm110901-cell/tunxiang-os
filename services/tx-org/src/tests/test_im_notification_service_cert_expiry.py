"""tx-org IMNotificationService.notify_cert_expiry 模板渲染测试（PR-01B sub-PR C）

PRD-01 食安合规：供应商证件临期/过期推送模板分级测试。
threshold 分级：
  - D+N (N>=0) → [CRITICAL] 已过期分支（停止验收 + 立即续证）
  - D-7        → [WARNING] 7 日内
  - D-15/D-30  → 普通临期预警

调用方 services/tx-supply/src/workers/cert_expiry_alerter.py 通过此模板生成
markdown 消息，再交给 send_wecom_bot 推送给食安总监 / 采购员。
"""
from __future__ import annotations

import pytest

from services.tx_org.src.services.im_notification_service import IMNotificationService


_BASE_KW = dict(
    supplier_name="徐记海鲜供应商A",
    cert_type="食品经营许可证",
    cert_number="XJ-2024-001",
    expire_date="2026-06-13",
    days_until_expiry=30,
    recipient_role="食安总监",
)


class TestNotifyCertExpiryTemplate:
    """模板分级 + 字段完整性 + markdown 结构。"""

    @pytest.mark.asyncio
    async def test_d30_renders_临期_warning_section(self):
        """D-30 → 普通临期预警标题（非 CRITICAL/WARNING）。"""
        svc = IMNotificationService()
        msg = await svc.notify_cert_expiry(threshold="D-30", **_BASE_KW)
        assert msg.startswith("### 供应商证件临期预警")
        assert "[CRITICAL]" not in msg
        assert "[WARNING]" not in msg

    @pytest.mark.asyncio
    async def test_d15_renders_临期_warning_section(self):
        """D-15 → 普通临期预警（与 D-30 同分支）。"""
        svc = IMNotificationService()
        kw = {**_BASE_KW, "days_until_expiry": 15}
        msg = await svc.notify_cert_expiry(threshold="D-15", **kw)
        assert msg.startswith("### 供应商证件临期预警")
        assert "D-15" in msg

    @pytest.mark.asyncio
    async def test_d7_renders_warning_severity(self):
        """D-7 → [WARNING] 7 日内分支。"""
        svc = IMNotificationService()
        kw = {**_BASE_KW, "days_until_expiry": 7}
        msg = await svc.notify_cert_expiry(threshold="D-7", **kw)
        assert msg.startswith("### [WARNING] 供应商证件即将过期（7 日内）")
        assert "D-7" in msg

    @pytest.mark.asyncio
    async def test_d_plus_0_renders_critical_severity(self):
        """D+0（到期当天） → [CRITICAL] 已过期分支。"""
        svc = IMNotificationService()
        kw = {**_BASE_KW, "days_until_expiry": 0}
        msg = await svc.notify_cert_expiry(threshold="D+0", **kw)
        assert msg.startswith("### [CRITICAL] 供应商证件已过期")
        assert "暂停" in msg or "停止" in msg

    @pytest.mark.asyncio
    async def test_d_plus_3_renders_critical_severity(self):
        """D+3（过期 3 天） → [CRITICAL] 已过期分支。"""
        svc = IMNotificationService()
        kw = {**_BASE_KW, "days_until_expiry": -3}
        msg = await svc.notify_cert_expiry(threshold="D+3", **kw)
        assert msg.startswith("### [CRITICAL] 供应商证件已过期")
        assert "D+3" in msg

    @pytest.mark.asyncio
    async def test_template_includes_all_required_fields(self):
        """模板必含：supplier_name / cert_type / cert_number / expire_date / recipient_role / threshold。"""
        svc = IMNotificationService()
        msg = await svc.notify_cert_expiry(threshold="D-30", **_BASE_KW)
        assert "徐记海鲜供应商A" in msg
        assert "食品经营许可证" in msg
        assert "XJ-2024-001" in msg
        assert "2026-06-13" in msg
        assert "食安总监" in msg
        assert "D-30" in msg
        assert "30 天" in msg

    @pytest.mark.asyncio
    async def test_template_recipient_role_purchaser_appears(self):
        """recipient_role='采购员' → 模板内含'采购员'文案，区别于食安总监。"""
        svc = IMNotificationService()
        kw = {**_BASE_KW, "recipient_role": "采购员"}
        msg = await svc.notify_cert_expiry(threshold="D-15", **kw)
        assert "采购员" in msg

    @pytest.mark.asyncio
    async def test_template_returns_markdown_heading(self):
        """模板必须是 markdown 格式（### 开头标题），便于企微机器人 markdown msgtype 渲染。"""
        svc = IMNotificationService()
        for threshold in ("D-30", "D-15", "D-7", "D+0", "D+1"):
            kw = {**_BASE_KW, "days_until_expiry": 30 if threshold.startswith("D-") else 0}
            msg = await svc.notify_cert_expiry(threshold=threshold, **kw)
            assert msg.startswith("###"), f"{threshold} 缺 markdown ### 标题: {msg[:80]}"
            assert "**供应商**" in msg, f"{threshold} 缺 markdown **bold**: {msg[:80]}"
