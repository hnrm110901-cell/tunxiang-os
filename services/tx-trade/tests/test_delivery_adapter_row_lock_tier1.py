"""Tier 1 行锁 / 幂等性测试：delivery_adapter 1 P1 + 4 P2 路径

核心约束：
  1) receive_order — 多平台 webhook 并发 receive 同一 platform_order_id 时，
     第二路 INSERT 必须 catch IntegrityError + rollback + 重 SELECT existing
     按幂等已存在分支返回（防业务异常 + 防重复订单挂账）.
  2) confirm_order / mark_ready / cancel_order / complete_order —
     state machine 切换 SELECT 必须 FOR UPDATE 防多 webhook + 内部触发并发
     race 导致状态错乱.

业务场景（真实餐厅）：
  - 美团/饿了么/抖音 webhook 重试机制存在：网关侧重发 + 商户侧 ack 超时同时发生
  - 内部 Mac mini sync-engine 也可能触发同订单 state 切换
  - 200 桌晚高峰 + 外卖三平台 webhook + 后台自动接单：并发量真实存在

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1.5 (delivery_adapter)
  - Issue #532 (audit parent), PR-F of 6-PR fix roadmap (三发 P1，roadmap 收尾)
  - 修复参考范本：services/tx-member/src/services/stored_value_service.py 11 处锁
  - PR-D/E 测试范本：test_cashier_engine_row_lock_tier1.py /
    test_order_state_machine_tier1.py (同 _get_order(*, lock: bool=False) 模式)
  - PR-A/B/C/D/E 已 ship：#544 / #547 / #553 / PR-D / PR-E
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── pytest collection guard ──────────────────────────────────────────────────
# delivery_adapter 顶层 import `shared.ontology.src.database`，间接拖 shared.events
# 用 `dataclass(slots=True)`，仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError；
# CI Python 3.11 原生通过。用 sys.version_info gate 而非 sys.modules stub
# （PR-A round-1 教训：stub 注入 'shared' 包污染同目录 test_invoice_tier1.py 等）.
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ORDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
PLATFORM_ORDER_ID = "MT_TEST_RACE_001"


def _select_has_for_update(stmt) -> bool:
    """检测 SQLAlchemy Select 编译后 SQL 是否含 FOR UPDATE.

    用 postgresql 方言 compile 而非检查私有属性 `_for_update_arg`，更稳定
    （PR-A/B/C/D/E 同方法学）.
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


def _make_delivery_order(**kw):
    """构造 DeliveryOrder mock，含 state machine 业务路径需要的字段."""
    order = MagicMock()
    order.id = kw.get("id", ORDER_ID)
    order.tenant_id = kw.get("tenant_id", TENANT_ID)
    order.store_id = kw.get("store_id", STORE_ID)
    order.platform = kw.get("platform", "meituan")
    order.platform_order_id = kw.get("platform_order_id", PLATFORM_ORDER_ID)
    order.order_no = kw.get("order_no", "MT20260513120000ABCD")
    order.status = kw.get("status", "confirmed")
    order.total_fen = kw.get("total_fen", 8800)
    order.commission_fen = kw.get("commission_fen", 1584)
    order.merchant_receive_fen = kw.get("merchant_receive_fen", 7216)
    order.items_json = kw.get("items_json", [{"name": "招牌剁椒鱼头", "quantity": 1, "price_fen": 8800}])
    order.unmapped_items = kw.get("unmapped_items", [])
    order.confirmed_at = kw.get("confirmed_at", None)
    order.estimated_ready_min = kw.get("estimated_ready_min", None)
    order.ready_at = kw.get("ready_at", None)
    order.completed_at = kw.get("completed_at", None)
    order.cancelled_at = kw.get("cancelled_at", None)
    order.cancel_reason = kw.get("cancel_reason", None)
    order.cancel_responsible = kw.get("cancel_responsible", None)
    return order


def _make_adapter(session):
    """构造 DeliveryPlatformAdapter，注入 mock session.

    DeliveryPlatformAdapter.__init__ 签名是 (store_id: str, brand_id: str,
    tenant_id: str = "", ...)；传 str 避免 UUID 对象 normalize 时
    AttributeError（PR-D CI 教训：service constructor 接 str 不接 UUID）.

    `_notify_platform` 用 mock 覆盖：原 impl 调 `logger.info(..., event=...)`，
    与 structlog 自身保留参数 `event` 冲突，在单测路径无 DI 真客户端时会抛
    TypeError；本测试不验证通知行为，仅验证 SELECT FOR UPDATE 编译结果.
    """
    from services.tx_trade.src.services.delivery_adapter import DeliveryPlatformAdapter

    adapter = DeliveryPlatformAdapter(
        store_id=str(STORE_ID),
        brand_id="xj_seafood",
        tenant_id=str(TENANT_ID),
        menu_items=[{"name": "招牌剁椒鱼头", "dish_id": "D001", "price_fen": 8800}],
        db_session=session,
    )
    adapter._notify_platform = AsyncMock()  # 避开 structlog event= 冲突
    return adapter


def _build_session_capture(order_to_return):
    """构造 AsyncSession mock，capture 所有 execute 的 stmt + 支持 commit/add/rollback."""
    session = AsyncMock()
    captured: list = []

    async def mock_execute(stmt, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=order_to_return)
        return result

    session.execute = mock_execute
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.close = AsyncMock()
    return session, captured


# ─────────────────────────────────────────────────────────────────────────────
# 1 P1：receive_order INSERT race 兜底
# ─────────────────────────────────────────────────────────────────────────────


class TestReceiveOrderIntegrityErrorTier1:
    """receive_order INSERT race（P1）：catch IntegrityError + rollback + 重 SELECT.

    Race（audit doc §4.1.5）：
      两路并发 receive 同 platform_order_id → 各过 L155 existing 检查
      → 各 INSERT → 后写 commit 触发 unique constraint → IntegrityError
      若不 catch：抛异常 + 上游可能重试 → 业务异常.
    期望：第二路 catch + rollback + 重 SELECT existing 后按幂等已存在分支返回.
    """

    @pytest.mark.asyncio
    async def test_receive_order_catches_integrity_error_returns_existing(self):
        """并发 INSERT 同 platform_order_id：第二路 commit 触发 unique violation
        → catch IntegrityError → rollback → 重 SELECT 拿到先写者 → 按 duplicate=True 返回.
        """
        from sqlalchemy.exc import IntegrityError

        # 先写者最终入库的订单（重 SELECT 时返回）
        existing_after = _make_delivery_order(
            id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
            order_no="MT_FIRST_WRITER_001",
            status="confirmed",
        )

        session = AsyncMock()
        # 第一次 SELECT（L150 幂等检查）返回 None，第二次 SELECT（rollback 后重查）
        # 返回 existing_after — 用 side_effect 序列模拟两次不同结果.
        call_counter = {"n": 0}

        async def mock_execute(stmt, *args, **kwargs):
            call_counter["n"] += 1
            result = MagicMock()
            if call_counter["n"] == 1:
                # L150 幂等检查未命中
                result.scalar_one_or_none = MagicMock(return_value=None)
            else:
                # rollback 后重 SELECT 命中先写者
                result.scalar_one_or_none = MagicMock(return_value=existing_after)
            return result

        session.execute = mock_execute
        # commit 第一次抛 IntegrityError（模拟并发先写者已 commit）
        session.commit = AsyncMock(side_effect=IntegrityError("INSERT", {}, Exception("unique violation")))
        session.rollback = AsyncMock()
        session.add = MagicMock()
        session.close = AsyncMock()

        adapter = _make_adapter(session)

        result = await adapter.receive_order(
            platform="meituan",
            platform_order_id=PLATFORM_ORDER_ID,
            items=[{"name": "招牌剁椒鱼头", "quantity": 1, "price_fen": 8800}],
            total_fen=8800,
        )

        # 必须 rollback（防 session 处于 invalid 状态）
        session.rollback.assert_awaited_once()
        # 必须按 duplicate=True 返回
        assert result["duplicate"] is True, (
            f"INSERT race 兜底必须返回 duplicate=True 分支结构，实际: {result}"
        )
        # 必须返回先写者的 ID（不是本路尝试 INSERT 的新 ID）
        assert result["order_id"] == "00000000-0000-0000-0000-000000000099", (
            f"必须返回重 SELECT 拿到的先写者 ID，实际: {result['order_id']}"
        )
        assert result["order_no"] == "MT_FIRST_WRITER_001"

    @pytest.mark.asyncio
    async def test_receive_order_integrity_error_other_constraint_reraises(self):
        """IntegrityError 但不是 platform_order_id unique 触发（如 order_no 撞
        / 其他约束）→ 重 SELECT 返回 None → 应当 re-raise 不吞.
        防御性：仅当能确认是 platform_order_id 重复时才走幂等返回路径.
        """
        from sqlalchemy.exc import IntegrityError

        session = AsyncMock()
        call_counter = {"n": 0}

        async def mock_execute(stmt, *args, **kwargs):
            call_counter["n"] += 1
            result = MagicMock()
            # 两次 SELECT 都返回 None（非 platform_order_id 触发）
            result.scalar_one_or_none = MagicMock(return_value=None)
            return result

        session.execute = mock_execute
        session.commit = AsyncMock(side_effect=IntegrityError("INSERT", {}, Exception("other constraint")))
        session.rollback = AsyncMock()
        session.add = MagicMock()
        session.close = AsyncMock()

        adapter = _make_adapter(session)

        with pytest.raises(IntegrityError):
            await adapter.receive_order(
                platform="meituan",
                platform_order_id=PLATFORM_ORDER_ID,
                items=[{"name": "招牌剁椒鱼头", "quantity": 1, "price_fen": 8800}],
                total_fen=8800,
            )

        # rollback 应被调（防 session 残留 invalid 状态）
        session.rollback.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# 4 P2：state machine 切换 SELECT FOR UPDATE
# ─────────────────────────────────────────────────────────────────────────────


class TestDeliveryStateMachineRowLockTier1:
    """delivery_adapter 4 state machine 切换路径必须 FOR UPDATE 防并发 race.

    Race（audit doc §4.1.5 P2）：
      多平台 webhook 重试 + 内部触发可能并发命中同 order_id 同 status 切换
      → state machine 切换无锁导致状态先后顺序错乱（如同时 cancel + complete）.
    期望：4 路径 _get_order SELECT 编译后 SQL 含 FOR UPDATE.
    """

    @pytest.mark.asyncio
    async def test_confirm_order_uses_for_update_row_lock(self):
        """confirm_order：confirmed→preparing.

        Race：美团 webhook 重发"商户已确认"同时本地 KDS 触发"开始备餐"
        → 同读 status=confirmed → 双 transition → 后写覆盖前.
        """
        order = _make_delivery_order(status="confirmed")
        session, captured = _build_session_capture(order)
        adapter = _make_adapter(session)

        await adapter.confirm_order(order_id=str(ORDER_ID), estimated_ready_min=20)

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"confirm_order 的 _get_order SELECT 必须含 FOR UPDATE，"
            f"防 webhook 重发 + KDS 触发并发 race。captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_mark_ready_uses_for_update_row_lock(self):
        """mark_ready (原 start_preparing)：preparing→ready.

        Race：后厨 KDS"出餐"按钮 + Mac mini 边缘 Agent 自动判定出餐完成
        → 同读 status=preparing → 双 notify 平台 → 平台侧重复取餐通知.
        """
        order = _make_delivery_order(status="preparing")
        session, captured = _build_session_capture(order)
        adapter = _make_adapter(session)

        await adapter.mark_ready(order_id=str(ORDER_ID))

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"mark_ready 的 _get_order SELECT 必须含 FOR UPDATE，"
            f"防出餐 race 重复通知平台。captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_cancel_order_uses_for_update_row_lock(self):
        """cancel_order：任意非终态→cancelled.

        Race（audit doc §4.1.5 P2，最敏感分支）：
          顾客 APP 取消 + 商家手动取消并发 → 同读 status=preparing
          → 双 transition cancelled + 双 refund 计算 → 退款金额可能错算
          （如 customer + merchant 两次责任方计算结果不同 → 实际退款金额不一致）.
        """
        order = _make_delivery_order(status="preparing", total_fen=8800)
        session, captured = _build_session_capture(order)
        adapter = _make_adapter(session)

        await adapter.cancel_order(
            order_id=str(ORDER_ID),
            reason="顾客主动取消",
            responsible_party="customer",
        )

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"cancel_order 的 _get_order SELECT 必须含 FOR UPDATE，"
            f"防并发取消责任方判定错算退款。captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_complete_order_uses_for_update_row_lock(self):
        """complete_order：ready/delivering/preparing/confirmed→completed.

        Race：骑手"已送达"回传 + 商户手动"完成订单"并发
        → 同读 status=ready → 双 transition completed → 双结算单生成
        → 平台佣金双扣 / 商户实收 double-count.
        """
        order = _make_delivery_order(status="ready", platform="meituan")
        session, captured = _build_session_capture(order)
        adapter = _make_adapter(session)

        await adapter.complete_order(order_id=str(ORDER_ID))

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"complete_order 的 _get_order SELECT 必须含 FOR UPDATE，"
            f"防骑手回传 + 商户手动并发导致双结算。captured: {captured}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# _get_order helper 契约（lock kwarg 默认行为）
# ─────────────────────────────────────────────────────────────────────────────


class TestGetOrderHelperContract:
    """_get_order helper 契约：与 cashier_engine / order_service 100% 对齐.

    lock kwarg 默认 False 保 read-only 入口性能；显式 lock=True 进 FOR UPDATE.
    """

    @pytest.mark.asyncio
    async def test_get_order_default_no_lock(self):
        """默认 lock=False 不应加 FOR UPDATE，保 read-only 路径性能."""
        order = _make_delivery_order()
        session, captured = _build_session_capture(order)
        adapter = _make_adapter(session)

        await adapter._get_order(session, str(ORDER_ID))

        assert captured, "至少一次 SELECT 应被 capture"
        locked = [s for s in captured if _select_has_for_update(s)]
        assert not locked, (
            f"_get_order 默认 lock=False 不应加 FOR UPDATE，"
            f"保 read-only 路径性能。captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_get_order_lock_true_adds_for_update(self):
        """Tier 1 mutation 入口显式 lock=True 必须加 FOR UPDATE."""
        order = _make_delivery_order()
        session, captured = _build_session_capture(order)
        adapter = _make_adapter(session)

        await adapter._get_order(session, str(ORDER_ID), lock=True)

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            f"_get_order(lock=True) 必须加 FOR UPDATE。captured: {captured}"
        )
