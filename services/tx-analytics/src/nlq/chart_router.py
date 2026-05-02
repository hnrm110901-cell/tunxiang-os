"""图表类型智能路由（BI-1.3）

根据查询结果的列数、行数、数据类型，自动选择最佳图表类型。
"""

from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# 数据特征检测
# ---------------------------------------------------------------------------


def _count_numeric_columns(columns: list[str], rows: list[list]) -> int:
    if not rows or not rows[0]:
        return 0
    count = 0
    for i in range(len(columns)):
        try:
            float(rows[0][i])
            count += 1
        except (ValueError, TypeError):
            pass
    return count


def _count_text_columns(columns: list[str], rows: list[list]) -> int:
    if not rows or not rows[0]:
        return 0
    count = 0
    for i in range(len(columns)):
        try:
            float(rows[0][i])
        except (ValueError, TypeError):
            count += 1
    return count


def _has_time_column(columns: list[str], rows: list[list]) -> bool:
    """检测列名是否看起来像时间维度"""
    time_hints = ("date", "time", "月", "日", "hour", "week", "biz_date", "created", "month", "day")
    for col in columns:
        col_lower = col.lower()
        if any(hint in col_lower for hint in time_hints):
            return True
    return False


def _is_single_number(columns: list[str], rows: list[list]) -> bool:
    return len(rows) == 1 and len(columns) == 1 and _count_numeric_columns(columns, rows) == 1


def _is_single_dim_single_measure(columns: list[str], rows: list[list]) -> bool:
    return (
        len(columns) >= 2
        and _count_text_columns(columns, rows) >= 1
        and _count_numeric_columns(columns, rows) >= 1
    )


def _is_heatmap(columns: list[str], rows: list[list]) -> bool:
    return (
        len(columns) >= 3
        and _count_text_columns(columns, rows) >= 2
        and _count_numeric_columns(columns, rows) >= 1
    )


# ---------------------------------------------------------------------------
# 主路由函数
# ---------------------------------------------------------------------------


def select_chart_type(
    intent: str = "",
    columns: list[str] | None = None,
    rows: list[list] | None = None,
    explicit_chart: Optional[str] = None,
) -> str:
    """根据数据特征和意图，选择最佳图表类型。

    返回：metric | bar | line | pie | table | heatmap | scatter | comparison | gauge

    规则优先级：
    1. 显式指定 > 自动检测
    2. 单行单值 → metric
    3. 时间维 + 度量 → line
    4. 1 文本维 + 1 数值, <= 10 行 → bar/pie
    5. 1 文本维 + 1 数值, > 10 行 → bar
    6. 2 文本维 + 数值 → heatmap
    7. 多度量 → table
    """
    # 如果调用方已指定图表类型，直接使用
    if explicit_chart:
        return explicit_chart

    # 从 intent 推导默认类型
    intent_chart_map: dict[str, str] = {
        "comparison": "comparison",
        "gauge": "gauge",
        "scatter": "scatter",
        "heatmap": "heatmap",
    }
    for key, val in intent_chart_map.items():
        if key in intent.lower():
            return val

    # 无数据时回退
    if not columns or not rows:
        return "table"

    columns = columns or []
    rows = rows or []

    # 单行单列 → 大数字
    if _is_single_number(columns, rows):
        return "metric"

    row_count = len(rows)
    text_cols = _count_text_columns(columns, rows)
    num_cols = _count_numeric_columns(columns, rows)
    has_time = _has_time_column(columns, rows)

    # 时间维度 + 数值 → 趋势折线图
    if has_time and num_cols >= 1:
        return "line"

    # 2+ 文本维度 → 热力图
    if text_cols >= 2 and num_cols >= 1:
        return "heatmap"

    # 1 文本维 + 1 数值
    if text_cols >= 1 and num_cols == 1:
        if row_count <= 5:
            return "pie"
        return "bar"

    # 多数值列 → 表格
    if num_cols >= 2:
        return "table"

    # 默认
    return "table"


# ---------------------------------------------------------------------------
# 批量路由（用于对比展示）
# ---------------------------------------------------------------------------


def suggest_chart_options(
    columns: list[str],
    rows: list[list],
) -> list[dict[str, Any]]:
    """返回多个图表选项及匹配分数，供前端用户选择。

    返回格式：[{ "type": str, "score": float, "label": str }, ...]
    """
    options: list[dict[str, Any]] = []

    row_count = len(rows)
    text_cols = _count_text_columns(columns, rows)
    num_cols = _count_numeric_columns(columns, rows)
    has_time = _has_time_column(columns, rows)

    # 大数字
    if row_count == 1 and num_cols == 1:
        options.append({"type": "metric", "score": 1.0, "label": "大数字"})

    # 折线图
    if has_time and num_cols >= 1:
        options.append({"type": "line", "score": 0.9, "label": "折线图"})

    # 柱状图
    if text_cols >= 1 and num_cols >= 1:
        options.append({"type": "bar", "score": 0.8, "label": "柱状图"})

    # 饼图
    if text_cols >= 1 and num_cols == 1 and row_count <= 10:
        options.append({"type": "pie", "score": 0.7, "label": "饼图"})

    # 热力图
    if text_cols >= 2 and num_cols >= 1:
        options.append({"type": "heatmap", "score": 0.6, "label": "热力图"})

    # 表格（万能回退）
    options.append({"type": "table", "score": 0.5, "label": "表格"})

    return sorted(options, key=lambda o: o["score"], reverse=True)
