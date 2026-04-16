"""押金管理 API 路由

端点：
  POST /api/v1/deposits/                        — 收取押金
  POST /api/v1/deposits/{id}/apply              — 押金抵扣消费（关联 order_id）
  POST /api/v1/deposits/{id}/refund             — 退还押金
  POST /api/v1/deposits/{id}/convert            — 押金转收入
  GET  /api/v1/deposits/{id}                    — 押金详情
  GET  /api/v1/deposits/store/{store_id}        — 门店押金列表
  GET  /api/v1/deposits/report/ledger           — 押金台账报表
  GET  /api/v1/deposits/report/aging            — 押金账龄分析
  GET  /api/v1/deposits/report/shift-summary    — 结班押金汇总
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import DepositEventType
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/deposits", tags=["押金管理"])


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _serialize_row(row: dict) -> dict:
    """统一序列化：UUID → str，datetime → isoformat。"""
    result = {}
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


# ─── 依赖注入 ──────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── 请求/响应模型 ─────────────────────────────────────────────────────────────

class DepositCreate(BaseModel):
    store_id: uuid.UUID
    customer_id: Optional[uuid.UUID] = None
    reservation_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    amount_fen: int                      # 押金金额（分）
    payment_method: str                  # wechat/alipay/cash/card
    payment_ref: Optional[str] = None   # 支付流水号
    expires_days: int = 30              # 有效期天数，默认 30 天
    remark: Optional[str] = None


class DepositApply(BaseModel):
    order_id: uuid.UUID
    apply_amount_fen: int               # 本次抵扣金额（分）
    remark: Optional[str] = None


class DepositRefund(BaseModel):
    refund_amount_fen: int              # 本次退还金额（分）
    remark: Optional[str] = None


class DepositConvert(BaseModel):
    remark: Optional[str] = None


# ─── POST / — 收取押金 ────────────────────────────────────────────────────────

@router.post("/", summary="收取押金")
async def collect_deposit(
    body: DepositCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """收取押金，生成押金台账记录。押金可关联预订、订单或匿名收取。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")

    if body.amount_fen <= 0:
        raise HTTPException(status_code=400, detail="押金金额必须大于0")

    valid_methods = {"wechat", "alipay", "cash", "card"}
    if body.payment_method not in valid_methods:
        raise HTTPException(
            status_code=400,
            detail=f"payment_method 必须是: {', '.join(valid_methods)}",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)

    try:
        result = await db.execute(
            text("""
                INSERT INTO biz_deposits (
                    tenant_id, store_id, customer_id, reservation_id, order_id,
                    amount_fen, applied_amount_fen, refunded_amount_fen,
                    status, payment_method, payment_ref,
                    collected_at, expires_at, operator_id, remark
                ) VALUES (
                    :tenant_id::UUID, :store_id::UUID,
                    :customer_id::UUID, :reservation_id::UUID, :order_id::UUID,
                    :amount_fen, 0, 0,
                    'collected', :payment_method, :payment_ref,
                    NOW(), :expires_at, :operator_id::UUID, :remark
                )
                RETURNING id, status, collected_at, expires_at
            """),
            {
                "tenant_id": str(tid),
                "store_id": str(body.store_id),
                "customer_id": str(body.customer_id) if body.customer_id else None,
                "reservation_id": str(body.reservation_id) if body.reservation_id else None,
                "order_id": str(body.order_id) if body.order_id else None,
                "amount_fen": body.amount_fen,
                "payment_method": body.payment_method,
                "payment_ref": body.payment_ref,
                "expires_at": expires_at,
                "operator_id": str(op_id),
                "remark": body.remark,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("collect_deposit.failed", store_id=str(body.store_id),
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="押金收取失败") from exc

    deposit_id = str(row["id"])
    logger.info("deposit_collected", deposit_id=deposit_id,
                amount_fen=body.amount_fen, store_id=str(body.store_id))

    asyncio.create_task(emit_event(
        event_type=DepositEventType.COLLECTED,
        tenant_id=tid,
        stream_id=deposit_id,
        payload={
            "deposit_id": deposit_id,
            "amount_fen": body.amount_fen,
            "store_id": str(body.store_id),
            "customer_id": str(body.customer_id) if body.customer_id else None,
            "payment_method": body.payment_method,
        },
        store_id=body.store_id,
        source_service="tx-finance",
        metadata={"operator_id": str(op_id)},
    ))

    return {
        "ok": True,
        "data": {
            "deposit_id": deposit_id,
            "status": row["status"],
            "amount_fen": body.amount_fen,
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "collected_at": row["collected_at"].isoformat() if row["collected_at"] else None,
        },
        "error": None,
    }


# ─── POST /{id}/apply — 押金抵扣 ──────────────────────────────────────────────

@router.post("/{deposit_id}/apply", summary="押金抵扣消费")
async def apply_deposit(
    deposit_id: str = Path(..., description="押金ID"),
    body: DepositApply = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """将押金抵扣消费，更新已抵扣金额，若全部抵扣则状态变更为 fully_applied。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    did = _parse_uuid(deposit_id, "deposit_id")

    if body.apply_amount_fen <= 0:
        raise HTTPException(status_code=400, detail="抵扣金额必须大于0")

    try:
        # 查询当前押金状态
        fetch = await db.execute(
            text("""
                SELECT id, amount_fen, applied_amount_fen, refunded_amount_fen, status
                FROM biz_deposits
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(did), "tenant_id": str(tid)},
        )
        deposit = fetch.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("apply_deposit.fetch_failed", deposit_id=deposit_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询押金失败") from exc

    if deposit is None:
        raise HTTPException(status_code=404, detail=f"押金不存在: {deposit_id}")

    if deposit["status"] in ("refunded", "fully_applied", "written_off"):
        raise HTTPException(
            status_code=409,
            detail=f"押金状态 {deposit['status']} 不允许继续抵扣",
        )

    remaining = (
        deposit["amount_fen"]
        - deposit["applied_amount_fen"]
        - deposit["refunded_amount_fen"]
    )
    if body.apply_amount_fen > remaining:
        raise HTTPException(
            status_code=400,
            detail=f"抵扣金额 {body.apply_amount_fen} 超过可用余额 {remaining}（分）",
        )

    new_applied = deposit["applied_amount_fen"] + body.apply_amount_fen
    new_remaining = deposit["amount_fen"] - new_applied - deposit["refunded_amount_fen"]
    new_status = "fully_applied" if new_remaining == 0 else "partially_applied"

    try:
        result = await db.execute(
            text("""
                UPDATE biz_deposits
                SET applied_amount_fen = :new_applied,
                    status = :new_status,
                    order_id = COALESCE(order_id, :order_id::UUID),
                    updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                RETURNING id, status, applied_amount_fen, amount_fen, refunded_amount_fen
            """),
            {
                "new_applied": new_applied,
                "new_status": new_status,
                "order_id": str(body.order_id),
                "id": str(did),
                "tenant_id": str(tid),
            },
        )
        row = result.mappings().first()
        await db.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("apply_deposit.update_failed", deposit_id=deposit_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="押金抵扣失败") from exc

    logger.info("deposit_applied", deposit_id=deposit_id,
                apply_amount_fen=body.apply_amount_fen, order_id=str(body.order_id))

    asyncio.create_task(emit_event(
        event_type=DepositEventType.APPLIED,
        tenant_id=tid,
        stream_id=deposit_id,
        payload={
            "deposit_id": deposit_id,
            "applied_amount_fen": body.apply_amount_fen,
            "order_id": str(body.order_id),
            "new_status": new_status,
        },
        source_service="tx-finance",
        metadata={"operator_id": str(op_id)},
    ))

    return {
        "ok": True,
        "data": {
            "deposit_id": deposit_id,
            "status": row["status"],
            "amount_fen": row["amount_fen"],
            "applied_amount_fen": row["applied_amount_fen"],
            "refunded_amount_fen": row["refunded_amount_fen"],
            "remaining_fen": (
                row["amount_fen"]
                - row["applied_amount_fen"]
                - row["refunded_amount_fen"]
            ),
        },
        "error": None,
    }


# ─── POST /{id}/refund — 退还押金 ─────────────────────────────────────────────

@router.post("/{deposit_id}/refund", summary="退还押金")
async def refund_deposit(
    deposit_id: str = Path(..., description="押金ID"),
    body: DepositRefund = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """退还押金给客户，支持部分退还，全部退还后状态变更为 refunded。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    did = _parse_uuid(deposit_id, "deposit_id")

    if body.refund_amount_fen <= 0:
        raise HTTPException(status_code=400, detail="退还金额必须大于0")

    try:
        fetch = await db.execute(
            text("""
                SELECT id, amount_fen, applied_amount_fen, refunded_amount_fen, status
                FROM biz_deposits
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(did), "tenant_id": str(tid)},
        )
        deposit = fetch.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("refund_deposit.fetch_failed", deposit_id=deposit_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询押金失败") from exc

    if deposit is None:
        raise HTTPException(status_code=404, detail=f"押金不存在: {deposit_id}")

    if deposit["status"] in ("refunded", "fully_applied", "converted", "written_off"):
        raise HTTPException(
            status_code=409,
            detail=f"押金状态 {deposit['status']} 不允许退还",
        )

    remaining = (
        deposit["amount_fen"]
        - deposit["applied_amount_fen"]
        - deposit["refunded_amount_fen"]
    )
    if body.refund_amount_fen > remaining:
        raise HTTPException(
            status_code=400,
            detail=f"退还金额 {body.refund_amount_fen} 超过可用余额 {remaining}（分）",
        )

    new_refunded = deposit["refunded_amount_fen"] + body.refund_amount_fen
    new_remaining = deposit["amount_fen"] - deposit["applied_amount_fen"] - new_refunded
    new_status = "refunded" if new_remaining == 0 else deposit["status"]

    try:
        result = await db.execute(
            text("""
                UPDATE biz_deposits
                SET refunded_amount_fen = :new_refunded,
                    status = :new_status,
                    updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                RETURNING id, status, refunded_amount_fen, amount_fen, applied_amount_fen
            """),
            {
                "new_refunded": new_refunded,
                "new_status": new_status,
                "id": str(did),
                "tenant_id": str(tid),
            },
        )
        row = result.mappings().first()
        await db.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("refund_deposit.update_failed", deposit_id=deposit_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="押金退还失败") from exc

    logger.info("deposit_refunded", deposit_id=deposit_id,
                refund_amount_fen=body.refund_amount_fen)

    asyncio.create_task(emit_event(
        event_type=DepositEventType.REFUNDED,
        tenant_id=tid,
        stream_id=deposit_id,
        payload={
            "deposit_id": deposit_id,
            "refund_amount_fen": body.refund_amount_fen,
            "new_status": new_status,
            "remark": body.remark,
        },
        source_service="tx-finance",
        metadata={"operator_id": str(op_id)},
    ))

    return {
        "ok": True,
        "data": {
            "deposit_id": deposit_id,
            "status": row["status"],
            "amount_fen": row["amount_fen"],
            "applied_amount_fen": row["applied_amount_fen"],
            "refunded_amount_fen": row["refunded_amount_fen"],
            "remaining_fen": (
                row["amount_fen"]
                - row["applied_amount_fen"]
                - row["refunded_amount_fen"]
            ),
        },
        "error": None,
    }


# ─── POST /{id}/convert — 押金转收入 ──────────────────────────────────────────

@router.post("/{deposit_id}/convert", summary="押金转收入")
async def convert_deposit(
    deposit_id: str = Path(..., description="押金ID"),
    body: DepositConvert = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """将押金余额转为餐厅收入（不可撤销），通常在押金过期或客户放弃时操作。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    did = _parse_uuid(deposit_id, "deposit_id")

    try:
        fetch = await db.execute(
            text("""
                SELECT id, amount_fen, applied_amount_fen, refunded_amount_fen, status
                FROM biz_deposits
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(did), "tenant_id": str(tid)},
        )
        deposit = fetch.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("convert_deposit.fetch_failed", deposit_id=deposit_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询押金失败") from exc

    if deposit is None:
        raise HTTPException(status_code=404, detail=f"押金不存在: {deposit_id}")

    if deposit["status"] in ("refunded", "converted", "written_off"):
        raise HTTPException(
            status_code=409,
            detail=f"押金状态 {deposit['status']} 不允许转收入",
        )

    remaining = (
        deposit["amount_fen"]
        - deposit["applied_amount_fen"]
        - deposit["refunded_amount_fen"]
    )
    if remaining <= 0:
        raise HTTPException(status_code=400, detail="押金余额为0，无需转收入")

    try:
        result = await db.execute(
            text("""
                UPDATE biz_deposits
                SET status = 'converted',
                    updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                RETURNING id, status, amount_fen, applied_amount_fen, refunded_amount_fen
            """),
            {"id": str(did), "tenant_id": str(tid)},
        )
        row = result.mappings().first()
        await db.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("convert_deposit.update_failed", deposit_id=deposit_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="押金转收入失败") from exc

    logger.info("deposit_converted", deposit_id=deposit_id, converted_fen=remaining)

    asyncio.create_task(emit_event(
        event_type=DepositEventType.CONVERTED_TO_REVENUE,
        tenant_id=tid,
        stream_id=deposit_id,
        payload={
            "deposit_id": deposit_id,
            "converted_amount_fen": remaining,
            "remark": body.remark,
        },
        source_service="tx-finance",
        metadata={"operator_id": str(op_id)},
    ))

    return {
        "ok": True,
        "data": {
            "deposit_id": deposit_id,
            "status": row["status"],
            "converted_amount_fen": remaining,
        },
        "error": None,
    }


# ─── GET /{id} — 押金详情 ─────────────────────────────────────────────────────

@router.get("/{deposit_id}", summary="押金详情")
async def get_deposit(
    deposit_id: str = Path(..., description="押金ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取单笔押金的完整详情。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    did = _parse_uuid(deposit_id, "deposit_id")

    try:
        result = await db.execute(
            text("""
                SELECT id, store_id, customer_id, reservation_id, order_id,
                       amount_fen, applied_amount_fen, refunded_amount_fen,
                       (amount_fen - applied_amount_fen - refunded_amount_fen) AS remaining_fen,
                       status, payment_method, payment_ref,
                       collected_at, expires_at, operator_id, remark,
                       created_at, updated_at
                FROM biz_deposits
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(did), "tenant_id": str(tid)},
        )
        row = result.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("get_deposit.failed", deposit_id=deposit_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询押金失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"押金不存在: {deposit_id}")

    return {"ok": True, "data": _serialize_row(dict(row)), "error": None}


# ─── GET /store/{store_id} — 门店押金列表 ────────────────────────────────────

@router.get("/store/{store_id}", summary="门店押金列表")
async def list_by_store(
    store_id: str = Path(..., description="门店ID"),
    status: Optional[str] = Query(None, description="状态筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """返回指定门店的押金列表，支持按状态筛选，分页返回。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    where_clauses = ["tenant_id = :tenant_id::UUID", "store_id = :store_id::UUID"]
    params: dict = {"tenant_id": str(tid), "store_id": str(sid)}

    if status:
        valid_statuses = {
            "collected", "partially_applied", "fully_applied",
            "refunded", "converted", "written_off",
        }
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
            text(f"SELECT COUNT(*) FROM biz_deposits WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, customer_id, reservation_id, order_id,
                       amount_fen, applied_amount_fen, refunded_amount_fen,
                       (amount_fen - applied_amount_fen - refunded_amount_fen) AS remaining_fen,
                       status, payment_method, collected_at, expires_at, operator_id
                FROM biz_deposits
                WHERE {where_sql}
                ORDER BY collected_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(dict(row)) for row in items_result.mappings().all()]
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("list_deposits_by_store.failed", store_id=store_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询门店押金列表失败") from exc

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── GET /report/ledger — 押金台账 ───────────────────────────────────────────

@router.get("/report/ledger", summary="押金台账报表")
async def ledger_report(
    store_id: str = Query(..., description="门店ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """押金台账：按时间段汇总门店押金收取、抵扣、退还、转收入金额。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    try:
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_count,
                    COALESCE(SUM(amount_fen), 0) AS total_collected_fen,
                    COALESCE(SUM(applied_amount_fen), 0) AS total_applied_fen,
                    COALESCE(SUM(refunded_amount_fen), 0) AS total_refunded_fen,
                    COALESCE(SUM(
                        CASE WHEN status = 'converted'
                        THEN amount_fen - applied_amount_fen - refunded_amount_fen
                        ELSE 0 END
                    ), 0) AS total_converted_fen,
                    COALESCE(SUM(
                        CASE WHEN status NOT IN ('refunded', 'fully_applied', 'converted', 'written_off')
                        THEN amount_fen - applied_amount_fen - refunded_amount_fen
                        ELSE 0 END
                    ), 0) AS total_outstanding_fen
                FROM biz_deposits
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND collected_at >= :start_date::DATE
                  AND collected_at < (:end_date::DATE + INTERVAL '1 day')
            """),
            {
                "tenant_id": str(tid),
                "store_id": str(sid),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("deposit_ledger_report.failed", store_id=store_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="押金台账报表生成失败") from exc

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "start_date": start_date,
            "end_date": end_date,
            **dict(row),
        },
        "error": None,
    }


# ─── GET /report/aging — 押金账龄分析 ────────────────────────────────────────

@router.get("/report/aging", summary="押金账龄分析")
async def aging_report(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """按账龄分层统计未结押金数量和金额（0-7天 / 8-30天 / 31-90天 / 90天以上）。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    try:
        result = await db.execute(
            text("""
                SELECT
                    SUM(CASE WHEN age_days <= 7 THEN 1 ELSE 0 END) AS cnt_0_7d,
                    COALESCE(SUM(CASE WHEN age_days <= 7 THEN remaining_fen ELSE 0 END), 0) AS amt_0_7d,
                    SUM(CASE WHEN age_days BETWEEN 8 AND 30 THEN 1 ELSE 0 END) AS cnt_8_30d,
                    COALESCE(SUM(CASE WHEN age_days BETWEEN 8 AND 30 THEN remaining_fen ELSE 0 END), 0) AS amt_8_30d,
                    SUM(CASE WHEN age_days BETWEEN 31 AND 90 THEN 1 ELSE 0 END) AS cnt_31_90d,
                    COALESCE(SUM(CASE WHEN age_days BETWEEN 31 AND 90 THEN remaining_fen ELSE 0 END), 0) AS amt_31_90d,
                    SUM(CASE WHEN age_days > 90 THEN 1 ELSE 0 END) AS cnt_over_90d,
                    COALESCE(SUM(CASE WHEN age_days > 90 THEN remaining_fen ELSE 0 END), 0) AS amt_over_90d
                FROM (
                    SELECT
                        EXTRACT(DAY FROM NOW() - collected_at)::INTEGER AS age_days,
                        (amount_fen - applied_amount_fen - refunded_amount_fen) AS remaining_fen
                    FROM biz_deposits
                    WHERE tenant_id = :tenant_id::UUID
                      AND store_id = :store_id::UUID
                      AND status NOT IN ('refunded', 'fully_applied', 'converted', 'written_off')
                      AND (amount_fen - applied_amount_fen - refunded_amount_fen) > 0
                ) aged
            """),
            {"tenant_id": str(tid), "store_id": str(sid)},
        )
        row = result.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("deposit_aging_report.failed", store_id=store_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="押金账龄分析失败") from exc

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "aging": {
                "0_7_days":   {"count": row["cnt_0_7d"],    "amount_fen": row["amt_0_7d"]},
                "8_30_days":  {"count": row["cnt_8_30d"],   "amount_fen": row["amt_8_30d"]},
                "31_90_days": {"count": row["cnt_31_90d"],  "amount_fen": row["amt_31_90d"]},
                "over_90_days": {"count": row["cnt_over_90d"], "amount_fen": row["amt_over_90d"]},
            },
        },
        "error": None,
    }


# ─── GET /report/shift-summary — 结班押金汇总 ────────────────────────────────

@router.get("/report/shift-summary", summary="结班押金汇总")
async def shift_summary_report(
    store_id: str = Query(..., description="门店ID"),
    shift_date: date = Query(default_factory=date.today, description="班次日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """结班押金汇总：本班收押金 / 退押金 / 净留存。
    班次定义为当天 00:00 至 23:59:59（北京时间，Asia/Shanghai）。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    try:
        import zoneinfo
        cst = zoneinfo.ZoneInfo("Asia/Shanghai")
    except (ImportError, KeyError):
        cst = timezone(timedelta(hours=8))

    shift_start = datetime(shift_date.year, shift_date.month, shift_date.day,
                           0, 0, 0, tzinfo=cst).astimezone(timezone.utc)
    shift_end = datetime(shift_date.year, shift_date.month, shift_date.day,
                         23, 59, 59, tzinfo=cst).astimezone(timezone.utc)

    try:
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE collected_at >= :start AND collected_at <= :end_ts)
                        AS received_count,
                    COALESCE(SUM(amount_fen) FILTER (
                        WHERE collected_at >= :start AND collected_at <= :end_ts
                    ), 0) AS received_fen,
                    COUNT(*) FILTER (
                        WHERE refunded_amount_fen > 0
                          AND updated_at >= :start AND updated_at <= :end_ts
                    ) AS refunded_count,
                    COALESCE(SUM(refunded_amount_fen) FILTER (
                        WHERE refunded_amount_fen > 0
                          AND updated_at >= :start AND updated_at <= :end_ts
                    ), 0) AS refunded_fen
                FROM biz_deposits
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
            """),
            {
                "tenant_id": str(tid),
                "store_id": str(sid),
                "start": shift_start,
                "end_ts": shift_end,
            },
        )
        row = result.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.error("shift_summary_report.failed", store_id=store_id,
                     shift_date=str(shift_date), error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="结班押金汇总失败") from exc

    received_fen = int(row["received_fen"] or 0)
    refunded_fen = int(row["refunded_fen"] or 0)
    net_fen = received_fen - refunded_fen

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "shift_date": str(shift_date),
            "received_count": int(row["received_count"] or 0),
            "received_fen": received_fen,
            "refunded_count": int(row["refunded_count"] or 0),
            "refunded_fen": refunded_fen,
            "net_fen": net_fen,
        },
        "error": None,
    }
