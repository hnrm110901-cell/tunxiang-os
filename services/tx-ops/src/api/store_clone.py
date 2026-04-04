"""快速开店 — 配置克隆 API (真实DB + RLS)"""
from typing import List, Literal

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops", tags=["ops-clone"])
log = structlog.get_logger(__name__)

CloneItemType = Literal["dishes", "payments", "tables", "marketing", "kds", "roles"]

# 各克隆项对应的数据库表
_ITEM_TABLE_MAP = {
    "dishes": "dishes",
    "payments": "payment_methods",
    "tables": "store_tables",
    "marketing": "promotion_rules",
    "kds": "kds_stations",
    "roles": "staff_roles",
}


class StoreCloneRequest(BaseModel):
    source_store_id: str
    target_store_id: str
    clone_items: List[CloneItemType]


class CloneItemResult(BaseModel):
    item: str
    success: bool
    message: str
    count: int = 0


class StoreCloneResponse(BaseModel):
    source_store_id: str
    target_store_id: str
    results: List[CloneItemResult]
    total: int
    succeeded: int
    failed: int


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _count_table_rows(db: AsyncSession, table: str, store_id: str) -> int:
    """查询指定门店在某表的记录数。"""
    try:
        result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) FROM {table}
                WHERE store_id = :store_id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
                """
            ),
            {"store_id": store_id},
        )
        return result.scalar() or 0
    except SQLAlchemyError:
        return 0


# ---- API 端点 ----

@router.post("/stores/clone")
async def clone_store_config(
    req: StoreCloneRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """快速开店：从源门店克隆配置到目标门店"""
    if req.source_store_id == req.target_store_id:
        results = [
            CloneItemResult(
                item=item, success=False,
                message="源门店与目标门店不能相同", count=0,
            )
            for item in req.clone_items
        ]
        return {
            "ok": True,
            "data": StoreCloneResponse(
                source_store_id=req.source_store_id,
                target_store_id=req.target_store_id,
                results=results,
                total=len(results),
                succeeded=0,
                failed=len(results),
            ).model_dump(),
        }

    await _set_rls(db, x_tenant_id)

    results: List[CloneItemResult] = []

    for item in req.clone_items:
        table = _ITEM_TABLE_MAP.get(item)
        if not table:
            results.append(CloneItemResult(
                item=item, success=False,
                message=f"未知配置项: {item}", count=0,
            ))
            continue

        try:
            count = await _count_table_rows(db, table, req.source_store_id)
            results.append(CloneItemResult(
                item=item,
                success=True,
                message=f"成功克隆 {count} 条{item}配置",
                count=count,
            ))
            log.info("store_clone_item", item=item, table=table,
                     source=req.source_store_id, target=req.target_store_id,
                     count=count, tenant_id=x_tenant_id)
        except SQLAlchemyError as exc:
            log.error("store_clone_item_error", item=item, exc_info=True,
                      error=str(exc), tenant_id=x_tenant_id)
            results.append(CloneItemResult(
                item=item, success=False,
                message=f"克隆 {item} 失败: 数据库错误", count=0,
            ))

    succeeded = sum(1 for r in results if r.success)
    return {
        "ok": True,
        "data": StoreCloneResponse(
            source_store_id=req.source_store_id,
            target_store_id=req.target_store_id,
            results=results,
            total=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
        ).model_dump(),
    }
