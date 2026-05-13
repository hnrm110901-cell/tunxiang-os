"""Tier 1 测试：payment_saga_service FOR UPDATE 行锁

核心约束：补偿退款必须串行化，防止双 worker 并发 compensate 同一 saga
        导致双退款；多 worker recover 必须用 SKIP LOCKED 避免重复处理。

业务场景：
  1) 200 桌同时收银，1 桌支付超时被两 worker 同时 compensate
     → 必须只发起 1 次退款（资金路径硬约束）
  2) 服务器集群启动 3 个 pod 都跑 recover_pending_sagas
     → 必须不重复处理同一 saga（SKIP LOCKED 让出锁定 row）

关联文件：
  services/tx-trade/src/services/payment_saga_service.py
  docs/security/tier1-row-lock-audit-2026-05.md §4.1 + §8 PR-C
"""
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ─── pytest collection guard ──────────────────────────────────────────
# payment_saga_service 顶层 import `shared.events`，后者用 `dataclass(slots=True)`
# 仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError；CI Python 3.11 原生通过。
# 用 sys.version_info gate 而非 sys.modules stub（避免 PR-A round-1 教训：
# stub 注入 'shared' 包污染同目录 test_invoice_tier1.py 等真实 shared.* import）。
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )


def _make_mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_mock_gateway():
    gw = AsyncMock()
    gw.refund = AsyncMock(return_value={"status": "refunded"})
    return gw


def _captured_sql_texts(db_execute_mock) -> list[str]:
    """从 AsyncMock.execute 的 call_args_list 提取所有 text() SQL 字符串。"""
    sql_texts: list[str] = []
    for call in db_execute_mock.call_args_list:
        args, _kwargs = call
        if not args:
            continue
        sql_obj = args[0]
        # sqlalchemy.text() 返回 TextClause；str() 即 SQL 字符串
        sql_texts.append(str(sql_obj))
    return sql_texts


class TestCompensateRowLock:
    """compensate() 路径：SELECT payment_id 必须加 FOR UPDATE 锁住 saga row"""

    @pytest.mark.asyncio
    async def test_compensate_selects_with_for_update(self):
        """200 桌并发场景：1 桌支付超时被两 worker 同时 compensate

        期望：SELECT payment_id FROM payment_sagas ... 含 FOR UPDATE
        子句，让第二个 worker 阻塞等待，避免两个 worker 都读到 payment_id 后
        各调一次 refund 造成双退款。
        """
        from services.tx_trade.src.services.payment_saga_service import (
            PaymentSagaService,
            SagaStep,
        )

        db = _make_mock_db()

        # mock SELECT 返回 step=COMPENSATING（新建 saga 状态，允许走 refund 分支）
        # + 含 payment_id
        select_row = {
            "step": SagaStep.PAYING,  # 不是 COMPENSATED / COMPENSATING / FAILED 终态
            "payment_id": uuid.uuid4(),
            "payment_amount_fen": 8800,
        }
        select_result = MagicMock()
        select_result.mappings.return_value.first.return_value = select_row
        db.execute.return_value = select_result

        gw = _make_mock_gateway()
        svc = PaymentSagaService(db=db, tenant_id=TENANT_ID, payment_gateway=gw)

        saga_id = uuid.uuid4()
        await svc.compensate(saga_id=saga_id, reason="S3 失败")

        sql_texts = _captured_sql_texts(db.execute)
        # 至少有一条 SELECT 含 FOR UPDATE（锁定 saga row）
        select_with_lock = [
            s for s in sql_texts
            if "SELECT" in s.upper() and "FOR UPDATE" in s.upper()
            and "payment_sagas" in s
        ]
        assert select_with_lock, (
            f"compensate 的 SELECT 必须含 FOR UPDATE 子句以串行化退款。"
            f"实际 SQL: {sql_texts}"
        )

    @pytest.mark.asyncio
    async def test_compensate_idempotent_on_already_compensated(self):
        """saga 已 compensated → 直接 return True，不再调 refund

        场景：worker A 已成功 compensate，worker B 拿到锁后看到 step=compensated，
        直接返回 True 不重退款。
        """
        from services.tx_trade.src.services.payment_saga_service import (
            PaymentSagaService,
            SagaStep,
        )

        db = _make_mock_db()
        select_row = {
            "step": SagaStep.COMPENSATED,  # 已退款
            "payment_id": uuid.uuid4(),
            "payment_amount_fen": 8800,
        }
        select_result = MagicMock()
        select_result.mappings.return_value.first.return_value = select_row
        db.execute.return_value = select_result

        gw = _make_mock_gateway()
        svc = PaymentSagaService(db=db, tenant_id=TENANT_ID, payment_gateway=gw)

        result = await svc.compensate(saga_id=uuid.uuid4(), reason="重复触发")

        assert result is True, "已 compensated 必须返回 True（幂等成功）"
        gw.refund.assert_not_called(), "已 compensated 禁止再次发起退款"

    @pytest.mark.asyncio
    async def test_compensate_skip_when_in_progress(self):
        """saga 正在 compensating → 返回 False，不重复发起退款

        场景：worker A 正在跑 refund 但还没 commit；worker B 拿不到锁等待，
        A 完成后 B 拿到锁看到 step=compensating（极罕见但理论可能：A 网关调用慢
        没改 step），B 让出。
        """
        from services.tx_trade.src.services.payment_saga_service import (
            PaymentSagaService,
            SagaStep,
        )

        db = _make_mock_db()
        select_row = {
            "step": SagaStep.COMPENSATING,
            "payment_id": uuid.uuid4(),
            "payment_amount_fen": 8800,
        }
        select_result = MagicMock()
        select_result.mappings.return_value.first.return_value = select_row
        db.execute.return_value = select_result

        gw = _make_mock_gateway()
        svc = PaymentSagaService(db=db, tenant_id=TENANT_ID, payment_gateway=gw)

        result = await svc.compensate(saga_id=uuid.uuid4(), reason="并发触发")

        assert result is False, "正在 compensating 必须返回 False 让出"
        gw.refund.assert_not_called(), "正在 compensating 禁止重复退款"

    @pytest.mark.asyncio
    async def test_compensate_skip_when_already_failed(self):
        """saga 已 failed → 返回 False，不发起退款（已是终态，无 payment 可退）"""
        from services.tx_trade.src.services.payment_saga_service import (
            PaymentSagaService,
            SagaStep,
        )

        db = _make_mock_db()
        select_row = {
            "step": SagaStep.FAILED,
            "payment_id": None,
            "payment_amount_fen": 8800,
        }
        select_result = MagicMock()
        select_result.mappings.return_value.first.return_value = select_row
        db.execute.return_value = select_result

        gw = _make_mock_gateway()
        svc = PaymentSagaService(db=db, tenant_id=TENANT_ID, payment_gateway=gw)

        result = await svc.compensate(saga_id=uuid.uuid4(), reason="重复触发")

        assert result is False
        gw.refund.assert_not_called()


class TestRecoverPendingSagasSkipLocked:
    """recover_pending_sagas() 路径：多 worker 并发恢复必须用 SKIP LOCKED"""

    @pytest.mark.asyncio
    async def test_recover_uses_for_update_skip_locked(self):
        """3 pod 同时启动跑 recover_pending_sagas → SELECT 必须含 SKIP LOCKED

        期望：SELECT 含 `FOR UPDATE SKIP LOCKED` — worker A 锁的 row 让 worker B
        直接跳过（不阻塞），各 worker 自然分裂工作集，不会重复处理同一 saga。
        """
        from services.tx_trade.src.services.payment_saga_service import (
            PaymentSagaService,
        )

        db = _make_mock_db()
        # 返回空 rows（避免触发内部 _complete_order / compensate 路径）
        select_result = MagicMock()
        select_result.mappings.return_value.all.return_value = []
        db.execute.return_value = select_result

        gw = _make_mock_gateway()
        svc = PaymentSagaService(db=db, tenant_id=TENANT_ID, payment_gateway=gw)

        await svc.recover_pending_sagas()

        sql_texts = _captured_sql_texts(db.execute)
        recovery_select = [
            s for s in sql_texts
            if "SELECT" in s.upper() and "payment_sagas" in s
            and "FOR UPDATE" in s.upper() and "SKIP LOCKED" in s.upper()
        ]
        assert recovery_select, (
            f"recover_pending_sagas 的 SELECT 必须含 FOR UPDATE SKIP LOCKED，"
            f"避免多 worker 重复处理同一 saga。实际 SQL: {sql_texts}"
        )

    @pytest.mark.asyncio
    async def test_recover_returns_zero_when_all_rows_locked(self):
        """所有 row 被其他 worker 锁住时，本 worker SELECT 返回空 → 处理 0 条

        场景：worker A 抢到全部挂起 saga；worker B/C 起来后 SKIP LOCKED
        返回空集，正常退出（不阻塞，不重复处理）。
        """
        from services.tx_trade.src.services.payment_saga_service import (
            PaymentSagaService,
        )

        db = _make_mock_db()
        select_result = MagicMock()
        select_result.mappings.return_value.all.return_value = []
        db.execute.return_value = select_result

        gw = _make_mock_gateway()
        svc = PaymentSagaService(db=db, tenant_id=TENANT_ID, payment_gateway=gw)

        recovered = await svc.recover_pending_sagas()

        assert recovered == 0
