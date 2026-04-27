"""test_trade_audit_log — Sprint A4 审计日志服务单元测试

覆盖 services.trade_audit_log.write_audit 六条契约：
  1. 成功路径：SELECT set_config + INSERT，commit
  2. RLS：set_config 以传入的 tenant_id 绑定
  3. SQLAlchemyError：rollback + log.error，不抛 HTTPException
  4. amount_fen=None 允许（查询操作无金额）
  5. action 空串被拒（ValueError）
  6. user_id 空字符串被拒（ValueError）
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.services.trade_audit_log import write_audit

_TENANT = "00000000-0000-0000-0000-000000000001"
_USER = "11111111-1111-1111-1111-111111111111"
_STORE = "22222222-2222-2222-2222-222222222222"


def _mk_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_write_audit_success_inserts_row():
    db = _mk_db()
    await write_audit(
        db,
        tenant_id=_TENANT,
        store_id=_STORE,
        user_id=_USER,
        user_role="cashier",
        action="payment.create",
        target_type="order",
        target_id=str(uuid.uuid4()),
        amount_fen=8800,
        client_ip="127.0.0.1",
    )
    # 至少两次 execute：set_config + insert
    assert db.execute.await_count >= 2
    db.commit.assert_awaited_once()
    db.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_write_audit_binds_tenant_via_set_config():
    db = _mk_db()
    await write_audit(
        db,
        tenant_id=_TENANT,
        store_id=None,
        user_id=_USER,
        user_role="admin",
        action="refund.apply",
        target_type="payment",
        target_id=str(uuid.uuid4()),
        amount_fen=5000,
        client_ip=None,
    )
    # 首个 execute 应是 set_config('app.tenant_id', ...)
    first_call = db.execute.await_args_list[0]
    # SQLAlchemy text() 生成的 CompiledSQL 难以直接比较；检查参数中带 tenant_id
    # 通过 bind params / kwargs 的方式检查
    args, kwargs = first_call.args, first_call.kwargs
    # 参数字典中应出现 _TENANT
    flat = str(args) + str(kwargs)
    assert _TENANT in flat


@pytest.mark.asyncio
async def test_write_audit_swallows_sqlalchemy_error_and_rolls_back():
    db = _mk_db()
    db.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))

    # 审计日志不应阻塞主流程：不抛 HTTPException，不抛 SQLAlchemyError
    await write_audit(
        db,
        tenant_id=_TENANT,
        store_id=None,
        user_id=_USER,
        user_role="cashier",
        action="payment.create",
        target_type="order",
        target_id=str(uuid.uuid4()),
        amount_fen=100,
        client_ip=None,
    )
    db.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_write_audit_allows_none_amount():
    db = _mk_db()
    await write_audit(
        db,
        tenant_id=_TENANT,
        store_id=None,
        user_id=_USER,
        user_role="cashier",
        action="payment.query",
        target_type="payment",
        target_id=str(uuid.uuid4()),
        amount_fen=None,
        client_ip=None,
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_audit_rejects_empty_action():
    db = _mk_db()
    with pytest.raises(ValueError):
        await write_audit(
            db,
            tenant_id=_TENANT,
            store_id=None,
            user_id=_USER,
            user_role="cashier",
            action="",
            target_type="order",
            target_id=None,
            amount_fen=None,
            client_ip=None,
        )
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_write_audit_rejects_empty_user_id():
    db = _mk_db()
    with pytest.raises(ValueError):
        await write_audit(
            db,
            tenant_id=_TENANT,
            store_id=None,
            user_id="",
            user_role="cashier",
            action="payment.create",
            target_type=None,
            target_id=None,
            amount_fen=None,
            client_ip=None,
        )
    db.execute.assert_not_called()
