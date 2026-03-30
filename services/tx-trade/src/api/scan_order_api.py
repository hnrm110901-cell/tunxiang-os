"""扫码点餐 API — 扩展端点（补充 scan_order_routes.py）

8个端点：
1. POST /scan-order/qrcode/generate     — 生成桌码
2. POST /scan-order/qrcode/parse        — 解析桌码
3. POST /scan-order/create              — 扫码下单（含菜品列表）
4. POST /scan-order/add-items           — 加菜（同桌追加）
5. GET  /scan-order/table-order         — 查看当桌订单
6. POST /scan-order/checkout            — 请求结账
7. POST /scan-order/sync-kds            — 手动同步KDS
8. GET  /scan-order/stats               — 扫码点餐统计
"""
import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.scan_order_service import (
    generate_table_qrcode,
    parse_qrcode,
    create_scan_order,
    add_items_to_order,
    get_table_order,
    request_checkout,
    sync_to_kds,
    get_scan_order_stats,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/scan-order", tags=["scan-order-ext"])


# ─── 通用工具 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    raise HTTPException(status_code=code, detail={"ok": False, "data": None, "error": {"message": msg}})


# ─── 请求模型 ───


class QrcodeGenerateReq(BaseModel):
    store_id: str
    table_id: str


class QrcodeParseReq(BaseModel):
    code: str


class ScanOrderItemReq(BaseModel):
    dish_id: str
    quantity: int = Field(ge=1, default=1)
    notes: Optional[str] = None


class ScanOrderCreateReq(BaseModel):
    store_id: str
    table_id: str
    items: list[ScanOrderItemReq]
    customer_id: Optional[str] = None


class AddItemsReq(BaseModel):
    order_id: str
    items: list[ScanOrderItemReq]


class CheckoutReq(BaseModel):
    order_id: str


class SyncKdsReq(BaseModel):
    order_id: str


# ─── 1. 生成桌码 ───


@router.post("/qrcode/generate")
async def api_generate_qrcode(
    req: QrcodeGenerateReq,
    request: Request,
):
    """生成桌码 — 含门店+桌号编码，返回桌码字符串和小程序跳转路径"""
    tenant_id = _get_tenant_id(request)

    result = generate_table_qrcode(
        store_id=req.store_id,
        table_id=req.table_id,
        tenant_id=tenant_id,
    )

    return _ok(result)


# ─── 2. 解析桌码 ───


@router.post("/qrcode/parse")
async def api_parse_qrcode(
    req: QrcodeParseReq,
    request: Request,
):
    """解析桌码 — 从桌码字符串中提取门店简码和桌号"""
    _get_tenant_id(request)

    try:
        result = parse_qrcode(req.code)
    except ValueError as e:
        _err(str(e))
        return

    return _ok(result)


# ─── 3. 扫码下单 ───


@router.post("/create")
async def api_create_scan_order(
    req: ScanOrderCreateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """扫码下单 — 创建订单并添加菜品，自动同步KDS

    同桌已有订单时自动追加。
    """
    tenant_id = _get_tenant_id(request)

    items = [
        {
            "dish_id": item.dish_id,
            "quantity": item.quantity,
            "notes": item.notes or "",
        }
        for item in req.items
    ]

    try:
        result = await create_scan_order(
            store_id=req.store_id,
            table_id=req.table_id,
            items=items,
            customer_id=req.customer_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()
    return _ok(result)


# ─── 4. 加菜（同桌追加） ───


@router.post("/add-items")
async def api_add_items(
    req: AddItemsReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """加菜 — 同桌追加菜品到现有订单，自动同步KDS"""
    tenant_id = _get_tenant_id(request)

    items = [
        {
            "dish_id": item.dish_id,
            "quantity": item.quantity,
            "notes": item.notes or "",
        }
        for item in req.items
    ]

    try:
        result = await add_items_to_order(
            order_id=req.order_id,
            items=items,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()
    return _ok(result)


# ─── 5. 查看当桌订单 ───


@router.get("/table-order")
async def api_get_table_order(
    store_id: str = Query(..., description="门店ID"),
    table_id: str = Query(..., description="桌号"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """查看当桌订单 — 返回桌台当前进行中的订单及明细"""
    tenant_id = _get_tenant_id(request)

    result = await get_table_order(
        store_id=store_id,
        table_id=table_id,
        tenant_id=tenant_id,
        db=db,
    )

    if not result:
        return _ok({"order": None, "message": "当桌暂无订单"})

    return _ok(result)


# ─── 6. 请求结账 ───


@router.post("/checkout")
async def api_request_checkout(
    req: CheckoutReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """请求结账 — 通知收银台该桌需要结账"""
    tenant_id = _get_tenant_id(request)

    try:
        result = await request_checkout(
            order_id=req.order_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()
    return _ok(result)


# ─── 7. 手动同步KDS ───


@router.post("/sync-kds")
async def api_sync_kds(
    req: SyncKdsReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """手动同步KDS — 将未发送的菜品推送到后厨"""
    tenant_id = _get_tenant_id(request)

    try:
        result = await sync_to_kds(
            order_id=req.order_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()
    return _ok(result)


# ─── 8. 扫码点餐统计 ───


@router.get("/stats")
async def api_get_stats(
    store_id: str = Query(..., description="门店ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """扫码点餐统计 — 指定门店和日期范围的扫码点餐数据"""
    tenant_id = _get_tenant_id(request)

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        _err("日期格式错误，请使用 YYYY-MM-DD")
        return

    if start > end:
        _err("开始日期不能大于结束日期")
        return

    result = await get_scan_order_stats(
        store_id=store_id,
        date_range=(start, end),
        tenant_id=tenant_id,
        db=db,
    )

    return _ok(result)
