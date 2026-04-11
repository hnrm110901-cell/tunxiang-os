"""
团餐/企业客户路由 — Y-A9 Mock→DB 改造（v206）

企业客户主数据管理 + 团餐订单创建（授信校验/折扣应用/菜品白名单）+ 批量出账 + 对账导出

全部端点已接入 DB（corporate_customers / corporate_orders / corporate_bills）
"""

import csv
import io
import json
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/corporate", tags=["corporate-orders"])


# ─── DB 依赖 ─────────────────────────────────────────────────────────────────

def _get_tenant_id(request: Request) -> str:
    return request.headers.get("X-Tenant-Id", "default")


async def _get_db(request: Request):
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


def _available_credit(credit_limit_fen: int, used_credit_fen: int) -> int:
    return credit_limit_fen - used_credit_fen


# ─── 请求/响应模型 ────────────────────────────────────────────────────────────

class CreateCustomerReq(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=100, description="企业名称")
    company_code: Optional[str] = Field(None, max_length=30, description="企业编码（全局唯一）")
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    billing_type: str = Field(default="monthly", description="monthly/weekly/immediate")
    credit_limit_fen: int = Field(default=0, ge=0, description="授信额度（分）")
    tax_no: Optional[str] = Field(None, max_length=30, description="开票税号")
    invoice_title: Optional[str] = Field(None, max_length=100, description="发票抬头")
    discount_rate: float = Field(default=1.0, ge=0.0, le=1.0, description="企业折扣率")
    approved_menu_ids: List[str] = Field(default_factory=list, description="菜品ID白名单")


class UpdateCustomerReq(BaseModel):
    company_name: Optional[str] = Field(None, min_length=1, max_length=100)
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    billing_type: Optional[str] = None
    credit_limit_fen: Optional[int] = Field(None, ge=0)
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
    request: Request,
    status: Optional[str] = Query(None, description="状态过滤：active/suspended"),
    keyword: Optional[str] = Query(None, description="公司名关键词搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    conditions = ["is_deleted = FALSE"]
    params: dict = {"limit": size, "offset": (page - 1) * size}
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if keyword:
        conditions.append("company_name ILIKE :keyword")
        params["keyword"] = f"%{keyword}%"

    where = " AND ".join(conditions)

    count_row = await db.execute(text(f"SELECT COUNT(*) FROM corporate_customers WHERE {where}"), params)
    total = count_row.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT *, credit_limit_fen - used_credit_fen AS available_credit_fen
            FROM corporate_customers
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return _ok({"items": items, "total": total, "page": page, "size": size})


# ─── 2. 新增企业客户 ──────────────────────────────────────────────────────────

@router.post("/customers", summary="新增企业客户", status_code=201)
async def create_customer(
    request: Request, req: CreateCustomerReq,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)

    # 编码唯一性校验
    if req.company_code:
        dup = await db.execute(
            text("SELECT id FROM corporate_customers WHERE company_code = :code AND is_deleted = FALSE"),
            {"code": req.company_code},
        )
        if dup.fetchone():
            raise HTTPException(status_code=409, detail=f"企业编码 '{req.company_code}' 已存在")

    row = await db.execute(
        text("""
            INSERT INTO corporate_customers
                (tenant_id, store_id, company_name, company_code, contact_name, contact_phone,
                 billing_type, credit_limit_fen, tax_no, invoice_title, discount_rate, approved_menu_ids)
            VALUES
                (:tenant_id, :tenant_id, :name, :code, :contact, :phone,
                 :billing, :credit, :tax, :invoice, :discount, :menu_ids::jsonb)
            RETURNING *, credit_limit_fen - used_credit_fen AS available_credit_fen
        """),
        {
            "tenant_id": tenant_id, "name": req.company_name, "code": req.company_code,
            "contact": req.contact_name, "phone": req.contact_phone,
            "billing": req.billing_type, "credit": req.credit_limit_fen,
            "tax": req.tax_no, "invoice": req.invoice_title,
            "discount": req.discount_rate, "menu_ids": json.dumps(req.approved_menu_ids),
        },
    )
    await db.commit()
    customer = dict(row.fetchone()._mapping)
    logger.info("corporate_customer.created", customer_id=str(customer["id"]))
    return _ok(customer)


# ─── 3. 更新企业客户 ──────────────────────────────────────────────────────────

@router.put("/customers/{customer_id}", summary="更新企业客户")
async def update_customer(
    customer_id: str, req: UpdateCustomerReq,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")

    # 构建SET子句（安全参数化）
    set_parts = []
    params: dict = {"cid": customer_id}
    for k, v in updates.items():
        if k == "approved_menu_ids":
            set_parts.append(f"approved_menu_ids = :val_{k}::jsonb")
            params[f"val_{k}"] = json.dumps(v)
        else:
            set_parts.append(f"{k} = :val_{k}")
            params[f"val_{k}"] = v
    set_parts.append("updated_at = NOW()")

    row = await db.execute(
        text(f"""
            UPDATE corporate_customers
            SET {', '.join(set_parts)}
            WHERE id = :cid AND is_deleted = FALSE
            RETURNING *, credit_limit_fen - used_credit_fen AS available_credit_fen
        """),
        params,
    )
    await db.commit()
    updated = row.fetchone()
    if not updated:
        raise HTTPException(status_code=404, detail=f"企业客户 '{customer_id}' 不存在")
    return _ok(dict(updated._mapping))


# ─── 4. 授信额度查询 ──────────────────────────────────────────────────────────

@router.get("/customers/{customer_id}/credit", summary="授信额度查询")
async def get_credit(customer_id: str, db: AsyncSession = Depends(_get_db)) -> dict:
    row = await db.execute(
        text("""
            SELECT id, company_name, credit_limit_fen, used_credit_fen, billing_type,
                   credit_limit_fen - used_credit_fen AS available_credit_fen,
                   CASE WHEN credit_limit_fen > 0
                        THEN ROUND(used_credit_fen::numeric / credit_limit_fen * 100, 2)
                        ELSE 0 END AS usage_percent
            FROM corporate_customers
            WHERE id = :cid AND is_deleted = FALSE
        """),
        {"cid": customer_id},
    )
    customer = row.fetchone()
    if not customer:
        raise HTTPException(status_code=404, detail=f"企业客户 '{customer_id}' 不存在")
    return _ok(dict(customer._mapping))


# ─── 5. 创建企业订单 ──────────────────────────────────────────────────────────

@router.post("/orders", summary="创建企业订单", status_code=201)
async def create_corporate_order(
    request: Request, req: CreateCorporateOrderReq,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)

    # 查询客户
    cust_row = await db.execute(
        text("""
            SELECT id, company_name, status, credit_limit_fen, used_credit_fen,
                   discount_rate, approved_menu_ids
            FROM corporate_customers
            WHERE id = :cid AND is_deleted = FALSE
        """),
        {"cid": req.corporate_customer_id},
    )
    customer = cust_row.fetchone()
    if not customer:
        raise HTTPException(status_code=404, detail=f"企业客户 '{req.corporate_customer_id}' 不存在")
    if customer.status != "active":
        raise HTTPException(status_code=400, detail=f"企业客户状态为 '{customer.status}'，无法下单")

    # 菜品白名单校验
    approved_ids = customer.approved_menu_ids or []
    if approved_ids:
        for item in req.items:
            if item.dish_id not in approved_ids:
                raise HTTPException(status_code=400, detail=f"菜品 '{item.dish_id}' 不在白名单中")

    # 计算金额
    original_fen = sum(item.qty * item.unit_price_fen for item in req.items)
    discount_rate = Decimal(str(customer.discount_rate))
    final_fen = int((Decimal(str(original_fen)) * discount_rate).to_integral_value(rounding=ROUND_HALF_UP))

    # 授信校验
    available = customer.credit_limit_fen - customer.used_credit_fen
    if final_fen > available:
        raise HTTPException(
            status_code=400,
            detail=f"授信额度不足：可用 {available} 分，本单需 {final_fen} 分",
        )

    # 创建订单 + 更新授信（事务内）
    order_no = f"CO-{uuid.uuid4().hex[:12].upper()}"
    order_row = await db.execute(
        text("""
            INSERT INTO corporate_orders
                (tenant_id, store_id, corporate_customer_id, order_no, items,
                 original_amount_fen, discount_rate, final_amount_fen)
            VALUES
                (:tid, :sid, :cid, :no, :items::jsonb,
                 :original, :discount, :final)
            RETURNING id, order_no, final_amount_fen, ordered_at
        """),
        {
            "tid": tenant_id, "sid": req.store_id, "cid": req.corporate_customer_id,
            "no": order_no, "items": json.dumps([i.model_dump() for i in req.items]),
            "original": original_fen, "discount": float(discount_rate), "final": final_fen,
        },
    )

    # 更新已用授信
    await db.execute(
        text("""
            UPDATE corporate_customers
            SET used_credit_fen = used_credit_fen + :amount, updated_at = NOW()
            WHERE id = :cid
        """),
        {"cid": req.corporate_customer_id, "amount": final_fen},
    )
    await db.commit()

    order = order_row.fetchone()
    logger.info("corporate_order.created", order_no=order_no, final_fen=final_fen)
    return _ok({
        "order_id": str(order.id), "order_no": order.order_no,
        "company_name": customer.company_name,
        "original_amount_fen": original_fen,
        "discount_rate": float(discount_rate),
        "final_amount_fen": final_fen,
        "ordered_at": str(order.ordered_at),
    })


# ─── 6. 企业订单列表 ──────────────────────────────────────────────────────────

@router.get("/orders", summary="企业订单列表")
async def list_corporate_orders(
    corporate_customer_id: Optional[str] = Query(None),
    order_date: Optional[date] = Query(None),
    billing_status: Optional[str] = Query(None, description="unbilled/billed"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    conditions = ["1=1"]
    params: dict = {"limit": size, "offset": (page - 1) * size}
    if corporate_customer_id:
        conditions.append("o.corporate_customer_id = :cid")
        params["cid"] = corporate_customer_id
    if order_date:
        conditions.append("o.ordered_at::date = :odate")
        params["odate"] = order_date
    if billing_status == "billed":
        conditions.append("o.billed = TRUE")
    elif billing_status == "unbilled":
        conditions.append("o.billed = FALSE")

    where = " AND ".join(conditions)
    count_row = await db.execute(text(f"SELECT COUNT(*) FROM corporate_orders o WHERE {where}"), params)
    total = count_row.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT o.*, c.company_name
            FROM corporate_orders o
            JOIN corporate_customers c ON c.id = o.corporate_customer_id
            WHERE {where}
            ORDER BY o.ordered_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return _ok({"items": items, "total": total, "page": page, "size": size})


# ─── 7. 批量账单生成 ──────────────────────────────────────────────────────────

@router.post("/orders/bulk-bill", summary="批量账单生成")
async def bulk_bill(
    request: Request, req: BulkBillReq,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)

    # 查客户
    cust_row = await db.execute(
        text("SELECT id, company_name FROM corporate_customers WHERE id = :cid AND is_deleted = FALSE"),
        {"cid": req.corporate_customer_id},
    )
    customer = cust_row.fetchone()
    if not customer:
        raise HTTPException(status_code=404, detail=f"企业客户 '{req.corporate_customer_id}' 不存在")

    # 汇总未出账订单
    agg = await db.execute(
        text("""
            SELECT COUNT(*) AS cnt, COALESCE(SUM(final_amount_fen), 0) AS total
            FROM corporate_orders
            WHERE corporate_customer_id = :cid
              AND billed = FALSE
              AND ordered_at::date BETWEEN :start AND :end
        """),
        {"cid": req.corporate_customer_id, "start": req.billing_period_start, "end": req.billing_period_end},
    )
    summary = agg.fetchone()
    if not summary or summary.cnt == 0:
        raise HTTPException(status_code=400, detail="该周期内无可出账订单")

    # 创建账单
    bill_no = f"BILL-{uuid.uuid4().hex[:10].upper()}"
    bill_row = await db.execute(
        text("""
            INSERT INTO corporate_bills
                (tenant_id, store_id, corporate_customer_id, bill_no,
                 period_start, period_end, order_count, total_amount_fen)
            VALUES
                (:tid, :tid, :cid, :bno, :start, :end, :cnt, :total)
            RETURNING id
        """),
        {
            "tid": tenant_id, "cid": req.corporate_customer_id, "bno": bill_no,
            "start": req.billing_period_start, "end": req.billing_period_end,
            "cnt": summary.cnt, "total": summary.total,
        },
    )
    bill_id = bill_row.scalar()

    # 标记订单已出账
    await db.execute(
        text("""
            UPDATE corporate_orders
            SET billed = TRUE, bill_id = :bill_id
            WHERE corporate_customer_id = :cid
              AND billed = FALSE
              AND ordered_at::date BETWEEN :start AND :end
        """),
        {"bill_id": bill_id, "cid": req.corporate_customer_id,
         "start": req.billing_period_start, "end": req.billing_period_end},
    )
    await db.commit()

    logger.info("corporate.bulk_bill.created", bill_no=bill_no, orders=summary.cnt, total_fen=summary.total)
    return _ok({
        "bill_id": str(bill_id), "bill_no": bill_no,
        "company_name": customer.company_name,
        "period_start": str(req.billing_period_start),
        "period_end": str(req.billing_period_end),
        "order_count": summary.cnt,
        "total_amount_fen": summary.total,
        "total_amount_yuan": round(summary.total / 100, 2),
    })


# ─── 8. 对账导出 CSV ──────────────────────────────────────────────────────────

@router.get("/export", summary="对账导出（CSV）")
async def export_reconciliation(
    corporate_customer_id: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    fmt: str = Query("csv", alias="format"),
    db: AsyncSession = Depends(_get_db),
) -> PlainTextResponse:
    rows = await db.execute(
        text("""
            SELECT o.order_no, c.company_name, o.store_id,
                   o.original_amount_fen, o.discount_rate, o.final_amount_fen,
                   CASE WHEN o.billed THEN 'billed' ELSE 'unbilled' END AS billing_status,
                   o.ordered_at
            FROM corporate_orders o
            JOIN corporate_customers c ON c.id = o.corporate_customer_id
            WHERE o.corporate_customer_id = :cid
              AND o.ordered_at::date BETWEEN :start AND :end
            ORDER BY o.ordered_at
        """),
        {"cid": corporate_customer_id, "start": date_from, "end": date_to},
    )
    orders = rows.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["订单号", "企业名称", "门店ID", "原始金额(分)", "折扣率", "实际金额(分)", "账单状态", "下单时间"])
    for o in orders:
        writer.writerow([
            o.order_no, o.company_name, o.store_id,
            o.original_amount_fen, o.discount_rate, o.final_amount_fen,
            o.billing_status, str(o.ordered_at),
        ])

    filename = f"corporate_bill_{corporate_customer_id}_{date_from}_{date_to}.csv"
    return PlainTextResponse(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
