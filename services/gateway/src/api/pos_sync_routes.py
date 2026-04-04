"""
POS 同步状态与日志查询 API 路由

端点:
  GET  /api/v1/integrations/sync-logs  — 查询同步历史
       参数: merchant_code (可选), days (可选, 默认7), page, size

所有端点需要 X-Tenant-ID header（由 TenantMiddleware 注入）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Query, Request
from sqlalchemy import text

from ..response import ok

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/integrations", tags=["pos-sync"])


@router.get("/sync-logs")
async def get_sync_logs(
    request: Request,
    merchant_code: Optional[str] = Query(None, description="商户代码：czyz / zqx / sgc"),
    sync_type: Optional[str] = Query(None, description="同步类型过滤"),
    days: int = Query(7, ge=1, le=90, description="查询最近 N 天，默认 7"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> dict:
    """
    查询品智POS数据同步历史日志。

    - 支持按商户代码、同步类型过滤
    - 按 started_at 倒序，支持分页
    - 仅返回当前租户的数据（RLS 隔离）
    """
    tenant_id: Optional[str] = getattr(request.state, "tenant_id", None)

    if not tenant_id:
        return ok({
            "items": [],
            "total": 0,
            "page": page,
            "size": size,
            "message": "X-Tenant-ID 未配置，返回空结果",
        })

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    offset = (page - 1) * size

    try:
        from shared.ontology.src.database import async_session_factory

        async with async_session_factory() as db:
            # 设置 RLS 上下文
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )

            # 构建过滤条件
            conditions = ["tenant_id = :tenant_id::uuid", "started_at >= :since"]
            params: dict = {"tenant_id": str(tenant_id), "since": since}

            if merchant_code:
                conditions.append("merchant_code = :merchant_code")
                params["merchant_code"] = merchant_code

            if sync_type:
                conditions.append("sync_type = :sync_type")
                params["sync_type"] = sync_type

            where_clause = " AND ".join(conditions)

            # 总数查询
            count_result = await db.execute(
                text(f"SELECT COUNT(*) FROM sync_logs WHERE {where_clause}"),
                params,
            )
            total: int = count_result.scalar() or 0

            # 数据查询
            rows_result = await db.execute(
                text(
                    f"""
                    SELECT
                        id, tenant_id, merchant_code, sync_type, status,
                        records_synced, error_msg, started_at, finished_at, created_at
                    FROM sync_logs
                    WHERE {where_clause}
                    ORDER BY started_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": size, "offset": offset},
            )
            rows = rows_result.mappings().all()

            items = [
                {
                    "id": str(row["id"]),
                    "merchant_code": row["merchant_code"],
                    "sync_type": row["sync_type"],
                    "status": row["status"],
                    "records_synced": row["records_synced"],
                    "error_msg": row["error_msg"],
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
                    "duration_seconds": (
                        (row["finished_at"] - row["started_at"]).total_seconds()
                        if row["finished_at"] and row["started_at"]
                        else None
                    ),
                }
                for row in rows
            ]

        logger.info(
            "sync_logs_queried",
            tenant_id=str(tenant_id),
            merchant_code=merchant_code,
            days=days,
            total=total,
        )
        return ok({
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        })

    except ImportError:
        logger.warning("sync_logs_db_not_configured")
        return ok({
            "items": [],
            "total": 0,
            "page": page,
            "size": size,
            "message": "数据库未配置，返回空结果",
        })
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("sync_logs_query_failed", error=str(exc), exc_info=True)
        return ok({
            "items": [],
            "total": 0,
            "page": page,
            "size": size,
            "message": f"查询失败: {exc}",
        })
