"""同步管理 API 路由

端点：
  POST /api/v1/ops/sync/trigger            — 手动触发全量/指定系统同步
  GET  /api/v1/ops/sync/status             — 查看各系统同步状态
  GET  /api/v1/ops/sync/logs               — 同步日志列表（ProTable格式）
  POST /api/v1/ops/sync/trigger/{system_name} — 触发单个系统同步

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需传 X-Tenant-ID header。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..services.multi_system_sync_service import (
    ALL_SYSTEMS,
    SYSTEM_AOQIWEI_CRM,
    SYSTEM_AOQIWEI_SUPPLY,
    SYSTEM_PINZHI,
    SYSTEM_YIDING,
    MultiSystemSyncService,
)

router = APIRouter(prefix="/api/v1/ops/sync", tags=["sync-management"])
log = structlog.get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────
# DB Engine 懒初始化
# ──────────────────────────────────────────────────────────────────────

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/tunxiang",
        )
        _engine = create_async_engine(db_url, pool_size=5, max_overflow=10)
    return _engine


def _get_service() -> MultiSystemSyncService:
    return MultiSystemSyncService(_get_engine())


# ──────────────────────────────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────────────────────────────

_VALID_SYSTEMS = frozenset(ALL_SYSTEMS)


class TriggerSyncReq(BaseModel):
    """手动触发全量/多系统同步请求"""

    tenant_id: str = Field(..., description="租户ID")
    store_ids: List[str] = Field(..., min_length=1, description="门店ID列表")
    systems: Optional[List[str]] = Field(
        None,
        description=(
            "要同步的系统列表，留空则同步全部。"
            f"可选值: {sorted(_VALID_SYSTEMS)}"
        ),
    )


class TriggerSingleSystemReq(BaseModel):
    """触发单个系统同步请求"""

    store_ids: List[str] = Field(..., min_length=1, description="门店ID列表")


# ──────────────────────────────────────────────────────────────────────
# 端点实现
# ──────────────────────────────────────────────────────────────────────


@router.post("/trigger")
async def trigger_sync(
    req: TriggerSyncReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """手动触发全量或指定系统同步

    - 同步在当前请求内同步执行（不通过 Celery 队列），适合运营人员手动补跑。
    - 如果 systems 为空，触发 pinzhi / aoqiwei_crm / aoqiwei_supply / yiding 全部四个。
    - 返回各系统同步结果汇总。
    """
    # 校验 tenant_id 一致性（防止越权）
    if req.tenant_id != x_tenant_id:
        raise HTTPException(
            status_code=403,
            detail="body.tenant_id 与 X-Tenant-ID 不一致",
        )

    if req.systems:
        invalid = set(req.systems) - _VALID_SYSTEMS
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"不支持的系统标识: {sorted(invalid)}，可选值: {sorted(_VALID_SYSTEMS)}",
            )

    log.info(
        "sync_trigger_requested",
        tenant_id=x_tenant_id,
        store_ids=req.store_ids,
        systems=req.systems,
    )

    try:
        svc = _get_service()
        result = await svc.sync_all(
            tenant_id=x_tenant_id,
            store_ids=req.store_ids,
            systems=req.systems,
        )
    except (ValueError, RuntimeError) as exc:
        log.error("sync_trigger_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"ok": True, "data": result}


@router.post("/trigger/{system_name}")
async def trigger_single_system(
    system_name: str,
    req: TriggerSingleSystemReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """触发单个系统同步

    路径参数 system_name 可选：pinzhi / aoqiwei_crm / aoqiwei_supply / yiding
    """
    if system_name not in _VALID_SYSTEMS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的系统标识: {system_name!r}，可选值: {sorted(_VALID_SYSTEMS)}",
        )

    log.info(
        "sync_single_system_trigger",
        tenant_id=x_tenant_id,
        system=system_name,
        store_ids=req.store_ids,
    )

    svc = _get_service()
    results: List[Dict[str, Any]] = []

    for store_id in req.store_ids:
        try:
            if system_name == SYSTEM_PINZHI:
                r = await svc.sync_pinzhi_orders(x_tenant_id, store_id)
            elif system_name == SYSTEM_AOQIWEI_CRM:
                r = await svc.sync_aoqiwei_members(x_tenant_id, store_id)
            elif system_name == SYSTEM_AOQIWEI_SUPPLY:
                r = await svc.sync_aoqiwei_inventory(x_tenant_id, store_id)
            elif system_name == SYSTEM_YIDING:
                r = await svc.sync_yiding_reservations(x_tenant_id, store_id)
            else:
                r = {"synced": 0, "errors": ["未实现的系统"]}
            results.append({"store_id": store_id, **r})
        except (ValueError, RuntimeError) as exc:
            log.error(
                "sync_single_system_store_failed",
                system=system_name,
                store_id=store_id,
                error=str(exc),
                exc_info=True,
            )
            results.append({"store_id": store_id, "synced": 0, "errors": [str(exc)]})

    total_synced = sum(r.get("synced", 0) for r in results)
    all_errors = [e for r in results for e in r.get("errors", [])]

    return {
        "ok": True,
        "data": {
            "system": system_name,
            "total_synced": total_synced,
            "by_store": results,
            "errors": all_errors,
        },
    }


@router.get("/status")
async def get_sync_status(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """查看各系统同步状态

    返回各系统最近24小时的同步时间、成功率、最近错误。
    """
    try:
        svc = _get_service()
        status = await svc.get_sync_status(x_tenant_id)
    except (ValueError, RuntimeError) as exc:
        log.error("get_sync_status_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"ok": True, "data": status}


@router.get("/logs")
async def list_sync_logs(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    system: Optional[str] = Query(None, description="过滤系统标识"),
    store_id: Optional[str] = Query(None, description="过滤门店ID"),
    status: Optional[str] = Query(None, description="过滤状态：success/partial_error"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> Dict[str, Any]:
    """同步日志列表（ProTable 数据格式）

    从 operation_logs 表读取 log_type='sync_record' 的记录，支持分页和过滤。

    返回格式符合 ProTable 规范：
      {"ok": true, "data": {"items": [...], "total": N}}
    """
    import json as _json

    offset = (page - 1) * page_size

    conditions = [
        "tenant_id = :tenant_id",
        "log_type  = 'sync_record'",
    ]
    params: Dict[str, Any] = {
        "tenant_id": x_tenant_id,
        "limit": page_size,
        "offset": offset,
    }

    if system:
        conditions.append("payload->>'system' = :system")
        params["system"] = system
    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where_clause = " AND ".join(conditions)

    try:
        engine = _get_engine()
        async with engine.connect() as conn:
            count_row = await conn.execute(
                text(f"SELECT COUNT(*) FROM operation_logs WHERE {where_clause}"),  # noqa: S608
                params,
            )
            total: int = count_row.scalar() or 0

            rows = await conn.execute(
                text(f"""
                    SELECT id, status, store_id, payload, created_at
                    FROM   operation_logs
                    WHERE  {where_clause}
                    ORDER  BY created_at DESC
                    LIMIT  :limit OFFSET :offset
                """),  # noqa: S608
                params,
            )
            items = []
            for row in rows.fetchall():
                payload_data: Dict[str, Any] = {}
                if row.payload:
                    try:
                        payload_data = _json.loads(row.payload) if isinstance(row.payload, str) else row.payload
                    except (ValueError, TypeError):
                        pass

                items.append({
                    "id": str(row.id),
                    "status": row.status,
                    "store_id": row.store_id,
                    "system": payload_data.get("system"),
                    "synced": payload_data.get("synced", 0),
                    "skipped": payload_data.get("skipped", 0),
                    "errors": payload_data.get("errors", []),
                    "duration_ms": payload_data.get("duration_ms"),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                })

    except (ValueError, RuntimeError) as exc:
        log.error("list_sync_logs_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }
