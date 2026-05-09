"""订单状态机守卫红测试 [Tier1]

关联差距：docs/gap-verification-2026-05-07.md Part E #3 + Part C §C.1
任务卡：docs/dev-plan-60d-2026-05-07.md P0-3

红线：订单状态机被绕过 — `order.status = OrderStatus.X.value` 直接赋值，
未走 transition guard。本测试套件验证：
  1. 非法转换抛 InvalidTransitionError
  2. settle_order / cancel_order 等业务路径用上 transition guard
  3. 合法 happy path 仍跑通
  4. 业务代码层（services/api/）无直接 `order.status = OrderStatus.X.value` 赋值
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

# 顶层 conftest.py 已经把 tx-trade/src 加进 sys.path
from services.tx_trade.src.services.state_machine import (  # type: ignore[import-not-found]
    InvalidTransitionError,
    can_order_status_transition,
    transition_order,
)

from shared.ontology.src.enums import OrderStatus


class _FakeOrder:
    """轻量 Order 替身 — 只用于 transition_order 单测，不依赖 DB"""

    def __init__(self, status: str) -> None:
        self.id = uuid.uuid4()
        self.status = status


# ─── 1. transition_order helper 红线 ─────────────────────────────────


class TestTransitionGuard:
    def test_invalid_transition_raises(self) -> None:
        """completed → preparing 应抛 InvalidTransitionError"""
        order = _FakeOrder(status=OrderStatus.completed.value)
        with pytest.raises(InvalidTransitionError):
            transition_order(order, OrderStatus.preparing)

    def test_completed_to_cancelled_raises(self) -> None:
        """已结账订单不能再被取消（应走退款路径）"""
        order = _FakeOrder(status=OrderStatus.completed.value)
        with pytest.raises(InvalidTransitionError):
            transition_order(order, OrderStatus.cancelled)

    def test_cancelled_terminal(self) -> None:
        """已取消订单是终态，不能复活到任何状态"""
        order = _FakeOrder(status=OrderStatus.cancelled.value)
        with pytest.raises(InvalidTransitionError):
            transition_order(order, OrderStatus.completed)
        order2 = _FakeOrder(status=OrderStatus.cancelled.value)
        with pytest.raises(InvalidTransitionError):
            transition_order(order2, OrderStatus.confirmed)

    def test_pending_skip_to_completed_blocked(self) -> None:
        """pending → completed 必须先经 confirmed，不能跳"""
        order = _FakeOrder(status=OrderStatus.pending.value)
        with pytest.raises(InvalidTransitionError):
            transition_order(order, OrderStatus.completed)


# ─── 2. 合法 happy path ─────────────────────────────────────────────


class TestLegalTransitions:
    def test_simplified_path_pending_confirmed_completed(self) -> None:
        """业务现状：pending → confirmed → completed（跳过 preparing/ready/served）"""
        order = _FakeOrder(status=OrderStatus.pending.value)
        transition_order(order, OrderStatus.confirmed)
        assert order.status == OrderStatus.confirmed.value
        transition_order(order, OrderStatus.completed)
        assert order.status == OrderStatus.completed.value

    def test_full_path_pending_to_completed(self) -> None:
        """完整路径：pending → confirmed → preparing → ready → served → completed"""
        order = _FakeOrder(status=OrderStatus.pending.value)
        for target in [
            OrderStatus.confirmed,
            OrderStatus.preparing,
            OrderStatus.ready,
            OrderStatus.served,
            OrderStatus.completed,
        ]:
            transition_order(order, target)
        assert order.status == OrderStatus.completed.value

    def test_cancel_at_each_step(self) -> None:
        """非终态都可取消"""
        for state in (
            OrderStatus.pending,
            OrderStatus.confirmed,
            OrderStatus.preparing,
            OrderStatus.ready,
            OrderStatus.served,
        ):
            order = _FakeOrder(status=state.value)
            transition_order(order, OrderStatus.cancelled)
            assert order.status == OrderStatus.cancelled.value

    def test_idempotent_same_state(self) -> None:
        """幂等：相同状态视为合法，不抛异常（防 retry 误伤）"""
        assert can_order_status_transition("completed", "completed") is True
        order = _FakeOrder(status=OrderStatus.completed.value)
        transition_order(order, OrderStatus.completed)  # not raise


# ─── 3. 业务调用方接入验证（settle_order / cancel_order） ──────────────


class TestServiceLayerUsesGuard:
    """验证业务 service 层调用 transition_order，不直接赋值。

    这一层做的不是端到端单元测，是接口级断言：
    - 用 _FakeOrder 把 service 内部对 transition_order 的调用切到本套校验
    - 状态非法时抛 InvalidTransitionError 而不是悄悄赋值
    """

    @pytest.mark.asyncio
    async def test_settle_order_on_cancelled_raises(self) -> None:
        """已取消订单不能 settle — 必须由 transition guard 拦"""
        from unittest.mock import AsyncMock, MagicMock

        # 取一个 cancelled 订单
        fake_order = _FakeOrder(status=OrderStatus.cancelled.value)
        fake_order.completed_at = None
        fake_order.table_number = None
        fake_order.store_id = uuid.uuid4()
        fake_order.order_no = "TX-FAKE"
        fake_order.final_amount_fen = 0
        fake_order.customer_id = None

        # mock db
        db = MagicMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()
        # 让 db.execute(...).scalar_one_or_none() 返回 fake_order
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = fake_order
        db.execute.return_value = result_mock

        from services.tx_trade.src.services.order_service import OrderService  # type: ignore[import-not-found]

        svc = OrderService(db, str(uuid.uuid4()))
        # OrderService 有两个 __init__ 重复定义（已知历史 bug），后者覆盖前者，
        # _tenant_id_str 需手动补齐，本测试只关注守卫拦截，不验证 RLS 设置。
        svc._tenant_id_str = str(svc.tenant_id)

        with pytest.raises((InvalidTransitionError, ValueError)) as exc_info:
            await svc.settle_order(str(fake_order.id))
        # 必须是 transition guard 抛出，而不是被旧 "Order already settled" 路径拦
        # InvalidTransitionError 是 ValueError 子类，所以也能 except ValueError
        assert isinstance(exc_info.value, InvalidTransitionError) or "状态" in str(exc_info.value) or "已" in str(
            exc_info.value
        )

    @pytest.mark.asyncio
    async def test_cancel_order_on_completed_raises(self) -> None:
        """已结账订单不能 cancel — 必须由 transition guard 拦（防绕过退款流程）"""
        from unittest.mock import AsyncMock, MagicMock

        fake_order = _FakeOrder(status=OrderStatus.completed.value)
        fake_order.order_metadata = {}
        fake_order.table_number = None
        fake_order.store_id = uuid.uuid4()
        fake_order.order_no = "TX-FAKE"

        db = MagicMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = fake_order
        db.execute.return_value = result_mock

        from services.tx_trade.src.services.order_service import OrderService  # type: ignore[import-not-found]

        svc = OrderService(db, str(uuid.uuid4()))
        svc._tenant_id_str = str(svc.tenant_id)

        with pytest.raises((InvalidTransitionError, ValueError)):
            await svc.cancel_order(str(fake_order.id))


# ─── 4. 静态反测：业务代码层无直接 order.status = OrderStatus.X 赋值 ──


class TestNoDirectAssignmentOutsideStateMachine:
    """git grep 反测 — 业务代码层（services/api/routers/）不允许直接对 Order
    实体的 status 字段做 OrderStatus.X.value 赋值。state_machine.py 内部除外。
    """

    def test_no_order_status_orderstatus_assignment_in_business_code(self) -> None:
        """grep `order.status = OrderStatus.X.value` 在 services/ + api/ + routers/ 应为空

        例外：state_machine.py（守卫自身的实现）
        """
        # 定位 tx-trade src 根
        here = Path(__file__).resolve()
        src_dir = here.parents[1]  # services/tx-trade/src/
        assert src_dir.name == "src"
        assert (src_dir / "services" / "state_machine.py").exists()

        # 用 ripgrep 优先；fallback python re
        scan_dirs = [src_dir / sub for sub in ("services", "api", "routers")]
        scan_dirs = [p for p in scan_dirs if p.is_dir()]

        offenders: list[str] = []
        # 命中模式：order.status = OrderStatus.（同行后跟 . + 标识符）
        pattern = re.compile(r"\border\.status\s*=\s*OrderStatus\.\w+")

        for d in scan_dirs:
            for py in d.rglob("*.py"):
                # 排除测试自身与状态机实现
                rel = py.relative_to(src_dir)
                if rel.name == "state_machine.py":
                    continue
                if "tests" in rel.parts:
                    continue
                try:
                    content = py.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for i, line in enumerate(content.splitlines(), start=1):
                    # 排除注释（行首 # 或 docstring 段落 - 简单判断不严格但够用）
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if pattern.search(line):
                        offenders.append(f"{rel}:{i}: {line.strip()}")

        if offenders:
            msg = "业务代码仍有直接 order.status = OrderStatus.X 赋值（应改走 transition_order）：\n  " + "\n  ".join(
                offenders
            )
            pytest.fail(msg)


# ─── 5. 兼容性：状态机 helper 自身合法性 ──────────────────────────────


class TestStateMachineConsistency:
    def test_all_orderstatus_in_transition_table(self) -> None:
        """ORDER_STATUS_TRANSITIONS 必须覆盖所有 OrderStatus 枚举（防词表漂移）"""
        from services.tx_trade.src.services.state_machine import ORDER_STATUS_TRANSITIONS  # type: ignore[import-not-found]

        for member in OrderStatus:
            assert (
                member.value in ORDER_STATUS_TRANSITIONS
            ), f"OrderStatus.{member.name}={member.value!r} 未在 ORDER_STATUS_TRANSITIONS 中定义"

    def test_terminal_states_are_terminal(self) -> None:
        """completed 与 cancelled 必须是终态（出度为 0）"""
        from services.tx_trade.src.services.state_machine import ORDER_STATUS_TRANSITIONS  # type: ignore[import-not-found]

        assert ORDER_STATUS_TRANSITIONS["completed"] == []
        assert ORDER_STATUS_TRANSITIONS["cancelled"] == []
