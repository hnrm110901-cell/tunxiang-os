"""加盟收费闭环 API — 天财商龙对齐版

功能覆盖：
  B1. 加盟费账单管理
      POST   /api/v1/franchise/fee-bills              — 生成账单
      GET    /api/v1/franchise/fee-bills              — 账单列表
      GET    /api/v1/franchise/fee-bills/overdue      — 逾期账单
      GET    /api/v1/franchise/fee-bills/{bill_id}    — 账单详情
      POST   /api/v1/franchise/fee-bills/{bill_id}/record-payment  — 记录收款（支持部分付款）
      POST   /api/v1/franchise/fee-bills/{bill_id}/send-reminder   — 发送催款提醒

  B2. 自动出账规则
      POST   /api/v1/franchise/billing-rules                      — 配置出账规则
      GET    /api/v1/franchise/billing-rules                      — 规则列表
      POST   /api/v1/franchise/billing-rules/{rule_id}/trigger    — 手动触发出账

  B3. 收费汇总报表
      GET    /api/v1/franchise/fee-report/summary                 — 收费汇总
      GET    /api/v1/franchise/fee-report/by-franchise            — 各加盟商收费明细

路由前缀: /api/v1/franchise
账单状态: pending → partial → paid / overdue
支持四类费用: joining_fee / royalty / ad_fee / supply_fee

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/franchise", tags=["franchise-fee"])

# 支持的账单类型
VALID_BILL_TYPES = {"joining_fee", "royalty", "ad_fee", "supply_fee"}
# 账单类型中文映射
BILL_TYPE_LABELS = {
    "joining_fee": "加盟费",
    "royalty": "特许经营费",
    "ad_fee": "广告费",
    "supply_fee": "供应链服务费",
}


# ─── 辅助函数 ──────────────────────────────────────────────────────────────────


def _err(status: int, msg: str):
    raise HTTPException(
        status_code=status,
        detail={"ok": False, "error": {"message": msg}},
    )


async def _set_rls(db: AsyncSession, tenant_id: str) -> uuid.UUID:
    """设置 RLS session 变量并返回 UUID。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    try:
        return uuid.UUID(tenant_id)
    except ValueError:
        _err(400, f"无效的 tenant_id: {tenant_id}")


async def _fetch_bill(db: AsyncSession, bill_id: uuid.UUID, tid: uuid.UUID) -> dict:
    """查询账单，不存在则 404。"""
    res = await db.execute(
        text("""
            SELECT b.id, b.franchise_id, f.name AS franchise_name,
                   b.bill_type, b.amount_fen, b.paid_fen, b.status,
                   b.due_date, b.billing_period, b.created_at, b.updated_at
            FROM franchise_fee_bills b
            LEFT JOIN franchisees f ON f.id = b.franchise_id AND f.tenant_id = b.tenant_id
            WHERE b.id = :bid AND b.tenant_id = :tid AND b.is_deleted IS NOT TRUE
        """),
        {"bid": bill_id, "tid": tid},
    )
    row = res.fetchone()
    if not row:
        _err(404, "账单不存在")
    return {
        "id": str(row[0]),
        "franchise_id": str(row[1]),
        "franchise_name": row[2],
        "bill_type": row[3],
        "bill_type_label": BILL_TYPE_LABELS.get(row[3], row[3]),
        "amount_fen": row[4],
        "paid_fen": row[5] or 0,
        "unpaid_fen": (row[4] or 0) - (row[5] or 0),
        "status": row[6],
        "due_date": row[7].isoformat() if row[7] else None,
        "billing_period": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
        "updated_at": row[10].isoformat() if row[10] else None,
    }


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class CreateFeeBillReq(BaseModel):
    franchise_id: str = Field(..., description="加盟商 ID")
    bill_type: str = Field(..., description="joining_fee|royalty|ad_fee|supply_fee")
    amount_fen: int = Field(..., gt=0, description="账单金额（分）")
    due_date: str = Field(..., description="到期日 YYYY-MM-DD")
    billing_period: Optional[str] = Field(None, description="账期，如 2026-04")
    notes: Optional[str] = Field(None, max_length=500)


class RecordPaymentReq(BaseModel):
    paid_amount_fen: int = Field(..., gt=0, description="本次收款金额（分），支持部分付款")
    payment_method: str = Field("transfer", description="transfer/cash/wechat/alipay")
    payment_date: Optional[str] = Field(None, description="收款日期 YYYY-MM-DD，空则取今日")
    receipt_no: Optional[str] = Field(None, max_length=100, description="收据/流水号")
    notes: Optional[str] = Field(None, max_length=500)


class CreateBillingRuleReq(BaseModel):
    franchise_id: str = Field(..., description="加盟商 ID")
    fee_type: str = Field(..., description="joining_fee|royalty|ad_fee|supply_fee")
    amount_fen: Optional[int] = Field(None, gt=0, description="固定金额（分）")
    rate: Optional[float] = Field(None, gt=0, le=1, description="比率（0-1，与 amount_fen 二选一）")
    billing_cycle: str = Field(..., pattern="^(monthly|quarterly|yearly)$")
    billing_day: int = Field(..., ge=1, le=28, description="每月/每季/每年的第几天出账")
    start_date: str = Field(..., description="规则生效起始日 YYYY-MM-DD")
    notes: Optional[str] = Field(None, max_length=300)


# ══════════════════════════════════════════════════════════════════════════════
# B1. 加盟费账单管理
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/fee-bills", status_code=201)
async def create_fee_bill(
    req: CreateFeeBillReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """生成加盟费账单，支持四类费用。"""
    tid = await _set_rls(db, x_tenant_id)

    if req.bill_type not in VALID_BILL_TYPES:
        _err(400, f"无效的 bill_type，支持: {', '.join(VALID_BILL_TYPES)}")

    try:
        franchise_uuid = uuid.UUID(req.franchise_id)
    except ValueError:
        _err(400, "无效的 franchise_id")

    try:
        due_date = date.fromisoformat(req.due_date)
    except ValueError:
        _err(400, "无效的 due_date 格式，应为 YYYY-MM-DD")

    # 校验加盟商存在
    fran_res = await db.execute(
        text("SELECT id, name FROM franchisees WHERE id = :fid AND tenant_id = :tid AND is_deleted = false"),
        {"fid": franchise_uuid, "tid": tid},
    )
    fran_row = fran_res.fetchone()
    if not fran_row:
        _err(404, "加盟商不存在")

    bill_id = uuid.uuid4()
    # 判断是否已逾期
    today = date.today()
    initial_status = "overdue" if due_date < today else "pending"

    try:
        await db.execute(
            text("""
                INSERT INTO franchise_fee_bills
                  (id, tenant_id, franchise_id, bill_type, amount_fen, paid_fen,
                   status, due_date, billing_period, notes, created_by)
                VALUES (:id, :tid, :fid, :btype, :amount, 0,
                        :status, :due_date, :period, :notes, :operator)
            """),
            {
                "id": bill_id,
                "tid": tid,
                "fid": franchise_uuid,
                "btype": req.bill_type,
                "amount": req.amount_fen,
                "status": initial_status,
                "due_date": due_date,
                "period": req.billing_period,
                "notes": req.notes,
                "operator": x_operator,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("create_fee_bill.db_error", error=str(exc))
        _err(500, "数据库写入失败")

    log.info(
        "franchise_fee_bill.created",
        bill_id=str(bill_id),
        franchise_id=req.franchise_id,
        bill_type=req.bill_type,
        amount_fen=req.amount_fen,
        tenant_id=x_tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "id": str(bill_id),
            "franchise_id": req.franchise_id,
            "franchise_name": fran_row[1],
            "bill_type": req.bill_type,
            "bill_type_label": BILL_TYPE_LABELS[req.bill_type],
            "amount_fen": req.amount_fen,
            "status": initial_status,
            "due_date": req.due_date,
        },
    }


@router.get("/fee-bills")
async def list_fee_bills(
    franchise_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(pending|paid|overdue|partial)$"),
    bill_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """账单列表，支持多条件筛选。"""
    tid = await _set_rls(db, x_tenant_id)

    where = "WHERE b.tenant_id = :tid AND b.is_deleted IS NOT TRUE"
    params: dict = {"tid": tid}

    if franchise_id:
        try:
            params["franchise_id"] = uuid.UUID(franchise_id)
        except ValueError:
            _err(400, "无效的 franchise_id")
        where += " AND b.franchise_id = :franchise_id"

    if status:
        where += " AND b.status = :status"
        params["status"] = status

    if bill_type:
        if bill_type not in VALID_BILL_TYPES:
            _err(400, f"无效的 bill_type，支持: {', '.join(VALID_BILL_TYPES)}")
        where += " AND b.bill_type = :bill_type"
        params["bill_type"] = bill_type

    if date_from:
        try:
            params["date_from"] = date.fromisoformat(date_from)
        except ValueError:
            _err(400, "无效的 date_from")
        where += " AND b.due_date >= :date_from"

    if date_to:
        try:
            params["date_to"] = date.fromisoformat(date_to)
        except ValueError:
            _err(400, "无效的 date_to")
        where += " AND b.due_date <= :date_to"

    count_res = await db.execute(
        text(f"SELECT COUNT(*) FROM franchise_fee_bills b {where}"), params
    )
    total = count_res.scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    rows = await db.execute(
        text(f"""
            SELECT b.id, b.franchise_id, f.name AS franchise_name,
                   b.bill_type, b.amount_fen, b.paid_fen, b.status,
                   b.due_date, b.billing_period, b.created_at,
                   CASE WHEN b.status = 'overdue' THEN CURRENT_DATE - b.due_date ELSE 0 END AS overdue_days
            FROM franchise_fee_bills b
            LEFT JOIN franchisees f ON f.id = b.franchise_id AND f.tenant_id = b.tenant_id
            {where}
            ORDER BY b.due_date ASC, b.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [
        {
            "id": str(r[0]),
            "franchise_id": str(r[1]),
            "franchise_name": r[2],
            "bill_type": r[3],
            "bill_type_label": BILL_TYPE_LABELS.get(r[3], r[3]),
            "amount_fen": r[4],
            "paid_fen": r[5] or 0,
            "unpaid_fen": (r[4] or 0) - (r[5] or 0),
            "status": r[6],
            "due_date": r[7].isoformat() if r[7] else None,
            "billing_period": r[8],
            "created_at": r[9].isoformat() if r[9] else None,
            "overdue_days": r[10] or 0,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/fee-bills/overdue")
async def list_overdue_bills(
    franchise_id: Optional[str] = Query(None),
    bill_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """逾期账单列表，含逾期天数和逾期金额。同时将到期未付账单自动标记为 overdue。"""
    tid = await _set_rls(db, x_tenant_id)

    # 自动将到期未付账单标记为逾期
    try:
        await db.execute(
            text("""
                UPDATE franchise_fee_bills
                SET status = 'overdue', updated_at = now()
                WHERE tenant_id = :tid
                  AND status = 'pending'
                  AND due_date < CURRENT_DATE
                  AND is_deleted IS NOT TRUE
            """),
            {"tid": tid},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        log.warning("overdue_bills.auto_mark_failed", error=str(exc))

    where = "WHERE b.tenant_id = :tid AND b.status = 'overdue' AND b.is_deleted IS NOT TRUE"
    params: dict = {"tid": tid}

    if franchise_id:
        try:
            params["franchise_id"] = uuid.UUID(franchise_id)
        except ValueError:
            _err(400, "无效的 franchise_id")
        where += " AND b.franchise_id = :franchise_id"

    if bill_type:
        if bill_type not in VALID_BILL_TYPES:
            _err(400, f"无效的 bill_type")
        where += " AND b.bill_type = :bill_type"
        params["bill_type"] = bill_type

    count_res = await db.execute(
        text(f"SELECT COUNT(*) FROM franchise_fee_bills b {where}"), params
    )
    total = count_res.scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    rows = await db.execute(
        text(f"""
            SELECT b.id, b.franchise_id, f.name AS franchise_name,
                   b.bill_type, b.amount_fen, b.paid_fen, b.due_date, b.billing_period,
                   CURRENT_DATE - b.due_date AS overdue_days,
                   b.amount_fen - COALESCE(b.paid_fen, 0) AS overdue_amount_fen
            FROM franchise_fee_bills b
            LEFT JOIN franchisees f ON f.id = b.franchise_id AND f.tenant_id = b.tenant_id
            {where}
            ORDER BY overdue_days DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [
        {
            "id": str(r[0]),
            "franchise_id": str(r[1]),
            "franchise_name": r[2],
            "bill_type": r[3],
            "bill_type_label": BILL_TYPE_LABELS.get(r[3], r[3]),
            "amount_fen": r[4],
            "paid_fen": r[5] or 0,
            "due_date": r[6].isoformat() if r[6] else None,
            "billing_period": r[7],
            "overdue_days": r[8] or 0,
            "overdue_amount_fen": r[9] or 0,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/fee-bills/{bill_id}")
async def get_fee_bill_detail(
    bill_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """账单详情，含收款记录列表。"""
    tid = await _set_rls(db, x_tenant_id)
    try:
        bid = uuid.UUID(bill_id)
    except ValueError:
        _err(400, "无效的 bill_id")

    bill = await _fetch_bill(db, bid, tid)

    # 查询收款记录
    payments_res = await db.execute(
        text("""
            SELECT id, paid_amount_fen, payment_method, payment_date, receipt_no, notes, created_at
            FROM franchise_fee_payments
            WHERE bill_id = :bid AND tenant_id = :tid
            ORDER BY created_at DESC
        """),
        {"bid": bid, "tid": tid},
    )
    payments = [
        {
            "id": str(r[0]),
            "paid_amount_fen": r[1],
            "payment_method": r[2],
            "payment_date": r[3].isoformat() if r[3] else None,
            "receipt_no": r[4],
            "notes": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in payments_res.fetchall()
    ]

    bill["payments"] = payments
    return {"ok": True, "data": bill}


@router.post("/fee-bills/{bill_id}/record-payment")
async def record_payment(
    req: RecordPaymentReq,
    bill_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """记录收款，支持部分付款（partial payment）。自动更新账单状态。"""
    tid = await _set_rls(db, x_tenant_id)
    try:
        bid = uuid.UUID(bill_id)
    except ValueError:
        _err(400, "无效的 bill_id")

    bill = await _fetch_bill(db, bid, tid)
    if bill["status"] == "paid":
        _err(400, "账单已全额付清，无需再次收款")

    payment_date = date.today()
    if req.payment_date:
        try:
            payment_date = date.fromisoformat(req.payment_date)
        except ValueError:
            _err(400, "无效的 payment_date 格式，应为 YYYY-MM-DD")

    remaining_fen = bill["unpaid_fen"]
    if req.paid_amount_fen > remaining_fen:
        _err(400, f"收款金额（{req.paid_amount_fen}分）超过未付金额（{remaining_fen}分）")

    payment_id = uuid.uuid4()
    new_paid_fen = bill["paid_fen"] + req.paid_amount_fen
    new_remaining = bill["amount_fen"] - new_paid_fen
    new_status = "paid" if new_remaining <= 0 else "partial"

    try:
        # 插入收款记录
        await db.execute(
            text("""
                INSERT INTO franchise_fee_payments
                  (id, tenant_id, bill_id, franchise_id, paid_amount_fen,
                   payment_method, payment_date, receipt_no, notes, created_by)
                VALUES (:id, :tid, :bid, :fid, :amount,
                        :method, :pdate, :receipt, :notes, :operator)
            """),
            {
                "id": payment_id,
                "tid": tid,
                "bid": bid,
                "fid": uuid.UUID(bill["franchise_id"]),
                "amount": req.paid_amount_fen,
                "method": req.payment_method,
                "pdate": payment_date,
                "receipt": req.receipt_no,
                "notes": req.notes,
                "operator": x_operator,
            },
        )

        # 更新账单已付金额和状态
        await db.execute(
            text("""
                UPDATE franchise_fee_bills
                SET paid_fen = :new_paid, status = :new_status, updated_at = now()
                WHERE id = :bid AND tenant_id = :tid
            """),
            {"new_paid": new_paid_fen, "new_status": new_status, "bid": bid, "tid": tid},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("record_payment.db_error", error=str(exc))
        _err(500, "数据库写入失败")

    log.info(
        "franchise_fee.payment_recorded",
        bill_id=bill_id,
        payment_id=str(payment_id),
        paid_amount_fen=req.paid_amount_fen,
        new_status=new_status,
        tenant_id=x_tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "payment_id": str(payment_id),
            "bill_id": bill_id,
            "paid_amount_fen": req.paid_amount_fen,
            "total_paid_fen": new_paid_fen,
            "remaining_fen": new_remaining,
            "bill_status": new_status,
        },
    }


@router.post("/fee-bills/{bill_id}/send-reminder")
async def send_payment_reminder(
    bill_id: str = Path(...),
    background_tasks: BackgroundTasks = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """发送催款提醒（触发企微/短信通知到加盟商联系人）。"""
    tid = await _set_rls(db, x_tenant_id)
    try:
        bid = uuid.UUID(bill_id)
    except ValueError:
        _err(400, "无效的 bill_id")

    bill = await _fetch_bill(db, bid, tid)
    if bill["status"] == "paid":
        _err(400, "账单已付清，无需催款")

    # 查询联系人信息
    contact_res = await db.execute(
        text("""
            SELECT contact_phone, contact_email, name
            FROM franchisees
            WHERE id = :fid AND tenant_id = :tid AND is_deleted = false
        """),
        {"fid": uuid.UUID(bill["franchise_id"]), "tid": tid},
    )
    contact_row = contact_res.fetchone()

    # 记录催款日志
    try:
        await db.execute(
            text("""
                INSERT INTO franchise_reminder_logs
                  (tenant_id, bill_id, franchise_id, reminder_type, sent_by, bill_status, unpaid_fen)
                VALUES (:tid, :bid, :fid, 'wecom_sms', :operator, :status, :unpaid)
            """),
            {
                "tid": tid,
                "bid": bid,
                "fid": uuid.UUID(bill["franchise_id"]),
                "operator": x_operator,
                "status": bill["status"],
                "unpaid": bill["unpaid_fen"],
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        log.warning("send_reminder.log_failed", error=str(exc))

    log.info(
        "franchise_fee.reminder_sent",
        bill_id=bill_id,
        franchise_id=bill["franchise_id"],
        unpaid_fen=bill["unpaid_fen"],
        tenant_id=x_tenant_id,
    )

    # 实际通知发送由企微/短信网关处理（此处为 stub，生产环境接入 im_sync_routes）
    return {
        "ok": True,
        "data": {
            "bill_id": bill_id,
            "franchise_name": bill["franchise_name"],
            "contact_phone": contact_row[0] if contact_row else None,
            "unpaid_fen": bill["unpaid_fen"],
            "reminder_sent": True,
            "channels": ["wecom", "sms"],
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# B2. 自动出账规则
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/billing-rules", status_code=201)
async def create_billing_rule(
    req: CreateBillingRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """配置自动出账规则（月/季/年周期）。"""
    tid = await _set_rls(db, x_tenant_id)

    if req.fee_type not in VALID_BILL_TYPES:
        _err(400, f"无效的 fee_type，支持: {', '.join(VALID_BILL_TYPES)}")
    if req.amount_fen is None and req.rate is None:
        _err(400, "amount_fen 和 rate 至少提供一个")
    if req.amount_fen is not None and req.rate is not None:
        _err(400, "amount_fen 和 rate 只能提供一个")

    try:
        franchise_uuid = uuid.UUID(req.franchise_id)
    except ValueError:
        _err(400, "无效的 franchise_id")

    try:
        start_date = date.fromisoformat(req.start_date)
    except ValueError:
        _err(400, "无效的 start_date 格式，应为 YYYY-MM-DD")

    # 校验加盟商存在
    fran_res = await db.execute(
        text("SELECT id FROM franchisees WHERE id = :fid AND tenant_id = :tid AND is_deleted = false"),
        {"fid": franchise_uuid, "tid": tid},
    )
    if not fran_res.fetchone():
        _err(404, "加盟商不存在")

    rule_id = uuid.uuid4()
    try:
        await db.execute(
            text("""
                INSERT INTO franchise_billing_rules
                  (id, tenant_id, franchise_id, fee_type, amount_fen, rate,
                   billing_cycle, billing_day, start_date, status, notes, created_by)
                VALUES (:id, :tid, :fid, :fee_type, :amount, :rate,
                        :cycle, :bday, :start_date, 'active', :notes, :operator)
            """),
            {
                "id": rule_id,
                "tid": tid,
                "fid": franchise_uuid,
                "fee_type": req.fee_type,
                "amount": req.amount_fen,
                "rate": req.rate,
                "cycle": req.billing_cycle,
                "bday": req.billing_day,
                "start_date": start_date,
                "notes": req.notes,
                "operator": x_operator,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("create_billing_rule.db_error", error=str(exc))
        _err(500, "数据库写入失败")

    log.info(
        "franchise_billing_rule.created",
        rule_id=str(rule_id),
        franchise_id=req.franchise_id,
        fee_type=req.fee_type,
        billing_cycle=req.billing_cycle,
        tenant_id=x_tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "id": str(rule_id),
            "franchise_id": req.franchise_id,
            "fee_type": req.fee_type,
            "fee_type_label": BILL_TYPE_LABELS.get(req.fee_type, req.fee_type),
            "billing_cycle": req.billing_cycle,
            "billing_day": req.billing_day,
            "start_date": req.start_date,
            "status": "active",
        },
    }


@router.get("/billing-rules")
async def list_billing_rules(
    franchise_id: Optional[str] = Query(None),
    fee_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(active|paused|expired)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """自动出账规则列表。"""
    tid = await _set_rls(db, x_tenant_id)

    where = "WHERE r.tenant_id = :tid"
    params: dict = {"tid": tid}

    if franchise_id:
        try:
            params["franchise_id"] = uuid.UUID(franchise_id)
        except ValueError:
            _err(400, "无效的 franchise_id")
        where += " AND r.franchise_id = :franchise_id"

    if fee_type:
        if fee_type not in VALID_BILL_TYPES:
            _err(400, f"无效的 fee_type")
        where += " AND r.fee_type = :fee_type"
        params["fee_type"] = fee_type

    if status:
        where += " AND r.status = :status"
        params["status"] = status

    count_res = await db.execute(
        text(f"SELECT COUNT(*) FROM franchise_billing_rules r {where}"), params
    )
    total = count_res.scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    rows = await db.execute(
        text(f"""
            SELECT r.id, r.franchise_id, f.name AS franchise_name,
                   r.fee_type, r.amount_fen, r.rate, r.billing_cycle,
                   r.billing_day, r.start_date, r.status, r.last_triggered_at
            FROM franchise_billing_rules r
            LEFT JOIN franchisees f ON f.id = r.franchise_id AND f.tenant_id = r.tenant_id
            {where}
            ORDER BY r.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [
        {
            "id": str(r[0]),
            "franchise_id": str(r[1]),
            "franchise_name": r[2],
            "fee_type": r[3],
            "fee_type_label": BILL_TYPE_LABELS.get(r[3], r[3]),
            "amount_fen": r[4],
            "rate": r[5],
            "billing_cycle": r[6],
            "billing_day": r[7],
            "start_date": r[8].isoformat() if r[8] else None,
            "status": r[9],
            "last_triggered_at": r[10].isoformat() if r[10] else None,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.post("/billing-rules/{rule_id}/trigger", status_code=202)
async def trigger_billing_rule(
    rule_id: str = Path(...),
    billing_period: Optional[str] = Query(None, description="手动指定账期 YYYY-MM，默认当月"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动触发出账规则（测试用），立即按规则生成一条账单。"""
    tid = await _set_rls(db, x_tenant_id)
    try:
        rid = uuid.UUID(rule_id)
    except ValueError:
        _err(400, "无效的 rule_id")

    # 查询规则
    rule_res = await db.execute(
        text("""
            SELECT id, franchise_id, fee_type, amount_fen, rate, billing_cycle, billing_day
            FROM franchise_billing_rules
            WHERE id = :rid AND tenant_id = :tid AND status = 'active'
        """),
        {"rid": rid, "tid": tid},
    )
    rule_row = rule_res.fetchone()
    if not rule_row:
        _err(404, "规则不存在或未启用")

    franchise_id = rule_row[1]
    fee_type = rule_row[2]
    amount_fen = rule_row[3]
    rate = rule_row[4]

    # 确定账期和到期日
    from datetime import datetime as dt
    now = dt.now()
    period_str = billing_period or now.strftime("%Y-%m")
    try:
        period_date = date.fromisoformat(period_str + "-01")
    except ValueError:
        _err(400, "无效的 billing_period 格式，应为 YYYY-MM")

    billing_day = rule_row[6]
    import calendar
    max_day = calendar.monthrange(period_date.year, period_date.month)[1]
    actual_day = min(billing_day, max_day)
    due_date = date(period_date.year, period_date.month, actual_day)

    # 如果是比率，需要基于营业额计算（此处用固定金额的回退逻辑）
    final_amount = amount_fen
    if rate is not None and amount_fen is None:
        # 实际应查询该加盟商当月营业额，此处暂用 0 占位，实际接入时替换
        log.warning("billing_rule.rate_billing_not_fully_implemented", rule_id=rule_id)
        final_amount = 0  # 占位

    if not final_amount or final_amount <= 0:
        _err(400, "无法计算账单金额，请直接指定 amount_fen 的规则或接入营业额数据")

    bill_id = uuid.uuid4()
    today = date.today()
    initial_status = "overdue" if due_date < today else "pending"

    try:
        await db.execute(
            text("""
                INSERT INTO franchise_fee_bills
                  (id, tenant_id, franchise_id, bill_type, amount_fen, paid_fen,
                   status, due_date, billing_period, notes, created_by)
                VALUES (:id, :tid, :fid, :btype, :amount, 0,
                        :status, :due_date, :period, :notes, :operator)
            """),
            {
                "id": bill_id,
                "tid": tid,
                "fid": franchise_id,
                "btype": fee_type,
                "amount": final_amount,
                "status": initial_status,
                "due_date": due_date,
                "period": period_str,
                "notes": f"规则 {rule_id} 手动触发",
                "operator": x_operator,
            },
        )

        # 更新规则最后触发时间
        await db.execute(
            text("UPDATE franchise_billing_rules SET last_triggered_at = now() WHERE id = :rid AND tenant_id = :tid"),
            {"rid": rid, "tid": tid},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("trigger_billing_rule.db_error", error=str(exc))
        _err(500, "数据库写入失败")

    log.info(
        "franchise_billing_rule.triggered",
        rule_id=rule_id,
        bill_id=str(bill_id),
        period=period_str,
        tenant_id=x_tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "rule_id": rule_id,
            "bill_id": str(bill_id),
            "billing_period": period_str,
            "amount_fen": final_amount,
            "due_date": due_date.isoformat(),
            "status": initial_status,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# B3. 收费汇总报表
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/fee-report/summary")
async def get_fee_report_summary(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    bill_type: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """收费汇总：总应收、总已收、总逾期、收缴率及分类明细。"""
    tid = await _set_rls(db, x_tenant_id)

    where = "WHERE b.tenant_id = :tid AND b.is_deleted IS NOT TRUE"
    params: dict = {"tid": tid}

    if date_from:
        try:
            params["date_from"] = date.fromisoformat(date_from)
        except ValueError:
            _err(400, "无效的 date_from")
        where += " AND b.due_date >= :date_from"

    if date_to:
        try:
            params["date_to"] = date.fromisoformat(date_to)
        except ValueError:
            _err(400, "无效的 date_to")
        where += " AND b.due_date <= :date_to"

    if bill_type:
        if bill_type not in VALID_BILL_TYPES:
            _err(400, f"无效的 bill_type")
        where += " AND b.bill_type = :bill_type"
        params["bill_type"] = bill_type

    # 汇总统计
    summary_res = await db.execute(
        text(f"""
            SELECT
                SUM(b.amount_fen)                                           AS total_billed_fen,
                SUM(COALESCE(b.paid_fen, 0))                                AS total_paid_fen,
                SUM(CASE WHEN b.status = 'overdue'
                    THEN b.amount_fen - COALESCE(b.paid_fen, 0) ELSE 0 END) AS total_overdue_fen,
                COUNT(*)                                                     AS total_bills,
                COUNT(CASE WHEN b.status = 'paid' THEN 1 END)               AS paid_count,
                COUNT(CASE WHEN b.status = 'overdue' THEN 1 END)            AS overdue_count
            FROM franchise_fee_bills b
            {where}
        """),
        params,
    )
    row = summary_res.fetchone()
    total_billed = row[0] or 0
    total_paid = row[1] or 0
    total_overdue = row[2] or 0
    collection_rate = round(total_paid / total_billed, 4) if total_billed > 0 else 0.0

    # 分类统计
    by_type_res = await db.execute(
        text(f"""
            SELECT
                b.bill_type,
                SUM(b.amount_fen)            AS billed_fen,
                SUM(COALESCE(b.paid_fen, 0)) AS paid_fen,
                COUNT(*)                     AS bill_count
            FROM franchise_fee_bills b
            {where}
            GROUP BY b.bill_type
            ORDER BY billed_fen DESC
        """),
        params,
    )
    by_type = [
        {
            "bill_type": r[0],
            "bill_type_label": BILL_TYPE_LABELS.get(r[0], r[0]),
            "billed_fen": r[1] or 0,
            "paid_fen": r[2] or 0,
            "unpaid_fen": (r[1] or 0) - (r[2] or 0),
            "bill_count": r[3] or 0,
            "collection_rate": round((r[2] or 0) / r[1], 4) if r[1] else 0.0,
        }
        for r in by_type_res.fetchall()
    ]

    return {
        "ok": True,
        "data": {
            "total_billed_fen": total_billed,
            "total_paid_fen": total_paid,
            "total_overdue_fen": total_overdue,
            "collection_rate": collection_rate,
            "total_bills": row[3] or 0,
            "paid_count": row[4] or 0,
            "overdue_count": row[5] or 0,
            "by_type": by_type,
            "date_from": date_from,
            "date_to": date_to,
        },
    }


@router.get("/fee-report/by-franchise")
async def get_fee_report_by_franchise(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    bill_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """各加盟商收费明细：含应收、已收、逾期金额、最近收款日期。"""
    tid = await _set_rls(db, x_tenant_id)

    where = "WHERE b.tenant_id = :tid AND b.is_deleted IS NOT TRUE"
    params: dict = {"tid": tid}

    if date_from:
        try:
            params["date_from"] = date.fromisoformat(date_from)
        except ValueError:
            _err(400, "无效的 date_from")
        where += " AND b.due_date >= :date_from"

    if date_to:
        try:
            params["date_to"] = date.fromisoformat(date_to)
        except ValueError:
            _err(400, "无效的 date_to")
        where += " AND b.due_date <= :date_to"

    if bill_type:
        if bill_type not in VALID_BILL_TYPES:
            _err(400, f"无效的 bill_type")
        where += " AND b.bill_type = :bill_type"
        params["bill_type"] = bill_type

    count_res = await db.execute(
        text(f"""
            SELECT COUNT(DISTINCT b.franchise_id)
            FROM franchise_fee_bills b {where}
        """),
        params,
    )
    total = count_res.scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    rows = await db.execute(
        text(f"""
            SELECT
                b.franchise_id,
                f.name AS franchise_name,
                f.contact_phone,
                SUM(b.amount_fen)                                                  AS total_billed_fen,
                SUM(COALESCE(b.paid_fen, 0))                                       AS total_paid_fen,
                SUM(CASE WHEN b.status = 'overdue'
                    THEN b.amount_fen - COALESCE(b.paid_fen, 0) ELSE 0 END)        AS overdue_amount_fen,
                MAX(p.payment_date)                                                AS last_payment_date,
                COUNT(CASE WHEN b.status = 'overdue' THEN 1 END)                  AS overdue_bill_count
            FROM franchise_fee_bills b
            LEFT JOIN franchisees f ON f.id = b.franchise_id AND f.tenant_id = b.tenant_id
            LEFT JOIN franchise_fee_payments p ON p.bill_id = b.id AND p.tenant_id = b.tenant_id
            {where}
            GROUP BY b.franchise_id, f.name, f.contact_phone
            ORDER BY overdue_amount_fen DESC, total_billed_fen DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [
        {
            "franchise_id": str(r[0]),
            "franchise_name": r[1],
            "contact_phone": r[2],
            "total_billed_fen": r[3] or 0,
            "total_paid_fen": r[4] or 0,
            "unpaid_fen": (r[3] or 0) - (r[4] or 0),
            "overdue_amount_fen": r[5] or 0,
            "last_payment_date": r[6].isoformat() if r[6] else None,
            "overdue_bill_count": r[7] or 0,
            "collection_rate": round((r[4] or 0) / r[3], 4) if r[3] else 0.0,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
