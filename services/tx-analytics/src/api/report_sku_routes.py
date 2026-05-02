"""固定报表SKU API — BI-1.5，按域浏览/查询/导出固定报表模板"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query as QueryParam
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..reports.sku import list_skus, get_sku, ALL_SKUS, TOTAL_COUNT

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics/report-skus", tags=["report-skus"])


@router.get("/")
async def api_list_domains() -> dict:
    """列出所有SKU域及模板计数"""
    domains = {}
    for domain, skus in ALL_SKUS.items():
        domains[domain] = {
            "count": len(skus),
            "sample_names": [s["name"] for s in skus[:5]],
        }
    return {"ok": True, "data": {"domains": domains, "total_skus": TOTAL_COUNT}}


@router.get("/{domain}")
async def api_list_skus(domain: str) -> dict:
    """列出某域下所有SKU模板"""
    skus = list_skus(domain)
    if not skus:
        raise HTTPException(status_code=404, detail=f"未找到域 '{domain}'")
    summary = [
        {
            "sku_id": s["sku_id"],
            "name": s["name"],
            "description": s.get("description", ""),
            "columns": len(s.get("columns", [])),
        }
        for s in skus
    ]
    return {"ok": True, "data": {"domain": domain, "count": len(skus), "skus": summary}}


@router.get("/{domain}/{sku_id}")
async def api_get_sku(domain: str, sku_id: str) -> dict:
    """获取单个SKU模板详情（含参数定义和SQL）"""
    sku = get_sku(domain, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail=f"未找到SKU '{domain}/{sku_id}'")
    return {
        "ok": True,
        "data": {
            "sku_id": sku["sku_id"],
            "name": sku["name"],
            "description": sku.get("description", ""),
            "domain": sku.get("domain", domain),
            "columns": sku.get("columns", []),
            "default_params": {
                k: str(v) for k, v in sku.get("default_params", {}).items()
            },
            "sql_preview": (sku.get("sql", "") or "")[:300],
        },
    }


@router.post("/{domain}/{sku_id}/execute")
async def api_execute_sku(
    domain: str,
    sku_id: str,
    params: dict = {},
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """执行SKU模板查询"""
    sku = get_sku(domain, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail=f"未找到SKU '{domain}/{sku_id}'")

    sql = sku.get("sql", "") or ""
    if not sql.strip():
        raise HTTPException(status_code=400, detail="SKU模板缺少SQL定义")

    try:
        merged_params = dict(sku.get("default_params", {}))
        merged_params.update(params)
        merged_params["tenant_id"] = x_tenant_id

        result = await db.execute(text(sql), merged_params)
        rows = result.fetchall()
        columns = list(result.keys()) if rows else []

        return {
            "ok": True,
            "data": {
                "sku_id": sku_id,
                "columns": columns,
                "rows": [dict(zip(columns, row)) for row in rows],
                "row_count": len(rows),
            },
        }
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("sku_execute_error", domain=domain, sku_id=sku_id, exc_info=True)
        raise HTTPException(status_code=500, detail="SKU查询执行失败") from exc


@router.post("/{domain}/{sku_id}/export")
async def api_export_sku(
    domain: str,
    sku_id: str,
    format: str = QueryParam("csv", regex="^(csv|json)$"),
    params: dict = {},
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """导出SKU结果为CSV/JSON"""
    sku = get_sku(domain, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail=f"未找到SKU '{domain}/{sku_id}'")

    sql = sku.get("sql", "") or ""
    try:
        merged_params = dict(sku.get("default_params", {}))
        merged_params.update(params)
        merged_params["tenant_id"] = x_tenant_id

        result = await db.execute(text(sql), merged_params)
        rows = result.fetchall()
        columns = list(result.keys()) if rows else []

        if format == "json":
            import json
            data = [dict(zip(columns, row)) for row in rows]
            return StreamingResponse(
                iter([json.dumps(data, ensure_ascii=False, default=str)]),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={sku_id}.json"},
            )

        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={sku_id}.csv"},
        )
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("sku_export_error", domain=domain, sku_id=sku_id, exc_info=True)
        raise HTTPException(status_code=500, detail="SKU导出失败") from exc


@router.get("/search")
async def api_search_skus(q: str = QueryParam(..., min_length=1)) -> dict:
    """关键词搜索SKU"""
    results = []
    from ..reports.sku import search_skus as _search
    for sku in _search(q):
        results.append({
            "sku_id": sku["sku_id"],
            "name": sku["name"],
            "domain": sku.get("domain", ""),
            "description": sku.get("description", ""),
        })
    return {"ok": True, "data": {"query": q, "results": results, "count": len(results)}}
