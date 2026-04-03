"""沽清全链路同步服务

流程：
  1. 后厨在KDS屏幕标记某菜品缺料/沽清
  2. 写入 soldout_records 表（带sync_status追踪）
  3. 通知 tx-menu 服务（更新菜品可售状态）
  4. 通过 Mac mini WebSocket 推送到 POS（前台实时灰显）
  5. 通过 Mac mini 推送事件到小程序（顾客端实时沽清）

恢复沽清：
  - 采购到货 / 厨师手动恢复后可取消沽清
  - 恢复后同步到全链路
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.soldout_record import SoldoutRecord

logger = structlog.get_logger()

MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")
TX_MENU_URL = os.getenv("TX_MENU_SERVICE_URL", "http://tx-menu:8001")


async def mark_soldout(
    tenant_id: str,
    store_id: str,
    dish_id: str,
    dish_name: str,
    reason: Optional[str],
    reported_by: Optional[str],
    db: AsyncSession,
) -> dict:
    """标记菜品沽清，并触发全链路同步。"""
    # 检查是否已沽清
    result = await db.execute(
        select(SoldoutRecord).where(
            SoldoutRecord.tenant_id == uuid.UUID(tenant_id),
            SoldoutRecord.store_id == uuid.UUID(store_id),
            SoldoutRecord.dish_id == uuid.UUID(dish_id),
            SoldoutRecord.is_active.is_(True),
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {
            "dish_id": dish_id,
            "already_soldout": True,
            "soldout_at": existing.soldout_at.isoformat(),
        }

    now = datetime.now(timezone.utc)
    record = SoldoutRecord(
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(store_id),
        dish_id=uuid.UUID(dish_id),
        dish_name=dish_name,
        soldout_at=now,
        reason=reason,
        reported_by=uuid.UUID(reported_by) if reported_by else None,
        source="kds",
        is_active=True,
        sync_status={"pos": False, "miniapp": False, "kds": True},
    )
    db.add(record)
    await db.flush()
    record_id = str(record.id)

    sync_results = await _sync_soldout_to_all(
        record_id=record_id,
        tenant_id=tenant_id,
        store_id=store_id,
        dish_id=dish_id,
        dish_name=dish_name,
        action="soldout",
        db=db,
    )

    await db.commit()

    logger.info(
        "kds.soldout.marked",
        dish_id=dish_id,
        dish_name=dish_name,
        sync=sync_results,
    )
    return {
        "dish_id": dish_id,
        "record_id": record_id,
        "soldout_at": now.isoformat(),
        "sync_status": sync_results,
    }


async def restore_soldout(
    tenant_id: str,
    store_id: str,
    dish_id: str,
    db: AsyncSession,
) -> dict:
    """恢复沽清（菜品重新可售），触发全链路同步。"""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(SoldoutRecord).where(
            SoldoutRecord.tenant_id == uuid.UUID(tenant_id),
            SoldoutRecord.store_id == uuid.UUID(store_id),
            SoldoutRecord.dish_id == uuid.UUID(dish_id),
            SoldoutRecord.is_active.is_(True),
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise ValueError(f"菜品 {dish_id} 当前不在沽清状态")

    await db.execute(
        update(SoldoutRecord)
        .where(SoldoutRecord.id == record.id)
        .values(is_active=False, restore_at=now, updated_at=now)
    )

    sync_results = await _sync_soldout_to_all(
        record_id=str(record.id),
        tenant_id=tenant_id,
        store_id=store_id,
        dish_id=dish_id,
        dish_name=record.dish_name,
        action="restore",
        db=db,
    )

    await db.commit()

    logger.info("kds.soldout.restored", dish_id=dish_id, sync=sync_results)
    return {
        "dish_id": dish_id,
        "restored_at": now.isoformat(),
        "sync_status": sync_results,
    }


async def get_active_soldout(
    tenant_id: str,
    store_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询当前门店所有沽清菜品。"""
    result = await db.execute(
        select(SoldoutRecord).where(
            SoldoutRecord.tenant_id == uuid.UUID(tenant_id),
            SoldoutRecord.store_id == uuid.UUID(store_id),
            SoldoutRecord.is_active.is_(True),
        )
    )
    records = result.scalars().all()
    return [
        {
            "dish_id": str(r.dish_id),
            "dish_name": r.dish_name,
            "soldout_at": r.soldout_at.isoformat(),
            "reason": r.reason,
            "source": r.source,
        }
        for r in records
    ]


# ─── 内部同步逻辑 ───

async def _sync_soldout_to_all(
    record_id: str,
    tenant_id: str,
    store_id: str,
    dish_id: str,
    dish_name: str,
    action: str,
    db: AsyncSession,
) -> dict:
    """向 tx-menu 和 Mac mini WebSocket 同步沽清状态。"""
    sync_status: dict[str, bool] = {}

    # 1. 同步到 tx-menu（POS 和小程序菜单的可售状态）
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{TX_MENU_URL}/api/v1/menu/dishes/{dish_id}/soldout",
                json={
                    "store_id": store_id,
                    "action": action,
                    "reason": f"KDS同步 record_id={record_id}",
                },
                headers={"X-Tenant-ID": tenant_id},
            )
            sync_status["menu_service"] = resp.status_code == 200
    except httpx.RequestError as e:
        logger.warning("kds.soldout.sync.menu_failed", error=str(e))
        sync_status["menu_service"] = False

    # 2. 通过 Mac mini WebSocket 推送到 KDS 屏 + POS
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(
                f"{MAC_STATION_URL}/api/kds/broadcast",
                json={
                    "event": "soldout_changed",
                    "store_id": store_id,
                    "data": {
                        "dish_id": dish_id,
                        "dish_name": dish_name,
                        "action": action,
                        "record_id": record_id,
                    },
                },
                headers={"X-Tenant-ID": tenant_id},
            )
            sync_status["ws_push"] = resp.status_code == 200
    except httpx.RequestError as e:
        logger.warning("kds.soldout.sync.ws_failed", error=str(e))
        sync_status["ws_push"] = False

    # 更新 sync_status 字段
    await db.execute(
        update(SoldoutRecord)
        .where(SoldoutRecord.id == uuid.UUID(record_id))
        .values(
            sync_status={
                "pos": sync_status.get("menu_service", False),
                "miniapp": sync_status.get("menu_service", False),
                "kds": True,
                "ws_push": sync_status.get("ws_push", False),
            }
        )
    )

    return sync_status
