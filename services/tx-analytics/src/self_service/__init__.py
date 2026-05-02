"""自助取数（Self-Service Analytics）— 业务用户拖拽式自助查询

BI-1.2: 让业务用户无需写 SQL，通过拖拽字段即可完成取数分析。

核心组件：
  FieldRegistry  — 可用字段注册表（从数据仓库表结构自动发现）
  QueryCompiler  — 将拖拽配置编译为参数化 SQL
  PivotConfig   — 透视表配置
  QueryValidator — 查询校验（防注入 + 超时保护）
"""

from .field_registry import (
    DataType,
    FieldRegistry,
    FieldType,
    FIELDS_BY_DOMAIN,
    QueryField,
)
from .query_compiler import (
    ColumnMeta,
    QueryCompiler,
    QueryConfig,
    QueryFilter,
    QueryOrder,
    QueryResult,
    QueryValue,
)
from .pivot import PivotConfig, pivot_result
from .saved_query import SavedQuery, SavedQueryService
from .validation import QueryValidator, ValidationError

__all__ = [
    # field_registry
    "FieldRegistry",
    "QueryField",
    "FieldType",
    "DataType",
    "FIELDS_BY_DOMAIN",
    # query_compiler
    "QueryCompiler",
    "QueryConfig",
    "QueryValue",
    "QueryFilter",
    "QueryOrder",
    "QueryResult",
    "ColumnMeta",
    # pivot
    "PivotConfig",
    "pivot_result",
    # validation
    "QueryValidator",
    "ValidationError",
    # saved_query
    "SavedQuery",
    "SavedQueryService",
]
