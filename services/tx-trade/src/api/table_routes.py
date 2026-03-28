"""桌台与包厢经营中心 API — 转台/并台/拆台/清台/看板/包厢/分析

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.table_operations import (
    transfer_table,
    merge_tables,
    split_table,
    clear_table,
    lock_table,
    get_table_status_board,
)
from ..services.room_rules import (
    check_minimum_charge,
    get_room_config,
    get_room_usage_today,
)

router = APIRouter(prefix="/api/v1/tables", tags=["tables"])


# ─── 工具函数 ───


def _get_tenant_id(request: Request) -> uuid.UUID:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return uuid.UUID(str(tid))


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── 请求模型 ───


class TransferTableReq(BaseModel):
    from_table_id: uuid.UUID
    to_table_id: uuid.UUID
    order_id: uuid.UUID


class MergeTablesReq(BaseModel):
    table_ids: list[uuid.UUID] = Field(min_length=2)
    main_table_id: uuid.UUID


class SplitTableReq(BaseModel):
    table_id: uuid.UUID
    new_orders: list[dict] = Field(default_factory=list, description="[{table_id, order_id}]")


class LockTableReq(BaseModel):
    table_id: uuid.UUID
    reservation_id: uuid.UUID


# ─── 1. 转台 ───


@router.post("/transfer")
async def api_transfer_table(
    req: TransferTableReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """转台 — 将顾客及订单从一张桌移动到另一张桌"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await transfer_table(
            from_table_id=req.from_table_id,
            to_table_id=req.to_table_id,
            order_id=req.order_id,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 2. 并台 ───


@router.post("/merge")
async def api_merge_tables(
    req: MergeTablesReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """并台 — 将多张桌合并到主桌"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await merge_tables(
            table_ids=req.table_ids,
            main_table_id=req.main_table_id,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 3. 拆台 ───


@router.post("/split")
async def api_split_table(
    req: SplitTableReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """拆台 — 将并台状态解除"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await split_table(
            table_id=req.table_id,
            new_orders=req.new_orders,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 4. 清台 ───


@router.post("/clear/{table_id}")
async def api_clear_table(
    table_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """清台 — 恢复桌台为空闲状态"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await clear_table(
            table_id=table_id,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 5. 桌态看板 ───


@router.get("/board/{store_id}")
async def api_table_board(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """桌态看板 — 全店桌台状态总览"""
    tenant_id = _get_tenant_id(request)
    result = await get_table_status_board(
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )
    return _ok(result)


# ─── 6. 包厢状态 ───


@router.get("/rooms/{store_id}")
async def api_room_status(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """包厢状态 — 今日所有包厢使用情况"""
    tenant_id = _get_tenant_id(request)
    result = await get_room_usage_today(
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )
    return _ok(result)


# ─── 7. 翻台分析（代理到 tx-analytics） ───


@router.get("/analytics/{store_id}")
async def api_table_analytics(
    store_id: uuid.UUID,
    date: Optional[str] = Query(None, description="日期 YYYY-MM-DD，默认今天"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """翻台分析 — 翻台率、使用率等核心指标

    注：完整分析由 tx-analytics 服务提供，此处提供快速摘要。
    """
    from datetime import date as date_type

    tenant_id = _get_tenant_id(request)

    # 解析日期
    if date:
        try:
            target_date = date_type.fromisoformat(date)
        except ValueError:
            _err(f"日期格式错误: {date}，需 YYYY-MM-DD")
            return
    else:
        from datetime import datetime, timezone
        target_date = datetime.now(timezone.utc).date()

    # 快速桌态统计（复用看板数据）
    board = await get_table_status_board(
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )
    stats = board["stats"]

    # 包厢使用情况
    rooms = await get_room_usage_today(
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )
    rooms_occupied = sum(1 for r in rooms if r["status"] == "occupied")

    return _ok({
        "store_id": str(store_id),
        "date": str(target_date),
        "table_stats": stats,
        "room_summary": {
            "total": len(rooms),
            "occupied": rooms_occupied,
            "utilization_rate": round(rooms_occupied / len(rooms), 4) if rooms else 0.0,
        },
    })
