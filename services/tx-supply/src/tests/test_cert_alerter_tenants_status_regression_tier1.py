"""cert_expiry_alerter tenants SQL filter regression test (Tier 2 — 2026-05-16).

修复 PR #698 §19 round-1 P1-2 surface 的 pre-existing bug:
`cert_expiry_alerter._fetch_active_tenants` + `_get_tenant_webhook_urls` 用
`WHERE is_deleted = FALSE` 过滤 tenants 表, 但 v006 建 tenants 表只有 id/code/name/
brand_name/pos_system/pos_config/status/created_at/updated_at, **无 is_deleted 列**.
原 SQL 运行时 ProgrammingError, 被外层 fail-open 吞 → worker 永不告警,
PRD-01 supplier cert 食安合规 alert 静默失效.

修法 (与 PR #698 `registry.list_active_tenants` 一致):
`WHERE is_deleted = FALSE` → `WHERE status = 'active'`

参考: feedback_tenants_v006_schema_no_is_deleted.md
"""

from __future__ import annotations

import inspect
import re


def test_fetch_active_tenants_uses_status_filter() -> None:
    """_fetch_active_tenants SQL 必须用 status='active', 禁 is_deleted=FALSE."""
    from services.tx_supply.src.workers.cert_expiry_alerter import _fetch_active_tenants

    body = inspect.getsource(_fetch_active_tenants)

    assert "status = 'active'" in body or 'status = "active"' in body, (
        "_fetch_active_tenants SQL 必须 filter status='active' (v006 schema). "
        "tenants 表无 is_deleted 列, 用 is_deleted = FALSE 会 ProgrammingError "
        "致 worker 永不告警, supplier cert 食安合规 alert 静默失效."
    )
    assert not re.search(r"is_deleted\s*=\s*FALSE", body), (
        "_fetch_active_tenants 不可用 is_deleted = FALSE — tenants 表 v006 无此列. "
        "用 status='active' 替代."
    )


def test_get_tenant_webhook_urls_uses_status_filter() -> None:
    """_get_tenant_webhook_urls SQL 必须用 status='active', 禁 is_deleted=FALSE."""
    from services.tx_supply.src.workers.cert_expiry_alerter import _get_tenant_webhook_urls

    body = inspect.getsource(_get_tenant_webhook_urls)

    assert "status = 'active'" in body or 'status = "active"' in body, (
        "_get_tenant_webhook_urls SQL 必须 filter status='active' (v006 schema)."
    )
    assert not re.search(r"is_deleted\s*=\s*FALSE", body), (
        "_get_tenant_webhook_urls 不可用 is_deleted = FALSE — tenants 表无此列."
    )
