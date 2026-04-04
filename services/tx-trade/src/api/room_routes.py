"""包间管理 API — 服务费/超时/可用时段/结账低消校验

面向高端餐饮（徐记海鲜等），包间是核心营收场景。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。金额单位：分(fen)。
"""
import uuid
from datetime import date as date_type, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.room_rules import (
    calculate_service_charge,
    check_room_timeout,
    enforce_min_spend_at_checkout,
    get_room_availability,
)

router = APIRouter(prefix="/api/v1/trade/rooms", tags=["rooms"])


# ─── 工具函数 ───


def _get_tenant_id(request: Request) -> uuid.UUID:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return uuid.UUID(str(tid))


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 1. 包间可用时段 ───


@router.get("/availability")
async def api_room_availability(
    store_id: uuid.UUID = Query(..., description="门店ID"),
    date: str = Query(None, description="日期 YYYY-MM-DD，默认今天"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """查询门店所有包间在指定日期的可用时段

    交叉比对预订记录，返回每个包间的午市/晚市占用情况。
    用于前台接待、线上预订展示。
    """
    tenant_id = _get_tenant_id(request)

    if date:
        try:
            target_date = date_type.fromisoformat(date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"ok": False, "data": None, "error": {"message": f"日期格式错误: {date}，需 YYYY-MM-DD"}},
            )
    else:
        target_date = datetime.now(timezone.utc).date()

    try:
        result = await get_room_availability(
            store_id=store_id,
            target_date=target_date,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "data": None, "error": {"message": str(exc)}},
        )

    return _ok(result)


# ─── 2. 包间超时检查 ───


@router.get("/{table_no}/timeout")
async def api_room_timeout(
    table_no: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """检查包间是否超过用餐时限

    返回超时状态、已用时间、超出分钟数。
    前端据此弹出超时提醒通知。
    """
    tenant_id = _get_tenant_id(request)

    try:
        result = await check_room_timeout(
            table_no=table_no,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "data": None, "error": {"message": str(exc)}},
        )

    return _ok(result)


# ─── 3. 包间服务费计算 ───


@router.get("/{table_no}/service-charge")
async def api_room_service_charge(
    table_no: str,
    order_id: uuid.UUID = Query(..., description="订单ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """计算包间服务费/包间费

    根据包间配置，按比例(service_charge_rate)或固定金额(room_fee_fen)计算。
    比例优先于固定金额。
    """
    tenant_id = _get_tenant_id(request)

    try:
        result = await calculate_service_charge(
            order_id=order_id,
            table_no=table_no,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "data": None, "error": {"message": str(exc)}},
        )

    return _ok(result)


# ─── 4. 结账低消校验 ───


@router.post("/{table_no}/enforce-min-spend")
async def api_enforce_min_spend(
    table_no: str,
    order_id: uuid.UUID = Query(..., description="订单ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """结账时校验包间低消是否达标

    若未达标，返回差额及是否建议自动加收包间服务费补齐。
    收银员据此决定是否补收或提示顾客加点。
    """
    tenant_id = _get_tenant_id(request)

    try:
        result = await enforce_min_spend_at_checkout(
            order_id=order_id,
            table_no=table_no,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "data": None, "error": {"message": str(exc)}},
        )

    return _ok(result)
