"""
测试 Phase 2 Month 3 — ISV 生命周期管理
- verify_developer
- request_tier_upgrade
- set_webhook
- get_developer_status
- admin_review_upgrade
- admin_update_status
"""
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/zhilian")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from src.api.isv_management import (  # noqa: E402
    TIER_ORDER,
    TIER_LABELS,
    verify_developer,
    request_tier_upgrade,
    set_webhook,
    get_developer_status,
    admin_review_upgrade,
    admin_update_status,
    RequestUpgradeBody,
    SetWebhookBody,
    ReviewUpgradeBody,
    UpdateStatusBody,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_dev(
    tier="free",
    is_verified=True,
    status="active",
    webhook_url=None,
    upgrade_request_tier=None,
    upgrade_reviewed_at=None,
) -> dict:
    return {
        "id": "dev_test001",
        "name": "测试开发者",
        "email": "test@example.com",
        "company": "测试公司",
        "tier": tier,
        "status": status,
        "is_verified": is_verified,
        "verified_at": None,
        "webhook_url": webhook_url,
        "upgrade_request_tier": upgrade_request_tier,
        "upgrade_request_reason": "需要更高 API 额度",
        "upgrade_requested_at": None,
        "upgrade_reviewed_at": upgrade_reviewed_at,
        "upgrade_review_note": None,
        "created_at": None,
    }


def _make_db(dev: dict = None, email_found: bool = False) -> AsyncMock:
    db = AsyncMock()
    mapping = MagicMock()
    mapping.first.return_value = dev
    mapping_all = MagicMock()
    mapping_all.all.return_value = [dev] if dev else []
    result = MagicMock()
    result.mappings.return_value = mapping
    result.scalar.return_value = 0
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


# ── TIER_ORDER / TIER_LABELS ──────────────────────────────────────────────────

class TestTierConfig:
    def test_tier_order_ascending(self):
        assert TIER_ORDER == ["free", "basic", "pro", "enterprise"]

    def test_all_tiers_have_labels(self):
        for t in TIER_ORDER:
            assert t in TIER_LABELS

    def test_labels_in_chinese(self):
        for label in TIER_LABELS.values():
            assert label  # non-empty
            assert any('\u4e00' <= c <= '\u9fff' for c in label), f"{label} 不含中文"


# ── verify_developer ──────────────────────────────────────────────────────────

class TestVerifyDeveloper:
    def test_unverified_gets_verified(self):
        dev = _make_dev(is_verified=False)
        db = _make_db(dev)
        result = asyncio.run(verify_developer("dev_test001", db))
        assert "成功" in result["message"] or result.get("verified_at")

    def test_already_verified_returns_message(self):
        from datetime import datetime
        dev = _make_dev(is_verified=True)
        dev["verified_at"] = datetime.utcnow()
        db = _make_db(dev)
        result = asyncio.run(verify_developer("dev_test001", db))
        assert "已完成验证" in result["message"]


# ── request_tier_upgrade ──────────────────────────────────────────────────────

class TestRequestTierUpgrade:
    def test_free_to_basic_succeeds(self):
        dev = _make_dev(tier="free", is_verified=True)
        db = _make_db(dev)
        body = RequestUpgradeBody(target_tier="basic", reason="业务扩展需要更高调用量")
        result = asyncio.run(request_tier_upgrade("dev_test001", body, db))
        assert result["status"] == "pending_review"

    def test_unverified_raises_403(self):
        from fastapi import HTTPException
        dev = _make_dev(tier="free", is_verified=False)
        db = _make_db(dev)
        body = RequestUpgradeBody(target_tier="basic", reason="需要升级")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(request_tier_upgrade("dev_test001", body, db))
        assert exc.value.status_code == 403

    def test_downgrade_raises_400(self):
        from fastapi import HTTPException
        dev = _make_dev(tier="pro", is_verified=True)
        db = _make_db(dev)
        body = RequestUpgradeBody(target_tier="basic", reason="想降级")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(request_tier_upgrade("dev_test001", body, db))
        assert exc.value.status_code == 400

    def test_same_tier_raises_400(self):
        from fastapi import HTTPException
        dev = _make_dev(tier="basic", is_verified=True)
        db = _make_db(dev)
        body = RequestUpgradeBody(target_tier="basic", reason="申请保持不变")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(request_tier_upgrade("dev_test001", body, db))
        assert exc.value.status_code == 400

    def test_short_reason_raises_400(self):
        from fastapi import HTTPException
        dev = _make_dev(tier="free", is_verified=True)
        db = _make_db(dev)
        body = RequestUpgradeBody(target_tier="basic", reason="太短")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(request_tier_upgrade("dev_test001", body, db))
        assert exc.value.status_code == 400

    def test_pending_upgrade_blocks_new_request(self):
        from fastapi import HTTPException
        dev = _make_dev(tier="free", is_verified=True, upgrade_request_tier="basic", upgrade_reviewed_at=None)
        db = _make_db(dev)
        body = RequestUpgradeBody(target_tier="pro", reason="再次申请更高级别")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(request_tier_upgrade("dev_test001", body, db))
        assert exc.value.status_code == 409


# ── set_webhook ───────────────────────────────────────────────────────────────

class TestSetWebhook:
    def test_https_webhook_accepted(self):
        dev = _make_dev()
        db = _make_db(dev)
        body = SetWebhookBody(webhook_url="https://my-isv.example.com/callback")
        result = asyncio.run(set_webhook("dev_test001", body, db))
        assert result["webhook_url"].startswith("https://")

    def test_http_webhook_rejected(self):
        from fastapi import HTTPException
        dev = _make_dev()
        db = _make_db(dev)
        body = SetWebhookBody(webhook_url="http://my-isv.example.com/callback")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(set_webhook("dev_test001", body, db))
        assert exc.value.status_code == 400


# ── admin_review_upgrade ──────────────────────────────────────────────────────

class TestAdminReviewUpgrade:
    def _make_admin_user(self):
        user = MagicMock()
        user.username = "admin"
        return user

    def test_approve_changes_tier(self):
        from datetime import datetime
        dev = _make_dev(tier="free", upgrade_request_tier="basic", upgrade_reviewed_at=None)
        db = _make_db(dev)
        body = ReviewUpgradeBody(approved=True, note="资质审核通过")
        result = asyncio.run(admin_review_upgrade("dev_test001", body, db, self._make_admin_user()))
        assert result["new_tier"] == "basic"
        assert "批准" in result["message"]

    def test_reject_requires_note(self):
        from fastapi import HTTPException
        dev = _make_dev(tier="free", upgrade_request_tier="basic", upgrade_reviewed_at=None)
        db = _make_db(dev)
        body = ReviewUpgradeBody(approved=False, note=None)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin_review_upgrade("dev_test001", body, db, self._make_admin_user()))
        assert exc.value.status_code == 400

    def test_no_pending_request_raises_404(self):
        from fastapi import HTTPException
        dev = _make_dev(tier="free", upgrade_request_tier=None)
        db = _make_db(dev)
        body = ReviewUpgradeBody(approved=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin_review_upgrade("dev_test001", body, db, self._make_admin_user()))
        assert exc.value.status_code == 404

    def test_already_reviewed_raises_409(self):
        from fastapi import HTTPException
        from datetime import datetime
        dev = _make_dev(tier="basic", upgrade_request_tier="pro", upgrade_reviewed_at=datetime.utcnow())
        db = _make_db(dev)
        body = ReviewUpgradeBody(approved=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin_review_upgrade("dev_test001", body, db, self._make_admin_user()))
        assert exc.value.status_code == 409


# ── admin_update_status ───────────────────────────────────────────────────────

class TestAdminUpdateStatus:
    def _make_admin_user(self):
        user = MagicMock()
        user.username = "admin"
        return user

    def test_suspend_active_account(self):
        dev = _make_dev(status="active")
        db = _make_db(dev)
        body = UpdateStatusBody(status="suspended")
        result = asyncio.run(admin_update_status("dev_test001", body, db, self._make_admin_user()))
        assert result["status"] == "suspended"

    def test_reactivate_suspended_account(self):
        dev = _make_dev(status="suspended")
        db = _make_db(dev)
        body = UpdateStatusBody(status="active")
        result = asyncio.run(admin_update_status("dev_test001", body, db, self._make_admin_user()))
        assert result["status"] == "active"

    def test_invalid_status_raises_400(self):
        from fastapi import HTTPException
        dev = _make_dev(status="active")
        db = _make_db(dev)
        body = UpdateStatusBody(status="deleted")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin_update_status("dev_test001", body, db, self._make_admin_user()))
        assert exc.value.status_code == 400

    def test_same_status_returns_no_change_message(self):
        dev = _make_dev(status="active")
        db = _make_db(dev)
        body = UpdateStatusBody(status="active")
        result = asyncio.run(admin_update_status("dev_test001", body, db, self._make_admin_user()))
        assert "无需变更" in result["message"]
