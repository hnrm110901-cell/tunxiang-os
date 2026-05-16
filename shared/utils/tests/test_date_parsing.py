"""shared.utils.date_parsing 单元测试.

覆盖 parse_year_month() 正常 / 边界 / 畸形输入. issue #699 follow-up.
"""

from __future__ import annotations

import pytest

from shared.utils.date_parsing import parse_year_month


# ── 正常路径 ─────────────────────────────────────────────────────────────────


def test_parse_year_month_basic() -> None:
    assert parse_year_month("2026-03") == (2026, 3)


def test_parse_year_month_january() -> None:
    assert parse_year_month("2026-01") == (2026, 1)


def test_parse_year_month_december() -> None:
    assert parse_year_month("2026-12") == (2026, 12)


def test_parse_year_month_distant_year() -> None:
    """年份纯数字, 无范围限制 (caller 决定业务范围)."""
    assert parse_year_month("1900-06") == (1900, 6)
    assert parse_year_month("2099-06") == (2099, 6)


def test_parse_year_month_extra_trailing_chars_ignored() -> None:
    """长输入只取前 7 位, 与原 `month[:4] + month[5:7]` slice 语义一致."""
    assert parse_year_month("2026-03-15") == (2026, 3)
    assert parse_year_month("2026-03T00:00:00") == (2026, 3)


# ── 边界 / 畸形 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        "",  # 空串
        "20",  # 太短
        "2026",  # 缺月份
        "2026-",  # 缺月份数字
        "2026-3",  # 月份只有 1 位 (len < 7)
    ],
)
def test_parse_year_month_too_short(bad: str) -> None:
    assert parse_year_month(bad) is None


@pytest.mark.parametrize(
    "bad",
    [
        "2026/03",  # 错误分隔符
        "202603 ",  # 无分隔符
        "2026.03",  # 错误分隔符
        "abcd-03",  # year 非数字
        "2026-ab",  # month 非数字
        "2026-00",  # month=0
        "2026-13",  # month=13
        "2026-99",  # month=99
    ],
)
def test_parse_year_month_malformed(bad: str) -> None:
    assert parse_year_month(bad) is None


def test_parse_year_month_fullwidth_chars() -> None:
    """全角数字不应被 int() 接受 (实际上 Python int 接受全角, 但分隔符校验先 fail)."""
    # 全角分隔符
    assert parse_year_month("2026－03") is None


@pytest.mark.parametrize(
    "non_str",
    [
        None,
        42,
        ["2026", "03"],
        ("2026", "03"),
        {"year": 2026, "month": 3},
    ],
)
def test_parse_year_month_non_string(non_str: object) -> None:
    assert parse_year_month(non_str) is None  # type: ignore[arg-type]
