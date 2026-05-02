"""OLAP 多维分析 API 路由 — BI-1.1

端点列表:
  POST /api/v1/analytics/olap/query       — 执行 OLAP 查询
  GET  /api/v1/analytics/olap/cubes        — 列出所有 Cube
  GET  /api/v1/analytics/olap/cubes/{name} — 单个 Cube 元数据
  POST /api/v1/analytics/olap/drill        — 下钻查询
  POST /api/v1/analytics/olap/export       — 导出 CSV/Excel

鉴权: X-Tenant-ID header 必填
响应格式: { "ok": bool, "data": {}, "error": {} }
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..olap.cache import (
    get_cached_result,
    is_heavy_query,
    set_cached_result,
)
from ..olap.engine import (
    FilterDef,
    OLAPEngine,
    OLAPExecutionError,
    OLAPQuery,
    OLAPResult,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics/olap", tags=["olap"])

_engine = OLAPEngine()


# ─── 1. 执行 OLAP 查询 ────────────────────────────────────────────────


@router.post("/query")
async def api_olap_query(
    query: OLAPQuery,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    use_cache: bool = Query(default=True, description="是否使用缓存"),
    include_sql: bool = Query(default=False, description="响应是否包含生成的SQL"),
) -> dict:
    """执行 OLAP 多维分析查询

    请求体: OLAPQuery JSON
      {
        "cube": "sales_cube",
        "measures": ["revenue", "order_count"],
        "dimensions": ["month", "store_id"],
        "filters": [{"field": "store_id", "operator": "eq", "value": "..."}],
        "drill_path": ["date", "month"],
        "order_by": [{"field": "revenue", "direction": "desc"}],
        "limit": 100,
        "offset": 0
      }

    返回: OLAPResult JSON
    """
    try:
        # 1. 尝试从缓存获取
        if use_cache:
            query_json = query.model_dump_json()
            cached = await get_cached_result(x_tenant_id, query_json)
            if cached is not None:
                log.debug("olap_query_cache_hit", cube=query.cube)
                return {"ok": True, "data": cached, "cached": True}

        # 2. 执行查询
        result: OLAPResult = await _engine.query(
            db=db, q=query, tenant_id=x_tenant_id
        )

        # 3. 构建响应（默认不暴露 SQL）
        response_data = result.model_dump()
        if not include_sql:
            response_data.pop("query_sql", None)

        # 3. 写入缓存
        result_json = result.model_dump_json()
        if use_cache:
            heavy = is_heavy_query(len(query.dimensions), len(query.measures))
            await set_cached_result(
                x_tenant_id,
                query.model_dump_json(),
                result_json,
                is_heavy=heavy,
            )

        return {"ok": True, "data": response_data, "cached": False}

    except ValueError as exc:
        log.warning("olap_query_validation_error", cube=query.cube, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OLAPExecutionError as exc:
        log.error("olap_query_execution_error", cube=query.cube, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("olap_query_db_error", cube=query.cube, exc_info=True)
        raise HTTPException(status_code=500, detail="数据库查询失败，请稍后重试") from exc


# ─── 2. 列出所有 Cube ──────────────────────────────────────────────────


@router.get("/cubes")
async def api_olap_list_cubes(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出所有可用 OLAP Cube 的元数据"""
    try:
        cubes = _engine.list_cubes()
        data = [cube.model_dump() for cube in cubes]
        return {"ok": True, "data": {"cubes": data, "count": len(data)}}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("olap_list_cubes_error", exc_info=True)
        raise HTTPException(status_code=500, detail="获取 Cube 列表失败") from exc


# ─── 3. 单个 Cube 元数据 ────────────────────────────────────────────────


@router.get("/cubes/{name}")
async def api_olap_get_cube(
    name: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取指定 Cube 的完整元数据（度量 + 维度）"""
    try:
        cube = _engine.get_cube(name)
        return {"ok": True, "data": cube.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("olap_get_cube_error", cube=name, exc_info=True)
        raise HTTPException(status_code=500, detail="获取 Cube 信息失败") from exc


# ─── 4. 下钻查询 ───────────────────────────────────────────────────────


class DrillRequest(BaseModel):
    cube: str
    drill_dim: str
    filters: list = []


@router.post("/drill")
async def api_olap_drill(
    body: DrillRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """在指定 Cube 和维度上执行下钻查询

    请求体:
      {
        "cube": "sales_cube",
        "drill_dim": "month",
        "filters": [{"field": "store_id", "operator": "eq", "value": "..."}]
      }
    """
    try:
        filters = [FilterDef(**f) for f in body.filters]
        result: OLAPResult = await _engine.drill(
            db=db,
            cube=body.cube,
            drill_dim=body.drill_dim,
            filters=filters,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": result.model_dump()}

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OLAPExecutionError as exc:
        log.error("olap_drill_execution_error", cube=body.cube, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("olap_drill_db_error", cube=body.cube, exc_info=True)
        raise HTTPException(status_code=500, detail="下钻查询失败，请稍后重试") from exc


# ─── 5. 导出查询结果 ───────────────────────────────────────────────────


class ExportRequest(BaseModel):
    query: OLAPQuery
    format: str = "csv"  # "csv" | "xlsx"


@router.post("/export")
async def api_olap_export(
    body: ExportRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """导出 OLAP 查询结果

    请求体:
      {
        "query": { OLAPQuery JSON },
        "format": "csv"
      }

    返回: 文件流（Content-Disposition: attachment）
    """
    try:
        result: OLAPResult = await _engine.query(
            db=db, q=body.query, tenant_id=x_tenant_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OLAPExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("olap_export_query_error", cube=body.query.cube, exc_info=True)
        raise HTTPException(status_code=500, detail="导出查询失败") from exc

    if body.format == "csv":
        return _build_csv_response(result, body.query.cube)

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported export format: {body.format!r}. Supported: csv",
    )


# ─── CSV 导出辅助 ───────────────────────────────────────────────────────


def _build_csv_response(result: OLAPResult, cube_name: str) -> StreamingResponse:
    """将 OLAPResult 转为 CSV StreamingResponse"""
    output = io.StringIO()
    writer = csv.writer(output)

    # 表头
    writer.writerow(result.columns)

    # 数据行
    for row in result.rows:
        writer.writerow(row)

    output.seek(0)
    filename = f"olap_{cube_name}_{_timestamp_slug()}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _timestamp_slug() -> str:
    """生成时间戳 slug 用于文件名"""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
