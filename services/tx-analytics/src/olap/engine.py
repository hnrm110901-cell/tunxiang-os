"""OLAP 多维分析引擎 — 钻取/切片/切块/透视

BI-1.1: 多维分析引擎核心实现。
接受 OLAPQuery 请求，编译参数化 SQL，执行并返回 OLAPResult。
"""

from __future__ import annotations

import hashlib
import json
import time
from enum import Enum
from typing import Any, Literal, Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ─── Aggregation Enum ──────────────────────────────────────────────────────────


class AggFunction(str, Enum):
    SUM = "SUM"
    AVG = "AVG"
    COUNT = "COUNT"
    COUNT_DISTINCT = "COUNT_DISTINCT"
    MIN = "MIN"
    MAX = "MAX"


# ─── Pydantic Models ───────────────────────────────────────────────────────────


class MeasureDef(BaseModel):
    """度量定义 — Cube 中可聚合的数值字段"""

    name: str
    label: str
    aggregation: AggFunction
    source_expression: str  # SQL 表达式，如 "COALESCE(total_revenue_fen, 0)"
    format: Optional[str] = None  # 展示格式，如 "¥#,##0.00"
    unit: Optional[str] = None  # 单位，如 "分", "克", "次"


class DimensionDef(BaseModel):
    """维度定义 — Cube 中可分组/下钻的字段"""

    name: str
    label: str
    source_field: str  # SQL 表达式，如 "report_date", "date_trunc('month', report_date)"
    drill_level: int = 1  # 1=粗粒度，越大越细
    parent_dim: Optional[str] = None  # 层级父维度名称，用于下钻路径


class FilterDef(BaseModel):
    """筛选条件"""

    field: str
    operator: Literal[
        "eq", "neq", "gt", "gte", "lt", "lte",
        "in", "not_in", "between", "like",
        "is_null", "is_not_null",
    ]
    value: Optional[Any] = None
    value2: Optional[Any] = None  # between 的上界


class SortDef(BaseModel):
    """排序定义"""

    field: str
    direction: Literal["asc", "desc"] = "asc"


class OLAPQuery(BaseModel):
    """OLAP 查询请求"""

    cube: str
    measures: list[str]
    dimensions: list[str]
    filters: list[FilterDef] = []
    drill_path: list[str] = []  # 层级下钻路径，如 ["year", "month", "day"]
    order_by: list[SortDef] = []
    limit: int = Field(default=100, le=5000)
    offset: int = 0


class OLAPResult(BaseModel):
    """OLAP 查询结果"""

    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    drill_suggestions: list[str]  # 可用下钻维度名称
    query_sql: str  # 实际执行的 SQL（调试用）
    execution_ms: float


class CubeMeta(BaseModel):
    """Cube 元数据 — 包含度量、维度和描述"""

    name: str
    label: str
    description: str
    source_table: str
    measures: list[MeasureDef]
    dimensions: list[DimensionDef]


# ─── OLAP Engine ───────────────────────────────────────────────────────────────


class OLAPEngine:
    """OLAP 多维分析引擎

    用法:
        engine = OLAPEngine()
        cubes = engine.list_cubes()
        result = await engine.query(db, OLAPQuery(cube="sales_cube", ...))
    """

    def __init__(self) -> None:
        from .cubes import CUBES

        self._cubes: dict[str, dict] = CUBES

    # ── 元数据查询 ───────────────────────────────────────────────────────

    def list_cubes(self) -> list[CubeMeta]:
        """列出所有可用的 Cube 及其元数据"""
        result: list[CubeMeta] = []
        for name, cube_def in self._cubes.items():
            result.append(self._cube_to_meta(name, cube_def))
        return result

    def get_cube(self, name: str) -> CubeMeta:
        """获取单个 Cube 的元数据"""
        cube_def = self._cubes.get(name)
        if cube_def is None:
            raise ValueError(f"Unknown cube: {name!r}. Available: {list(self._cubes.keys())}")
        return self._cube_to_meta(name, cube_def)

    # ── 查询执行 ─────────────────────────────────────────────────────────

    async def query(
        self, db: AsyncSession, q: OLAPQuery, tenant_id: str
    ) -> OLAPResult:
        """执行 OLAP 查询

        流程:
        1. 查找 Cube 定义
        2. 校验度量/维度是否存在于 Cube
        3. 构建参数化 SQL
        4. 注入 tenant_id
        5. 执行查询
        6. 返回 OLAPResult
        """
        cube_def = self._cubes.get(q.cube)
        if cube_def is None:
            raise ValueError(f"Unknown cube: {q.cube!r}. Available: {list(self._cubes.keys())}")

        # 校验度量
        valid_measure_names = {m["name"] for m in cube_def["measures"]}
        for measure_name in q.measures:
            if measure_name not in valid_measure_names:
                raise ValueError(
                    f"Unknown measure: {measure_name!r}. "
                    f"Available in cube {q.cube!r}: {sorted(valid_measure_names)}"
                )

        # 校验维度
        valid_dim_names = {d["name"] for d in cube_def["dimensions"]}
        for dim_name in q.dimensions:
            if dim_name not in valid_dim_names:
                raise ValueError(
                    f"Unknown dimension: {dim_name!r}. "
                    f"Available in cube {q.cube!r}: {sorted(valid_dim_names)}"
                )

        # 校验排序字段
        sortable_fields = valid_measure_names | valid_dim_names
        for sort in q.order_by:
            if sort.field not in sortable_fields:
                raise ValueError(
                    f"Cannot sort by {sort.field!r}: not a valid measure or dimension "
                    f"in cube {q.cube!r}"
                )

        # 校验筛选字段（防御 SQL 注入）
        valid_filter_fields = valid_measure_names | valid_dim_names
        for filt in q.filters:
            if filt.field not in valid_filter_fields:
                raise ValueError(
                    f"Unknown filter field: {filt.field!r}. "
                    f"Valid filter fields in cube {q.cube!r}: {sorted(valid_filter_fields)}"
                )

        # 处理下钻路径：将 drill_path 中的维度追加到 dimensions
        all_dimensions = list(q.dimensions)
        for drill_dim in q.drill_path:
            if drill_dim not in all_dimensions:
                all_dimensions.append(drill_dim)

        # 构建 SQL
        from .sql_builder import build_olap_sql

        sql, params = build_olap_sql(cube_def, q, all_dimensions)

        # 注入 tenant_id（替换占位符中的 None）
        for key in params:
            if key.startswith("tenant_") and params[key] is None:
                params[key] = tenant_id

        # 执行查询
        start_ns = time.perf_counter_ns()
        try:
            result_proxy = await db.execute(text(sql), params)
            rows = result_proxy.fetchall()
        except (OperationalError, SQLAlchemyError) as exc:
            log.error(
                "olap_query_execution_error",
                cube=q.cube,
                measures=q.measures,
                dimensions=q.dimensions,
                exc_info=True,
            )
            raise OLAPExecutionError(f"OLAP query execution failed: {exc}") from exc

        execution_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0

        # 列名：维度在前，度量在后
        columns = all_dimensions + q.measures

        # 转换为行列表
        row_list: list[list[Any]] = []
        for row in rows:
            row_list.append([self._serialize_value(v) for v in row])

        # 下钻建议：从 Cube 定义中找比当前维度更细一层的维度
        drill_suggestions = self._compute_drill_suggestions(cube_def, all_dimensions)

        total_rows = len(row_list)

        return OLAPResult(
            columns=columns,
            rows=row_list,
            total_rows=total_rows,
            drill_suggestions=drill_suggestions,
            query_sql=str(result_proxy.context.compiled) if hasattr(result_proxy, "context") and result_proxy.context else sql,
            execution_ms=round(execution_ms, 2),
        )

    async def drill(
        self,
        db: AsyncSession,
        cube: str,
        drill_dim: str,
        filters: list[FilterDef],
        tenant_id: str,
    ) -> OLAPResult:
        """执行下钻查询

        基于当前筛选条件、在指定维度上向下钻取一层。
        例如：date → week → day 的三级下钻。
        """
        cube_def = self._cubes.get(cube)
        if cube_def is None:
            raise ValueError(f"Unknown cube: {cube!r}")

        # 查找钻取维度定义
        drill_dim_def = None
        for d in cube_def["dimensions"]:
            if d["name"] == drill_dim:
                drill_dim_def = d
                break
        if drill_dim_def is None:
            raise ValueError(f"Dimension {drill_dim!r} not found in cube {cube!r}")

        # 构建 drill_path：需要包含当前维度的父维度链
        drill_path = [drill_dim]
        current = drill_dim_def

        # 穿透层级：如果当前维度有 parent_dim，也加入 drill_path
        while current.get("parent_dim"):
            parent_name = current["parent_dim"]
            parent_def = None
            for d in cube_def["dimensions"]:
                if d["name"] == parent_name:
                    parent_def = d
                    break
            if parent_def is None:
                break
            if parent_name not in drill_path:
                drill_path.insert(0, parent_name)
            current = parent_def

        # 构建查询：使用 cube 的所有默认度量
        default_measures = [m["name"] for m in cube_def["measures"][:4]]
        default_dimensions = list(drill_path)

        q = OLAPQuery(
            cube=cube,
            measures=default_measures,
            dimensions=default_dimensions,
            filters=filters,
            drill_path=drill_path,
        )
        return await self.query(db, q, tenant_id)

    # ── 内部辅助 ─────────────────────────────────────────────────────────

    def _cube_to_meta(self, name: str, cube_def: dict) -> CubeMeta:
        """将内部 dict 格式转换为 CubeMeta Pydantic 模型"""
        return CubeMeta(
            name=name,
            label=cube_def["label"],
            description=cube_def.get("description", ""),
            source_table=cube_def.get("source", ""),
            measures=[
                MeasureDef(**m) for m in cube_def.get("measures", [])
            ],
            dimensions=[
                DimensionDef(**d) for d in cube_def.get("dimensions", [])
            ],
        )

    def _compute_drill_suggestions(
        self, cube_def: dict, current_dimensions: list[str]
    ) -> list[str]:
        """计算可用下钻维度

        规则:
        - 当前维度的子维度（parent_dim 指向当前维度）即为可下钻维度
        - 未在当前查询中的根维度（drill_level=1）也可作为建议
        """
        suggestions: list[str] = []
        all_dims = cube_def.get("dimensions", [])
        current_set = set(current_dimensions)

        for dim in all_dims:
            dim_name = dim["name"]
            if dim_name in current_set:
                continue

            parent = dim.get("parent_dim")
            # 子维度：父维度在当前查询中 → 可下钻
            if parent is not None and parent in current_set:
                suggestions.append(dim_name)
            # 根维度且 drill_level=1：作为新增维度建议
            elif parent is None and dim.get("drill_level", 1) == 1:
                suggestions.append(dim_name)

        return suggestions

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """将数据库返回值序列化为 JSON 兼容类型"""
        from datetime import date, datetime, time as dt_time
        from decimal import Decimal
        from uuid import UUID

        if value is None:
            return None
        if isinstance(value, (datetime, date, dt_time)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, (int, float, str, bool)):
            return value
        return str(value)


# ─── Custom Exceptions ────────────────────────────────────────────────────────


class OLAPExecutionError(Exception):
    """OLAP 查询执行失败"""
    pass
