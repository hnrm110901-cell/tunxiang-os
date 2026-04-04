"""企业挂账 API 路由

端点：
  POST /api/v1/credit/agreements/                   — 创建挂账协议
  GET  /api/v1/credit/agreements/                   — 协议列表
  GET  /api/v1/credit/agreements/{id}               — 协议详情
  POST /api/v1/credit/agreements/{id}/charge        — 挂账消费
  POST /api/v1/credit/agreements/{id}/suspend       — 暂停协议
  GET  /api/v1/credit/agreements/{id}/bills         — 账单列表
  POST /api/v1/credit/bills/{id}/pay                — 还款
  GET  /api/v1/credit/agreements/{id}/statement     — 对账单（消费明细）
"""
import asyncio
import uuid
from datetime import datetime, date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import CreditEventType
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/credit", tags=["企业挂账"])

# 额度预警阈值（使用率超过此比例触发警告事件）
_LIMIT_WARNING_RATIO = 0.80


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _serialize_row(row: dict) -> dict:
    result = {}
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, (datetime, date)):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


# ─── 依赖注入 ──────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── 请求模型 ──────────────────────────────────────────────────────────────────

class AgreementCreate(BaseModel):
    brand_id: uuid.UUID
    company_name: str
    company_tax_no: Optional[str] = None
    credit_limit_fen: int = Field(..., gt=0, description="信用额度（分），必须大于0")
    billing_cycle: str = "monthly"          # monthly/weekly/biweekly
    due_day: int = Field(15, ge=1, le=28, description="账单日（1-28）")
    remark: Optional[str] = None


class CreditChargeRequest(BaseModel):
    order_id: uuid.UUID
    store_id: uuid.UUID
    charged_amount_fen: int = Field(..., gt=0, description="挂账金额（分）")
    remark: Optional[str] = None


class AgreementSuspendRequest(BaseModel):
    remark: Optional[str] = None


class BillPayRequest(BaseModel):
    pay_amount_fen: int = Field(..., gt=0, description="还款金额（分）")
    remark: Optional[str] = None


# ─── POST /agreements/ — 创建协议 ────────────────────────────────────────────

_APPROVAL_THRESHOLD_FEN = 5_000_000  # 信用额度 >= 5万元时需审批


@router.post("/agreements/", summary="创建企业挂账协议")
async def create_agreement(
    body: AgreementCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """创建企业挂账协议（品牌级）。
    信用额度 < 5万元时直接生效（status=active）；
    信用额度 >= 5万元时进入待审批状态（status=pending_approval），并触发审批流。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")

    valid_cycles = {"monthly", "weekly", "biweekly"}
    if body.billing_cycle not in valid_cycles:
        raise HTTPException(
            status_code=400,
            detail=f"billing_cycle 必须是: {', '.join(valid_cycles)}",
        )

    # 根据额度决定初始状态
    needs_approval = body.credit_limit_fen >= _APPROVAL_THRESHOLD_FEN
    initial_status = "pending_approval" if needs_approval else "active"

    try:
        result = await db.execute(
            text("""
                INSERT INTO biz_credit_agreements (
                    tenant_id, brand_id, company_name, company_tax_no,
                    credit_limit_fen, used_amount_fen,
                    billing_cycle, due_day, status,
                    created_by, remark
                ) VALUES (
                    :tenant_id::UUID, :brand_id::UUID, :company_name, :company_tax_no,
                    :credit_limit_fen, 0,
                    :billing_cycle, :due_day, :status,
                    :created_by::UUID, :remark
                )
                RETURNING id, status, created_at
            """),
            {
                "tenant_id": str(tid),
                "brand_id": str(body.brand_id),
                "company_name": body.company_name,
                "company_tax_no": body.company_tax_no,
                "credit_limit_fen": body.credit_limit_fen,
                "billing_cycle": body.billing_cycle,
                "due_day": body.due_day,
                "status": initial_status,
                "created_by": str(op_id),
                "remark": body.remark,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except Exception as exc:
        logger.error("create_agreement.failed", company_name=body.company_name,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="创建挂账协议失败") from exc

    agreement_id = str(row["id"])
    logger.info(
        "credit_agreement_created",
        agreement_id=agreement_id,
        company_name=body.company_name,
        credit_limit_fen=body.credit_limit_fen,
        status=initial_status,
    )

    # 大额协议旁路触发审批流（不阻塞响应）
    if needs_approval:
        asyncio.create_task(emit_event(
            event_type="approval.requested",
            tenant_id=str(tid),
            stream_id=agreement_id,
            payload={
                "approval_type": "credit_agreement",
                "subject_id": agreement_id,
                "company_name": body.company_name,
                "credit_limit_fen": body.credit_limit_fen,
                "requested_by": str(op_id),
            },
            source_service="tx-finance",
        ))

    return {
        "ok": True,
        "data": {
            "agreement_id": agreement_id,
            "status": row["status"],
            "company_name": body.company_name,
            "credit_limit_fen": body.credit_limit_fen,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "requires_approval": needs_approval,
        },
        "error": None,
    }


# ─── GET /agreements/ — 协议列表 ─────────────────────────────────────────────

@router.get("/agreements/", summary="企业挂账协议列表")
async def list_agreements(
    brand_id: Optional[str] = Query(None, description="品牌ID"),
    status: Optional[str] = Query(None, description="状态: active/suspended/terminated"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """返回企业挂账协议列表，支持按品牌和状态筛选。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    where_clauses = ["tenant_id = :tenant_id::UUID"]
    params: dict = {"tenant_id": str(tid)}

    if brand_id:
        bid = _parse_uuid(brand_id, "brand_id")
        where_clauses.append("brand_id = :brand_id::UUID")
        params["brand_id"] = str(bid)

    if status:
        valid_statuses = {"active", "suspended", "terminated", "pending_approval"}
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"status 必须是: {', '.join(valid_statuses)}",
            )
        where_clauses.append("status = :status")
        params["status"] = status

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM biz_credit_agreements WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, brand_id, company_name, company_tax_no,
                       credit_limit_fen, used_amount_fen,
                       (credit_limit_fen - used_amount_fen) AS available_fen,
                       billing_cycle, due_day, status,
                       created_by, approved_by, approved_at, created_at
                FROM biz_credit_agreements
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(dict(row)) for row in items_result.mappings().all()]
    except Exception as exc:
        logger.error("list_agreements.failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询协议列表失败") from exc

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── GET /agreements/{id} — 协议详情 ─────────────────────────────────────────

@router.get("/agreements/{agreement_id}", summary="协议详情")
async def get_agreement(
    agreement_id: str = Path(..., description="协议ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取单个企业挂账协议的完整详情，含使用率计算。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    aid = _parse_uuid(agreement_id, "agreement_id")

    try:
        result = await db.execute(
            text("""
                SELECT id, brand_id, company_name, company_tax_no,
                       credit_limit_fen, used_amount_fen,
                       (credit_limit_fen - used_amount_fen) AS available_fen,
                       ROUND(used_amount_fen::NUMERIC / NULLIF(credit_limit_fen, 0) * 100, 2) AS usage_rate_pct,
                       billing_cycle, due_day, status,
                       created_by, approved_by, approved_at, remark,
                       created_at, updated_at
                FROM biz_credit_agreements
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(aid), "tenant_id": str(tid)},
        )
        row = result.mappings().first()
    except Exception as exc:
        logger.error("get_agreement.failed", agreement_id=agreement_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询协议失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"协议不存在: {agreement_id}")

    return {"ok": True, "data": _serialize_row(dict(row)), "error": None}


# ─── POST /agreements/{id}/charge — 挂账消费 ─────────────────────────────────

@router.post("/agreements/{agreement_id}/charge", summary="挂账消费")
async def charge_credit(
    agreement_id: str = Path(..., description="协议ID"),
    body: CreditChargeRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """挂账消费：校验额度，更新已用额度，写消费记录。
    使用率超过 80% 时旁路发射 credit.limit_warning 事件。
    额度不足时返回 402 Payment Required。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    aid = _parse_uuid(agreement_id, "agreement_id")

    try:
        fetch = await db.execute(
            text("""
                SELECT id, company_name, credit_limit_fen, used_amount_fen, status
                FROM biz_credit_agreements
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(aid), "tenant_id": str(tid)},
        )
        agreement = fetch.mappings().first()
    except Exception as exc:
        logger.error("charge_credit.fetch_failed", agreement_id=agreement_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询协议失败") from exc

    if agreement is None:
        raise HTTPException(status_code=404, detail=f"协议不存在: {agreement_id}")

    if agreement["status"] != "active":
        raise HTTPException(
            status_code=409,
            detail=f"协议状态 {agreement['status']} 不允许挂账消费",
        )

    available = agreement["credit_limit_fen"] - agreement["used_amount_fen"]
    if body.charged_amount_fen > available:
        raise HTTPException(
            status_code=402,
            detail=(
                f"信用额度不足：可用 {available} 分，本次需 {body.charged_amount_fen} 分"
            ),
        )

    new_used = agreement["used_amount_fen"] + body.charged_amount_fen

    try:
        # 更新已用额度
        await db.execute(
            text("""
                UPDATE biz_credit_agreements
                SET used_amount_fen = :new_used,
                    updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"new_used": new_used, "id": str(aid), "tenant_id": str(tid)},
        )

        # 写消费记录
        charge_result = await db.execute(
            text("""
                INSERT INTO biz_credit_charges (
                    tenant_id, agreement_id, order_id, store_id,
                    charged_amount_fen, charged_at, operator_id, remark
                ) VALUES (
                    :tenant_id::UUID, :agreement_id::UUID, :order_id::UUID, :store_id::UUID,
                    :charged_amount_fen, NOW(), :operator_id::UUID, :remark
                )
                RETURNING id, charged_at
            """),
            {
                "tenant_id": str(tid),
                "agreement_id": str(aid),
                "order_id": str(body.order_id),
                "store_id": str(body.store_id),
                "charged_amount_fen": body.charged_amount_fen,
                "operator_id": str(op_id),
                "remark": body.remark,
            },
        )
        charge_row = charge_result.mappings().first()
        await db.commit()
    except Exception as exc:
        logger.error("charge_credit.failed", agreement_id=agreement_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="挂账消费失败") from exc

    charge_id = str(charge_row["id"])
    usage_rate = new_used / agreement["credit_limit_fen"] if agreement["credit_limit_fen"] else 0

    logger.info("credit_charged", charge_id=charge_id, agreement_id=agreement_id,
                charged_amount_fen=body.charged_amount_fen, usage_rate=usage_rate)

    # 旁路发射挂账消费事件
    asyncio.create_task(emit_event(
        event_type=CreditEventType.CHARGED,
        tenant_id=tid,
        stream_id=agreement_id,
        payload={
            "charge_id": charge_id,
            "agreement_id": agreement_id,
            "order_id": str(body.order_id),
            "charged_amount_fen": body.charged_amount_fen,
            "new_used_amount_fen": new_used,
            "usage_rate": round(usage_rate, 4),
        },
        store_id=body.store_id,
        source_service="tx-finance",
        metadata={"operator_id": str(op_id)},
    ))

    # 额度使用率超过 80% → 发射预警事件
    if usage_rate >= _LIMIT_WARNING_RATIO:
        asyncio.create_task(emit_event(
            event_type=CreditEventType.LIMIT_WARNING,
            tenant_id=tid,
            stream_id=agreement_id,
            payload={
                "agreement_id": agreement_id,
                "company_name": agreement["company_name"],
                "credit_limit_fen": agreement["credit_limit_fen"],
                "used_amount_fen": new_used,
                "usage_rate_pct": round(usage_rate * 100, 2),
            },
            source_service="tx-finance",
        ))
        logger.warning("credit_limit_warning", agreement_id=agreement_id,
                       usage_rate_pct=round(usage_rate * 100, 2))

    return {
        "ok": True,
        "data": {
            "charge_id": charge_id,
            "agreement_id": agreement_id,
            "charged_amount_fen": body.charged_amount_fen,
            "new_used_amount_fen": new_used,
            "available_fen": agreement["credit_limit_fen"] - new_used,
            "usage_rate_pct": round(usage_rate * 100, 2),
            "limit_warning": usage_rate >= _LIMIT_WARNING_RATIO,
        },
        "error": None,
    }


# ─── POST /agreements/{id}/suspend — 暂停协议 ────────────────────────────────

@router.post("/agreements/{agreement_id}/suspend", summary="暂停挂账协议")
async def suspend_agreement(
    agreement_id: str = Path(..., description="协议ID"),
    body: AgreementSuspendRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """暂停挂账协议，暂停后该企业不能继续挂账消费，但已有账单不受影响。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    aid = _parse_uuid(agreement_id, "agreement_id")

    try:
        result = await db.execute(
            text("""
                UPDATE biz_credit_agreements
                SET status = 'suspended',
                    remark = COALESCE(:remark, remark),
                    updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                  AND status = 'active'
                RETURNING id, status, updated_at
            """),
            {
                "remark": body.remark,
                "id": str(aid),
                "tenant_id": str(tid),
            },
        )
        row = result.mappings().first()
        await db.commit()
    except Exception as exc:
        logger.error("suspend_agreement.failed", agreement_id=agreement_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="暂停协议失败") from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"协议不存在或非 active 状态: {agreement_id}",
        )

    logger.info("credit_agreement_suspended", agreement_id=agreement_id,
                operator_id=str(op_id))

    return {
        "ok": True,
        "data": {
            "agreement_id": agreement_id,
            "status": row["status"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        },
        "error": None,
    }


# ─── GET /agreements/{id}/bills — 账单列表 ────────────────────────────────────

@router.get("/agreements/{agreement_id}/bills", summary="挂账账单列表")
async def list_bills(
    agreement_id: str = Path(..., description="协议ID"),
    status: Optional[str] = Query(None, description="状态: pending/partial_paid/paid/overdue"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询指定协议的账单列表，支持按状态筛选，分页返回。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    aid = _parse_uuid(agreement_id, "agreement_id")

    where_clauses = [
        "tenant_id = :tenant_id::UUID",
        "agreement_id = :agreement_id::UUID",
    ]
    params: dict = {"tenant_id": str(tid), "agreement_id": str(aid)}

    if status:
        valid_statuses = {"pending", "partial_paid", "paid", "overdue"}
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"status 必须是: {', '.join(valid_statuses)}",
            )
        where_clauses.append("status = :status")
        params["status"] = status

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM biz_credit_bills WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, bill_no, period_start, period_end,
                       total_amount_fen, paid_amount_fen,
                       (total_amount_fen - paid_amount_fen) AS unpaid_fen,
                       status, due_date, generated_at, paid_at
                FROM biz_credit_bills
                WHERE {where_sql}
                ORDER BY period_start DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(dict(row)) for row in items_result.mappings().all()]
    except Exception as exc:
        logger.error("list_bills.failed", agreement_id=agreement_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询账单列表失败") from exc

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── POST /bills/{id}/pay — 还款 ─────────────────────────────────────────────

@router.post("/bills/{bill_id}/pay", summary="账单还款")
async def pay_bill(
    bill_id: str = Path(..., description="账单ID"),
    body: BillPayRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """为挂账账单还款，支持部分还款，全部还清后状态变为 paid，同步减少协议已用额度。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    bid = _parse_uuid(bill_id, "bill_id")

    try:
        fetch = await db.execute(
            text("""
                SELECT b.id, b.agreement_id, b.total_amount_fen, b.paid_amount_fen, b.status,
                       a.used_amount_fen, a.credit_limit_fen
                FROM biz_credit_bills b
                JOIN biz_credit_agreements a ON a.id = b.agreement_id
                WHERE b.id = :id::UUID AND b.tenant_id = :tenant_id::UUID
            """),
            {"id": str(bid), "tenant_id": str(tid)},
        )
        bill = fetch.mappings().first()
    except Exception as exc:
        logger.error("pay_bill.fetch_failed", bill_id=bill_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询账单失败") from exc

    if bill is None:
        raise HTTPException(status_code=404, detail=f"账单不存在: {bill_id}")

    if bill["status"] == "paid":
        raise HTTPException(status_code=409, detail="账单已还清，无需重复还款")

    unpaid = bill["total_amount_fen"] - bill["paid_amount_fen"]
    if body.pay_amount_fen > unpaid:
        raise HTTPException(
            status_code=400,
            detail=f"还款金额 {body.pay_amount_fen} 超过未还金额 {unpaid}（分）",
        )

    new_paid = bill["paid_amount_fen"] + body.pay_amount_fen
    new_bill_status = "paid" if new_paid >= bill["total_amount_fen"] else "partial_paid"
    new_used = max(0, bill["used_amount_fen"] - body.pay_amount_fen)

    try:
        # 更新账单
        await db.execute(
            text("""
                UPDATE biz_credit_bills
                SET paid_amount_fen = :new_paid,
                    status = :new_status,
                    paid_at = CASE WHEN :new_status = 'paid' THEN NOW() ELSE paid_at END,
                    updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {
                "new_paid": new_paid,
                "new_status": new_bill_status,
                "id": str(bid),
                "tenant_id": str(tid),
            },
        )

        # 还款后减少协议已用额度
        await db.execute(
            text("""
                UPDATE biz_credit_agreements
                SET used_amount_fen = :new_used,
                    updated_at = NOW()
                WHERE id = :agreement_id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {
                "new_used": new_used,
                "agreement_id": str(bill["agreement_id"]),
                "tenant_id": str(tid),
            },
        )
        await db.commit()
    except Exception as exc:
        logger.error("pay_bill.failed", bill_id=bill_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="账单还款失败") from exc

    logger.info("credit_payment_received", bill_id=bill_id,
                pay_amount_fen=body.pay_amount_fen, new_status=new_bill_status)

    asyncio.create_task(emit_event(
        event_type=CreditEventType.PAYMENT_RECEIVED,
        tenant_id=tid,
        stream_id=str(bill["agreement_id"]),
        payload={
            "bill_id": bill_id,
            "agreement_id": str(bill["agreement_id"]),
            "pay_amount_fen": body.pay_amount_fen,
            "new_bill_status": new_bill_status,
            "new_used_amount_fen": new_used,
        },
        source_service="tx-finance",
        metadata={"operator_id": str(op_id)},
    ))

    return {
        "ok": True,
        "data": {
            "bill_id": bill_id,
            "bill_status": new_bill_status,
            "paid_amount_fen": new_paid,
            "unpaid_fen": bill["total_amount_fen"] - new_paid,
            "agreement_used_amount_fen": new_used,
        },
        "error": None,
    }


# ─── GET /agreements/{id}/statement — 对账单 ─────────────────────────────────

@router.get("/agreements/{agreement_id}/statement", summary="企业消费对账单")
async def get_statement(
    agreement_id: str = Path(..., description="协议ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """企业挂账消费对账单：指定日期范围内的消费明细，供财务核对和企业确认使用。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    aid = _parse_uuid(agreement_id, "agreement_id")

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="日期格式错误，请使用 YYYY-MM-DD",
        ) from exc

    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    offset = (page - 1) * size

    try:
        # 协议信息
        agr_result = await db.execute(
            text("""
                SELECT id, company_name, credit_limit_fen, billing_cycle, status
                FROM biz_credit_agreements
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(aid), "tenant_id": str(tid)},
        )
        agreement = agr_result.mappings().first()
        if agreement is None:
            raise HTTPException(status_code=404, detail=f"协议不存在: {agreement_id}")

        # 消费明细
        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM biz_credit_charges
                WHERE tenant_id = :tenant_id::UUID
                  AND agreement_id = :agreement_id::UUID
                  AND charged_at >= :start_date::DATE
                  AND charged_at < (:end_date::DATE + INTERVAL '1 day')
            """),
            {
                "tenant_id": str(tid),
                "agreement_id": str(aid),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        total = count_result.scalar()

        charges_result = await db.execute(
            text("""
                SELECT id, order_id, store_id, charged_amount_fen, charged_at,
                       operator_id, remark
                FROM biz_credit_charges
                WHERE tenant_id = :tenant_id::UUID
                  AND agreement_id = :agreement_id::UUID
                  AND charged_at >= :start_date::DATE
                  AND charged_at < (:end_date::DATE + INTERVAL '1 day')
                ORDER BY charged_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "tenant_id": str(tid),
                "agreement_id": str(aid),
                "start_date": start_date,
                "end_date": end_date,
                "limit": size,
                "offset": offset,
            },
        )
        charges = [_serialize_row(dict(row)) for row in charges_result.mappings().all()]

        # 汇总
        summary_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(charged_amount_fen), 0) AS total_charged_fen,
                       COUNT(*) AS total_transactions
                FROM biz_credit_charges
                WHERE tenant_id = :tenant_id::UUID
                  AND agreement_id = :agreement_id::UUID
                  AND charged_at >= :start_date::DATE
                  AND charged_at < (:end_date::DATE + INTERVAL '1 day')
            """),
            {
                "tenant_id": str(tid),
                "agreement_id": str(aid),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        summary = dict(summary_result.mappings().first())
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_statement.failed", agreement_id=agreement_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="对账单查询失败") from exc

    return {
        "ok": True,
        "data": {
            "agreement_id": agreement_id,
            "company_name": agreement["company_name"],
            "start_date": start_date,
            "end_date": end_date,
            "summary": summary,
            "charges": {"items": charges, "total": total, "page": page, "size": size},
        },
        "error": None,
    }
