"""交易域 API — 订单 CRUD + 支付 + 小票打印（已接通数据库）

R-A1-3 / Tier1（commit 5ec4660d 基建之上的路由集成）：
  - settle_order / create_payment 接 X-Idempotency-Key header
  - 闭环 apps/web-pos R-补2-1 (commit 48aba740) 客户端契约
  - 防 saga 双扣 / 储值双扣 / 第三方支付双扣
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.api_idempotency import (
    IdempotencyKeyConflict,
    acquire_idempotency_lock,
    compute_request_hash,
    get_cached_response,
    store_cached_response,
)
from ..services.order_service import OrderService
from ..services.payment_service import PaymentService
from ..services.receipt_service import ReceiptService

router = APIRouter(prefix="/api/v1/trade", tags=["trade"])

# 路由模板（含 {order_id} 占位）— 仅用于审查/文档，不直接喂给 cache。
# 路由代码必须 .format(order_id=order_id) 注入实际 order_id 后再传给 cache 层，
# 否则 advisory_lock_id / request_hash / cache PK 都跨 order 共享 → 同 key 串扰。
# 见 §19 复审 P1（chatgpt-codex-connector PR #111 第 2 条 review）。
_ROUTE_SETTLE_TEMPLATE = "/api/v1/trade/orders/{order_id}/settle"
_ROUTE_PAYMENT_TEMPLATE = "/api/v1/trade/orders/{order_id}/payments"


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _concrete_route(template: str, order_id: str) -> str:
    """模板 → 含具体 order_id 的路径。

    R-A1-3 P1 修复：把 order_id 注入 route_path，让 advisory_lock_id /
    request_hash / cache PK 三处都按 (tenant, key, order, route) 唯一定位 →
    即便客户端 bug 让两个不同 order 共用同一 X-Idempotency-Key（例如 settle
    空 body + 同 key），也不会跨 order 共享 cache 命中或锁。
    """
    return template.format(order_id=order_id)


async def _check_idempotency_cache(
    db: AsyncSession,
    *,
    tenant_id: str,
    idempotency_key: Optional[str],
    route_template: str,
    order_id: str,
    body_for_hash: str,
) -> tuple[Optional[dict], str, str]:
    """路由进入时调用：取 advisory_lock + 检查 cache。

    Args:
        route_template: 含 {order_id} 占位的路由模板（_ROUTE_SETTLE_TEMPLATE 等）。
        order_id: 当前请求的具体 order_id；与 template 拼成 concrete route_path
                  作为 cache PK / advisory_lock 的一部分（防跨 order 串扰）。

    Returns:
        (cached_body, request_hash, route_path) —
            cached_body 非 None 时直接返回给客户端（路由 short-circuit）；
            否则继续业务处理，业务完成后调用方用 route_path 调 store_cached_response。

    Raises:
        HTTPException(422) on IdempotencyKeyConflict（同 key 不同 body）
    """
    route_path = _concrete_route(route_template, order_id)

    if not idempotency_key:
        return None, "", route_path

    request_hash = compute_request_hash("POST", route_path, body_for_hash)

    # 取事务级锁（同 (tenant, key, route_path) 并发自动串行，commit 自动释放）
    await acquire_idempotency_lock(
        db, tenant_id=tenant_id, idempotency_key=idempotency_key, route_path=route_path,
    )

    try:
        cached = await get_cached_response(
            db,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            route_path=route_path,
            request_hash=request_hash,
        )
    except IdempotencyKeyConflict as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "message": str(exc),
            },
        ) from exc

    if cached is not None:
        return cached.body, request_hash, route_path
    return None, request_hash, route_path


# ─── 请求模型 ───


class CreateOrderReq(BaseModel):
    store_id: str
    order_type: str = "dine_in"
    table_no: Optional[str] = None
    customer_id: Optional[str] = None
    waiter_id: Optional[str] = None


class AddItemReq(BaseModel):
    dish_id: str
    dish_name: str
    quantity: int
    unit_price_fen: int
    notes: Optional[str] = None
    customizations: Optional[dict] = None


class UpdateItemQtyReq(BaseModel):
    new_quantity: int


class ApplyDiscountReq(BaseModel):
    discount_fen: int
    reason: str = ""


class CreatePaymentReq(BaseModel):
    method: str
    amount_fen: int
    trade_no: Optional[str] = None
    credit_account_name: Optional[str] = None


class RefundReq(BaseModel):
    payment_id: str
    amount_fen: int
    refund_type: str = "full"
    reason: str = ""


# ─── 订单端点 ───


@router.post("/orders")
async def create_order(req: CreateOrderReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.create_order(
        store_id=req.store_id,
        order_type=req.order_type,
        table_no=req.table_no,
        customer_id=req.customer_id,
        waiter_id=req.waiter_id,
    )
    return {"ok": True, "data": result, "error": None}


@router.post("/orders/{order_id}/items")
async def add_item(order_id: str, req: AddItemReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.add_item(
        order_id=order_id,
        dish_id=req.dish_id,
        dish_name=req.dish_name,
        quantity=req.quantity,
        unit_price_fen=req.unit_price_fen,
        notes=req.notes,
        customizations=req.customizations,
    )
    return {"ok": True, "data": result, "error": None}


@router.patch("/orders/{order_id}/items/{item_id}")
async def update_item(
    order_id: str, item_id: str, req: UpdateItemQtyReq, request: Request, db: AsyncSession = Depends(get_db)
):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.update_item_quantity(item_id=item_id, new_quantity=req.new_quantity)
    return {"ok": True, "data": result, "error": None}


@router.delete("/orders/{order_id}/items/{item_id}")
async def remove_item(order_id: str, item_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.remove_item(item_id=item_id)
    return {"ok": True, "data": result, "error": None}


@router.post("/orders/{order_id}/discount")
async def apply_discount(order_id: str, req: ApplyDiscountReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.apply_discount(order_id=order_id, discount_fen=req.discount_fen, reason=req.reason)
    return {"ok": True, "data": result, "error": None}


@router.post("/orders/{order_id}/settle")
async def settle_order(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """结算订单。R-A1-3 / Tier1：X-Idempotency-Key replay cache 防 saga 双扣。

    客户端契约（apps/web-pos R-补2-1）：
      - replay 时携带 `X-Idempotency-Key: settle:{order_id}`
      - 同 key 重试 → 服务端读 cache → 返回原响应（不再处理业务）
      - 同 key 不同 body → 422 IDEMPOTENCY_KEY_CONFLICT
    """
    tenant_id = _get_tenant_id(request)

    # 路由进入：检 cache（命中则 short-circuit）
    # settle_order 无 request body，body_for_hash 用空串
    # route_template + order_id → concrete route_path（防同 key 跨 order 串扰）
    cached_body, request_hash, route_path = await _check_idempotency_cache(
        db,
        tenant_id=tenant_id,
        idempotency_key=x_idempotency_key,
        route_template=_ROUTE_SETTLE_TEMPLATE,
        order_id=order_id,
        body_for_hash="",
    )
    if cached_body is not None:
        return cached_body

    # 业务处理
    svc = OrderService(db, tenant_id)
    result = await svc.settle_order(order_id=order_id)
    response_body = {"ok": True, "data": result, "error": None}

    # 落 cache（仍持 advisory_lock，事务尚未 commit）
    if x_idempotency_key:
        await store_cached_response(
            db,
            tenant_id=tenant_id,
            idempotency_key=x_idempotency_key,
            route_path=route_path,
            request_hash=request_hash,
            response_status=200,
            response_body=response_body,
        )

    return response_body


@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, reason: str = "", request: Request = None, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.cancel_order(order_id=order_id, reason=reason)
    return {"ok": True, "data": result, "error": None}


@router.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.get_order(order_id=order_id)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"ok": True, "data": result, "error": None}


# ─── 支付端点 ───


@router.post("/orders/{order_id}/payments")
async def create_payment(
    order_id: str,
    req: CreatePaymentReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """创建支付。R-A1-3 / Tier1：X-Idempotency-Key replay cache 防双扣。

    客户端契约（apps/web-pos R-补2-1）：
      - replay 时携带 `X-Idempotency-Key: payment:{order_id}:{method}`
      - 同 key 重试 → cache 命中 → 不再扣会员储值/不再调第三方支付
    """
    tenant_id = _get_tenant_id(request)

    # body_for_hash 用 pydantic 序列化，比 raw bytes 更稳定（字段顺序固定）
    # route_template + order_id → concrete route_path（防同 key 跨 order 串扰）
    cached_body, request_hash, route_path = await _check_idempotency_cache(
        db,
        tenant_id=tenant_id,
        idempotency_key=x_idempotency_key,
        route_template=_ROUTE_PAYMENT_TEMPLATE,
        order_id=order_id,
        body_for_hash=req.model_dump_json(),
    )
    if cached_body is not None:
        return cached_body

    svc = PaymentService(db, tenant_id)
    result = await svc.create_payment(
        order_id=order_id,
        method=req.method,
        amount_fen=req.amount_fen,
        trade_no=req.trade_no,
        credit_account_name=req.credit_account_name,
    )
    response_body = {"ok": True, "data": result, "error": None}

    if x_idempotency_key:
        await store_cached_response(
            db,
            tenant_id=tenant_id,
            idempotency_key=x_idempotency_key,
            route_path=route_path,
            request_hash=request_hash,
            response_status=200,
            response_body=response_body,
        )

    return response_body


@router.post("/orders/{order_id}/refund")
async def refund(order_id: str, req: RefundReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = PaymentService(db, _get_tenant_id(request))
    result = await svc.process_refund(
        order_id=order_id,
        payment_id=req.payment_id,
        amount_fen=req.amount_fen,
        refund_type=req.refund_type,
        reason=req.reason,
    )
    return {"ok": True, "data": result, "error": None}


@router.get("/orders/{order_id}/payments")
async def get_payments(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = PaymentService(db, _get_tenant_id(request))
    result = await svc.get_order_payments(order_id=order_id)
    return {"ok": True, "data": result, "error": None}


# ─── 打印端点 ───


@router.post("/orders/{order_id}/print/receipt")
async def print_receipt(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    content = ReceiptService.format_receipt(order, store_name="屯象")
    return {"ok": True, "data": {"content_base64": content.hex(), "content_length": len(content)}, "error": None}


@router.post("/orders/{order_id}/print/kitchen")
async def print_kitchen(order_id: str, station: str = "", request: Request = None, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if station:
        content = ReceiptService.format_kitchen_order(order, station=station)
        return {"ok": True, "data": {"station": station, "content_length": len(content)}, "error": None}

    # 自动按档口分单
    stations = ReceiptService.split_by_station(order)
    results = []
    for st, items in stations.items():
        station_order = {**order, "items": items}
        content = ReceiptService.format_kitchen_order(station_order, station=st)
        results.append({"station": st, "item_count": len(items), "content_length": len(content)})
    return {"ok": True, "data": {"stations": results}, "error": None}
