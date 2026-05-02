"""查询校验 — 防注入 + 超时保护 + 合理性检查

校验规则：
  1. 所有 field_ids 必须在注册表中存在
  2. 度量字段（MEASURE）不能在维度（rows/columns）中使用
  3. 维度字段（DIMENSION/DATE_DIM）不能在 values 中直接使用
  4. 至少选择了一个度量值
  5. 维度数量不超过 10（性能保护）
  6. 过滤值类型与字段数据类型匹配
  7. 过滤值无 SQL 注入特征
  8. LIMIT 上限保护
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .field_registry import DataType, FieldRegistry, FieldType, QueryField
from .query_compiler import QueryConfig, QueryFilter, QueryValue


class ValidationError(Exception):
    """查询校验错误"""

    def __init__(self, message: str, field: str = ""):
        self.message = message
        self.field = field
        super().__init__(message)


# SQL 注入特征模式
_INJECTION_PATTERNS = [
    re.compile(r'(\b(select|insert|update|delete|drop|alter|create|truncate|exec|execute)\b)',
               re.IGNORECASE),
    re.compile(r'(--)'),            # SQL 注释
    re.compile(r'(;)'),              # 多语句分隔
    re.compile(r'(/\*)'),            # 块注释
    re.compile(r'(xp_cmdshell)'),    # MSSQL
    re.compile(r'(information_schema)'),
]

MAX_DIMENSIONS = 10
MAX_LIMIT = 10000


def _detect_injection(value: Any) -> bool:
    """检测值中是否包含 SQL 注入特征。"""
    if value is None:
        return False
    if isinstance(value, (int, float, bool)):
        return False
    str_val = str(value)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(str_val):
            return True
    return False


class QueryValidator:
    """查询配置校验器"""

    def __init__(self):
        pass

    def validate(self, config: QueryConfig) -> list[ValidationError]:
        """校验查询配置，返回错误列表（空列表 = 通过）。"""
        errors: list[ValidationError] = []

        # 1. 所有 field_ids 存在
        for fid in config.rows:
            field = FieldRegistry.get_field(fid)
            if field is None:
                errors.append(ValidationError(f"未知字段: {fid}", field=fid))

        for fid in config.columns:
            field = FieldRegistry.get_field(fid)
            if field is None:
                errors.append(ValidationError(f"未知字段: {fid}", field=fid))

        for qv in config.values:
            field = FieldRegistry.get_field(qv.field_id)
            if field is None:
                errors.append(ValidationError(f"未知字段: {qv.field_id}", field=qv.field_id))

        # 2. 至少一个度量值
        if len(config.values) == 0:
            errors.append(ValidationError("至少需要选择一个度量值"))

        # 3. 维度数量限制
        total_dims = len(config.rows) + len(config.columns)
        if total_dims > MAX_DIMENSIONS:
            errors.append(ValidationError(
                f"维度数量 {total_dims} 超过上限 {MAX_DIMENSIONS}，请减少维度"
            ))

        # 4. 度量字段不能在 rows/columns 中使用
        for fid in config.rows:
            field = FieldRegistry.get_field(fid)
            if field and field.field_type == FieldType.MEASURE:
                errors.append(ValidationError(
                    '度量字段 \'{}\' 不能用作行维度，请拖入“值”区域'.format(field.label),
                    field=fid,
                ))

        for fid in config.columns:
            field = FieldRegistry.get_field(fid)
            if field and field.field_type == FieldType.MEASURE:
                errors.append(ValidationError(
                    '度量字段 \'{}\' 不能用作列维度，请拖入“值”区域'.format(field.label),
                    field=fid,
                ))

        # 5. LIMIT 检查
        if config.limit > MAX_LIMIT:
            errors.append(ValidationError(
                f"每页行数 {config.limit} 超过上限 {MAX_LIMIT}"
            ))

        # 6. 过滤值类型检查 + 注入检测
        for filt in config.filters:
            field = FieldRegistry.get_field(filt.field_id)
            if field is None:
                continue

            # 注入检测
            if _detect_injection(filt.value):
                errors.append(ValidationError(
                    f"过滤字段 '{field.label}' 的值可能包含非法字符",
                    field=filt.field_id,
                ))

            if _detect_injection(filt.value2):
                errors.append(ValidationError(
                    f"过滤字段 '{field.label}' 的值可能包含非法字符",
                    field=filt.field_id,
                ))

            # 运算符是否允许
            if filt.operator not in field.allowed_operators:
                errors.append(ValidationError(
                    f"字段 '{field.label}' 不支持运算符 '{filt.operator}'，"
                    f"允许: {', '.join(field.allowed_operators)}",
                    field=filt.field_id,
                ))

            # 类型校验
            self._validate_filter_value_type(field, filt, errors)

        # 7. 排序字段校验
        for o in config.order_by:
            field = FieldRegistry.get_field(o.field_id)
            if field is None:
                errors.append(ValidationError(f"排序字段 '{o.field_id}' 不存在", field=o.field_id))
            elif not field.sortable:
                errors.append(ValidationError(
                    f"字段 '{field.label}' 不支持排序",
                    field=o.field_id,
                ))

        return errors

    def _validate_filter_value_type(
        self, field: QueryField, filt: QueryFilter, errors: list[ValidationError]
    ) -> None:
        """校验过滤值与字段数据类型匹配。"""
        if filt.operator in ("is_null", "is_not_null"):
            return  # 不需要值

        if filt.value is None and filt.operator not in ("is_null", "is_not_null"):
            errors.append(ValidationError(
                f"过滤字段 '{field.label}' 的值不能为空",
                field=filt.field_id,
            ))
            return

        data_type = field.data_type

        if data_type in (DataType.NUMBER, DataType.MONEY, DataType.PERCENT):
            try:
                float(str(filt.value))
            except (ValueError, TypeError):
                errors.append(ValidationError(
                    f"过滤字段 '{field.label}' 的值应为数字",
                    field=filt.field_id,
                ))

        elif data_type == DataType.BOOLEAN:
            valid_bools = (True, False, "true", "false", "True", "False", 1, 0, "1", "0")
            if filt.value not in valid_bools:
                errors.append(ValidationError(
                    f"过滤字段 '{field.label}' 的值应为布尔值",
                    field=filt.field_id,
                ))

        elif data_type == DataType.DATE:
            date_str = str(filt.value)
            if not re.match(r'^\d{4}-\d{2}-\d{2}', date_str):
                errors.append(ValidationError(
                    f"过滤字段 '{field.label}' 的值应为日期格式 YYYY-MM-DD",
                    field=filt.field_id,
                ))

        # STRING 类型不做强制类型校验，但长度限制
        if data_type == DataType.STRING and len(str(filt.value)) > 500:
            errors.append(ValidationError(
                f"过滤字段 '{field.label}' 的值过长（最大 500 字符）",
                field=filt.field_id,
            ))

    def validate_or_raise(self, config: QueryConfig) -> None:
        """校验查询配置，失败时抛出第一个错误。"""
        errors = self.validate(config)
        if errors:
            raise errors[0]
