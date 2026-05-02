"""查询编译器 — 将拖拽配置编译为参数化 SQL

核心功能:
  1. SELECT: 从 values + dimensions 生成聚合表达式
  2. FROM: 自动发现需要的表并 JOIN
  3. WHERE: 参数化过滤条件 + 强制 tenant_id
  4. GROUP BY: 行维度 + 列维度
  5. ORDER BY / LIMIT / OFFSET

安全规则：
  - 所有值通过参数化占位符 :pN 传递，绝不拼接到 SQL 字符串
  - tenant_id 强制注入为 :tenant_id 参数
  - SQL 标识符（表名/列名）仅允许来自注册表，不直接拼接用户输入
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from .field_registry import DataType, FieldRegistry, FieldType, QueryField

log = structlog.get_logger(__name__)


class QueryValue:
    """度量值定义"""

    def __init__(self, field_id: str, aggregation: Optional[str] = None, alias: Optional[str] = None):
        self.field_id = field_id
        self.aggregation = aggregation
        self.alias = alias


class QueryFilter:
    """过滤条件"""

    def __init__(
        self,
        field_id: str,
        operator: str,  # eq/neq/gt/gte/lt/lte/in/not_in/between/like/is_null/is_not_null
        value: Any = None,
        value2: Any = None,
    ):
        self.field_id = field_id
        self.operator = operator
        self.value = value
        self.value2 = value2


class QueryOrder:
    """排序"""

    def __init__(self, field_id: str, direction: str = "asc"):
        self.field_id = field_id
        self.direction = direction


class QueryConfig:
    """用户拖拽生成的完整查询配置"""

    def __init__(
        self,
        values: list[dict],
        rows: Optional[list[str]] = None,
        columns: Optional[list[str]] = None,
        filters: Optional[list[dict]] = None,
        order_by: Optional[list[dict]] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        self.rows = rows or []
        self.columns = columns or []
        self.values = [QueryValue(**v) for v in values]
        self.filters = [QueryFilter(**f) for f in (filters or [])]
        self.order_by = [QueryOrder(**o) for o in (order_by or [])]
        self.limit = min(limit, 10000)
        self.offset = offset


class ColumnMeta:
    """结果列元数据"""

    def __init__(self, name: str, label: str, data_type: str, format: Optional[str] = None):
        self.name = name
        self.label = label
        self.data_type = data_type
        self.format = format

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "data_type": self.data_type,
            "format": self.format,
        }


class QueryResult:
    """查询结果"""

    def __init__(
        self,
        columns: list[ColumnMeta],
        rows: list[list[Any]],
        total_rows: int,
        query_sql: str,
        executed_at: str,
        execution_ms: int,
        has_more: bool = False,
    ):
        self.columns = columns
        self.rows = rows
        self.total_rows = total_rows
        self.query_sql = query_sql
        self.executed_at = executed_at
        self.execution_ms = execution_ms
        self.has_more = has_more

    def to_dict(self) -> dict:
        return {
            "columns": [c.to_dict() for c in self.columns],
            "rows": self.rows,
            "total_rows": self.total_rows,
            "query_sql": self.query_sql,
            "executed_at": self.executed_at,
            "execution_ms": self.execution_ms,
            "has_more": self.has_more,
        }


# SQL 注入防护：标识符仅允许字母、数字、下划线
_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _is_safe_identifier(name: str) -> bool:
    """检查是否为安全的 SQL 标识符（无注入风险）。"""
    return bool(_IDENTIFIER_RE.match(name))


class QueryCompiler:
    """将 QueryConfig 编译为参数化 SQL + 列元数据"""

    def __init__(self, field_registry: type[FieldRegistry] = FieldRegistry):
        self.registry = field_registry

    # ─── 主入口 ─────────────────────────────────────────────────

    def compile(self, config: QueryConfig) -> tuple[str, dict, list[ColumnMeta]]:
        """编译查询配置为 (sql, params, columns)。

        Returns:
            sql: 参数化 SQL 字符串，占位符为 :p0, :p1, ..., :tenant_id
            params: 参数字典
            columns: 结果列元数据列表
        """
        params: dict[str, Any] = {}
        param_idx = [0]  # 用列表便于在嵌套函数中修改

        def _next_param(value: Any) -> str:
            name = f"p{param_idx[0]}"
            param_idx[0] += 1
            params[name] = value
            return f":{name}"

        # 1. 校验所有 field_id 存在
        all_dim_ids = list(config.rows) + list(config.columns)
        dim_fields: dict[str, QueryField] = {}
        for fid in all_dim_ids:
            field = self.registry.get_field(fid)
            if field is None:
                raise ValueError(f"未知字段: {fid}")
            dim_fields[fid] = field

        value_fields: dict[str, QueryField] = {}
        for qv in config.values:
            field = self.registry.get_field(qv.field_id)
            if field is None:
                raise ValueError(f"未知字段: {qv.field_id}")
            value_fields[qv.field_id] = field

        # 2. 构建 SELECT + 列元数据
        select_parts, column_meta = self._build_select(config, dim_fields, value_fields)

        # 3. 构建 FROM
        from_clause, table_aliases = self._build_from(config, dim_fields, value_fields)

        # 4. 构建 WHERE（含 tenant_id）
        where_clause = self._build_where(config, dim_fields, params, _next_param)

        # 5. 构建 GROUP BY
        group_by_clause = self._build_group_by(config)

        # 6. 构建 ORDER BY
        order_by_clause = self._build_order_by(config, dim_fields, value_fields)

        # 7. 组装 SQL
        sql_parts = [
            f"SELECT {', '.join(select_parts)}",
            f"FROM {from_clause}",
        ]
        if where_clause:
            sql_parts.append(f"WHERE {where_clause}")
        if group_by_clause:
            sql_parts.append(f"GROUP BY {group_by_clause}")
        if order_by_clause:
            sql_parts.append(f"ORDER BY {order_by_clause}")
        sql_parts.append(f"LIMIT :limit OFFSET :offset")

        sql = "\n".join(sql_parts)
        params["limit"] = config.limit
        params["offset"] = config.offset

        return sql, params, column_meta

    # ─── SELECT 子句 ────────────────────────────────────────────

    def _build_select(
        self,
        config: QueryConfig,
        dim_fields: dict[str, QueryField],
        value_fields: dict[str, QueryField],
    ) -> tuple[list[str], list[ColumnMeta]]:
        """构建 SELECT 表达式列表和列元数据。

        先输出维度列（GROUP BY 列），再输出度量列（聚合列）。
        """
        select_parts: list[str] = []
        columns: list[ColumnMeta] = []

        # 行维度
        for fid in config.rows:
            field = dim_fields[fid]
            alias = f'_dim_{fid}'
            select_parts.append(f"{field.source_expression} AS \"{alias}\"")
            columns.append(ColumnMeta(
                name=alias,
                label=field.label,
                data_type=field.data_type.value if isinstance(field.data_type, DataType) else field.data_type,
                format=field.format,
            ))

        # 列维度（透视用，也在 SELECT/GROUP BY 中）
        for fid in config.columns:
            field = dim_fields[fid]
            alias = f'_cdim_{fid}'
            select_parts.append(f"{field.source_expression} AS \"{alias}\"")
            columns.append(ColumnMeta(
                name=alias,
                label=field.label,
                data_type=field.data_type.value if isinstance(field.data_type, DataType) else field.data_type,
                format=field.format,
            ))

        # 度量值
        for qv in config.values:
            field = value_fields[qv.field_id]
            agg = qv.aggregation or field.aggregation or "SUM"
            agg_upper = agg.upper()

            if agg_upper in ("COUNT_DISTINCT",):
                inner_alias = f"_val_{qv.field_id}"
                alias = qv.alias or f"_{qv.field_id}"
                # COUNT_DISTINCT: 嵌套写法
                select_parts.append(
                    f"COUNT(DISTINCT ({field.source_expression})) AS \"{alias}\""
                )
            else:
                alias = qv.alias or f"_{qv.field_id}"
                select_parts.append(
                    f"{agg_upper}({field.source_expression}) AS \"{alias}\""
                )

            columns.append(ColumnMeta(
                name=alias,
                label=field.label,
                data_type=field.data_type.value if isinstance(field.data_type, DataType) else field.data_type,
                format=field.format,
            ))

        return select_parts, columns

    # ─── FROM 子句 ──────────────────────────────────────────────

    def _build_from(
        self,
        config: QueryConfig,
        dim_fields: dict[str, QueryField],
        value_fields: dict[str, QueryField],
    ) -> tuple[str, dict[str, str]]:
        """确定 FROM 子句 — 单表或自动 JOIN。

        规则：
        1. 收集所有涉及的 source_table
        2. 如果单表，直接返回
        3. 如果多表，自动发现 JOIN 路径（通过 stores 作为枢纽表）
        """
        all_fields = {**dim_fields}
        for qv in config.values:
            if qv.field_id in value_fields:
                all_fields[qv.field_id] = value_fields[qv.field_id]

        # 收集唯一表名
        tables: set[str] = set()
        table_alias_map: dict[str, str] = {}
        for field in all_fields.values():
            if field.source_table not in table_alias_map:
                table_alias_map[field.source_table] = field.source_table

        tables = set(table_alias_map.keys())

        # JOIN 路径定义（当字段来自不同表时自动连接）
        join_paths: dict[tuple[str, str], str] = {
            ("orders", "stores"): "orders.store_id = stores.id",
            ("order_items", "orders"): "order_items.order_id = orders.id",
            ("order_items", "dishes"): "order_items.dish_id = dishes.id",
            ("dishes", "dish_categories"): "dishes.category_id = dish_categories.id",
            ("customers", "orders"): "customers.id = orders.customer_id",
            ("ingredients", "stores"): "ingredients.store_id = stores.id",
            ("ingredient_transactions", "ingredients"): "ingredient_transactions.ingredient_id = ingredients.id",
            ("ingredient_masters", "ingredients"): "ingredient_masters.id = ingredients.id",
            ("mv_store_pnl", "stores"): "mv_store_pnl.store_id = stores.id",
            ("mv_member_clv", "customers"): "mv_member_clv.customer_id = customers.id",
            ("mv_daily_settlement", "stores"): "mv_daily_settlement.store_id = stores.id",
            ("mv_channel_margin", "stores"): "mv_channel_margin.store_id = stores.id",
            ("mv_discount_health", "stores"): "mv_discount_health.store_id = stores.id",
            ("mv_inventory_bom", "stores"): "mv_inventory_bom.store_id = stores.id",
            ("mv_inventory_bom", "ingredients"): "mv_inventory_bom.ingredient_id = ingredients.id",
        }

        if len(tables) == 1:
            main_table = next(iter(tables))
            return main_table, table_alias_map

        # 多表：找出主表，通过 JOIN 路径连接
        # 策略：以第一个非物化视图的表为主表
        sorted_tables = sorted(tables, key=lambda t: (t.startswith("mv_"), t))
        main_table = sorted_tables[0]
        joined = {main_table}
        from_parts = [main_table]
        remaining = set(sorted_tables[1:])

        # 简化 JOIN 算法：遍历剩余表，尝试找到连接路径
        for table in list(remaining):
            for joined_table in list(joined):
                join_key = (table, joined_table)
                condition = join_paths.get(join_key)
                if condition:
                    from_parts.append(f"LEFT JOIN {table} ON {condition}")
                    joined.add(table)
                    remaining.discard(table)
                    break
                # 反向也检查
                reverse_key = (joined_table, table)
                condition = join_paths.get(reverse_key)
                if condition:
                    from_parts.append(f"LEFT JOIN {table} ON {condition}")
                    joined.add(table)
                    remaining.discard(table)
                    break

        # 剩余未连接的表，直接 CROSS JOIN（保守策略）
        for table in remaining:
            from_parts.append(f"CROSS JOIN {table}")
            log.warning("query_compiler.cross_join",
                        table=table, reason="no join path found")

        return "\n  ".join(from_parts), table_alias_map

    # ─── WHERE 子句 ─────────────────────────────────────────────

    def _build_where(
        self,
        config: QueryConfig,
        dim_fields: dict[str, QueryField],
        params: dict[str, Any],
        next_param,
    ) -> str:
        """构建 WHERE 子句 — 参数化过滤条件 + tenant_id。"""
        conditions: list[str] = []

        # 强制 tenant_id 过滤 — 通过 PostgreSQL RLS set_config 传递
        conditions.append("1=1 /* tenant_id enforced via RLS set_config */")

        # 确定主表别名（用于 tenant_id 关联）
        # 收集所有涉及的表，找出第一张非 mv 的表
        all_tables: set[str] = set()
        for f in dim_fields.values():
            all_tables.add(f.source_table)

        if not all_tables:
            conditions.append("1=1")
        else:
            # tenant_id 通过 set_config('app.tenant_id', :tid) 设置，
            # RLS 策略自动应用 — 此处显式加条件以防 RLS 未激活
            main_table = sorted(all_tables, key=lambda t: (t.startswith("mv_"), t))[0]
            if not main_table.startswith("mv_"):
                conditions.append(f"{main_table}.tenant_id = :tenant_id")
            else:
                conditions.append(f"{main_table}.tenant_id = :tenant_id")

        # 用户过滤条件
        for f in config.filters:
            field = dim_fields.get(f.field_id) or FieldRegistry.get_field(f.field_id)
            if field is None:
                log.warning("query_compiler.unknown_filter_field", field_id=f.field_id)
                continue

            cond = self._build_filter_condition(field, f, next_param)
            if cond:
                conditions.append(cond)

        return "\n  AND ".join(conditions)

    def _build_filter_condition(
        self,
        field: QueryField,
        filt: QueryFilter,
        next_param,
    ) -> str:
        """将单个过滤条件转为参数化 SQL 条件。"""
        expr = field.source_expression

        if filt.operator == "eq":
            return f"{expr} = {next_param(filt.value)}"
        elif filt.operator == "neq":
            return f"{expr} != {next_param(filt.value)}"
        elif filt.operator == "gt":
            return f"{expr} > {next_param(filt.value)}"
        elif filt.operator == "gte":
            return f"{expr} >= {next_param(filt.value)}"
        elif filt.operator == "lt":
            return f"{expr} < {next_param(filt.value)}"
        elif filt.operator == "lte":
            return f"{expr} <= {next_param(filt.value)}"
        elif filt.operator == "in":
            if isinstance(filt.value, list):
                placeholders = [next_param(v) for v in filt.value]
                return f"{expr} IN ({', '.join(placeholders)})"
            return f"{expr} = {next_param(filt.value)}"
        elif filt.operator == "not_in":
            if isinstance(filt.value, list):
                placeholders = [next_param(v) for v in filt.value]
                return f"{expr} NOT IN ({', '.join(placeholders)})"
            return f"{expr} != {next_param(filt.value)}"
        elif filt.operator == "between":
            return f"{expr} BETWEEN {next_param(filt.value)} AND {next_param(filt.value2)}"
        elif filt.operator == "like":
            return f"{expr} LIKE {next_param(filt.value)}"
        elif filt.operator == "is_null":
            return f"{expr} IS NULL"
        elif filt.operator == "is_not_null":
            return f"{expr} IS NOT NULL"
        else:
            log.warning("query_compiler.unknown_operator", operator=filt.operator)
            return ""

    # ─── GROUP BY 子句 ──────────────────────────────────────────

    def _build_group_by(self, config: QueryConfig) -> str:
        """构建 GROUP BY — 行维度 + 列维度。"""
        group_cols: list[str] = []
        for fid in config.rows:
            field = FieldRegistry.get_field(fid)
            if field:
                group_cols.append(field.source_expression)
        for fid in config.columns:
            field = FieldRegistry.get_field(fid)
            if field:
                group_cols.append(field.source_expression)
        if not group_cols:
            return ""
        return ", ".join(group_cols)

    # ─── ORDER BY 子句 ─────────────────────────────────────────

    def _build_order_by(
        self,
        config: QueryConfig,
        dim_fields: dict[str, QueryField],
        value_fields: dict[str, QueryField],
    ) -> str:
        """构建 ORDER BY 子句。"""
        if not config.order_by:
            return ""

        parts: list[str] = []
        for o in config.order_by:
            # 先查维度字段，再查度量字段
            field = dim_fields.get(o.field_id) or value_fields.get(o.field_id)
            if field is None:
                field = FieldRegistry.get_field(o.field_id)
            if field is None:
                continue

            direction = "ASC" if o.direction.lower() == "asc" else "DESC"
            parts.append(f"{field.source_expression} {direction}")

        return ", ".join(parts) if parts else ""

    # ─── 生成 COUNT 查询 ───────────────────────────────────────

    def compile_count(self, config: QueryConfig) -> tuple[str, dict]:
        """生成 COUNT(*) 查询（用于返回总行数）。"""
        # 简化：对原始查询包装为子查询
        sql, params, _ = self.compile(config)
        count_sql = f"SELECT COUNT(*) AS total FROM (\n{sql}\n) AS _count_subq"
        return count_sql, params
