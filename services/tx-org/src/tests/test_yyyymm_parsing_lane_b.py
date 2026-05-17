"""issue #710 YYYY-MM dedup Phase 2 Lane B — tx-org helper regression tests.

直接测 parse_year_month helper 行为, 不 import service module (tx-org service 模块
有重 DB session / async 依赖). 7 个 service 文件的 9 sites 替换是 trivial pattern
(parse + None branch raise ValueError), 信代码 review + helper 行为 test 覆盖.

Sites (by service review):
- api/payslip.py:86 (_build_payslip helper, ValueError 上抛 FastAPI 422)
- services/attendance_compliance_service.py:1018 (raise ValueError)
- services/payroll_engine_v2.py:130 (raise ValueError, §17 薪资邻接)
- services/payroll_service.py:448-449 (合并成单 parse 调用, §17 薪资邻接)
- services/royalty_calculator.py:268, 709 (raise ValueError)
- services/store_ops_service.py:1008 (raise ValueError)
- services/transfer_cost_engine.py:286 (raise ValueError)
"""

from __future__ import annotations

from shared.utils.date_parsing import parse_year_month


def test_parse_year_month_valid() -> None:
    """合法 zero-padded YYYY-MM 返回 (year, month) tuple."""
    assert parse_year_month("2026-03") == (2026, 3)
    assert parse_year_month("2026-12") == (2026, 12)
    assert parse_year_month("2026-01") == (2026, 1)


def test_parse_year_month_single_digit_returns_none() -> None:
    """单数字月份 `2026-3` (len=6) 不接受 — issue #710 设计目标 zero-padded MM 严格化."""
    assert parse_year_month("2026-3") is None
    assert parse_year_month("2026-1") is None


def test_parse_year_month_malformed_returns_none() -> None:
    """畸形输入 (空 / 非日期 / 错分隔符 / 越界月份) 全返 None."""
    assert parse_year_month("") is None
    assert parse_year_month("abc") is None
    assert parse_year_month("2026/03") is None
    assert parse_year_month("2026-13") is None
    assert parse_year_month("2026-00") is None
