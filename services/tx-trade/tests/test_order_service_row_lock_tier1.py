"""Tier 1 行锁测试：order_service 2 P0 路径必须 with_for_update 防并发 race

核心约束：200 桌并发收银场景下，订单 SELECT-then-UPDATE 必须 FOR UPDATE
        串行化，防丢更新 / 双结算 / 双扣款。

业务场景（真实餐厅，非技术边界值）：
  1) apply_discount — 收银员打折 + 经理改折扣 race（比 cashier_engine 简化版
     更危险，连 margin 校验都没有，串行化是唯一防线）
  2) settle_order — POS 重试 / 网关回调 / 用户连点结算
     **Saga S3 链路依赖此函数**：payment_saga_service._complete_order 调用
     `order_service.settle_order(...)` 作为 S3 步骤；漏锁直接放大 saga 风险.

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1 (order_service 0 FOR UPDATE)
  - Issue #532 (audit parent), PR-E of 6-PR fix roadmap
  - 修复参考范本：services/tx-member/src/services/stored_value_service.py 11 处锁
  - PR-D 范本：services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py
  - PR-A/B/C/D 已 ship：PR #544 / #547 / #553 / #556
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── pytest collection guard ──────────────────────────────────────────────────
# order_service 顶层 import `shared.events`，后者用 `dataclass(slots=True)`
# 仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError；CI Python 3.11 原生通过。
# 用 sys.version_info gate 而非 sys.modules stub（PR-A round-1 教训：
# stub 注入 'shared' 包污染同目录 test_*_tier1.py 等真实 shared.* import）。
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ORDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _select_has_for_update(stmt) -> bool:
    """检测 SQLAlchemy Select 编译后 SQL 是否含 FOR UPDATE.

    用 postgresql 方言 compile 而非检查私有属性 `_for_update_arg`，
    更稳定（属性名在 SQLAlchemy 主版本间可能变化）。PR-A/B/C/D 已验证此模式。
    """
    from sqlalchemy.sql.selectable import Select
    from sqlalchemy.dialects import postgresql

    if not isinstance(stmt, Select):
        return False
    try:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        return "FOR UPDATE" in compiled.upper()
    except Exception:
        return getattr(stmt, "_for_update_arg", None) is not None


def _make_order(**kw):
    """构造 Order mock，含 order_service 业务路径需要的字段."""
    from shared.ontology.src.enums import OrderStatus

    order = MagicMock()
    order.id = kw.get("id", ORDER_ID)
    order.tenant_id = kw.get("tenant_id", TENANT_ID)
    order.store_id = kw.get("store_id", STORE_ID)
    order.status = kw.get("status", OrderStatus.confirmed.value)
    order.total_amount_fen = kw.get("total_amount_fen", 10000)
    order.discount_amount_fen = kw.get("discount_amount_fen", 0)
    order.final_amount_fen = kw.get("final_amount_fen", 10000)
    order.table_number = kw.get("table_number", "A01")
    order.order_no = kw.get("order_no", "TX20260513000001")
    order.order_metadata = kw.get("order_metadata", {})
    order.customer_id = kw.get("customer_id", None)
    order.completed_at = kw.get("completed_at", None)
    return order


def _make_service(db):
    """构造 OrderService 实例，注入 mock db.

    OrderService.__init__ 签名是 `tenant_id: str`，内部 `uuid.UUID(tenant_id)`
    再 normalize 为 UUID 对象。这里必须传 str — PR-D round-1 教训：
    传 UUID 对象触发 `uuid.UUID(uuid_obj)` → `.replace()` AttributeError
    (Python 3.11 CI 暴露；本机 3.9 module-level skip 跳过没暴露)。
    """
    from services.tx_trade.src.services.order_service import OrderService

    return OrderService(db=db, tenant_id=str(TENANT_ID))


def _build_db_capture(order_to_return):
    """构造 AsyncSession mock，capture 所有 execute 的 stmt.

    仅对 Order/OrderItem 查询返回 mock order；其他下游查询（如 release_table
    UPDATE 桌台、events 旁路）返回 None — 避免 MagicMock 参与算术 TypeError.
    """
    db = AsyncMock()
    captured: list = []

    async def mock_execute(stmt, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        stmt_str = str(stmt) if stmt is not None else ""
        is_order_query = (
            "FROM orders" in stmt_str or "FROM order_items" in stmt_str
        )
        result.scalar_one_or_none = MagicMock(
            return_value=order_to_return if is_order_query else None
        )
        result.one_or_none = MagicMock(return_value=None)
        return result

    db.execute = mock_execute
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db, captured


class TestOrderServiceRowLockTier1:
    """order_service.py 2 P0 路径必须 with_for_update 防并发丢更新.

    与 services/tx-member/src/services/stored_value_service.py 模式对齐
    （11 处 .with_for_update()）— 全仓 row-lock 最严谨服务.
    """

    @pytest.mark.asyncio
    async def test_apply_discount_uses_for_update_row_lock(self):
        """收银员打折 + 经理改折扣 race — 必须串行化保资金路径正确

        Race（audit doc §4.1 P0）：
          两路并发读 total_amount_fen=10000 → 各算 new_final = 10000 - discount
          → 各 ORM 属性赋值后第二个 flush 覆盖第一个 → 折扣金额错算.
        **比 cashier_engine.apply_discount 更危险** — 连 margin 校验都没有，
        串行化是唯一防线（audit doc §4.1 明示）.
        期望：select(Order) 编译后 SQL 含 FOR UPDATE 锁住 Order 行.
        """
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(status=OrderStatus.confirmed.value, total_amount_fen=10000)
        db, captured = _build_db_capture(order)
        svc = _make_service(db)

        await svc.apply_discount(
            order_id=str(ORDER_ID),
            discount_fen=1000,
            reason="VIP 折扣",
        )

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"apply_discount 的 SELECT(Order) 必须含 FOR UPDATE 锁 Order 行，"
            f"防 200 桌并发折扣丢更新（audit doc §4.1 P0）。captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_settle_order_uses_for_update_row_lock(self):
        """POS 重试 / 网关回调 / 用户连点 — 必须只完成 1 次结算

        Race（audit doc §4.1 P0，资金路径双结算）：
          两路并发读 status=confirmed → 各 transition_order(completed) →
          各更新 completed_at + 释放桌台 → 双结算 / 双桌台释放 / 双 ORDER.PAID 事件.
        **Saga S3 链路依赖此函数** — payment_saga_service._complete_order
        调用 order_service.settle_order；本函数加锁串行化即给 saga 补齐 S3 占位锁.
        期望：select(Order) 编译后 SQL 含 FOR UPDATE.
        """
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(
            status=OrderStatus.confirmed.value,
            total_amount_fen=10000,
            final_amount_fen=10000,
        )
        db, captured = _build_db_capture(order)
        svc = _make_service(db)

        # 注入 _release_table mock — 避免真 UPDATE Table SQL（桌台 release
        # 不在本 PR 范围；Order FOR UPDATE 串行化即可，audit doc §4.1 取舍）
        svc._release_table = AsyncMock()

        await svc.settle_order(order_id=str(ORDER_ID))

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"settle_order 的 SELECT(Order) 必须含 FOR UPDATE，"
            f"防 POS 重试 / saga S3 链路双结算（audit doc §4.1 P0）。"
            f"captured: {captured}"
        )


class TestGetOrderHelperContract:
    """_get_order helper 契约：lock kwarg 默认 False 保 read-only 入口性能.

    与 PR-D cashier_engine._get_order(lock=False) 模式对齐.
    """

    @pytest.mark.asyncio
    async def test_get_order_default_no_lock(self):
        """read-only 入口（如查单 / get_order）默认不加锁，避免阻塞高频读路径."""
        order = _make_order()
        db, captured = _build_db_capture(order)
        svc = _make_service(db)

        # get_order 是 read-only 入口，必须不加锁
        await svc.get_order(str(ORDER_ID))

        assert captured, "至少一次 SELECT 应被 capture"
        locked = [s for s in captured if _select_has_for_update(s)]
        assert not locked, (
            f"get_order (read-only) 不应加 FOR UPDATE，保 read-only 路径性能。"
            f"captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_cancel_order_uses_for_update_lock_s17b(self):
        """§17-B 终态保护: cancel_order 必须加 FOR UPDATE 防 settle/cancel race.

        历史: PR-E 方案 1 (#560) 边界外不加锁; §17-B (audit §11.2 选择题 3)
        创始人锁定 3B 显式幂等 release + 终态保护, cancel_order SELECT Order
        改用 _get_order(lock=True). 本测试由 §17-B 翻转预期, 锁定新契约.
        """
        order = _make_order()
        db, captured = _build_db_capture(order)
        svc = _make_service(db)

        await svc.cancel_order(order_id=str(ORDER_ID), reason="测试")

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            f"§17-B: cancel_order SELECT Order 必须含 FOR UPDATE 终态保护。"
            f"captured: {captured}"
        )


class TestApplyDiscountStatusGuard:
    """§17-D2 (closes issue #559): `order_service.apply_discount` status guard.

    main fix: apply_discount 拒绝 completed/cancelled 终态订单 — 防 POS 误操作 /
    后台脚本 bug 让已结订单 discount + final_amount_fen 漂移.

    与 cashier_engine.cancel_order L965-968 同模式 status guard.

    关联: issue #559 / PR #560 (PR-E) §19 reviewer P1#1 / audit doc §11.4 §17-D2.
    """

    @pytest.mark.asyncio
    async def test_apply_discount_rejects_completed_order(self):
        """§17-D2: apply_discount(status=completed) → raise ValueError "已结算".

        真实场景: POS 收银员对已结订单误操作打折 / 后台批量改折扣脚本未过滤 status.
        """
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(
            status=OrderStatus.completed.value,
            total_amount_fen=10000,
            completed_at=datetime.now(timezone.utc),
        )
        db, _captured = _build_db_capture(order)
        svc = _make_service(db)

        with pytest.raises(ValueError, match="已结算订单无法应用折扣"):
            await svc.apply_discount(
                order_id=str(ORDER_ID), discount_fen=2000, reason="audit"
            )

    @pytest.mark.asyncio
    async def test_apply_discount_rejects_cancelled_order(self):
        """§17-D2: apply_discount(status=cancelled) → raise ValueError "已取消".

        与 completed 拒绝同模式 — 已取消订单不应再改折扣.
        """
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(
            status=OrderStatus.cancelled.value,
            total_amount_fen=10000,
            order_metadata={"cancel_reason": "客户改单"},
        )
        db, _captured = _build_db_capture(order)
        svc = _make_service(db)

        with pytest.raises(ValueError, match="订单已取消"):
            await svc.apply_discount(
                order_id=str(ORDER_ID), discount_fen=2000, reason="audit"
            )

    @pytest.mark.asyncio
    async def test_apply_discount_on_confirmed_order_still_works_baseline(self):
        """baseline 正例: apply_discount(status=confirmed) 在 fix 前后都应正常工作.

        防 fix PR 误把 confirmed 列入禁止状态 (issue #559 修复决策点之一).
        """
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(
            status=OrderStatus.confirmed.value, total_amount_fen=10000
        )
        db, _captured = _build_db_capture(order)
        svc = _make_service(db)

        result = await svc.apply_discount(
            order_id=str(ORDER_ID), discount_fen=2000, reason="收银员折扣"
        )

        assert result["final_fen"] == 8000, (
            "confirmed 订单 apply_discount 应正常工作 — baseline 防 fix PR "
            "误把 confirmed 列入禁止状态. fix 应只禁 completed/cancelled."
        )
