"""issue #710 YYYY-MM dedup Phase 2 Lane C — tx-agent helper regression tests.

直接测 parse_year_month helper, 不 import service module (banquet_growth_agent.py
含 Python 3.10+ `|` type hint, 测试环境 3.9 兼容性问题). Service 替换是 trivial 5 行,
信代码 review + helper 行为 test 覆盖.

Sites (by service review):
- banquet_growth_agent.py:41 (单 month 取 helper tuple [1] 项)
- agent_kpi_routes.py:1044 (route HTTPException 400)
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
