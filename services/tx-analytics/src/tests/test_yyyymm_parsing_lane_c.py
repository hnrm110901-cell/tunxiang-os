"""issue #710 YYYY-MM dedup Phase 2 Lane C — tx-analytics helper regression tests.

直接测 parse_year_month helper, 不 import service module (避开 SQLAlchemy / shared
模块加载副作用). Service 替换 (hq_brand_analytics_service.py:622) 是 try/except 整段
替换为 None branch raise ValueError, 语义等价, 信代码 review + helper 行为 test 覆盖.

Site (by service review):
- hq_brand_analytics_service.py:622 (raise ValueError on None)
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
