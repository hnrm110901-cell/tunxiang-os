"""扫码付款码收款 API — DB版（v168 scan_pay_transactions）

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import PaymentEventType
from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services.trade_audit_log import write_audit

router = APIRouter(prefix="/api/v1/payments", tags=["scan-pay"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _detect_channel(auth_code: str) -> Literal["wechat", "alipay", "unionpay"]:
    if len(auth_code) < 2:
        return "unionpay"
    prefix2 = auth_code[:2]
    if prefix2 in {"10", "11", "12", "13", "14", "15"}:
        return "wechat"
    if prefix2 in {"25", "26", "27", "28", "29", "30"}:
        return "alipay"
    return "unionpay"


class ScanPayRequest(BaseModel):
    auth_code: str = Field(..., min_length=6, description="顾客付款码")
    amount_fen: int = Field(..., gt=0, description="收款金额（分）")
    store_id: str = Field(..., description="门店ID")
    cashier_id: str = Field(default="", description="收银员ID")
    description: str = Field(default="", description="备注")


@router.post("/scan-pay")
async def scan_pay(
    body: ScanPayRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
):
    """扫码收款 — 写入 scan_pay_transactions，模拟调用第三方支付（异步）。"""
    tenant_id = _get_tenant_id(request)
    channel = _detect_channel(body.auth_code)
    payment_id = "SPY-" + uuid.uuid4().hex[:12].upper()

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        await db.execute(
            text("""
                INSERT INTO scan_pay_transactions
                    (tenant_id, store_id, payment_id, auth_code, channel, amount_fen, cashier_id, status)
                VALUES
                    (:tenant_id, :store_id, :payment_id, :auth_code, :channel, :amount_fen, :cashier_id, 'pending')
            """),
            {
                "tenant_id": tenant_id,
                "store_id": body.store_id,
                "payment_id": payment_id,
                "auth_code": body.auth_code,
                "channel": channel,
                "amount_fen": body.amount_fen,
                "cashier_id": body.cashier_id,
            },
        )
        await db.commit()

        # 事件：支付发起
        asyncio.create_task(
            emit_event(
                event_type=PaymentEventType.INITIATED,
                tenant_id=tenant_id,
                stream_id=payment_id,
                payload={"amount_fen": body.amount_fen, "channel": channel, "store_id": body.store_id},
                store_id=body.store_id,
                source_service="tx-trade",
            )
        )

        # 异步模拟支付结果（实际应调用微信/支付宝 API）
        asyncio.create_task(_simulate_payment(payment_id, tenant_id, body.store_id, body.amount_fen, channel))

        # Sprint A4 审计留痕
        await write_audit(
            db,
            tenant_id=tenant_id,
            store_id=body.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="payment.scan_pay.create",
            target_type="payment",
            target_id=None,
            amount_fen=body.amount_fen,
            client_ip=user.client_ip,
        )

        return _ok(
            {
                "payment_id": payment_id,
                "channel": channel,
                "amount_fen": body.amount_fen,
                "status": "pending",
                "message": f"正在通过{channel}收款，请稍候",
            }
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"支付发起失败: {exc}")


async def _simulate_payment(payment_id: str, tenant_id: str, store_id: str, amount_fen: int, channel: str) -> None:
    """模拟异步支付回调（生产环境替换为第三方回调处理）。"""
    from shared.ontology.src.database import async_session_factory  # 避免循环导入

    await asyncio.sleep(2)
    # 生产环境：调用微信/支付宝收款 API，等待回调更新状态
    # 此处模拟支付成功，更新状态并发出确认事件
    try:
        async with async_session_factory() as db:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            await db.execute(
                text("""
                    UPDATE scan_pay_transactions
                    SET status = 'paid', paid_at = NOW(), updated_at = NOW()
                    WHERE payment_id = :payment_id AND tenant_id = :tenant_id AND status = 'pending'
                """),
                {"payment_id": payment_id, "tenant_id": tenant_id},
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — 模拟回调失败不影响主流程
        return

    # 事件：支付确认
    await emit_event(
        event_type=PaymentEventType.CONFIRMED,
        tenant_id=tenant_id,
        stream_id=payment_id,
        payload={"amount_fen": amount_fen, "channel": channel, "store_id": store_id},
        store_id=store_id,
        source_service="tx-trade",
    )


@router.get("/scan-pay/{payment_id}/status")
async def get_payment_status(
    payment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
):
    """查询支付状态。"""
    tenant_id = _get_tenant_id(request)
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT payment_id, channel, amount_fen, status,
                       merchant_order_id, paid_at, created_at
                FROM scan_pay_transactions
                WHERE payment_id = :payment_id
            """),
            {"payment_id": payment_id},
        )
        row = result.mappings().one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail=f"支付记录 {payment_id} 不存在")

        data = dict(row._mapping)
        for k in ("paid_at", "created_at"):
            if data.get(k):
                data[k] = data[k].isoformat()
        return _ok(data)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}")


@router.post("/scan-pay/{payment_id}/cancel")
async def cancel_payment(
    payment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
):
    """取消支付（仅限 pending 状态）。"""
    tenant_id = _get_tenant_id(request)
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            text("""
                UPDATE scan_pay_transactions
                SET status = 'cancelled', updated_at = NOW()
                WHERE payment_id = :payment_id AND status = 'pending'
                RETURNING payment_id, status
            """),
            {"payment_id": payment_id},
        )
        row = result.mappings().one_or_none()
        if not row:
            raise HTTPException(status_code=400, detail="支付记录不存在或已非 pending 状态")
        await db.commit()
        await write_audit(
            db,
            tenant_id=tenant_id,
            store_id=user.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="payment.scan_pay.cancel",
            target_type="payment",
            target_id=None,
            amount_fen=None,
            client_ip=user.client_ip,
        )
        return _ok({"payment_id": payment_id, "status": "cancelled"})
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"取消失败: {exc}")
