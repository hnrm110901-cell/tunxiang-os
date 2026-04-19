"""薪税申报服务测试 — tax_filing_service.py

覆盖:
- 纯工具函数：_parse_period / _mask_id_card / _iso_utc
- 主流程：generate_tax_declaration / submit_to_tax_bureau / check_filing_status
- 历史查询：get_filing_history
- 年度汇总：get_annual_summary (12 个月填充 / 越界年份)
- 重试：retry_filing (仅 rejected 可重试)
- 统计：get_filing_stats

通过 AsyncMock 模拟 AsyncSession + monkeypatch 替换 _sdk，无真实 DB 依赖。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# 确保 src 目录在导入路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services import tax_filing_service as tfs
from services.tax_filing_service import (
    TAX_FILING_STATUS,
    _iso_utc,
    _mask_id_card,
    _parse_period,
    check_filing_status,
    generate_tax_declaration,
    get_annual_summary,
    get_filing_history,
    get_filing_stats,
    retry_filing,
    submit_to_tax_bureau,
)

TENANT_ID = str(uuid4())
STORE_ID = str(uuid4())
EMP_ID = str(uuid4())
DECL_ID = str(uuid4())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


def _mk_result(
    one_or_none: dict | None = None,
    all_rows: list[dict] | None = None,
    scalar_value=None,
    one: dict | None = None,
) -> MagicMock:
    result = MagicMock()
    mappings = MagicMock()
    mappings.one_or_none = MagicMock(return_value=one_or_none)
    mappings.all = MagicMock(return_value=all_rows or [])
    mappings.one = MagicMock(return_value=one or {})
    result.mappings = MagicMock(return_value=mappings)
    result.scalar_one = MagicMock(return_value=scalar_value)
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 纯工具函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_parse_period_normal():
    """解析 YYYY-MM 正常格式"""
    assert _parse_period("2026-04") == (2026, 4)
    assert _parse_period("2026-12") == (2026, 12)


def test_parse_period_invalid_format_raises():
    """缺少分隔符时报错"""
    with pytest.raises(ValueError, match="月份格式"):
        _parse_period("202604")


def test_parse_period_out_of_range_raises():
    """年份越界（<2020 或 >2099）报错，月份>12 报错"""
    with pytest.raises(ValueError, match="越界"):
        _parse_period("1999-05")
    with pytest.raises(ValueError, match="越界"):
        _parse_period("2026-13")


def test_mask_id_card_normal():
    """18 位身份证：前 4 + 中间 10 个星 + 后 4"""
    masked = _mask_id_card("110101199001011234")
    assert masked == "1101**********1234"
    assert len(masked) == 18


def test_mask_id_card_short_returns_stars():
    """<=8 位直接打码为 ****"""
    assert _mask_id_card("12345678") == "****"
    assert _mask_id_card("") == ""
    assert _mask_id_card(None) == ""


def test_iso_utc_handles_naive_and_none():
    """naive datetime 补上 utc，None 返回 None"""
    assert _iso_utc(None) is None
    naive = datetime(2026, 4, 1, 12, 0, 0)
    out = _iso_utc(naive)
    assert out is not None and out.endswith("+00:00")


def test_tax_filing_status_labels():
    """六种状态 label 存在"""
    for k in ("draft", "generated", "submitted", "accepted", "rejected", "completed"):
        assert k in TAX_FILING_STATUS


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 生成申报数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_generate_tax_declaration_store_not_found_raises():
    """门店不存在时报错"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=None)]
    with pytest.raises(ValueError, match="门店不存在"):
        await generate_tax_declaration(db, TENANT_ID, STORE_ID, "2026-04")


@pytest.mark.asyncio
async def test_generate_tax_declaration_success():
    """成功生成：汇总税额 = 每位员工税额之和"""
    db = _make_db()
    store_row = {"store_name": "长沙一店"}
    # 一条 payroll：gross=10000 net=7000 social=2000 hf=500 => tax = 500
    payroll_rows = [
        {
            "employee_id": uuid4(), "emp_name": "张三", "id_card_no": "110101199001011234",
            "gross_salary_fen": 10000, "month_tax_fen": 500,
            "cum_gross_fen": 10000, "cum_tax_fen": 500,
        },
        {
            "employee_id": uuid4(), "emp_name": "李四", "id_card_no": "110101199202022345",
            "gross_salary_fen": 20000, "month_tax_fen": 1500,
            "cum_gross_fen": 20000, "cum_tax_fen": 1500,
        },
    ]
    insert_result = MagicMock()
    insert_result.scalar_one = MagicMock(return_value=DECL_ID)
    db.execute.side_effect = [
        MagicMock(),                                # set_config
        _mk_result(one_or_none=store_row),          # 查门店
        _mk_result(all_rows=payroll_rows),          # 查 payroll
        insert_result,                              # INSERT RETURNING id
    ]
    out = await generate_tax_declaration(db, TENANT_ID, STORE_ID, "2026-04")
    assert out["declaration_id"] == DECL_ID
    assert out["month"] == "2026-04"
    assert out["store_name"] == "长沙一店"
    assert out["employee_count"] == 2
    assert out["total_tax_fen"] == 2000  # 500 + 1500
    # 身份证应打码
    assert "****" in out["employees"][0]["id_card_no_masked"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 提交到税局
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_submit_not_found_raises():
    """申报记录不存在时报错"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=None)]
    with pytest.raises(ValueError, match="申报记录不存在"):
        await submit_to_tax_bureau(db, TENANT_ID, DECL_ID)


@pytest.mark.asyncio
async def test_submit_wrong_status_raises():
    """状态非 generated/rejected 时报错"""
    db = _make_db()
    row = {"month": "2026-04", "declaration_data": "{}", "status": "submitted"}
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row)]
    with pytest.raises(ValueError, match="不可提交"):
        await submit_to_tax_bureau(db, TENANT_ID, DECL_ID)


@pytest.mark.asyncio
async def test_submit_success(monkeypatch):
    """成功提交：调用 SDK 并更新状态"""
    db = _make_db()
    row = {
        "month": "2026-04",
        "declaration_data": '{"employees": [{"employee_id": "e1"}]}',
        "status": "generated",
    }
    upd_result = MagicMock()
    upd_result.scalar_one = MagicMock(return_value=DECL_ID)
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row), upd_result]

    # Mock SDK
    fake_sdk_result = {
        "status": "accepted", "task_id": "T12345", "accepted_count": 1, "rejected": [],
    }
    monkeypatch.setattr(tfs._sdk, "submit_monthly_declaration",
                        AsyncMock(return_value=fake_sdk_result))
    out = await submit_to_tax_bureau(db, TENANT_ID, DECL_ID)
    assert out["status"] == "submitted"
    assert out["receipt_no"] == "T12345"
    assert out["accepted_count"] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 查询状态
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_check_filing_status_not_found_raises():
    """申报记录不存在时报错"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=None)]
    with pytest.raises(ValueError, match="申报记录不存在"):
        await check_filing_status(db, TENANT_ID, DECL_ID)


@pytest.mark.asyncio
async def test_check_filing_status_returns_status():
    """查询返回状态与回执号"""
    db = _make_db()
    submitted_at = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
    row = {"status": "submitted", "receipt_no": "R001", "submitted_at": submitted_at}
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row)]
    out = await check_filing_status(db, TENANT_ID, DECL_ID)
    assert out["status"] == "submitted"
    assert out["receipt_no"] == "R001"
    assert out["submitted_at"] is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 历史记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_filing_history_empty():
    """无历史记录时返回空列表"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(all_rows=[])]
    out = await get_filing_history(db, TENANT_ID, STORE_ID, 2026)
    assert out == []


@pytest.mark.asyncio
async def test_get_filing_history_returns_list():
    """返回历史列表，按月份降序"""
    db = _make_db()
    rows = [
        {
            "declaration_id": uuid4(), "month": "2026-04", "store_name": "一店",
            "employee_count": 10, "total_tax_fen": 50000, "status": "submitted",
            "submitted_at": datetime(2026, 4, 20, tzinfo=timezone.utc),
        },
        {
            "declaration_id": uuid4(), "month": "2026-03", "store_name": "一店",
            "employee_count": 9, "total_tax_fen": 40000, "status": "completed",
            "submitted_at": datetime(2026, 3, 22, tzinfo=timezone.utc),
        },
    ]
    db.execute.side_effect = [MagicMock(), _mk_result(all_rows=rows)]
    out = await get_filing_history(db, TENANT_ID, STORE_ID, 2026)
    assert len(out) == 2
    assert out[0]["total_tax_fen"] == 50000
    assert out[1]["status"] == "completed"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 年度汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_annual_summary_year_out_of_range():
    """年度越界报错"""
    db = _make_db()
    with pytest.raises(ValueError, match="年度越界"):
        await get_annual_summary(db, TENANT_ID, EMP_ID, 2010)


@pytest.mark.asyncio
async def test_get_annual_summary_employee_not_found():
    """员工不存在时报错"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=None)]
    with pytest.raises(ValueError, match="员工不存在"):
        await get_annual_summary(db, TENANT_ID, EMP_ID, 2026)


@pytest.mark.asyncio
async def test_get_annual_summary_fills_12_months():
    """年度汇总始终返回 12 条月度记录（缺失月份填 0）"""
    db = _make_db()
    emp_row = {"emp_name": "张三"}
    # 仅 2 个月有数据
    payroll_rows = [
        {
            "period_month": 1, "gross_salary_fen": 10000, "net_salary_fen": 7000,
            "social_insurance_fen": 2000, "housing_fund_fen": 500,
        },  # tax = 500
        {
            "period_month": 3, "gross_salary_fen": 20000, "net_salary_fen": 15000,
            "social_insurance_fen": 3500, "housing_fund_fen": 1000,
        },  # tax = 500
    ]
    db.execute.side_effect = [
        MagicMock(),
        _mk_result(one_or_none=emp_row),
        _mk_result(all_rows=payroll_rows),
    ]
    out = await get_annual_summary(db, TENANT_ID, EMP_ID, 2026)
    assert out["year"] == 2026
    assert len(out["months"]) == 12
    # 1 月 500 + 3 月 500 = 1000
    assert out["total_tax_fen"] == 1000
    assert out["total_taxable_fen"] == 30000
    # 缺失的 2 月应为 0
    feb = out["months"][1]
    assert feb["month"] == "2026-02"
    assert feb["tax_fen"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 重试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_retry_filing_wrong_status_raises():
    """非 rejected 状态不可重试"""
    db = _make_db()
    row = {"month": "2026-04", "declaration_data": "{}", "status": "generated"}
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row)]
    with pytest.raises(ValueError, match="不可重试"):
        await retry_filing(db, TENANT_ID, DECL_ID)


@pytest.mark.asyncio
async def test_retry_filing_success(monkeypatch):
    """rejected 状态重试成功"""
    db = _make_db()
    row = {
        "month": "2026-04",
        "declaration_data": '{"employees": []}',
        "status": "rejected",
    }
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row), MagicMock()]
    fake = {"status": "accepted", "task_id": "T002", "accepted_count": 0, "rejected": []}
    monkeypatch.setattr(tfs._sdk, "submit_monthly_declaration", AsyncMock(return_value=fake))
    out = await retry_filing(db, TENANT_ID, DECL_ID)
    assert out["status"] == "submitted"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_filing_stats_returns_counts():
    """统计返回 filed_months / total_tax_fen / total_headcount"""
    db = _make_db()
    row = {"filed_months": 3, "total_tax_fen": 150000, "total_headcount": 30}
    db.execute.side_effect = [MagicMock(), _mk_result(one=row)]
    out = await get_filing_stats(db, TENANT_ID, 2026)
    assert out["year"] == 2026
    assert out["filed_months"] == 3
    assert out["total_tax_fen"] == 150000
    assert out["total_headcount"] == 30


@pytest.mark.asyncio
async def test_get_filing_stats_default_year_is_current():
    """year 缺省使用当前 UTC 年份"""
    db = _make_db()
    row = {"filed_months": 0, "total_tax_fen": 0, "total_headcount": 0}
    db.execute.side_effect = [MagicMock(), _mk_result(one=row)]
    out = await get_filing_stats(db, TENANT_ID)
    assert out["year"] == datetime.now(timezone.utc).year
