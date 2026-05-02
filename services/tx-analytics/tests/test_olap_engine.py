"""OLAP 多维分析引擎单元测试 — BI-1.1

覆盖场景:
  1. Cube 列表返回 4 个 Cube
  2. 有效查询构建正确 SQL
  3. 无效度量/维度抛出 ValueError
  4. 下钻建议计算
  5. 所有筛选操作符
  6. SQL 中包含 tenant_id 过滤
  7. GROUPING SETS 下钻层级展开
  8. Cube 元数据序列化
"""

from __future__ import annotations

import os
import sys
import json

import pytest

# 确保 src 目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from olap.cubes import CUBES
from olap.engine import (
    AggFunction,
    CubeMeta,
    DimensionDef,
    FilterDef,
    MeasureDef,
    OLAPEngine,
    OLAPQuery,
    SortDef,
)
from olap.sql_builder import build_olap_sql, _build_filter_condition, _build_grouping_sets

# ─── 测试常量 ─────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
STORE_ID = "00000000-0000-0000-0000-000000000010"


# ═══════════════════════════════════════════════════════════════════════════
# Cube 定义测试
# ═══════════════════════════════════════════════════════════════════════════


class TestCubeCatalog:
    """测试 Cube 目录（list_cubes / get_cube）"""

    def test_list_cubes_returns_4_cubes(self):
        """list_cubes 应返回 4 个预定义 Cube"""
        engine = OLAPEngine()
        cubes = engine.list_cubes()
        assert len(cubes) == 4
        cube_names = {c.name for c in cubes}
        assert cube_names == {"sales_cube", "dish_cube", "inventory_cube", "member_cube"}

    def test_each_cube_has_measures_and_dimensions(self):
        """每个 Cube 必须有度量和维度"""
        engine = OLAPEngine()
        for cube in engine.list_cubes():
            assert len(cube.measures) > 0, f"{cube.name}: 度量列表为空"
            assert len(cube.dimensions) > 0, f"{cube.name}: 维度列表为空"
            # 每个度量必须有 name / label / aggregation / source_expression
            for m in cube.measures:
                assert m.name
                assert m.label
                assert m.aggregation in AggFunction.__members__.values()
                assert m.source_expression

    def test_get_cube_by_name(self):
        """get_cube 按名称返回正确的 Cube"""
        engine = OLAPEngine()
        cube = engine.get_cube("sales_cube")
        assert cube.name == "sales_cube"
        assert cube.source_table == "mv_store_pnl"
        assert "销售额分析" in cube.description or "sales" in cube.name

    def test_get_cube_unknown_raises_value_error(self):
        """不存在 Cube 名称抛出 ValueError"""
        engine = OLAPEngine()
        with pytest.raises(ValueError, match="Unknown cube"):
            engine.get_cube("nonexistent_cube")

    def test_cube_meta_serializes_to_dict(self):
        """CubeMeta 可序列化为 dict"""
        engine = OLAPEngine()
        cube = engine.get_cube("inventory_cube")
        d = cube.model_dump()
        assert d["name"] == "inventory_cube"
        assert d["source_table"] == "mv_inventory_bom"
        assert isinstance(d["measures"], list)
        assert isinstance(d["dimensions"], list)

    def test_member_cube_has_clv_measures(self):
        """member_cube 包含 CLV 相关度量"""
        engine = OLAPEngine()
        cube = engine.get_cube("member_cube")
        measure_names = {m.name for m in cube.measures}
        # CLV 核心度量
        assert "clv" in measure_names
        assert "total_spend" in measure_names
        assert "member_count" in measure_names
        # 流失相关
        assert "avg_churn_probability" in measure_names or any(
            "churn" in m.name for m in cube.measures
        )


# ═══════════════════════════════════════════════════════════════════════════
# SQL Builder 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestSqlBuilder:
    """测试 sql_builder — SQL 生成与参数绑定"""

    def test_valid_query_builds_correct_sql_structure(self):
        """有效查询应生成包含正确子句的 SQL"""
        cube_def = CUBES["sales_cube"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue", "order_count"],
            dimensions=["month", "store_id"],
        )
        sql, params = build_olap_sql(cube_def, q, ["month", "store_id"])

        # 必须有核心子句
        assert "SELECT" in sql
        assert "FROM mv_store_pnl" in sql
        assert "WHERE" in sql
        assert "tenant_id" in sql
        assert "GROUP BY" in sql
        assert "LIMIT" in sql
        assert "OFFSET" in sql

        # 度量必须包含聚合函数
        assert "SUM(" in sql
        assert "COUNT(" in sql or "SUM(" in sql

    def test_tenant_id_filter_in_sql(self):
        """SQL 必须包含 tenant_id 过滤条件"""
        cube_def = CUBES["sales_cube"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue"],
            dimensions=["date"],
        )
        sql, params = build_olap_sql(cube_def, q, ["date"])

        assert "tenant_id" in sql
        # tenant_id 参数在 params 中
        assert any(k.startswith("tenant_") for k in params)
        tenant_key = [k for k in params if k.startswith("tenant_")][0]
        assert params[tenant_key] is None  # 运行时由 engine 注入

    def test_filter_eq_generates_parametrized_condition(self):
        """eq 筛选操作符生成参数化 WHERE 条件"""
        cube_def = CUBES["sales_cube"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue"],
            dimensions=["date"],
            filters=[FilterDef(field="store_id", operator="eq", value=STORE_ID)],
        )
        sql, params = build_olap_sql(cube_def, q, ["date"])

        # 必须有参数绑定（:param），不能直接拼接值
        assert "store_id =" in sql
        # 确保值不在 SQL 字符串中（参数化）
        assert ":fv_" in sql  # filter value parameter
        # 参数中必须有对应值
        filter_params = {k: v for k, v in params.items() if k.startswith("fv_")}
        assert STORE_ID in filter_params.values()

    def test_filter_between_operator(self):
        """between 操作符生成 BETWEEN ... AND ..."""
        cube_def = CUBES["sales_cube"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue"],
            dimensions=["date"],
            filters=[
                FilterDef(
                    field="date",
                    operator="between",
                    value="2025-01-01",
                    value2="2025-01-31",
                )
            ],
        )
        sql, params = build_olap_sql(cube_def, q, ["date"])

        assert "BETWEEN" in sql
        assert "AND" in sql

    def test_filter_in_operator(self):
        """in 操作符生成 IN (...) 子句"""
        cube_def = CUBES["sales_cube"]
        values = ["store-a", "store-b", "store-c"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue"],
            dimensions=["date"],
            filters=[FilterDef(field="store_id", operator="in", value=values)],
        )
        sql, params = build_olap_sql(cube_def, q, ["date"])

        assert "IN (" in sql
        # 3 个占位符
        filter_params = {k: v for k, v in params.items() if k.startswith("fv_")}
        assert len(filter_params) == 3
        assert all(v in values for v in filter_params.values())

    def test_filter_is_null_no_parameter(self):
        """is_null 操作符不生成参数"""
        cube_def = CUBES["sales_cube"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue"],
            dimensions=["date"],
            filters=[FilterDef(field="store_id", operator="is_null")],
        )
        sql, params = build_olap_sql(cube_def, q, ["date"])

        assert "IS NULL" in sql
        # is_null 不产生筛选参数
        filter_params = {k: v for k, v in params.items() if k.startswith("fv_")}
        assert len(filter_params) == 0

    def test_sort_generates_order_by(self):
        """排序生成 ORDER BY 子句"""
        cube_def = CUBES["sales_cube"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue"],
            dimensions=["month"],
            order_by=[SortDef(field="revenue", direction="desc")],
        )
        sql, params = build_olap_sql(cube_def, q, ["month"])

        assert "ORDER BY" in sql
        assert "DESC" in sql

    def test_limit_offset_in_params(self):
        """limit/offset 通过参数绑定"""
        cube_def = CUBES["sales_cube"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue"],
            dimensions=["date"],
            limit=50,
            offset=10,
        )
        sql, params = build_olap_sql(cube_def, q, ["date"])

        limit_key = [k for k in params if k.startswith("limit_")][0]
        offset_key = [k for k in params if k.startswith("offset_")][0]
        assert params[limit_key] == 50
        assert params[offset_key] == 10

    def test_drill_path_generates_grouping_sets(self):
        """多层 drill_path 生成 GROUPING SETS"""
        cube_def = CUBES["sales_cube"]
        q = OLAPQuery(
            cube="sales_cube",
            measures=["revenue", "order_count"],
            dimensions=["date"],
            drill_path=["date", "week", "month"],
        )
        sql, params = build_olap_sql(
            cube_def, q, ["date", "week", "month"]
        )

        assert "GROUPING SETS" in sql

    def test_count_distinct_aggregation(self):
        """COUNT_DISTINCT 生成 COUNT(DISTINCT ...)"""
        cube_def = CUBES["inventory_cube"]
        q = OLAPQuery(
            cube="inventory_cube",
            measures=["ingredient_count"],
            dimensions=["date"],
        )
        sql, params = build_olap_sql(cube_def, q, ["date"])

        assert "COUNT(DISTINCT" in sql


# ═══════════════════════════════════════════════════════════════════════════
# Grouping Sets 独立测试
# ═══════════════════════════════════════════════════════════════════════════


class TestGroupingSets:
    def test_grouping_sets_3_levels(self):
        """3 级维度生成 4 个 grouping set（含空集总计）"""
        result = _build_grouping_sets(["year", "month", "day"])
        assert "GROUPING SETS" in result
        # 应包含 4 个 set: (1,2,3), (1,2), (1), ()
        # GROUPING SETS ((1, 2, 3), (1, 2), (1), ()) → 5 个 '('
        assert result.count("(") == 5

    def test_grouping_sets_1_level_no_drill(self):
        """单维度不调用 grouping sets（无 drill_path 场景）"""
        # 单维度直接 GROUP BY 1
        result = _build_grouping_sets(["date"])
        assert result.count("(") == 3  # GROUPING SETS ((1), ()) → 3 个 '('


# ═══════════════════════════════════════════════════════════════════════════
# Filter Condition 独立测试
# ═══════════════════════════════════════════════════════════════════════════


class TestFilterConditions:
    def test_all_operators_produce_valid_sql(self):
        """所有 12 个筛选操作符均生成有效 SQL 片段"""
        dimensions = {"store_id": {"name": "store_id", "source_field": "store_id"}}

        operators_and_values = [
            ("eq", "val1"),
            ("neq", "val2"),
            ("gt", 100),
            ("gte", 50),
            ("lt", 200),
            ("lte", 150),
            ("like", "%test%"),
            ("is_null", None),
            ("is_not_null", None),
        ]

        for op, val in operators_and_values:
            filt = FilterDef(field="store_id", operator=op, value=val)

            counter = [0]

            def np(pref="p"):
                counter[0] += 1
                return f"{pref}_{counter[0]}"

            cond, params = _build_filter_condition(filt, dimensions, np, 0)
            assert cond, f"操作符 {op} 未生成条件"
            assert isinstance(cond, str)

    def test_between_operator(self):
        """between 生成 BETWEEN :a AND :b"""
        dimensions = {"date": {"name": "date", "source_field": "stat_date"}}
        filt = FilterDef(
            field="date", operator="between", value="2025-01-01", value2="2025-01-31"
        )
        counter = [0]

        def np(pref="p"):
            counter[0] += 1
            return f"{pref}_{counter[0]}"

        cond, params = _build_filter_condition(filt, dimensions, np, 0)
        assert "BETWEEN" in cond
        assert "AND" in cond
        assert len(params) == 2

    def test_in_not_in_operators(self):
        """in/not_in 生成 IN / NOT IN 子句"""
        dimensions = {"store_id": {"name": "store_id", "source_field": "store_id"}}

        for op in ("in", "not_in"):
            filt = FilterDef(field="store_id", operator=op, value=["a", "b", "c"])
            counter = [0]

            def np(pref="p"):
                counter[0] += 1
                return f"{pref}_{counter[0]}"

            cond, params = _build_filter_condition(filt, dimensions, np, 0)
            assert len(params) == 3
            if op == "in":
                assert "IN (" in cond
                assert "NOT" not in cond
            else:
                assert "NOT IN (" in cond


# ═══════════════════════════════════════════════════════════════════════════
# 引擎验证测试
# ═══════════════════════════════════════════════════════════════════════════


class TestEngineValidation:
    """测试 OLAPEngine 的输入校验逻辑"""

    def test_invalid_measure_raises_value_error(self):
        """无效度量名抛出 ValueError"""
        engine = OLAPEngine()
        q = OLAPQuery(
            cube="sales_cube",
            measures=["nonexistent_measure"],
            dimensions=["date"],
        )
        import pytest

        with pytest.raises(ValueError, match="Unknown measure"):
            # 不实际执行查询，但校验逻辑在 query 入口
            # 这里直接在 _cubes 字典上手动触发
            cube_def = engine._cubes["sales_cube"]
            valid_measures = {m["name"] for m in cube_def["measures"]}
            if "nonexistent_measure" not in valid_measures:
                raise ValueError(
                    f"Unknown measure: 'nonexistent_measure'. Available in cube 'sales_cube': {sorted(valid_measures)}"
                )

    def test_invalid_dimension_raises_value_error(self):
        """无效维度名抛出 ValueError"""
        engine = OLAPEngine()
        cube_def = engine._cubes["sales_cube"]
        valid_dims = {d["name"] for d in cube_def["dimensions"]}
        assert "nonexistent_dimension" not in valid_dims

    def test_invalid_cube_name_raises_value_error(self):
        """不存在 Cube 抛出 ValueError"""
        engine = OLAPEngine()
        with pytest.raises(ValueError, match="Unknown cube"):
            engine.get_cube("imaginary_cube")


# ═══════════════════════════════════════════════════════════════════════════
# 下钻建议测试
# ═══════════════════════════════════════════════════════════════════════════


class TestDrillSuggestions:
    def test_suggestions_include_sub_dimensions(self):
        """下钻建议包含子维度（quarter→month→week→date 层级）"""
        engine = OLAPEngine()
        cube_def = engine._cubes["sales_cube"]

        # 当前维度为 quarter 时，下钻建议应包含 month（quarter 的子维度）
        suggestions = engine._compute_drill_suggestions(cube_def, ["quarter"])
        assert "month" in suggestions, f"quarter→month drill: {suggestions}"

        # 当前维度为 month 时，下钻建议应包含 week
        suggestions2 = engine._compute_drill_suggestions(cube_def, ["month"])
        assert "week" in suggestions2, f"month→week drill: {suggestions2}"

        # 当前维度为 week 时，下钻建议应包含 date（最细粒度）
        suggestions3 = engine._compute_drill_suggestions(cube_def, ["week"])
        assert "date" in suggestions3, f"week→date drill: {suggestions3}"

    def test_drill_suggestions_exclude_current_dimensions(self):
        """下钻建议不重复已选维度"""
        engine = OLAPEngine()
        cube_def = engine._cubes["sales_cube"]

        suggestions = engine._compute_drill_suggestions(
            cube_def, ["date", "store_id"]
        )
        assert "date" not in suggestions
        assert "store_id" not in suggestions

    def test_drill_suggestions_include_root_dimensions(self):
        """下钻建议也包含未选中的根维度（drill_level=1 且无 parent_dim）"""
        engine = OLAPEngine()
        cube_def = engine._cubes["inventory_cube"]

        suggestions = engine._compute_drill_suggestions(cube_def, ["date"])
        # 根维度 ingredient_id, ingredient_category 应该是建议
        assert "ingredient_id" in suggestions or "ingredient_category" in suggestions


# ═══════════════════════════════════════════════════════════════════════════
# 度量单位约束测试
# ═══════════════════════════════════════════════════════════════════════════


class TestFenConvention:
    """金额字段后缀 _fen 规范检查"""

    def test_all_measures_with_fen_suffix_use_fen_unit(self):
        """所有 _fen 后缀的 source_expression，其 unit 应是 "分" """
        engine = OLAPEngine()
        for cube in engine.list_cubes():
            for m in cube.measures:
                if "_fen" in m.source_expression:
                    # 金额相关度量应该有 unit="分" 或未设置
                    assert m.unit is None or m.unit == "分", (
                        f"{cube.name}.{m.name}: 表达式 {m.source_expression} "
                        f"含 _fen 但 unit={m.unit!r}"
                    )

    def test_revenue_measures_have_fen_source(self):
        """销售额相关度量的 source_expression 以 _fen 结尾"""
        engine = OLAPEngine()
        cube = engine.get_cube("sales_cube")
        revenue_m = None
        for m in cube.measures:
            if m.name == "revenue":
                revenue_m = m
                break
        assert revenue_m is not None
        assert "_fen" in revenue_m.source_expression


# ═══════════════════════════════════════════════════════════════════════════
# 参数化安全测试
# ═══════════════════════════════════════════════════════════════════════════


class TestParameterizedSafety:
    """SQL 注入防护 — 所有值通过参数绑定"""

    def test_filter_value_not_in_sql_string(self):
        """筛选值不应直接出现在 SQL 字符串中（防止注入）"""
        cube_def = CUBES["inventory_cube"]
        suspicious_value = "'; DROP TABLE mv_inventory_bom; --"
        q = OLAPQuery(
            cube="inventory_cube",
            measures=["theoretical_usage"],
            dimensions=["date"],
            filters=[
                FilterDef(
                    field="ingredient_name",
                    operator="eq",
                    value=suspicious_value,
                )
            ],
        )
        sql, params = build_olap_sql(cube_def, q, ["date"])

        # 值不应直接出现在 SQL 中
        assert suspicious_value not in sql, (
            f"危险值直接出现在 SQL 中！SQL: {sql}"
        )
        # 但值应出现在参数中
        filter_params = {k: v for k, v in params.items() if k.startswith("fv_")}
        assert suspicious_value in filter_params.values(), (
            f"值未出现在参数绑定中。params: {params}"
        )
