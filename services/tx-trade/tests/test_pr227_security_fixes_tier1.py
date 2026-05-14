"""Tier 1 测试：PR #227 §19 reviewer (round-1) 3 项 must-fix 闭环测试

PR #227 rebase 后 §19 reviewer (opus, B 选项真 BUG only) 发现 3 项必修：
  - P0-1: cashier_engine.update_item 缺 _get_order(lock=True) → lost-update 漏洞
  - P0-2: sync_ingest_router._apply_soft_delete 缺表名白名单 → SQL 注入面
  - P1-2: verify_edge_sync_auth Step 1-3 过渡期 secret 已配 + required=False 时
          旧 edge client 401 → 违反 4h 离线 SLA

本测试守门 3 项 fix 不被未来 regression 破坏。

业务场景（真实餐厅）：
  P0-1: 桌长 POS 加菜 + 服务员 PWA 改菜数量同时跑，必须串行写 quantity/subtotal
  P0-2: edge 同步 DELETE 操作如果未拦截恶意 table_name，UPDATE 语句拼接打开
        跨表数据破坏面（虽外层 ingest_changes 已白名单，函数级防御保证未来
        被孤立调用时仍安全）
  P1-2: Step 1-3 部署：prod 配 secret 但 required=false 让旧 Mac mini client
        逐步升级 — 旧 client 未发 X-Edge-* headers 时应回退兼容，不应立即 401
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── 路径 ──────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── pytest collection guard ──────────────────────────────────────────────
# cashier_engine / sync_ingest_router 顶层 import `shared.events`，后者用
# `dataclass(slots=True)` 仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError；
# CI Python 3.11 原生通过。用 sys.version_info gate 而非 sys.modules stub
# (feedback_pytest_stub_setdefault_pitfall.md 教训)。
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ═══════════════════════════════════════════════════════════════════════════
# P0-1: cashier_engine.update_item 必须 _get_order(lock=True)
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateItemRowLock:
    """update_item 函数头 _get_order 必须 lock=True 防 200 桌并发 lost-update。"""

    @pytest.mark.asyncio
    async def test_update_item_calls_get_order_with_lock_true(self):
        """改菜 quantity → update_item 必须 lock=True 持锁直至 commit。

        §19 P0-1 修复点：原 _get_order(order_uuid) 用 lock kwarg 默认 False，
        rebase 选 HEAD lock kwarg pattern 后必须显式传 lock=True。
        """
        from services.tx_trade.src.services.cashier_engine import CashierEngine

        engine = CashierEngine(db=AsyncMock(), tenant_id=str(TENANT_ID))
        order_id = str(uuid.uuid4())
        item_id = str(uuid.uuid4())

        # mock _get_order 接管原实现，只验 caller 传 lock=True
        engine._get_order = AsyncMock(side_effect=ValueError("expected_short_circuit"))

        with pytest.raises(ValueError, match="expected_short_circuit"):
            await engine.update_item(order_id=order_id, item_id=item_id, quantity=2)

        engine._get_order.assert_called_once()
        # 关键断言：lock=True 必须传入
        assert engine._get_order.call_args.kwargs.get("lock") is True, (
            "update_item 必须用 lock=True 持锁，否则 200 桌并发改同桌订单 lost-update"
        )

    # 注：`with_for_update() → FOR UPDATE SQL` 编译保证已被 PR #556 PR-D
    # test_cashier_engine_row_lock_tier1.py 全套覆盖，本测试不再重复。
    # 本测试聚焦 P0-1 修复点本身：update_item caller 端 lock=True kwarg。


# ═══════════════════════════════════════════════════════════════════════════
# P0-2: _apply_soft_delete 必须对非白名单表名抛 ValueError
# ═══════════════════════════════════════════════════════════════════════════


class TestApplySoftDeleteWhitelist:
    """_apply_soft_delete 函数级表名白名单防御，与 _upsert_record 模式对齐。"""

    @pytest.mark.asyncio
    async def test_disallowed_table_raises_value_error(self):
        """恶意 table_name → ValueError, 永远到不了 db.execute SQL 拼接.

        §19 P0-2 修复点：外层 ingest_changes 已有白名单拦截，但函数级防御
        保证未来被孤立调用时仍安全（与 _upsert_record._validate_columns 对齐）。
        """
        from services.tx_trade.src.routers.sync_ingest_router import _apply_soft_delete

        db = AsyncMock()
        db.execute = AsyncMock()
        change = MagicMock()
        change.table_name = "evil_table; DROP TABLE orders; --"
        change.record_id = "00000000-0000-0000-0000-000000000001"
        change.tenant_id = str(TENANT_ID)

        with pytest.raises(ValueError, match="table not allowed"):
            await _apply_soft_delete(db, change, MagicMock())

        # 关键断言：execute 永远不应被调用（fail-closed before SQL 拼接）
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_table_passes_through(self):
        """白名单内的 table_name → 正常走 UPDATE SQL（不抛 ValueError）。"""
        from services.tx_trade.src.routers.sync_ingest_router import (
            ALLOWED_TABLES,
            _apply_soft_delete,
        )

        assert "orders" in ALLOWED_TABLES, "orders 必须在白名单（否则同步 break）"

        db = AsyncMock()
        db.execute = AsyncMock()
        change = MagicMock()
        change.table_name = "orders"
        change.record_id = "00000000-0000-0000-0000-000000000001"
        change.tenant_id = str(TENANT_ID)

        await _apply_soft_delete(db, change, MagicMock())
        # 白名单内表必须走到 execute（不被防御拦截）
        db.execute.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# P1-2: verify_edge_sync_auth Step 1-3 过渡期兼容分支
# ═══════════════════════════════════════════════════════════════════════════


class TestVerifyEdgeSyncAuthStep1Compat:
    """Step 1-3 部署兼容：secret 已配 + required=False + 旧 client headers 缺失
    时回退 X-Tenant-ID 信任（warn 不阻断 4h 离线 SLA）。"""

    @pytest.mark.asyncio
    async def test_legacy_client_compat_branch_with_tenant_id(self, monkeypatch):
        """secret 已配 + required=False + 旧 client 无 X-Edge-* → 返回 x_tenant_id."""
        monkeypatch.setenv("EDGE_SYNC_HMAC_SECRET", "test-secret-do-not-leak")
        monkeypatch.setenv("EDGE_SYNC_HMAC_REQUIRED", "false")

        from services.tx_trade.src.routers.sync_ingest_router import verify_edge_sync_auth

        result = await verify_edge_sync_auth(
            x_edge_store_id=None,
            x_edge_tenant_id=None,
            x_edge_sync_ts=None,
            x_edge_sync_nonce=None,
            x_edge_store_token=None,
            x_tenant_id="tenant-legacy",
        )
        assert result == "tenant-legacy", (
            "Step 1-3 旧 client 必须回退 X-Tenant-ID 信任，不阻断 4h 离线 SLA"
        )

    @pytest.mark.asyncio
    async def test_legacy_client_compat_branch_without_tenant_id_raises_400(self, monkeypatch):
        """secret 已配 + required=False + 旧 client 无 X-Edge-* + 无 X-Tenant-ID → 400."""
        from fastapi import HTTPException

        monkeypatch.setenv("EDGE_SYNC_HMAC_SECRET", "test-secret-do-not-leak")
        monkeypatch.setenv("EDGE_SYNC_HMAC_REQUIRED", "false")

        from services.tx_trade.src.routers.sync_ingest_router import verify_edge_sync_auth

        with pytest.raises(HTTPException) as exc_info:
            await verify_edge_sync_auth(
                x_edge_store_id=None,
                x_edge_tenant_id=None,
                x_edge_sync_ts=None,
                x_edge_sync_nonce=None,
                x_edge_store_token=None,
                x_tenant_id=None,
            )
        assert exc_info.value.status_code == 400, "缺 X-Tenant-ID 应 400 不应 401"

    @pytest.mark.asyncio
    async def test_step4_required_true_still_401_without_headers(self, monkeypatch):
        """secret 已配 + required=True (Step 4) + headers 缺失 → 仍 401（严格门禁）.

        守门兼容分支不会因为 fix 引入而打开 Step 4 后的攻击面。
        """
        from fastapi import HTTPException

        monkeypatch.setenv("EDGE_SYNC_HMAC_SECRET", "test-secret-do-not-leak")
        monkeypatch.setenv("EDGE_SYNC_HMAC_REQUIRED", "true")

        from services.tx_trade.src.routers.sync_ingest_router import verify_edge_sync_auth

        with pytest.raises(HTTPException) as exc_info:
            await verify_edge_sync_auth(
                x_edge_store_id=None,
                x_edge_tenant_id=None,
                x_edge_sync_ts=None,
                x_edge_sync_nonce=None,
                x_edge_store_token=None,
                x_tenant_id="tenant-A",
            )
        assert exc_info.value.status_code == 401, (
            "Step 4 强制模式必须 401，兼容分支不能被 fix 引入而打开攻击面"
        )
