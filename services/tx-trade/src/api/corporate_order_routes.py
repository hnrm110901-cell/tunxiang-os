"""
团餐/企业客户路由
Y-A9

企业客户主数据管理 + 团餐订单创建（授信校验/折扣应用/菜品白名单）+ 批量出账 + 对账导出
"""
import csv
import io
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/corporate", tags=["corporate-orders"])

# ─── Mock 数据 ────────────────────────────────────────────────────────────────

MOCK_CORPORATE_CUSTOMERS: list[dict] = [
    {
        "id": "corp-001",
        "company_name": "湘雅医院",
        "company_code": "XY001",
        "contact_name": "张主任",
        "contact_phone": "0731-88888001",
        "billing_type": "monthly",
        "credit_limit_fen": 5_000_000,
        "used_credit_fen": 1_280_000,
        "tax_no": "91430100XXXXXXXX01",
        "invoice_title": "中南大学湘雅医院",
        "discount_rate": 0.95,
        "approved_menu_ids": [],
        "status": "active",
        "is_deleted": False,
        "created_at": "2026-01-01T08:00:00+08:00",
        "updated_at": "2026-04-01T10:00:00+08:00",
    },
    {
        "id": "corp-002",
        "company_name": "湖南大学",
        "company_code": "HNU002",
        "contact_name": "李老师",
        "contact_phone": "0731-88822002",
        "billing_type": "weekly",
        "credit_limit_fen": 2_000_000,
        "used_credit_fen": 680_000,
        "tax_no": "91430100XXXXXXXX02",
        "invoice_title": "湖南大学",
        "discount_rate": 0.92,
        "approved_menu_ids": [],
        "status": "active",
        "is_deleted": False,
        "created_at": "2026-02-01T08:00:00+08:00",
        "updated_at": "2026-04-02T09:30:00+08:00",
    },
]

# 模拟企业订单存储（内存 mock，生产替换 DB）
_MOCK_ORDERS: list[dict] = []
# 模拟账单存储
_MOCK_BILLS: list[dict] = []


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _find_customer(customer_id: str) -> dict | None:
    for c in MOCK_CORPORATE_CUSTOMERS:
        if c["id"] == customer_id and not c["is_deleted"]:
            return c
    return None


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _available_credit(customer: dict) -> int:
    """可用授信 = 授信额度 - 已用授信"""
    return customer["credit_limit_fen"] - customer["used_credit_fen"]


# ─── 请求/响应模型 ────────────────────────────────────────────────────────────

class CreateCustomerReq(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=100, description="企业名称")
    company_code: Optional[str] = Field(None, max_length=30, description="企业编码（全局唯一）")
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    billing_type: str = Field(default="monthly",
                              description="monthly/weekly/immediate：月结/周结/即结")
    credit_limit_fen: int = Field(default=0, ge=0, description="授信额度（分）")
    tax_no: Optional[str] = Field(None, max_length=30, description="开票税号")
    invoice_title: Optional[str] = Field(None, max_length=100, description="发票抬头")
    discount_rate: float = Field(default=1.0, ge=0.0, le=1.0,
                                 description="企业折扣率，如0.900=九折")
    approved_menu_ids: List[str] = Field(default_factory=list,
                                         description="菜品ID白名单，空=全部允许")


class UpdateCustomerReq(BaseModel):
    company_name: Optional[str] = Field(None, min_length=1, max_length=100)
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    billing_type: Optional[str] = None
    credit_limit_fen: Optional[int] = Field(None, ge=0, description="新授信额度（分）")
    tax_no: Optional[str] = Field(None, max_length=30)
    invoice_title: Optional[str] = Field(None, max_length=100)
    discount_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    approved_menu_ids: Optional[List[str]] = None
    status: Optional[str] = None


class OrderItemReq(BaseModel):
    dish_id: str
    dish_name: str = ""
    qty: int = Field(..., gt=0)
    unit_price_fen: int = Field(..., ge=0)


class CreateCorporateOrderReq(BaseModel):
    corporate_customer_id: str = Field(..., description="企业客户ID")
    store_id: str = Field(..., description="门店ID")
    items: List[OrderItemReq]
    remark: Optional[str] = Field(None, max_length=200)


class BulkBillReq(BaseModel):
    corporate_customer_id: str
    billing_period_start: date
    billing_period_end: date


# ─── 1. 企业客户列表 ──────────────────────────────────────────────────────────

@router.get("/customers", summary="企业客户列表")
async def list_customers(
    status: Optional[str] = Query(None, description="状态过滤：active/inactive"),
    keyword: Optional[str] = Query(None, description="公司名关键词搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出所有企业客户，支持状态过滤和关键词搜索。"""
    customers = [c for c in MOCK_CORPORATE_CUSTOMERS if not c["is_deleted"]]

    if status:
        customers = [c for c in customers if c["status"] == status]
    if keyword:
        customers = [c for c in customers
                     if keyword.lower() in c["company_name"].lower()]

    total = len(customers)
    start = (page - 1) * size
    items = customers[start: start + size]

    # 附加可用授信
    enriched = []
    for c in items:
        row = dict(c)
        row["available_credit_fen"] = _available_credit(c)
        enriched.append(row)

    return _ok({"items": enriched, "total": total, "page": page, "size": size})


# ─── 2. 新增企业客户 ──────────────────────────────────────────────────────────

@router.post("/customers", summary="新增企业客户", status_code=201)
async def create_customer(req: CreateCustomerReq) -> dict:
    """创建企业客户主数据记录。"""
    # 编码唯一性校验
    if req.company_code:
        existing = [c for c in MOCK_CORPORATE_CUSTOMERS
                    if c.get("company_code") == req.company_code and not c["is_deleted"]]
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"企业编码 '{req.company_code}' 已存在",
            )

    new_id = f"corp-{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    customer: dict = {
        "id": new_id,
        "company_name": req.company_name,
        "company_code": req.company_code,
        "contact_name": req.contact_name,
        "contact_phone": req.contact_phone,
        "billing_type": req.billing_type,
        "credit_limit_fen": req.credit_limit_fen,
        "used_credit_fen": 0,
        "tax_no": req.tax_no,
        "invoice_title": req.invoice_title,
        "discount_rate": req.discount_rate,
        "approved_menu_ids": req.approved_menu_ids,
        "status": "active",
        "is_deleted": False,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    MOCK_CORPORATE_CUSTOMERS.append(customer)
    logger.info("corporate_customer.created", customer_id=new_id,
                company_name=req.company_name)

    result = dict(customer)
    result["available_credit_fen"] = _available_credit(customer)
    return _ok(result)


# ─── 3. 更新企业客户 ──────────────────────────────────────────────────────────

@router.put("/customers/{customer_id}", summary="更新企业客户（含授信额度）")
async def update_customer(customer_id: str, req: UpdateCustomerReq) -> dict:
    """更新企业客户信息，包括授信额度调整。"""
    customer = _find_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"企业客户 '{customer_id}' 不存在")

    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")

    customer.update(updates)
    customer["updated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("corporate_customer.updated", customer_id=customer_id,
                fields=list(updates.keys()))

    result = dict(customer)
    result["available_credit_fen"] = _available_credit(customer)
    return _ok(result)


# ─── 4. 授信额度查询 ──────────────────────────────────────────────────────────

@router.get("/customers/{customer_id}/credit", summary="授信额度查询")
async def get_credit(customer_id: str) -> dict:
    """
    查询企业客户授信使用情况。
    可用授信 = credit_limit - used_credit
    """
    customer = _find_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"企业客户 '{customer_id}' 不存在")

    available = _available_credit(customer)
    usage_pct = (
        round(customer["used_credit_fen"] / customer["credit_limit_fen"] * 100, 2)
        if customer["credit_limit_fen"] > 0 else 0.0
    )
    return _ok({
        "customer_id": customer_id,
        "company_name": customer["company_name"],
        "credit_limit_fen": customer["credit_limit_fen"],
        "used_credit_fen": customer["used_credit_fen"],
        "available_credit_fen": available,
        "usage_percent": usage_pct,
        "billing_type": customer["billing_type"],
    })


# ─── 5. 创建企业订单 ──────────────────────────────────────────────────────────

@router.post("/orders", summary="创建企业订单", status_code=201)
async def create_corporate_order(req: CreateCorporateOrderReq) -> dict:
    """
    创建企业团餐订单：
    1. 验证企业客户有效性（status=active）
    2. 验证菜品白名单（approved_menu_ids 非空时校验）
    3. 计算折扣后金额
    4. 检查授信额度（used + amount ≤ limit）
    5. 写入订单，更新 used_credit_fen
    """
    customer = _find_customer(req.corporate_customer_id)
    if customer is None:
        raise HTTPException(status_code=404,
                            detail=f"企业客户 '{req.corporate_customer_id}' 不存在")
    if customer["status"] != "active":
        raise HTTPException(status_code=400,
                            detail=f"企业客户状态为 '{customer['status']}'，无法下单")

    # ── 菜品白名单校验 ──
    approved_ids: list = customer.get("approved_menu_ids") or []
    if approved_ids:
        for item in req.items:
            if item.dish_id not in approved_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"菜品 '{item.dish_id}' 不在企业允许点单的菜品白名单中",
                )

    # ── 原始金额 ──
    original_amount_fen = sum(item.qty * item.unit_price_fen for item in req.items)

    # ── 应用折扣率 ──
    discount_rate = Decimal(str(customer["discount_rate"]))
    discounted_amount_fen = int(
        (Decimal(str(original_amount_fen)) * discount_rate).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )

    # ── 授信额度校验 ──
    used = customer["used_credit_fen"]
    limit = customer["credit_limit_fen"]
    if used + discounted_amount_fen > limit:
        available = limit - used
        raise HTTPException(
            status_code=400,
            detail=(
                f"授信额度不足：可用 {available} 分，本单需 {discounted_amount_fen} 分。"
                f"请先结算欠款或调高授信额度。"
            ),
        )

    # ── 创建订单 ──
    order_id = f"CO-{uuid.uuid4().hex[:12].upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()
    order: dict = {
        "id": order_id,
        "corporate_customer_id": req.corporate_customer_id,
        "company_name": customer["company_name"],
        "store_id": req.store_id,
        "items": [i.model_dump() for i in req.items],
        "original_amount_fen": original_amount_fen,
        "discount_rate": float(discount_rate),
        "discounted_amount_fen": discounted_amount_fen,
        "billing_status": "unbilled",
        "remark": req.remark,
        "created_at": now_iso,
    }
    _MOCK_ORDERS.append(order)

    # 更新已用授信
    customer["used_credit_fen"] += discounted_amount_fen
    customer["updated_at"] = now_iso

    logger.info("corporate_order.created",
                order_id=order_id,
                customer_id=req.corporate_customer_id,
                original_fen=original_amount_fen,
                discounted_fen=discounted_amount_fen)

    return _ok({
        "order_id": order_id,
        "company_name": customer["company_name"],
        "original_amount_fen": original_amount_fen,
        "discount_rate": float(discount_rate),
        "discounted_amount_fen": discounted_amount_fen,
        "billing_status": "unbilled",
        "created_at": now_iso,
    })


# ─── 6. 企业订单列表 ──────────────────────────────────────────────────────────

@router.get("/orders", summary="企业订单列表")
async def list_corporate_orders(
    corporate_customer_id: Optional[str] = Query(None, description="按企业客户ID过滤"),
    order_date: Optional[date] = Query(None, description="按日期过滤 YYYY-MM-DD"),
    billing_status: Optional[str] = Query(None, description="账单状态：unbilled/billed"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出企业团餐订单，支持多维过滤。"""
    orders = list(_MOCK_ORDERS)

    if corporate_customer_id:
        orders = [o for o in orders
                  if o["corporate_customer_id"] == corporate_customer_id]
    if billing_status:
        orders = [o for o in orders if o["billing_status"] == billing_status]
    if order_date:
        date_str = order_date.isoformat()
        orders = [o for o in orders if o["created_at"].startswith(date_str)]

    total = len(orders)
    start = (page - 1) * size
    items = orders[start: start + size]

    return _ok({"items": items, "total": total, "page": page, "size": size})


# ─── 7. 批量账单生成 ──────────────────────────────────────────────────────────

@router.post("/orders/bulk-bill", summary="批量账单生成")
async def bulk_bill(req: BulkBillReq) -> dict:
    """
    将指定周期内所有 unbilled 订单汇总，生成账单（mock PDF 文本），标记为 billed。

    Body: {corporate_customer_id, billing_period_start, billing_period_end}
    """
    customer = _find_customer(req.corporate_customer_id)
    if customer is None:
        raise HTTPException(status_code=404,
                            detail=f"企业客户 '{req.corporate_customer_id}' 不存在")

    start_str = req.billing_period_start.isoformat()
    end_str = req.billing_period_end.isoformat()

    # 找出该周期内 unbilled 订单
    target_orders = [
        o for o in _MOCK_ORDERS
        if o["corporate_customer_id"] == req.corporate_customer_id
        and o["billing_status"] == "unbilled"
        and start_str <= o["created_at"][:10] <= end_str
    ]

    if not target_orders:
        raise HTTPException(
            status_code=400,
            detail=f"在 {start_str} ~ {end_str} 期间未找到可出账的未结算订单",
        )

    total_fen = sum(o["discounted_amount_fen"] for o in target_orders)
    order_count = len(target_orders)

    # 标记已出账
    billed_order_ids = []
    for o in target_orders:
        o["billing_status"] = "billed"
        billed_order_ids.append(o["id"])

    # 生成账单
    bill_id = f"BILL-{uuid.uuid4().hex[:10].upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()
    bill: dict = {
        "bill_id": bill_id,
        "corporate_customer_id": req.corporate_customer_id,
        "company_name": customer["company_name"],
        "billing_period_start": start_str,
        "billing_period_end": end_str,
        "order_count": order_count,
        "total_fen": total_fen,
        "billed_order_ids": billed_order_ids,
        "billing_type": customer["billing_type"],
        "discount_rate": customer["discount_rate"],
        "pdf_mock_text": (
            f"【屯象OS 企业账单】\n"
            f"企业：{customer['company_name']}\n"
            f"账期：{start_str} ~ {end_str}\n"
            f"订单数：{order_count}\n"
            f"合计金额：¥{total_fen / 100:.2f}\n"
            f"账单号：{bill_id}\n"
            f"出账时间：{now_iso}\n"
        ),
        "status": "issued",
        "created_at": now_iso,
    }
    _MOCK_BILLS.append(bill)

    logger.info("corporate.bulk_bill.created",
                bill_id=bill_id,
                customer_id=req.corporate_customer_id,
                order_count=order_count,
                total_fen=total_fen)

    return _ok({
        "bill_id": bill_id,
        "company_name": customer["company_name"],
        "billing_period_start": start_str,
        "billing_period_end": end_str,
        "order_count": order_count,
        "total_fen": total_fen,
        "status": "issued",
        "created_at": now_iso,
    })


# ─── 8. 对账导出 CSV ──────────────────────────────────────────────────────────

@router.get("/export", summary="对账导出（CSV）")
async def export_reconciliation(
    corporate_customer_id: str = Query(..., description="企业客户ID"),
    date_from: date = Query(..., description="起始日期 YYYY-MM-DD"),
    date_to: date = Query(..., description="截止日期 YYYY-MM-DD"),
    fmt: str = Query("csv", alias="format", description="导出格式（目前仅支持 csv）"),
) -> PlainTextResponse:
    """
    对账导出：返回指定时间段内企业订单的 CSV 格式账单明细。

    参数：corporate_customer_id, date_from, date_to, format=csv
    """
    customer = _find_customer(corporate_customer_id)
    if customer is None:
        raise HTTPException(status_code=404,
                            detail=f"企业客户 '{corporate_customer_id}' 不存在")

    start_str = date_from.isoformat()
    end_str = date_to.isoformat()

    orders = [
        o for o in _MOCK_ORDERS
        if o["corporate_customer_id"] == corporate_customer_id
        and start_str <= o["created_at"][:10] <= end_str
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "订单号", "企业名称", "门店ID",
        "原始金额(分)", "折扣率", "实际金额(分)",
        "账单状态", "下单时间",
    ])

    for o in orders:
        writer.writerow([
            o["id"],
            o["company_name"],
            o["store_id"],
            o["original_amount_fen"],
            o["discount_rate"],
            o["discounted_amount_fen"],
            o["billing_status"],
            o["created_at"],
        ])

    csv_content = output.getvalue()
    filename = f"corporate_bill_{corporate_customer_id}_{start_str}_{end_str}.csv"

    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
