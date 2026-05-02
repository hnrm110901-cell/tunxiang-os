"""透视表处理 — 将平面查询结果转为交叉表（行 x 列）

适用场景：业务用户拖拽"门店"到行、"月份"到列、"营收"到值时，
将平面 GROUP BY 结果转换为二维交叉表便于展示。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional


class PivotConfig:
    """透视表配置"""

    def __init__(
        self,
        row_field_id: str,
        col_field_id: str,
        value_field_id: str,
        include_totals: bool = True,
        include_percentages: bool = False,
    ):
        self.row_field_id = row_field_id
        self.col_field_id = col_field_id
        self.value_field_id = value_field_id
        self.include_totals = include_totals
        self.include_percentages = include_percentages


def pivot_result(
    columns: list[dict],
    rows: list[list[Any]],
    col_field_id: str,
    value_field_id: str,
    include_totals: bool = True,
    include_percentages: bool = False,
) -> dict:
    """将平面查询结果转为透视表格式。

    输入:
      columns: 列元数据列表
      rows: 数据行（list[list]）
      col_field_id: 列维度 field_id
      value_field_id: 度量 field_id
      include_totals: 是否包含合计
      include_percentages: 是否包含占比

    返回:
      {
        "row_headers": ["南山店", "福田店", ...],
        "column_headers": ["1月", "2月", "3月", ...],
        "data": [[100, 200, 300], [150, 250, 350], ...],
        "totals": {"row": [600, 750, ...], "col": [250, 450, 650, ...]},
        "percentages": [[...], ...]  // if include_percentages
      }
    """
    if not columns or not rows:
        return {
            "row_headers": [],
            "column_headers": [],
            "data": [],
        }

    # 找到列和值在 columns 中的索引
    col_alias = f'_cdim_{col_field_id}' if not col_field_id.startswith('_') else col_field_id
    val_alias = f'_{value_field_id}'
    # 也有可能是 _dim_ 前缀
    dim_col_alias = f'_dim_{col_field_id}'

    col_idx = None
    val_idx = None
    row_labels: list[str] = []

    for i, c in enumerate(columns):
        name = c.get("name", "")
        if name in (col_alias, dim_col_alias):
            col_idx = i
        elif name == val_alias:
            val_idx = i
        else:
            # 第一个非列/非值的列为行维度
            if not name.startswith(f'_cdim_') and col_idx is not None:
                row_labels.append(c.get("label", name))

    if col_idx is None or val_idx is None:
        # 回退：按位置推断
        # 第一列 = 行维度，第二列 = 列维度，第三列 = 值
        if len(columns) >= 3:
            col_idx = 1
            val_idx = 2
            row_labels = [columns[0].get("label", columns[0].get("name", "row"))]
        else:
            return {
                "row_headers": [],
                "column_headers": [],
                "data": [],
                "error": "无法确定透视维度，需要至少 3 列（行、列、值）",
            }

    # 构建交叉表数据
    pivot_data: dict[Any, dict[Any, Any]] = defaultdict(lambda: defaultdict(lambda: 0))

    for row in rows:
        row_key = row[0] if row else None
        col_key = row[col_idx] if len(row) > col_idx else None
        val = row[val_idx] if len(row) > val_idx else 0

        if row_key is not None and col_key is not None:
            pivot_data[row_key][col_key] = val

    # 收集去重的行头和列头
    row_headers_unique = list(pivot_data.keys())
    col_headers_set: set = set()
    for row_dict in pivot_data.values():
        col_headers_set.update(row_dict.keys())
    col_headers_unique = sorted(col_headers_set, key=str)

    # 将行头转为可读字符串
    row_headers = [str(r) for r in row_headers_unique]
    column_headers = [str(c) for c in col_headers_unique]

    # 构建数据矩阵
    data = []
    row_totals = []
    for rk in row_headers_unique:
        row_data = []
        row_sum = 0
        for ck in col_headers_unique:
            v = pivot_data[rk].get(ck, 0)
            row_data.append(v)
            row_sum += (v if isinstance(v, (int, float)) else 0)
        data.append(row_data)
        row_totals.append(row_sum)

    # 列合计
    col_totals = []
    for ci, ck in enumerate(col_headers_unique):
        col_sum = sum(data[ri][ci] for ri in range(len(row_headers_unique)))
        col_totals.append(col_sum)

    result: dict[str, Any] = {
        "row_headers": row_headers,
        "column_headers": column_headers,
        "data": data,
    }

    if include_totals:
        result["totals"] = {
            "row": row_totals,
            "col": col_totals,
        }

    if include_percentages and col_totals:
        grand_total = sum(col_totals)
        if grand_total > 0:
            percentages = []
            for row_data in data:
                pct_row = [
                    round(v / grand_total * 100, 1) if isinstance(v, (int, float)) and v > 0 else 0
                    for v in row_data
                ]
                percentages.append(pct_row)
            result["percentages"] = percentages

    return result


def pivot_from_config(
    result_columns: list[dict],
    result_rows: list[list[Any]],
    pivot_config: PivotConfig,
) -> dict:
    """从 PivotConfig 生成透视表。

    这是 pivot_result 的包装，自动从配置中提取参数。
    """
    return pivot_result(
        columns=result_columns,
        rows=result_rows,
        col_field_id=pivot_config.col_field_id,
        value_field_id=pivot_config.value_field_id,
        include_totals=pivot_config.include_totals,
        include_percentages=pivot_config.include_percentages,
    )
