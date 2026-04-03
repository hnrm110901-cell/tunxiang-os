"""菜单实时编辑 API — PATCH /api/v1/menu/dishes/{dish_id}/live"""
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/menu", tags=["menu-live-edit"])

MAC_STATION_URL = os.getenv("MAC_STATION_URL", "")


# ─── 请求体 ───

class LiveDishUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None          # 单位：分（整数）
    description: Optional[str] = None
    is_available: Optional[bool] = None  # 是否上架
    daily_limit: Optional[int] = None    # 每日限量，None=不限
    image_url: Optional[str] = None
    updated_by: Optional[str] = None     # 操作员名称（用于广播消息）


class BulkAvailabilityUpdate(BaseModel):
    dish_ids: list[str] = Field(..., min_length=1)
    is_available: bool
    reason: Optional[str] = None         # 例如 "今日估清" / "食材到货恢复"
    updated_by: Optional[str] = None


# ─── 广播工具 ───

async def _broadcast_menu_update(dish_id: str, changes: dict, updated_by: str) -> None:
    """向 mac-station 广播菜单变更事件，失败不影响主流程。"""
    if not MAC_STATION_URL:
        logger.debug("broadcast_skipped", reason="MAC_STATION_URL not set", dish_id=dish_id)
        return
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            await client.post(
                f"{MAC_STATION_URL}/api/kds/broadcast",
                json={
                    "event": "menu_dish_updated",
                    "data": {
                        "dish_id": dish_id,
                        "changes": changes,
                        "updated_by": updated_by,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
            logger.info("broadcast_sent", dish_id=dish_id, updated_by=updated_by)
        except httpx.RequestError as exc:
            logger.warning("broadcast_failed", dish_id=dish_id, error=str(exc))


async def _broadcast_bulk_update(dish_ids: list[str], is_available: bool, reason: str, updated_by: str) -> None:
    """向 mac-station 广播批量上下架事件，失败不影响主流程。"""
    if not MAC_STATION_URL:
        logger.debug("bulk_broadcast_skipped", reason="MAC_STATION_URL not set")
        return
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            await client.post(
                f"{MAC_STATION_URL}/api/kds/broadcast",
                json={
                    "event": "menu_bulk_availability_updated",
                    "data": {
                        "dish_ids": dish_ids,
                        "is_available": is_available,
                        "reason": reason,
                        "updated_by": updated_by,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
            logger.info("bulk_broadcast_sent", count=len(dish_ids), is_available=is_available)
        except httpx.RequestError as exc:
            logger.warning("bulk_broadcast_failed", error=str(exc))


# ─── 端点 ───

@router.patch("/dishes/{dish_id}/live")
async def live_update_dish(
    dish_id: str,
    req: LiveDishUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    实时编辑菜品（不停机同步到所有终端）。

    修改成功后立即广播到 mac-station，mac-station 通过 WebSocket 推送到
    KDS / 服务员端等所有在线终端，端到端延迟目标 ≤ 5s。
    """
    if not dish_id or not dish_id.strip():
        raise HTTPException(status_code=400, detail="dish_id 不能为空")

    changes = req.model_dump(exclude_none=True, exclude={"updated_by"})

    if not changes:
        raise HTTPException(status_code=400, detail="至少需要提供一个要修改的字段")

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    # Map pydantic field names to DB column names
    col_map = {
        "name": "dish_name",
        "price": "price_fen",
        "description": "description",
        "is_available": "is_available",
        "daily_limit": "daily_limit",
        "image_url": "image_url",
    }
    set_clauses = ", ".join(
        f"{col_map.get(k, k)} = :{k}" for k in changes
    )
    await db.execute(
        text(f"UPDATE dishes SET {set_clauses}, updated_at = NOW() WHERE id = :dish_id AND tenant_id = :tid::uuid AND is_deleted = false"),
        {**changes, "dish_id": dish_id, "tid": x_tenant_id},
    )
    await db.commit()

    synced_at = datetime.now(timezone.utc).isoformat()
    updated_by = req.updated_by or "unknown"

    logger.info(
        "live_dish_updated",
        dish_id=dish_id,
        changes=changes,
        updated_by=updated_by,
    )

    await _broadcast_menu_update(
        dish_id=dish_id,
        changes=changes,
        updated_by=updated_by,
    )

    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "synced_at": synced_at,
            "broadcast": bool(MAC_STATION_URL),
        },
    }


@router.post("/dishes/bulk-availability")
async def bulk_update_availability(
    req: BulkAvailabilityUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    批量上/下架菜品（例如今日估清）。

    支持一次操作多个菜品，修改后广播到所有终端。
    """
    if not req.dish_ids:
        raise HTTPException(status_code=400, detail="dish_ids 不能为空")

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    await db.execute(
        text("""
            UPDATE dishes
               SET is_available = :is_available, updated_at = NOW()
             WHERE id = ANY(:ids::uuid[])
               AND tenant_id = :tid::uuid
               AND is_deleted = false
        """),
        {
            "is_available": req.is_available,
            "ids": req.dish_ids,
            "tid": x_tenant_id,
        },
    )
    await db.commit()

    updated_by = req.updated_by or "unknown"
    reason = req.reason or ""

    logger.info(
        "bulk_availability_updated",
        dish_count=len(req.dish_ids),
        is_available=req.is_available,
        reason=reason,
        updated_by=updated_by,
    )

    await _broadcast_bulk_update(
        dish_ids=req.dish_ids,
        is_available=req.is_available,
        reason=reason,
        updated_by=updated_by,
    )

    return {
        "ok": True,
        "data": {
            "updated_count": len(req.dish_ids),
            "is_available": req.is_available,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "broadcast": bool(MAC_STATION_URL),
        },
    }
