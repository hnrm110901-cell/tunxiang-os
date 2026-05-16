"""日期字符串解析工具 (跨服务复用).

设计意图: 把分散在 services/ 各 API 模块里手写的 YYYY-MM 解析逻辑统一到一处,
caller 各自决定 404 / 400 / graceful skip 等错误处理策略.

issue #699 follow-up.
"""

from __future__ import annotations


def parse_year_month(s: str) -> tuple[int, int] | None:
    """解析 YYYY-MM 月份字符串.

    返回 (year, month) 元组, month 范围 1-12. 任何畸形输入返回 None.

    Args:
        s: 期望格式 "YYYY-MM" (例 "2026-03").

    Returns:
        (year, month) 元组, 或 None.

    设计要点:
        - 不抛异常, caller 各自走原行为 (HTTP 400 / graceful skip).
        - 严格校验分隔符 '-' (避免 "202603" 等隐式 slice 通过).
        - 月份范围 1-12 (数学正确性, 与 `datetime.date(y, m, 1)` 一致).
        - 非字符串输入返回 None (防御性).
    """
    if not isinstance(s, str) or len(s) < 7:
        return None
    if s[4] != "-":
        return None
    try:
        year = int(s[:4])
        month = int(s[5:7])
    except ValueError:
        return None
    if month < 1 or month > 12:
        return None
    return year, month
