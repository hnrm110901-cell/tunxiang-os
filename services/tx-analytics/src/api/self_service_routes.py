"""自助取数 API — 业务用户自助查询

BI-1.2: 让业务用户无需写 SQL，通过拖拽字段即可完成取数分析。

端点列表：
  GET  /api/v1/analytics/self-service/fields          — 列出可用字段
  GET  /api/v1/analytics/self-service/domains          — 列出数据域
  POST /api/v1/analytics/self-service/query            — 执行自助查询
  POST /api/v1/analytics/self-service/pivot            — 执行透视查询
  GET  /api/v1/analytics/self-service/saved            — 列出保存的查询
  POST /api/v1/analytics/self-service/saved            — 保存查询配置
  DELETE /api/v1/analytics/self-service/saved/{id}     — 删除保存的查询
  POST /api/v1/analytics/self-service/export           — 导出查询结果
"""

import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query as QueryParam
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db, _validate_tenant_id

from ..self_service.field_registry import FieldRegistry
from ..self_service.query_compiler import QueryCompiler, QueryConfig
from ..self_service.pivot import PivotConfig, pivot_from_config
from ..self_service.validation import QueryValidator, ValidationError
from ..self_service.saved_query import SavedQuery, SavedQueryService

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/analytics/self-service",
    tags=["self-service"],
)

_compiler = QueryCompiler(FieldRegistry)
_validator = QueryValidator()
_saved_svc = SavedQueryService()


# ─── Pydantic 请求模型 ───────────────────────────────────────────────────


class FilterItem(BaseModel):
    """筛选条件"""
    field_id: str
    operator: str = "eq"
    value: Any = None


class OrderByItem(BaseModel):
    """排序字段"""
    field_id: str
    direction: str = "asc"


class ValueItem(BaseModel):
    """度量值"""
    field_id: str
    aggregation: str = "SUM"


class SelfServiceQueryRequest(BaseModel):
    """自助查询请求"""
    rows: list[str] = Field(default_factory=list, description="行维度字段ID列表")
    columns: list[str] = Field(default_factory=list, description="列维度字段ID列表")
    values: list[ValueItem] = Field(default_factory=list, description="度量值定义")
    filters: list[FilterItem] = Field(default_factory=list, description="筛选条件")
    order_by: list[OrderByItem] = Field(default_factory=list, description="排序定义")
    limit: int = Field(default=100, ge=1, le=1000, description="返回行数上限")
    offset: int = Field(default=0, ge=0, description="分页偏移")


class SelfServicePivotRequest(BaseModel):
    """透视查询请求"""
    query: SelfServiceQueryRequest = Field(default_factory=SelfServiceQueryRequest)
    pivot: dict = Field(default_factory=dict, description="透视配置")


class SelfServiceSaveRequest(BaseModel):
    """保存查询配置请求"""
    id: str = Field(default="", description="为空则新建")
    name: str = Field(default="未命名查询")
    description: str = ""
    config: SelfServiceQueryRequest = Field(default_factory=SelfServiceQueryRequest)
    created_by: str = ""
    created_at: str = ""
    is_public: bool = False
    refresh_interval_min: Optional[int] = None
    tags: list[str] = Field(default_factory=list)


class SelfServiceExportRequest(BaseModel):
    """导出查询结果请求"""
    query: SelfServiceQueryRequest = Field(default_factory=SelfServiceQueryRequest)
    format: str = Field(default="csv", description="导出格式: csv/excel")


# ─── 1. 列出可用字段 ────────────────────────────────────────────


@router.get("/fields")
async def list_fields(
    domain: Optional[str] = QueryParam(None, description="数据域（sales/dish/member/cost/supply/finance）"),
    search: Optional[str] = QueryParam(None, description="搜索关键词"),
    grouped: bool = QueryParam(True, description="是否按域分组返回"),
):
    """列出所有可用字段。

    支持按域过滤、关键词搜索、分组展示。
    """
    try:
        if search:
            fields = FieldRegistry.search_fields(search)
            return {"ok": True, "data": {"fields": fields, "total": len(fields)}}

        if grouped and not domain:
            data = FieldRegistry.list_fields_grouped()
            return {"ok": True, "data": {"domains": data}}

        fields = FieldRegistry.list_fields(domain)
        return {
            "ok": True,
            "data": {
                "fields": fields,
                "total": len(fields),
            },
        }
    except (KeyError, ValueError, TypeError) as exc:
        log.error("list_fields.error", exc_info=True)
        raise HTTPException(status_code=500, detail="获取字段列表失败") from exc


# ─── 2. 列出数据域 ──────────────────────────────────────────────


@router.get("/domains")
async def list_domains():
    """列出所有数据域及其中文标签、字段数量。"""
    domains = FieldRegistry.list_domains()
    return {"ok": True, "data": {"domains": domains}}


# ─── 3. 执行自助查询 ───────────────────────────────────────────


@router.post("/query")
async def execute_query(
    body: SelfServiceQueryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    include_sql: bool = QueryParam(default=False, description="响应是否包含生成的SQL"),
):
    """执行自助查询。

    请求体:
    {
        "rows": ["sale_store_name"],
        "columns": [],
        "values": [{"field_id": "sale_total_revenue_fen", "aggregation": "SUM"}],
        "filters": [{"field_id": "sale_store_name", "operator": "eq", "value": "南山店"}],
        "order_by": [{"field_id": "sale_total_revenue_fen", "direction": "desc"}],
        "limit": 100,
        "offset": 0
    }
    """
    try:
        t0 = time.perf_counter()

        # 校验 tenant_id
        tenant_id = _validate_tenant_id(x_tenant_id)

        # 解析请求体
        config = QueryConfig(
            rows=body.rows,
            columns=body.columns,
            values=[v.model_dump() if hasattr(v, 'model_dump') else v for v in body.values],
            filters=[f.model_dump() if hasattr(f, 'model_dump') else f for f in body.filters],
            order_by=[o.model_dump() if hasattr(o, 'model_dump') else o for o in body.order_by],
            limit=body.limit,
            offset=body.offset,
        )

        # 校验
        errors = _validator.validate(config)
        if errors:
            return {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": errors[0].message,
                    "details": [{"field": e.field, "message": e.message} for e in errors],
                },
            }

        # 编译 SQL
        sql, params, column_meta = _compiler.compile(config)

        # 注入 tenant_id
        params["tenant_id"] = tenant_id

        # 通过 set_config 设置 RLS 上下文
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 执行查询
        result = await db.execute(text(sql), params)
        rows_raw = result.fetchall()

        # 处理结果行
        rows_data = []
        for row in rows_raw:
            converted = []
            for v in row:
                if isinstance(v, datetime):
                    converted.append(v.isoformat())
                elif hasattr(v, "isoformat"):
                    converted.append(str(v))
                else:
                    converted.append(v)
            rows_data.append(converted)

        # 查询总行数
        total_rows = len(rows_data)
        # 尝试 COUNT 查询获取实际总数
        try:
            count_sql, count_params = _compiler.compile_count(config)
            count_params["tenant_id"] = tenant_id
            cnt_result = await db.execute(text(count_sql), count_params)
            cnt_row = cnt_result.fetchone()
            if cnt_row:
                total_rows = cnt_row[0]
        except (OperationalError, SQLAlchemyError):
            log.warning("self_service_count_query_skipped", exc_info=True)
            # COUNT 查询失败不影响主查询，使用已获取行数作为 total

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        result = {
            "ok": True,
            "data": {
                "columns": [c.to_dict() for c in column_meta],
                "rows": rows_data,
                "total_rows": total_rows,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "execution_ms": elapsed_ms,
                "has_more": total_rows > config.limit,
            },
        }
        if include_sql:
            result["data"]["query_sql"] = sql
        return result
    except ValueError as exc:
        log.error("execute_query.validation_error", exc_info=True)
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": str(exc)}}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("execute_query.db_error", exc_info=True)
        raise HTTPException(status_code=500, detail="数据库查询失败，请检查查询条件后重试") from exc
    except Exception as exc:
        log.error("execute_query.unexpected_error", exc_info=True)
        raise HTTPException(status_code=500, detail="查询执行失败，请稍后重试") from exc


# ─── 4. 执行透视查询 ───────────────────────────────────────────


@router.post("/pivot")
async def execute_pivot(
    body: SelfServicePivotRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    include_sql: bool = QueryParam(default=False, description="响应是否包含生成的SQL"),
):
    """执行透视查询 — 将平面结果转为交叉表。

    请求体:
    {
        "query": { ...QueryConfig... },
        "pivot": {
            "row_field_id": "sale_store_name",
            "col_field_id": "sale_month",
            "value_field_id": "sale_total_revenue_fen",
            "include_totals": true,
            "include_percentages": false
        }
    }
    """
    try:
        t0 = time.perf_counter()
        tenant_id = _validate_tenant_id(x_tenant_id)

        query_body = body.query
        pivot_body = body.pivot

        config = QueryConfig(
            rows=query_body.rows,
            columns=query_body.columns,
            values=[v.model_dump() if hasattr(v, 'model_dump') else v for v in query_body.values],
            filters=[f.model_dump() if hasattr(f, 'model_dump') else f for f in query_body.filters],
            order_by=[o.model_dump() if hasattr(o, 'model_dump') else o for o in query_body.order_by],
            limit=query_body.limit,
            offset=query_body.offset,
        )

        # 确保透视的字段在查询中
        if pivot_body.get("row_field_id") not in config.rows:
            config.rows.insert(0, pivot_body["row_field_id"])
        if pivot_body.get("col_field_id") not in config.columns:
            config.columns.insert(0, pivot_body["col_field_id"])

        errors = _validator.validate(config)
        if errors:
            return {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": errors[0].message,
                    "details": [{"field": e.field, "message": e.message} for e in errors],
                },
            }

        sql, params, column_meta = _compiler.compile(config)
        params["tenant_id"] = tenant_id

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(text(sql), params)
        rows_raw = result.fetchall()

        rows_data = []
        for row in rows_raw:
            converted = []
            for v in row:
                if isinstance(v, datetime):
                    converted.append(v.isoformat())
                elif hasattr(v, "isoformat"):
                    converted.append(str(v))
                else:
                    converted.append(v)
            rows_data.append(converted)

        # 转为透视表
        pivot_config = PivotConfig(
            row_field_id=pivot_body.get("row_field_id", ""),
            col_field_id=pivot_body.get("col_field_id", ""),
            value_field_id=pivot_body.get("value_field_id", ""),
            include_totals=pivot_body.get("include_totals", True),
            include_percentages=pivot_body.get("include_percentages", False),
        )

        pivot_data = pivot_from_config(
            result_columns=[c.to_dict() for c in column_meta],
            result_rows=rows_data,
            pivot_config=pivot_config,
        )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        result = {
            "ok": True,
            "data": {
                "pivot": pivot_data,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "execution_ms": elapsed_ms,
            },
        }
        if include_sql:
            result["data"]["query_sql"] = sql
        return result
    except ValueError as exc:
        log.error("execute_pivot.validation_error", exc_info=True)
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": str(exc)}}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("execute_pivot.db_error", exc_info=True)
        raise HTTPException(status_code=500, detail="数据库查询失败") from exc
    except Exception as exc:
        log.error("execute_pivot.unexpected_error", exc_info=True)
        raise HTTPException(status_code=500, detail="透视查询执行失败") from exc


# ─── 5. 列出保存的查询 ──────────────────────────────────────────


@router.get("/saved")
async def list_saved_queries(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """列出当前租户下所有保存的查询。"""
    try:
        tenant_id = _validate_tenant_id(x_tenant_id)
        queries = await _saved_svc.list(db, tenant_id)
        return {
            "ok": True,
            "data": {
                "queries": [q.to_dict() for q in queries],
                "total": len(queries),
            },
        }
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("list_saved_queries.error", exc_info=True)
        raise HTTPException(status_code=500, detail="获取保存查询列表失败") from exc


# ─── 6. 保存查询配置 ───────────────────────────────────────────


@router.post("/saved")
async def save_query(
    body: SelfServiceSaveRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """保存查询配置。"""
    try:
        tenant_id = _validate_tenant_id(x_tenant_id)

        qc = body.config
        query_config = QueryConfig(
            rows=qc.rows,
            columns=qc.columns,
            values=[v.model_dump() if hasattr(v, 'model_dump') else v for v in qc.values],
            filters=[f.model_dump() if hasattr(f, 'model_dump') else f for f in qc.filters],
            order_by=[o.model_dump() if hasattr(o, 'model_dump') else o for o in qc.order_by],
            limit=qc.limit,
            offset=qc.offset,
        )

        saved = SavedQuery(
            id=body.id,
            tenant_id=tenant_id,
            name=body.name,
            description=body.description,
            config=query_config,
            created_by=body.created_by,
            created_at=body.created_at,
            updated_at="",
            is_public=body.is_public,
            refresh_interval_min=body.refresh_interval_min,
            tags=body.tags,
        )

        result = await _saved_svc.save(db, saved)
        return {"ok": True, "data": {"query": result.to_dict()}}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("save_query.error", exc_info=True)
        raise HTTPException(status_code=500, detail="保存查询失败") from exc


# ─── 7. 删除保存的查询 ──────────────────────────────────────────


@router.delete("/saved/{query_id}")
async def delete_saved_query(
    query_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """删除保存的查询。"""
    try:
        _validate_tenant_id(x_tenant_id)
        await _saved_svc.delete(db, query_id)
        return {"ok": True, "data": None}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("delete_saved_query.error", exc_info=True)
        raise HTTPException(status_code=500, detail="删除查询失败") from exc


# ─── 8. 导出查询结果 ───────────────────────────────────────────


@router.post("/export")
async def export_query(
    body: SelfServiceExportRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """导出查询结果为 CSV。"""
    try:
        tenant_id = _validate_tenant_id(x_tenant_id)
        query_body = body.query
        export_format = body.format

        config = QueryConfig(
            rows=query_body.rows,
            columns=query_body.columns,
            values=[v.model_dump() if hasattr(v, 'model_dump') else v for v in query_body.values],
            filters=[f.model_dump() if hasattr(f, 'model_dump') else f for f in query_body.filters],
            order_by=[o.model_dump() if hasattr(o, 'model_dump') else o for o in query_body.order_by],
            limit=min(query_body.limit, 50000),
            offset=0,
        )

        errors = _validator.validate(config)
        if errors:
            return {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": errors[0].message,
                },
            }

        sql, params, column_meta = _compiler.compile(config)
        params["tenant_id"] = tenant_id

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(text(sql), params)
        rows_raw = result.fetchall()

        # 生成 CSV
        import io

        output = io.StringIO()

        # 表头：使用 label
        headers = [c.label for c in column_meta]
        output.write(",".join(f'"{h}"' for h in headers) + "\n")

        # 数据行
        for row in rows_raw:
            values = []
            for v in row:
                if v is None:
                    values.append("")
                elif isinstance(v, (int, float)):
                    values.append(str(v))
                else:
                    # 转义引号
                    escaped = str(v).replace('"', '""')
                    values.append(f'"{escaped}"')
            output.write(",".join(values) + "\n")

        csv_content = output.getvalue()
        output.close()

        return StreamingResponse(
            io.BytesIO(csv_content.encode("utf-8-sig")),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=query_export.csv",
                "Content-Type": "text/csv; charset=utf-8",
            },
        )
    except ValueError as exc:
        log.error("export_query.validation_error", exc_info=True)
        return {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": str(exc)}}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("export_query.db_error", exc_info=True)
        raise HTTPException(status_code=500, detail="数据导出失败") from exc
    except Exception as exc:
        log.error("export_query.unexpected_error", exc_info=True)
        raise HTTPException(status_code=500, detail="导出失败") from exc
