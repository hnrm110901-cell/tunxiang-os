"""聚合支付/分账 API 路由 — Y-B2

端点清单（prefix: /api/v1/finance/split）：
  POST   /orders                      发起分账（从订单触发）
  GET    /orders                      分账订单列表
  GET    /orders/{id}                 分账订单详情
  POST   /orders/{id}/notify          接收微信/支付宝异步分账通知（验签mock）
  GET    /orders/{id}/records         分账明细
  POST   /adjustments                 差错账人工调账
  GET    /adjustments                 调账记录列表
  GET    /rules/preview               试算分润（按加盟商/品牌比例）

幂等机制：split_payment_records.idempotency_key = sha256(split_order_id + receiver_id)
异步通知验签（mock）：检查 X-Wechat-Pay-Signature 或 X-Alipay-Sign，非空即通过。
生产环境替换：使用微信/支付宝官方 SDK 验签逻辑。
"""
import hashlib
import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/finance/split", tags=["split-payment"])


# ── 依赖 ──────────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID 格式无效",
        )


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _make_idempotency_key(split_order_id: str, receiver_id: str) -> str:
    """生成幂等键：sha256(split_order_id + receiver_id)。"""
    raw = f"{split_order_id}:{receiver_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Pydantic Schema ────────────────────────────────────────────────────────────

class SplitReceiverItem(BaseModel):
    """单个收款方分账规则。"""
    receiver_type: str = Field(..., pattern=r'^(brand|franchise|platform_fee)$')
    receiver_id: str = Field(..., max_length=64, description="收款方标识")
    amount_fen: int = Field(..., gt=0, description="分账金额（分）")
    channel_sub_merchant_id: Optional[str] = Field(None, max_length=64)


class CreateSplitOrderBody(BaseModel):
    """发起分账请求体。"""
    order_id: uuid.UUID
    total_fen: int = Field(..., gt=0, description="总金额（分）")
    channel: str = Field(..., pattern=r'^(wechat|alipay)$')
    merchant_order_id: str = Field(..., max_length=64, description="渠道侧商户订单号，全局唯一")
    receivers: list[SplitReceiverItem] = Field(..., min_length=1, description="分账明细列表")


class AsyncNotifyBody(BaseModel):
    """异步分账通知请求体（微信/支付宝回调 payload）。"""
    notify_id: str = Field(..., max_length=64, description="渠道通知ID")
    split_result: str = Field(..., pattern=r'^(success|failed)$')
    receiver_id: Optional[str] = Field(None, max_length=64)
    extra: Optional[dict[str, Any]] = None


class AdjustmentCreateBody(BaseModel):
    """差错账调账请求体。"""
    split_record_id: uuid.UUID
    reason: str = Field(..., max_length=500)
    adjusted_amount_fen: int = Field(..., gt=0, description="调整后金额（分）")
    adjusted_by: str = Field(..., max_length=64, description="操作人 ID 或邮箱")


class PreviewSplitRuleItem(BaseModel):
    """试算分润规则。"""
    receiver_type: str = Field(..., pattern=r'^(brand|franchise|platform_fee)$')
    receiver_id: str = Field(..., max_length=64)
    ratio: int = Field(..., ge=1, le=10000, description="分润比例（万分比，10000=100%）")


class PreviewSplitBody(BaseModel):
    """试算分润请求体。"""
    total_fen: int = Field(..., gt=0)
    split_rules: list[PreviewSplitRuleItem] = Field(..., min_length=1)


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_split_order(
    body: CreateSplitOrderBody,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """发起分账订单，同时写入分账主表和明细表（幂等：merchant_order_id唯一）。"""
    from sqlalchemy import text
    import json

    # 校验各方金额之和不超过总金额
    total_split = sum(r.amount_fen for r in body.receivers)
    if total_split > body.total_fen:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"各方分账金额之和 {total_split} 超过总金额 {body.total_fen}",
        )

    split_order_id = uuid.uuid4()
    try:
        # 写分账主表
        await db.execute(
            text("""
                INSERT INTO split_payment_orders (
                    id, tenant_id, order_id, total_fen, channel,
                    merchant_order_id, split_status, split_count
                ) VALUES (
                    :id, :tenant_id, :order_id, :total_fen, :channel,
                    :merchant_order_id, 'splitting', :split_count
                )
            """),
            {
                "id": str(split_order_id),
                "tenant_id": str(tenant_id),
                "order_id": str(body.order_id),
                "total_fen": body.total_fen,
                "channel": body.channel,
                "merchant_order_id": body.merchant_order_id,
                "split_count": len(body.receivers),
            },
        )

        # 写分账明细（逐条插入，幂等键防重）
        for receiver in body.receivers:
            idem_key = _make_idempotency_key(str(split_order_id), receiver.receiver_id)
            record_id = uuid.uuid4()
            await db.execute(
                text("""
                    INSERT INTO split_payment_records (
                        id, split_order_id, tenant_id, receiver_type, receiver_id,
                        amount_fen, channel_sub_merchant_id, split_result, idempotency_key
                    ) VALUES (
                        :id, :split_order_id, :tenant_id, :receiver_type, :receiver_id,
                        :amount_fen, :channel_sub_merchant_id, 'pending', :idempotency_key
                    )
                    ON CONFLICT (idempotency_key) DO NOTHING
                """),
                {
                    "id": str(record_id),
                    "split_order_id": str(split_order_id),
                    "tenant_id": str(tenant_id),
                    "receiver_type": receiver.receiver_type,
                    "receiver_id": receiver.receiver_id,
                    "amount_fen": receiver.amount_fen,
                    "channel_sub_merchant_id": receiver.channel_sub_merchant_id,
                    "idempotency_key": idem_key,
                },
            )

        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("split_order_duplicate", merchant_order_id=body.merchant_order_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"merchant_order_id={body.merchant_order_id} 已存在，请勿重复发起",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("split_order_create_error", error=str(exc))
        raise HTTPException(status_code=500, detail="发起分账失败") from exc

    logger.info(
        "split_order_created",
        split_order_id=str(split_order_id),
        merchant_order_id=body.merchant_order_id,
        tenant_id=str(tenant_id),
    )
    return _ok({
        "split_order_id": str(split_order_id),
        "merchant_order_id": body.merchant_order_id,
        "split_status": "splitting",
        "split_count": len(body.receivers),
    })


@router.get("/orders")
async def list_split_orders(
    split_status: Optional[str] = Query(None, description="pending/splitting/completed/failed"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """分账订单列表。"""
    from sqlalchemy import text

    where_clause = "tenant_id = :tenant_id AND is_deleted = false"
    params: dict[str, Any] = {"tenant_id": str(tenant_id)}

    if split_status:
        where_clause += " AND split_status = :split_status"
        params["split_status"] = split_status

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM split_payment_orders WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        rows_result = await db.execute(
            text(
                f"SELECT * FROM split_payment_orders WHERE {where_clause} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = [dict(r._mapping) for r in rows_result]
    except SQLAlchemyError as exc:
        logger.error("split_orders_list_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询分账订单失败") from exc

    return _ok({"items": rows, "total": total, "page": page, "size": size})


@router.get("/orders/{split_order_id}")
async def get_split_order(
    split_order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """分账订单详情。"""
    from sqlalchemy import text

    try:
        result = await db.execute(
            text("""
                SELECT * FROM split_payment_orders
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": str(split_order_id), "tenant_id": str(tenant_id)},
        )
        row = result.fetchone()
    except SQLAlchemyError as exc:
        logger.error("split_order_get_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询分账订单失败") from exc

    if not row:
        raise HTTPException(status_code=404, detail="分账订单不存在")

    return _ok(dict(row._mapping))


@router.post("/orders/{split_order_id}/notify")
async def receive_async_notify(
    split_order_id: uuid.UUID,
    body: AsyncNotifyBody,
    request: Request,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """接收微信/支付宝异步分账通知。

    验签规则（mock）：
    - 检查 X-Wechat-Pay-Signature 或 X-Alipay-Sign header，非空即视为通过。
    - 生产环境替换方式：
      微信：使用 wechatpayv3 SDK 中的 RSAVerifier.verify() 进行签名验证。
      支付宝：使用 alipay-sdk-python 中的 verify() 方法验证 RSA2 签名。
    """
    # mock 验签
    wechat_sig = request.headers.get("X-Wechat-Pay-Signature", "")
    alipay_sig = request.headers.get("X-Alipay-Sign", "")

    if not wechat_sig and not alipay_sig:
        # 宽松策略：无签名头时记录警告但不拒绝（POC阶段）
        logger.warning(
            "split_notify_no_signature",
            split_order_id=str(split_order_id),
            note="MOCK_MODE: 生产环境必须校验渠道签名",
        )

    from sqlalchemy import text

    try:
        # 更新对应 receiver 的分账结果
        if body.receiver_id:
            await db.execute(
                text("""
                    UPDATE split_payment_records
                    SET split_result = :split_result,
                        async_notify_id = :notify_id,
                        updated_at = NOW()
                    WHERE split_order_id = :split_order_id
                      AND receiver_id = :receiver_id
                      AND tenant_id = :tenant_id
                """),
                {
                    "split_result": body.split_result,
                    "notify_id": body.notify_id,
                    "split_order_id": str(split_order_id),
                    "receiver_id": body.receiver_id,
                    "tenant_id": str(tenant_id),
                },
            )

        # 检查是否所有明细均已完成，若是则更新主单状态
        pending_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM split_payment_records
                WHERE split_order_id = :split_order_id
                  AND split_result = 'pending'
                  AND is_deleted = false
            """),
            {"split_order_id": str(split_order_id)},
        )
        pending_count = pending_result.scalar_one()

        if pending_count == 0:
            await db.execute(
                text("""
                    UPDATE split_payment_orders
                    SET split_status = 'completed', updated_at = NOW()
                    WHERE id = :id AND tenant_id = :tenant_id
                """),
                {"id": str(split_order_id), "tenant_id": str(tenant_id)},
            )

        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("split_notify_error", split_order_id=str(split_order_id), error=str(exc))
        raise HTTPException(status_code=500, detail="处理异步通知失败") from exc

    logger.info(
        "split_notify_processed",
        split_order_id=str(split_order_id),
        notify_id=body.notify_id,
        split_result=body.split_result,
    )
    return _ok({"notify_id": body.notify_id, "processed": True})


@router.get("/orders/{split_order_id}/records")
async def list_split_records(
    split_order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """分账明细列表。"""
    from sqlalchemy import text

    try:
        result = await db.execute(
            text("""
                SELECT * FROM split_payment_records
                WHERE split_order_id = :split_order_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
                ORDER BY created_at ASC
            """),
            {"split_order_id": str(split_order_id), "tenant_id": str(tenant_id)},
        )
        rows = [dict(r._mapping) for r in result]
    except SQLAlchemyError as exc:
        logger.error("split_records_list_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询分账明细失败") from exc

    return _ok({"items": rows, "total": len(rows)})


@router.post("/adjustments", status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    body: AdjustmentCreateBody,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """差错账人工调账：记录调账日志，并更新分账明细金额。"""
    from sqlalchemy import text

    # 先查原始记录，获取 original_amount_fen
    try:
        orig_result = await db.execute(
            text("""
                SELECT id, amount_fen FROM split_payment_records
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": str(body.split_record_id), "tenant_id": str(tenant_id)},
        )
        orig_row = orig_result.fetchone()
    except SQLAlchemyError as exc:
        logger.error("adjustment_fetch_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询原始分账记录失败") from exc

    if not orig_row:
        raise HTTPException(status_code=404, detail="分账记录不存在")

    original_amount_fen = int(orig_row.amount_fen)
    adjustment_id = uuid.uuid4()

    try:
        # 写调账日志
        await db.execute(
            text("""
                INSERT INTO split_adjustment_logs (
                    id, tenant_id, split_record_id, reason,
                    original_amount_fen, adjusted_amount_fen, adjusted_by
                ) VALUES (
                    :id, :tenant_id, :split_record_id, :reason,
                    :original_amount_fen, :adjusted_amount_fen, :adjusted_by
                )
            """),
            {
                "id": str(adjustment_id),
                "tenant_id": str(tenant_id),
                "split_record_id": str(body.split_record_id),
                "reason": body.reason,
                "original_amount_fen": original_amount_fen,
                "adjusted_amount_fen": body.adjusted_amount_fen,
                "adjusted_by": body.adjusted_by,
            },
        )

        # 更新分账明细金额
        await db.execute(
            text("""
                UPDATE split_payment_records
                SET amount_fen = :adjusted_amount_fen, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "adjusted_amount_fen": body.adjusted_amount_fen,
                "id": str(body.split_record_id),
                "tenant_id": str(tenant_id),
            },
        )

        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("adjustment_create_error", error=str(exc))
        raise HTTPException(status_code=500, detail="创建调账记录失败") from exc

    logger.info(
        "adjustment_created",
        adjustment_id=str(adjustment_id),
        split_record_id=str(body.split_record_id),
        original=original_amount_fen,
        adjusted=body.adjusted_amount_fen,
        adjusted_by=body.adjusted_by,
    )
    return _ok({
        "adjustment_id": str(adjustment_id),
        "split_record_id": str(body.split_record_id),
        "original_amount_fen": original_amount_fen,
        "adjusted_amount_fen": body.adjusted_amount_fen,
    })


@router.get("/adjustments")
async def list_adjustments(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """调账记录列表。"""
    from sqlalchemy import text

    offset = (page - 1) * size
    try:
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM split_adjustment_logs WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        )
        total = count_result.scalar_one()

        rows_result = await db.execute(
            text("""
                SELECT * FROM split_adjustment_logs
                WHERE tenant_id = :tenant_id
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"tenant_id": str(tenant_id), "limit": size, "offset": offset},
        )
        rows = [dict(r._mapping) for r in rows_result]
    except SQLAlchemyError as exc:
        logger.error("adjustments_list_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询调账记录失败") from exc

    return _ok({"items": rows, "total": total, "page": page, "size": size})


@router.get("/rules/preview")
async def preview_split_rules(
    total_fen: int = Query(..., gt=0, description="总金额（分）"),
    rules: str = Query(..., description="JSON 编码的分润规则数组，格式见 PreviewSplitRuleItem"),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict[str, Any]:
    """试算分润：按比例计算各方应得金额（整数，分），余数归第一方。

    rules 参数示例（URL encoded JSON）：
    [{"receiver_type":"brand","receiver_id":"brand_001","ratio":2000},
     {"receiver_type":"franchise","receiver_id":"store_001","ratio":7000},
     {"receiver_type":"platform_fee","receiver_id":"platform","ratio":1000}]
    比例单位：万分比（10000 = 100%）。
    """
    import json as _json

    try:
        raw_rules = _json.loads(rules)
        parsed_rules = [PreviewSplitRuleItem(**r) for r in raw_rules]
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"rules 参数格式错误: {exc}",
        ) from exc

    total_ratio = sum(r.ratio for r in parsed_rules)
    if total_ratio != 10000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"分润比例之和必须等于 10000（当前 {total_ratio}）",
        )

    # 整数分割：各方 floor(total * ratio / 10000)，余数归第一方
    preview_items = []
    allocated = 0
    for i, rule in enumerate(parsed_rules):
        amount = (total_fen * rule.ratio) // 10000  # 整数除法，无浮点
        preview_items.append({
            "receiver_type": rule.receiver_type,
            "receiver_id": rule.receiver_id,
            "ratio": rule.ratio,
            "amount_fen": amount,
        })
        allocated += amount

    # 余数归第一方（保证总和=total_fen）
    remainder = total_fen - allocated
    if remainder != 0 and preview_items:
        preview_items[0]["amount_fen"] += remainder

    # 验证：各方之和 == total_fen
    assert sum(item["amount_fen"] for item in preview_items) == total_fen, (
        "分账金额计算错误，总和不等于输入金额"
    )

    return _ok({
        "total_fen": total_fen,
        "preview_items": preview_items,
        "amounts_are_integers": all(isinstance(item["amount_fen"], int) for item in preview_items),
    })
