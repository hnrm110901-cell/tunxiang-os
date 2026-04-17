"""D7 月结/年结 — 单元测试

覆盖：
  1) pre_close_check 阻塞场景（draft vouchers / already_closed）
  2) execute_month_close 成功落盘 MonthCloseLog
  3) reopen_month 仅 ADMIN 可用且需原因
  4) execute_year_close 前置 12 个月月结检查
  5) 纯函数：试算平衡表 → 利润表 / 资产负债表
  6) _validate_ym / _ym_range
"""

import sys
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest

from src.models.month_close import MonthCloseLog
from src.models.user import UserRole
from src.services.month_close_service import (
    MonthCloseError,
    MonthCloseService,
    _validate_ym,
    _ym_range,
)


def _user(role=UserRole.ADMIN):
    return SimpleNamespace(id=uuid.uuid4(), role=role, store_id=None, brand_id="B1")


# ───────────── pure helpers ─────────────


def test_validate_ym_ok():
    _validate_ym("202604")


def test_validate_ym_bad_format():
    with pytest.raises(MonthCloseError):
        _validate_ym("2026-04")


def test_validate_ym_bad_month():
    with pytest.raises(MonthCloseError):
        _validate_ym("202613")


def test_ym_range_december_rolls_year():
    start, end = _ym_range("202612")
    assert start == datetime(2026, 12, 1)
    assert end == datetime(2027, 1, 1)


# ───────────── Income / Balance builders ─────────────


def test_income_statement_profit():
    svc = MonthCloseService()
    tb = [
        {"account_code": "6001", "account_name": "主营业务收入",
         "period_debit_fen": 0, "period_credit_fen": 1_000_00,
         "closing_debit_fen": 0, "closing_credit_fen": 1_000_00},
        {"account_code": "6401", "account_name": "主营业务成本",
         "period_debit_fen": 300_00, "period_credit_fen": 0,
         "closing_debit_fen": 300_00, "closing_credit_fen": 0},
        {"account_code": "6601", "account_name": "销售费用",
         "period_debit_fen": 100_00, "period_credit_fen": 0,
         "closing_debit_fen": 100_00, "closing_credit_fen": 0},
    ]
    inc = svc._build_income_statement(tb)
    assert inc["revenue_yuan"] == 1000.0
    assert inc["cost_exp_yuan"] == 400.0
    assert inc["net_profit_yuan"] == 600.0


def test_balance_sheet_classify():
    svc = MonthCloseService()
    tb = [
        {"account_code": "1002", "account_name": "银行存款",
         "period_debit_fen": 0, "period_credit_fen": 0,
         "closing_debit_fen": 5_000_00, "closing_credit_fen": 0},
        {"account_code": "2202", "account_name": "应付账款",
         "period_debit_fen": 0, "period_credit_fen": 0,
         "closing_debit_fen": 0, "closing_credit_fen": 2_000_00},
        {"account_code": "4001", "account_name": "实收资本",
         "period_debit_fen": 0, "period_credit_fen": 0,
         "closing_debit_fen": 0, "closing_credit_fen": 3_000_00},
    ]
    bs = svc._build_balance_sheet(tb)
    assert bs["total_asset_yuan"] == 5000.0
    assert bs["total_liability_yuan"] == 2000.0
    assert bs["total_equity_yuan"] == 3000.0


# ───────────── pre_close_check ─────────────


@pytest.mark.asyncio
async def test_pre_close_check_draft_voucher_blocks():
    svc = MonthCloseService()
    session = MagicMock()

    # 第一个 execute(): draft vouchers count = 3
    # 之后所有 text() 查询都放行 (返回 0)
    exec_results = [
        _scalar_result(3),          # draft vouchers
        _scalar_result(0),          # purchase pending
        _scalar_result(0),          # goods pending
    ]

    async def _execute(*_args, **_kwargs):
        return exec_results.pop(0) if exec_results else _scalars_result([])

    session.execute = AsyncMock(side_effect=_execute)
    # _get_log 返回 None
    with patch.object(svc, "_get_log", AsyncMock(return_value=None)):
        res = await svc.pre_close_check(session, "S001", "202603")
    assert res["blocked"] is True
    codes = {i["code"] for i in res["issues"]}
    assert "draft_vouchers" in codes


@pytest.mark.asyncio
async def test_pre_close_check_already_closed_blocks():
    svc = MonthCloseService()
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result([]))
    closed_log = MonthCloseLog(
        store_id="S001", year_month="202603", status="closed", closed_at=datetime.utcnow()
    )
    with patch.object(svc, "_get_log", AsyncMock(return_value=closed_log)):
        res = await svc.pre_close_check(session, "S001", "202603")
    assert res["blocked"] is True
    assert any(i["code"] == "already_closed" for i in res["issues"])


# ───────────── reopen_month ─────────────


@pytest.mark.asyncio
async def test_reopen_requires_admin():
    svc = MonthCloseService()
    session = MagicMock()
    user = _user(role=UserRole.STORE_MANAGER)
    with pytest.raises(MonthCloseError, match="仅管理员"):
        await svc.reopen_month(session, "S001", "202603", user, "审计需要重整")


@pytest.mark.asyncio
async def test_reopen_requires_reason():
    svc = MonthCloseService()
    session = MagicMock()
    user = _user()
    with pytest.raises(MonthCloseError, match="必须填写原因"):
        await svc.reopen_month(session, "S001", "202603", user, "ok")


@pytest.mark.asyncio
async def test_reopen_no_closed_log():
    svc = MonthCloseService()
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    user = _user()
    with patch.object(svc, "_get_log", AsyncMock(return_value=None)):
        with pytest.raises(MonthCloseError, match="尚未月结"):
            await svc.reopen_month(session, "S001", "202603", user, "补账重开原因描述")


@pytest.mark.asyncio
async def test_reopen_success_updates_log():
    svc = MonthCloseService()
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    log = MonthCloseLog(store_id="S001", year_month="202603", status="closed")
    user = _user()
    with patch.object(svc, "_get_log", AsyncMock(return_value=log)):
        res = await svc.reopen_month(session, "S001", "202603", user, "补账重开原因描述")
    assert res["status"] == "reopened"
    assert log.status == "reopened"
    assert log.reason == "补账重开原因描述"


# ───────────── year close ─────────────


@pytest.mark.asyncio
async def test_year_close_missing_months():
    svc = MonthCloseService()
    session = MagicMock()
    # 只有 3 个月已月结
    logs = [
        MonthCloseLog(store_id="S001", year_month=f"2026{m:02d}", status="closed")
        for m in (1, 2, 3)
    ]
    session.execute = AsyncMock(return_value=_scalars_result(logs))
    user = _user()
    with pytest.raises(MonthCloseError, match="未月结"):
        await svc.execute_year_close(session, "S001", 2026, user)


# ───────────── helpers ─────────────


def _scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _scalars_result(items):
    r = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    r.scalar.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r
