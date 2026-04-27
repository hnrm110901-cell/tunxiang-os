"""支付对账报表 API

端点：
  GET /api/v1/finance/payment-reconciliation  — 按支付渠道汇总对账
  GET /api/v1/finance/payment-details         — 逐笔支付明细
  GET /api/v1/finance/cashier-receipts        — 收银员收款统计
  GET /api/v1/finance/crm-reconciliation      — CRM储值卡对账
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/finance", tags=["payment-reconciliation"])

# ─── 渠道配置 ─────────────────────────────────────────────────────────────────

CHANNEL_NAMES: dict[str, str] = {
    "wechat": "微信支付",
    "alipay": "支付宝",
    "cash": "现金",
    "card": "银行卡",
    "member_card": "会员卡",
    "other": "其他",
}

# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class ChannelSummary(BaseModel):
    channel: str
    channel_name: str
    transaction_count: int = Field(ge=0)
    total_amount_fen: int = Field(ge=0)
    fee_fen: int = Field(ge=0)
    net_amount_fen: int = Field(ge=0)


class PaymentReconciliationResponse(BaseModel):
    ok: bool = True
    data: dict


class PaymentDetailItem(BaseModel):
    payment_id: str
    order_id: str
    channel: str
    amount_fen: int
    paid_at: str
    cashier_name: str
    store_name: str


class CashierReceiptItem(BaseModel):
    cashier_id: str
    cashier_name: str
    shift_count: int
    total_amount_fen: int
    order_count: int
    channel_breakdown: dict


class CrmMismatchItem(BaseModel):
    member_id: str
    member_name: str
    phone: str
    crm_amount_fen: int
    finance_amount_fen: int
    diff_fen: int
    type: str  # recharge / consume


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    """从 Header 提取 tenant_id，返回带 RLS 的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _validate_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    try:
        uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"X-Tenant-ID 格式错误: {exc}",
        ) from exc
    return x_tenant_id


def _validate_date_range(start_date: str, end_date: str) -> tuple[date, date]:
    try:
        d_start = date.fromisoformat(start_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"start_date 格式错误: {start_date}，请使用 YYYY-MM-DD",
        ) from exc
    try:
        d_end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"end_date 格式错误: {end_date}，请使用 YYYY-MM-DD",
        ) from exc
    if d_start > d_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date 不能晚于 end_date",
        )
    return d_start, d_end


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} 格式错误: {exc}",
        ) from exc
    return value


# ─── GET /payment-reconciliation ─────────────────────────────────────────────


@router.get(
    "/payment-reconciliation",
    summary="按支付渠道汇总对账",
    description="按日期范围查询各支付渠道的交易汇总，支持门店/品牌过滤。",
)
async def get_payment_reconciliation(
    start_date: str = Query(..., description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    store_id: Optional[str] = Query(None, description="门店 ID（可选）"),
    brand_id: Optional[str] = Query(None, description="品牌 ID（可选）"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_validate_tenant_id),
):
    d_start, d_end = _validate_date_range(start_date, end_date)

    sql_parts = [
        "SELECT channel, COUNT(*) AS transaction_count,",
        "       COALESCE(SUM(amount_fen), 0) AS total_amount_fen,",
        "       COALESCE(SUM(COALESCE(fee_fen, 0)), 0) AS fee_fen",
        "FROM payments",
        "WHERE paid_at::date BETWEEN :start_date AND :end_date",
    ]
    params: dict = {"start_date": d_start, "end_date": d_end}

    if store_id:
        _validate_uuid(store_id, "store_id")
        sql_parts.append("AND store_id = :store_id")
        params["store_id"] = store_id

    if brand_id:
        _validate_uuid(brand_id, "brand_id")
        sql_parts.append("AND brand_id = :brand_id")
        params["brand_id"] = brand_id

    sql_parts.append("GROUP BY channel ORDER BY total_amount_fen DESC")
    sql = text(" ".join(sql_parts))
    result = await db.execute(sql, params)
    rows = result.fetchall()

    channel_summaries: list[dict] = []
    for row in rows:
        ch = str(row.channel) if row.channel else "other"
        fee = int(row.fee_fen)
        total = int(row.total_amount_fen)
        channel_summaries.append(
            {
                "channel": ch,
                "channel_name": CHANNEL_NAMES.get(ch, ch),
                "transaction_count": int(row.transaction_count),
                "total_amount_fen": total,
                "fee_fen": fee,
                "net_amount_fen": total - fee,
            }
        )

    grand_total_fen = sum(c["total_amount_fen"] for c in channel_summaries)
    total_transactions = sum(c["transaction_count"] for c in channel_summaries)

    logger.info(
        "payment_reconciliation.ok",
        tenant_id=tenant_id,
        channel_count=len(channel_summaries),
        grand_total_fen=grand_total_fen,
    )

    return {
        "ok": True,
        "data": {
            "start_date": start_date,
            "end_date": end_date,
            "channels": channel_summaries,
            "grand_total_fen": grand_total_fen,
            "total_transactions": total_transactions,
        },
    }


# ─── GET /payment-details ─────────────────────────────────────────────────────


@router.get(
    "/payment-details",
    summary="逐笔支付明细",
    description="分页查询逐笔支付记录，支持渠道/门店/收银员过滤。",
)
async def get_payment_details(
    start_date: str = Query(..., description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    channel: Optional[str] = Query(None, description="支付渠道（可选）"),
    store_id: Optional[str] = Query(None, description="门店 ID（可选）"),
    cashier_id: Optional[str] = Query(None, description="收银员 ID（可选）"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_validate_tenant_id),
):
    d_start, d_end = _validate_date_range(start_date, end_date)

    if channel and channel not in CHANNEL_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"channel 无效，合法值：{', '.join(CHANNEL_NAMES.keys())}",
        )

    where_parts = ["p.paid_at::date BETWEEN :start_date AND :end_date"]
    params: dict = {"start_date": d_start, "end_date": d_end}

    if channel:
        where_parts.append("p.channel = :channel")
        params["channel"] = channel
    if store_id:
        _validate_uuid(store_id, "store_id")
        where_parts.append("p.store_id = :store_id")
        params["store_id"] = store_id
    if cashier_id:
        _validate_uuid(cashier_id, "cashier_id")
        where_parts.append("p.cashier_id = :cashier_id")
        params["cashier_id"] = cashier_id

    where_clause = " AND ".join(where_parts)

    count_sql = text(f"SELECT COUNT(*) FROM payments p WHERE {where_clause}")
    count_result = await db.execute(count_sql, params)
    total = count_result.scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    sql = text(f"""
        SELECT p.id AS payment_id, p.order_id, p.channel, p.amount_fen,
               p.paid_at, e.name AS cashier_name, s.name AS store_name
        FROM payments p
        LEFT JOIN employees e ON p.cashier_id = e.id
        LEFT JOIN stores s ON p.store_id = s.id
        WHERE {where_clause}
        ORDER BY p.paid_at DESC LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(sql, params)
    rows = result.fetchall()

    items = [
        {
            "payment_id": str(row.payment_id),
            "order_id": str(row.order_id),
            "channel": str(row.channel) if row.channel else "other",
            "amount_fen": int(row.amount_fen),
            "paid_at": row.paid_at.isoformat() if row.paid_at else "",
            "cashier_name": row.cashier_name or "未知",
            "store_name": row.store_name or "未知",
        }
        for row in rows
    ]

    logger.info("payment_details.ok", tenant_id=tenant_id, total=total, page=page)

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


# ─── GET /cashier-receipts ────────────────────────────────────────────────────


@router.get(
    "/cashier-receipts",
    summary="收银员收款统计",
    description="按收银员分组汇总收款，含班次数/总金额/渠道明细。",
)
async def get_cashier_receipts(
    start_date: str = Query(..., description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    store_id: Optional[str] = Query(None, description="门店 ID（可选）"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_validate_tenant_id),
):
    d_start, d_end = _validate_date_range(start_date, end_date)

    sql_parts = [
        "SELECT p.cashier_id,",
        "       e.name AS cashier_name,",
        "       COUNT(DISTINCT p.shift_id) AS shift_count,",
        "       COALESCE(SUM(p.amount_fen), 0) AS total_amount_fen,",
        "       COUNT(*) AS order_count,",
        "       COALESCE(SUM(CASE WHEN p.channel='wechat'      THEN p.amount_fen ELSE 0 END), 0) AS wechat_fen,",
        "       COALESCE(SUM(CASE WHEN p.channel='alipay'      THEN p.amount_fen ELSE 0 END), 0) AS alipay_fen,",
        "       COALESCE(SUM(CASE WHEN p.channel='cash'        THEN p.amount_fen ELSE 0 END), 0) AS cash_fen,",
        "       COALESCE(SUM(CASE WHEN p.channel='card'        THEN p.amount_fen ELSE 0 END), 0) AS card_fen,",
        "       COALESCE(SUM(CASE WHEN p.channel='member_card' THEN p.amount_fen ELSE 0 END), 0) AS member_card_fen,",
        "       COALESCE(SUM(CASE WHEN p.channel NOT IN ('wechat','alipay','cash','card','member_card') THEN p.amount_fen ELSE 0 END), 0) AS other_fen",
        "FROM payments p",
        "LEFT JOIN employees e ON p.cashier_id = e.id",
        "WHERE p.paid_at::date BETWEEN :start_date AND :end_date",
    ]
    params: dict = {"start_date": d_start, "end_date": d_end}

    if store_id:
        _validate_uuid(store_id, "store_id")
        sql_parts.append("AND p.store_id = :store_id")
        params["store_id"] = store_id

    sql_parts.append("GROUP BY p.cashier_id, e.name ORDER BY total_amount_fen DESC")
    sql = text(" ".join(sql_parts))
    result = await db.execute(sql, params)
    rows = result.fetchall()

    cashiers: list[dict] = []
    for row in rows:
        cashiers.append(
            {
                "cashier_id": str(row.cashier_id) if row.cashier_id else "unknown",
                "cashier_name": row.cashier_name or "未知",
                "shift_count": int(row.shift_count),
                "total_amount_fen": int(row.total_amount_fen),
                "order_count": int(row.order_count),
                "channel_breakdown": {
                    "wechat": int(row.wechat_fen),
                    "alipay": int(row.alipay_fen),
                    "cash": int(row.cash_fen),
                    "card": int(row.card_fen),
                    "member_card": int(row.member_card_fen),
                    "other": int(row.other_fen),
                },
            }
        )

    logger.info("cashier_receipts.ok", tenant_id=tenant_id, cashier_count=len(cashiers))

    return {
        "ok": True,
        "data": {
            "start_date": start_date,
            "end_date": end_date,
            "cashiers": cashiers,
        },
    }


# ─── GET /crm-reconciliation ──────────────────────────────────────────────────


@router.get(
    "/crm-reconciliation",
    summary="CRM 储值卡对账",
    description="比对会员储值充值/消费（CRM）与财务系统支付记录，返回差异列表。",
)
async def get_crm_reconciliation(
    start_date: str = Query(..., description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    store_id: Optional[str] = Query(None, description="门店 ID（可选）"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_validate_tenant_id),
):
    """CRM 储值卡对账 — 比对 stored_value_transactions 与 payments(member_card)。"""
    d_start, d_end = _validate_date_range(start_date, end_date)

    store_filter = ""
    params: dict = {"start_date": d_start, "end_date": d_end}
    if store_id:
        _validate_uuid(store_id, "store_id")
        store_filter = "AND svt.store_id = :store_id"
        params["store_id"] = store_id

    # 按会员聚合: CRM侧(stored_value_transactions) vs 财务侧(payments where channel=member_card)
    sql = text(f"""
        WITH crm_side AS (
            SELECT
                svt.member_id,
                svt.type,
                COALESCE(SUM(svt.amount_fen), 0) AS crm_total_fen
            FROM stored_value_transactions svt
            WHERE svt.created_at::date BETWEEN :start_date AND :end_date
              {store_filter}
            GROUP BY svt.member_id, svt.type
        ),
        finance_side AS (
            SELECT
                p.member_id,
                CASE WHEN p.amount_fen >= 0 THEN 'recharge' ELSE 'consume' END AS type,
                COALESCE(SUM(ABS(p.amount_fen)), 0) AS finance_total_fen
            FROM payments p
            WHERE p.channel = 'member_card'
              AND p.paid_at::date BETWEEN :start_date AND :end_date
            GROUP BY p.member_id, CASE WHEN p.amount_fen >= 0 THEN 'recharge' ELSE 'consume' END
        )
        SELECT
            COALESCE(c.member_id, f.member_id) AS member_id,
            COALESCE(c.type, f.type) AS txn_type,
            COALESCE(c.crm_total_fen, 0) AS crm_amount_fen,
            COALESCE(f.finance_total_fen, 0) AS finance_amount_fen,
            COALESCE(c.crm_total_fen, 0) - COALESCE(f.finance_total_fen, 0) AS diff_fen
        FROM crm_side c
        FULL OUTER JOIN finance_side f ON c.member_id = f.member_id AND c.type = f.type
        WHERE COALESCE(c.crm_total_fen, 0) != COALESCE(f.finance_total_fen, 0)
        ORDER BY ABS(COALESCE(c.crm_total_fen, 0) - COALESCE(f.finance_total_fen, 0)) DESC
        LIMIT 100
    """)
    result = await db.execute(sql, params)
    mismatch_rows = result.fetchall()

    # 总匹配数
    match_sql = text(f"""
        WITH crm_side AS (
            SELECT member_id, type, COALESCE(SUM(amount_fen), 0) AS total
            FROM stored_value_transactions
            WHERE created_at::date BETWEEN :start_date AND :end_date
            {store_filter}
            GROUP BY member_id, type
        ),
        finance_side AS (
            SELECT member_id,
                   CASE WHEN amount_fen >= 0 THEN 'recharge' ELSE 'consume' END AS type,
                   COALESCE(SUM(ABS(amount_fen)), 0) AS total
            FROM payments WHERE channel = 'member_card'
              AND paid_at::date BETWEEN :start_date AND :end_date
            GROUP BY member_id, CASE WHEN amount_fen >= 0 THEN 'recharge' ELSE 'consume' END
        )
        SELECT COUNT(*) FROM crm_side c
        JOIN finance_side f ON c.member_id = f.member_id AND c.type = f.type
        WHERE c.total = f.total
    """)
    match_result = await db.execute(match_sql, params)
    match_count = match_result.scalar() or 0

    mismatch_items = []
    for row in mismatch_rows:
        m = row._mapping
        mismatch_items.append(
            {
                "member_id": str(m["member_id"]) if m["member_id"] else "unknown",
                "crm_amount_fen": int(m["crm_amount_fen"]),
                "finance_amount_fen": int(m["finance_amount_fen"]),
                "diff_fen": int(m["diff_fen"]),
                "type": m["txn_type"] or "unknown",
            }
        )

    total_diff_fen = sum(abs(item["diff_fen"]) for item in mismatch_items)

    logger.info(
        "crm_reconciliation.ok",
        tenant_id=tenant_id,
        match_count=match_count,
        mismatch_count=len(mismatch_items),
    )

    return {
        "ok": True,
        "data": {
            "start_date": start_date,
            "end_date": end_date,
            "match_count": match_count,
            "mismatch_count": len(mismatch_items),
            "total_diff_fen": total_diff_fen,
            "mismatch_items": mismatch_items,
        },
    }
