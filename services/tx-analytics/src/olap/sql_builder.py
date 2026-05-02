"""OLAP 动态 SQL 构建器

根据 Cube 定义和 OLAPQuery 请求，生成参数化 SQL 语句。
核心原则：
  - 所有值通过参数绑定（:param），绝不使用 f-string 拼接用户值
  - 自动追加 tenant_id 筛选
  - 支持 ROLLUP / GROUPING SETS 增强聚合
  - 支持下钻层级展开
"""

from __future__ import annotations

import re
from typing import Any

from .engine import AggFunction, OLAPQuery

# SQL 标识符安全校验正则（防御深度层）
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def build_olap_sql(
    cube_def: dict[str, Any],
    query: OLAPQuery,
    all_dimensions: list[str],
) -> tuple[str, dict[str, Any]]:
    """构建参数化 OLAP 查询 SQL

    Args:
        cube_def: Cube 定义 dict（含 measures, dimensions, source）
        query: OLAP 查询请求
        all_dimensions: 已展开下钻路径后的完整维度列表

    Returns:
        (sql_string, params_dict) — sql 使用 :param 占位符，params 为绑定值
    """
    source_table = cube_def["source"]
    measures = {m["name"]: m for m in cube_def["measures"]}
    dimensions = {d["name"]: d for d in cube_def["dimensions"]}
    params: dict[str, Any] = {}
    param_counter = [0]  # 可变计数器，用 list 包装以便在闭包中修改

    def next_param(prefix: str = "p") -> str:
        """生成唯一参数名"""
        param_counter[0] += 1
        return f"{prefix}_{param_counter[0]}"

    # ── SELECT 子句 ──────────────────────────────────────────────────────

    select_parts: list[str] = []

    # 维度列
    for dim_name in all_dimensions:
        dim_def = dimensions[dim_name]
        alias = dim_name
        select_parts.append(f"{dim_def['source_field']} AS {alias}")

    # 度量列
    for measure_name in query.measures:
        m = measures[measure_name]
        agg_fn = m["aggregation"]
        expr = m["source_expression"]
        alias = measure_name

        if agg_fn == AggFunction.COUNT_DISTINCT.value:
            select_parts.append(f"COUNT(DISTINCT {expr}) AS {alias}")
        else:
            select_parts.append(f"{agg_fn}({expr}) AS {alias}")

    select_clause = ",\n       ".join(select_parts)

    # ── FROM 子句 ────────────────────────────────────────────────────────

    from_clause = source_table

    # ── WHERE 子句（含 tenant_id + 用户筛选） ────────────────────────────

    where_parts: list[str] = []

    # 自动追加 tenant_id 筛选 — 始终生效
    tenant_param = next_param("tenant")
    where_parts.append(f"tenant_id = :{tenant_param}")
    params[tenant_param] = None  # 运行时由调用方替换（见 engine.py）

    # 用户筛选条件
    for i, filt in enumerate(query.filters):
        cond_sql, cond_params = _build_filter_condition(filt, dimensions, next_param, i)
        where_parts.append(cond_sql)
        params.update(cond_params)

    where_clause = " AND ".join(where_parts)

    # ── GROUP BY 子句 ────────────────────────────────────────────────────

    group_parts: list[str] = []
    for idx, dim_name in enumerate(all_dimensions):
        group_parts.append(str(idx + 1))  # GROUP BY 用列序号，简洁

    group_by_clause = ", ".join(group_parts)

    # 如果有下钻路径，使用 GROUPING SETS 支持上卷
    if query.drill_path and len(query.drill_path) > 1:
        group_by_clause = _build_grouping_sets(all_dimensions)

    # ── HAVING 子句 ──────────────────────────────────────────────────────
    # OLAP 查询暂不强制 HAVING，但预留扩展点
    having_clause: str | None = None

    # ── ORDER BY 子句 ──────────────────────────────────────────────────

    order_parts: list[str] = []
    if query.order_by:
        for sort in query.order_by:
            direction = sort.direction.upper()
            # 排序字段可能在度量或维度中
            if sort.field in measures:
                order_parts.append(f"{sort.field} {direction}")
            elif sort.field in dimensions:
                order_parts.append(f"{sort.field} {direction}")
    else:
        # 默认按第一个维度升序
        if all_dimensions:
            order_parts.append(f"{all_dimensions[0]} ASC")

    order_clause = ", ".join(order_parts)

    # ── LIMIT / OFFSET ───────────────────────────────────────────────────

    limit_param = next_param("limit")
    offset_param = next_param("offset")
    params[limit_param] = query.limit
    params[offset_param] = query.offset

    # ── 组装完整 SQL ─────────────────────────────────────────────────────

    sql = (
        f"SELECT {select_clause}\n"
        f"FROM {from_clause}\n"
        f"WHERE {where_clause}"
    )

    if group_by_clause:
        sql += f"\nGROUP BY {group_by_clause}"

    if having_clause:
        sql += f"\nHAVING {having_clause}"

    if order_clause:
        sql += f"\nORDER BY {order_clause}"

    sql += f"\nLIMIT :{limit_param} OFFSET :{offset_param}"

    return sql, params


# ─── Filter Helper ──────────────────────────────────────────────────────────


def _build_filter_condition(
    filt: Any,  # FilterDef
    dimensions: dict[str, dict],
    next_param: Any,
    filter_index: int,
) -> tuple[str, dict[str, Any]]:
    """将单个 FilterDef 转换为 WHERE 条件片段 + 参数

    所有值通过 :param 占位符绑定，绝不拼接到 SQL 字符串中。
    """
    params: dict[str, Any] = {}

    # 将筛选字段名解析为实际的 source_field
    dim_def = dimensions.get(filt.field)
    if dim_def is None:
        # 防御深度：回退路径必须通过标识符安全校验
        if not _SAFE_IDENTIFIER_RE.match(filt.field):
            raise ValueError(
                f"Invalid filter field identifier: {filt.field!r}"
            )
        source_field = filt.field
    else:
        source_field = dim_def["source_field"]

    op = filt.operator

    if op == "is_null":
        return f"{source_field} IS NULL", params

    if op == "is_not_null":
        return f"{source_field} IS NOT NULL", params

    if op == "between":
        p1 = next_param(f"fv_{filter_index}_lo")
        p2 = next_param(f"fv_{filter_index}_hi")
        params[p1] = filt.value
        params[p2] = filt.value2
        return f"{source_field} BETWEEN :{p1} AND :{p2}", params

    if op == "in":
        values = filt.value
        if not isinstance(values, (list, tuple)):
            values = [values]
        placeholders: list[str] = []
        for idx, val in enumerate(values):
            p = next_param(f"fv_{filter_index}_{idx}")
            params[p] = val
            placeholders.append(f":{p}")
        in_list = ", ".join(placeholders)
        return f"{source_field} IN ({in_list})", params

    if op == "not_in":
        values = filt.value
        if not isinstance(values, (list, tuple)):
            values = [values]
        placeholders = []
        for idx, val in enumerate(values):
            p = next_param(f"fv_{filter_index}_{idx}")
            params[p] = val
            placeholders.append(f":{p}")
        in_list = ", ".join(placeholders)
        return f"{source_field} NOT IN ({in_list})", params

    # 单值操作符: eq, neq, gt, gte, lt, lte, like
    p = next_param(f"fv_{filter_index}")
    params[p] = filt.value

    op_map: dict[str, str] = {
        "eq": "=",
        "neq": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "like": "LIKE",
    }
    sql_op = op_map.get(op, "=")

    return f"{source_field} {sql_op} :{p}", params


# ─── GROUPING SETS Helper ──────────────────────────────────────────────────


def _build_grouping_sets(all_dimensions: list[str]) -> str:
    """为多层钻取路径生成 GROUPING SETS 子句

    例如 dimensions=[year, month, day]:
        GROUP BY GROUPING SETS ((year, month, day), (year, month), (year), ())

    这样单次查询即可获得所有上卷级别的聚合值。
    """
    n = len(all_dimensions)
    sets: list[str] = []

    # 从最细粒度到最粗粒度（包括空集 = 总计行）
    for i in range(n, -1, -1):
        subset = all_dimensions[:i]
        if subset:
            nums = [str(idx + 1) for idx in range(i)]
            sets.append(f"({', '.join(nums)})")
        else:
            # 空集 = 全局总计
            sets.append("()")

    return "GROUPING SETS (" + ", ".join(sets) + ")"
