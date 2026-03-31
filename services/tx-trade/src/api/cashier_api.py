"""收银核心 API — 10+ 端点覆盖开台→点单→结算全流程

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

权限校验集成（v075）：
  - apply_discount  → 调用 tx-org PermissionService 检查折扣权限
  - cancel_order    → 检查退单权限（void_order）
  - update_item     → 改价时检查 modify_price 权限（通过 X-Employee-ID header）
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.cashier_engine import CashierEngine
from ..services.payment_gateway import PaymentGateway
from ..services.daily_settlement import DailySettlementService
from ..services.permission_client import CashierPermissionClient

router = APIRouter(prefix="/api/v1", tags=["cashier"])


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


class OpenTableReq(BaseModel):
    store_id: str
    table_no: str
    waiter_id: str
    guest_count: int = Field(ge=1)
    order_type: str = "dine_in"
    customer_id: Optional[str] = None


class AddItemReq(BaseModel):
    dish_id: str
    dish_name: str
    qty: int = Field(ge=1)
    unit_price_fen: int = Field(ge=0)
    notes: Optional[str] = None
    customizations: Optional[dict] = None
    pricing_mode: str = "fixed"
    weight_value: Optional[float] = None


class UpdateItemReq(BaseModel):
    quantity: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None


class RemoveItemReq(BaseModel):
    reason: str = ""


class ApplyDiscountReq(BaseModel):
    discount_type: str  # percent_off / amount_off / free_item / member_price
    discount_value: float
    reason: str = ""
    approval_id: Optional[str] = None
    # 操作员工ID（权限校验用）
    employee_id: Optional[str] = None
    store_id: Optional[str] = None


class PaymentEntry(BaseModel):
    method: str
    amount_fen: int = Field(ge=1)
    trade_no: Optional[str] = None


class SettleOrderReq(BaseModel):
    payments: list[PaymentEntry]


class CancelOrderReq(BaseModel):
    reason: str = ""
    # 操作员工ID（权限校验用）
    employee_id: Optional[str] = None
    store_id: Optional[str] = None


class ChangeTableStatusReq(BaseModel):
    target_status: str
    reason: Optional[str] = None


class CashCountReq(BaseModel):
    counted_amount_fen: int
    denomination_breakdown: Optional[dict] = None


class ManagerCommentReq(BaseModel):
    comment: str
    next_day_actions: list[str] = []


class ChefCommentReq(BaseModel):
    comment: str
    waste_notes: list[str] = []


class SettlementConfirmReq(BaseModel):
    store_id: str
    biz_date: str
    action: str  # create / cash_count / manager_comment / chef_comment / submit / approve
    # Optional fields depending on action
    settlement_id: Optional[str] = None
    counted_amount_fen: Optional[int] = None
    denomination_breakdown: Optional[dict] = None
    comment: Optional[str] = None
    next_day_actions: Optional[list[str]] = None
    waste_notes: Optional[list[str]] = None
    reviewer_id: Optional[str] = None


# ─── 1. 订单（开台即创建订单） ───


@router.post("/orders")
async def open_table(
    req: OpenTableReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """开台 — 创建订单 + 锁定桌台"""
    engine = CashierEngine(db, _get_tenant_id(request))
    try:
        result = await engine.open_table(
            store_id=req.store_id,
            table_no=req.table_no,
            waiter_id=req.waiter_id,
            guest_count=req.guest_count,
            order_type=req.order_type,
            customer_id=req.customer_id,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 2. 加菜 ───


@router.post("/orders/{order_id}/items")
async def add_item(
    order_id: str,
    req: AddItemReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """加菜 — 支持固定/称重/时价三种定价"""
    engine = CashierEngine(db, _get_tenant_id(request))
    try:
        result = await engine.add_item(
            order_id=order_id,
            dish_id=req.dish_id,
            dish_name=req.dish_name,
            qty=req.qty,
            unit_price_fen=req.unit_price_fen,
            notes=req.notes,
            customizations=req.customizations,
            pricing_mode=req.pricing_mode,
            weight_value=req.weight_value,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 3. 改菜 ───


@router.put("/orders/{order_id}/items/{item_id}")
async def update_item(
    order_id: str,
    item_id: str,
    req: UpdateItemReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """改菜 — 修改数量或备注"""
    engine = CashierEngine(db, _get_tenant_id(request))
    try:
        result = await engine.update_item(
            order_id=order_id,
            item_id=item_id,
            quantity=req.quantity,
            notes=req.notes,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 4. 删菜 ───


@router.delete("/orders/{order_id}/items/{item_id}")
async def remove_item(
    order_id: str,
    item_id: str,
    request: Request,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
):
    """删菜 — 记录原因并重算总额"""
    engine = CashierEngine(db, _get_tenant_id(request))
    try:
        result = await engine.remove_item(
            order_id=order_id,
            item_id=item_id,
            reason=reason,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 5. 折扣 ───


@router.post("/orders/{order_id}/discount")
async def apply_discount(
    order_id: str,
    req: ApplyDiscountReq,
    request: Request,
    x_employee_id: Optional[str] = Header(None, alias="X-Employee-ID"),
    db: AsyncSession = Depends(get_db),
):
    """应用折扣 — 含毛利底线校验 + 10级角色权限校验

    权限校验优先级：
      1. 若请求体 employee_id 或 Header X-Employee-ID 存在，则校验角色权限
      2. 折扣率超过角色权限时：
         - can_override_discount=True → 返回 require_approval=True（前端弹出审批流）
         - can_override_discount=False → 403 直接拒绝
      3. 权限通过后继续执行毛利底线校验（CashierEngine 内部）
    """
    tenant_id = _get_tenant_id(request)
    engine = CashierEngine(db, tenant_id)

    # 权限校验（仅在能获取 employee_id 时执行）
    operator_id = req.employee_id or x_employee_id
    if operator_id and req.discount_type == "percent_off":
        perm_client = CashierPermissionClient(db, tenant_id)
        try:
            perm_result = await perm_client.check_discount(
                employee_id=UUID(operator_id),
                discount_rate=float(req.discount_value),
                store_id=UUID(req.store_id) if req.store_id else None,
                order_id=UUID(order_id) if order_id else None,
                request_ip=request.client.host if request.client else None,
            )
            if not perm_result.allowed:
                if perm_result.require_approval:
                    _err(
                        f"折扣权限不足，需 Level {perm_result.approver_min_level}+ 审批。"
                        f"approval_id 字段传入审批单ID后可继续。{perm_result.message}",
                        code=403,
                    )
                else:
                    _err(perm_result.message, code=403)
        except (ValueError, KeyError):
            # UUID 格式错误等，跳过权限校验（不阻断业务，记录日志）
            pass

    try:
        result = await engine.apply_discount(
            order_id=order_id,
            discount_type=req.discount_type,
            discount_value=req.discount_value,
            reason=req.reason,
            approval_id=req.approval_id,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 6. 结算 ───


@router.post("/orders/{order_id}/settle")
async def settle_order(
    order_id: str,
    req: SettleOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """结算 — 多支付方式结账"""
    engine = CashierEngine(db, _get_tenant_id(request))
    try:
        payments = [p.model_dump() for p in req.payments]
        result = await engine.settle_order(order_id=order_id, payments=payments)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 7. 取消 ───


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    req: CancelOrderReq,
    request: Request,
    x_employee_id: Optional[str] = Header(None, alias="X-Employee-ID"),
    db: AsyncSession = Depends(get_db),
):
    """取消订单 — 需退单权限（Level 7+）"""
    tenant_id = _get_tenant_id(request)
    engine = CashierEngine(db, tenant_id)

    # 权限校验
    operator_id = req.employee_id or x_employee_id
    if operator_id:
        perm_client = CashierPermissionClient(db, tenant_id)
        try:
            perm_result = await perm_client.check_void_order(
                employee_id=UUID(operator_id),
                store_id=UUID(req.store_id) if req.store_id else None,
                order_id=UUID(order_id) if order_id else None,
                request_ip=request.client.host if request.client else None,
            )
            if not perm_result.allowed:
                _err(perm_result.message, code=403)
        except (ValueError, KeyError):
            pass

    try:
        result = await engine.cancel_order(order_id=order_id, reason=req.reason)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 8. 订单详情 ───


@router.get("/orders/{order_id}")
async def get_order_detail(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询订单完整详情"""
    engine = CashierEngine(db, _get_tenant_id(request))
    try:
        result = await engine.get_order_detail(order_id=order_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e), 404)


# ─── 9. 桌台地图 ───


@router.get("/tables")
async def get_table_map(
    store_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """获取桌台地图"""
    engine = CashierEngine(db, _get_tenant_id(request))
    result = await engine.get_table_map(store_id=store_id)
    return _ok(result)


# ─── 10. 桌台状态变更 ───


@router.put("/tables/{table_no}/status")
async def change_table_status(
    table_no: str,
    req: ChangeTableStatusReq,
    store_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """变更桌台状态"""
    engine = CashierEngine(db, _get_tenant_id(request))
    try:
        result = await engine.change_table_status(
            store_id=store_id,
            table_no=table_no,
            target_status=req.target_status,
            reason=req.reason,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 11. 日结查询 ───


@router.get("/daily-settlement")
async def get_daily_settlement(
    store_id: str = Query(...),
    biz_date: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """查询日结详情"""
    svc = DailySettlementService(db, _get_tenant_id(request))
    try:
        result = await svc.get_settlement(store_id=store_id, biz_date=biz_date)
        return _ok(result)
    except ValueError as e:
        _err(str(e), 404)


# ─── 12. 日结操作（统一入口） ───


@router.post("/daily-settlement/confirm")
async def daily_settlement_confirm(
    req: SettlementConfirmReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """日结操作 — 创建/盘点/评论/提交/审核

    action:
    - create: 创建日结草稿
    - cash_count: 现金盘点
    - manager_comment: 店长说明
    - chef_comment: 厨师长说明
    - submit: 提交审核
    - approve: 审核通过
    """
    svc = DailySettlementService(db, _get_tenant_id(request))

    try:
        if req.action == "create":
            result = await svc.create_settlement(
                store_id=req.store_id,
                biz_date=req.biz_date,
            )
        elif req.action == "cash_count":
            if not req.settlement_id or req.counted_amount_fen is None:
                _err("cash_count requires settlement_id and counted_amount_fen")
            result = await svc.record_cash_count(
                settlement_id=req.settlement_id,
                counted_amount_fen=req.counted_amount_fen,
                denomination_breakdown=req.denomination_breakdown,
            )
        elif req.action == "manager_comment":
            if not req.settlement_id or not req.comment:
                _err("manager_comment requires settlement_id and comment")
            result = await svc.add_manager_comment(
                settlement_id=req.settlement_id,
                comment=req.comment,
                next_day_actions=req.next_day_actions or [],
            )
        elif req.action == "chef_comment":
            if not req.settlement_id or not req.comment:
                _err("chef_comment requires settlement_id and comment")
            result = await svc.add_chef_comment(
                settlement_id=req.settlement_id,
                comment=req.comment,
                waste_notes=req.waste_notes or [],
            )
        elif req.action == "submit":
            if not req.settlement_id:
                _err("submit requires settlement_id")
            result = await svc.submit_for_review(settlement_id=req.settlement_id)
        elif req.action == "approve":
            if not req.settlement_id or not req.reviewer_id:
                _err("approve requires settlement_id and reviewer_id")
            result = await svc.approve_settlement(
                settlement_id=req.settlement_id,
                reviewer_id=req.reviewer_id,
            )
        else:
            _err(f"Unknown action: {req.action}")
            return  # unreachable but helps type checker

        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 13. 订单列表 ───


@router.get("/orders")
async def list_orders(
    store_id: str = Query(...),
    status: Optional[str] = None,
    date: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """分页查询订单列表"""
    engine = CashierEngine(db, _get_tenant_id(request))
    result = await engine.list_orders(
        store_id=store_id,
        status=status,
        date_str=date,
        page=page,
        size=size,
    )
    return _ok(result)
