"""宴席定金在线支付 + 电子确认单 API

路由前缀：/api/v1/banquet

端点：
  # 定金支付
  POST   /{banquet_id}/deposit                  — 创建定金记录
  GET    /{banquet_id}/deposit                  — 获取定金状态
  POST   /{banquet_id}/deposit/wechat-pay       — 发起微信小程序支付
  POST   /deposit/callback                      — 微信支付回调（无需 X-Tenant-ID）

  # 电子确认单
  POST   /{banquet_id}/confirmation             — 创建确认单
  GET    /{banquet_id}/confirmation             — 获取确认单
  POST   /{banquet_id}/confirmation/sign        — 顾客确认签字
  GET    /{banquet_id}/confirmation/summary     — 确认单摘要（PDF导出用）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_no_rls, get_db_with_tenant

from ..security.rbac import (
    UserContext,
    assert_mfa_for_high_value,
    require_role_audited,
)
from ..services.banquet_payment_service import BanquetPaymentService
from ..services.trade_audit_log import write_audit

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/banquet", tags=["banquet-payment"])


# ─── 工具 ───────────────────────────────────────────────────────────────────


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _get_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", "")  # cutover 后只信 InternalJwtMiddleware 注入的 state
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID")
    return tenant_id


async def _get_db(request: Request):
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


async def _get_db_no_tenant():
    """无租户隔离的 DB session，仅用于微信支付回调端点。
    要求 DB 用户持有 BYPASSRLS 权限，参见 get_db_no_rls。
    """
    async for session in get_db_no_rls():
        yield session


def _svc(request: Request, db: AsyncSession = Depends(_get_db)) -> BanquetPaymentService:
    tenant_id = _get_tenant_id(request)
    return BanquetPaymentService(tenant_id=tenant_id, db=db)


# ─── Request Models ──────────────────────────────────────────────────────────


class CreateDepositReq(BaseModel):
    total_deposit_fen: int = Field(..., gt=0, description="应付定金总额（分）")
    due_date: Optional[date] = None


class WechatPayReq(BaseModel):
    openid: str = Field(..., min_length=1, description="顾客微信 openid（小程序获取）")
    notify_url: str = Field(
        default="https://your-domain.com/api/v1/banquet/deposit/callback",
        description="支付结果回调 URL",
    )


class WechatCallbackReq(BaseModel):
    payment_no: str
    wechat_transaction_id: str
    paid_fen: int = Field(..., ge=0)
    paid_at: datetime


class CreateConfirmationReq(BaseModel):
    menu_items: list[dict] = Field(..., min_length=1)
    guest_count: int = Field(..., ge=1)
    confirmed_by_name: str = Field(..., min_length=1)
    confirmed_by_phone: str = Field(..., min_length=1)
    special_requirements: str = ""


class SignConfirmationReq(BaseModel):
    signature_data: Optional[str] = None  # Base64 签名图像


# ─── 定金支付端点 ────────────────────────────────────────────────────────────


@router.post("/{banquet_id}/deposit")
async def create_deposit(
    banquet_id: UUID,
    body: CreateDepositReq,
    request: Request,
    db: AsyncSession = Depends(_get_db),
    user: UserContext = Depends(require_role_audited("banquet.deposit.create", "store_manager", "admin")),
):
    """创建定金记录（初始状态 pending；仅店长/管理员）。

    PR-7 / R-A4-4 后续：≥ ¥5000 的定金强制 MFA 验证。
    阈值可通过环境变量 TX_MFA_THRESHOLD_FEN__BANQUET_DEPOSIT_CREATE 覆盖。
    """
    # 高额定金强制 MFA — 防 store_manager token 泄漏被批量盗刷大额定金
    await assert_mfa_for_high_value(
        user,
        db,
        action="banquet.deposit.create",
        amount_fen=body.total_deposit_fen,
        request_id=request.headers.get("X-Request-Id") if hasattr(request, "headers") else None,
    )
    try:
        tenant_id = UUID(_get_tenant_id(request))
        svc = BanquetPaymentService(tenant_id=str(tenant_id), db=db)
        deposit = await svc.create_deposit(
            banquet_id=banquet_id,
            tenant_id=tenant_id,
            total_deposit_fen=body.total_deposit_fen,
            due_date=body.due_date,
        )
        await write_audit(
            db,
            tenant_id=str(tenant_id),
            store_id=user.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="banquet.deposit.create",
            target_type="banquet",
            target_id=str(banquet_id),
            amount_fen=body.total_deposit_fen,
            client_ip=user.client_ip,
        )
        return _ok(deposit.model_dump(mode="json"))
    except ValueError as exc:
        return _err(str(exc))


@router.get("/{banquet_id}/deposit")
async def get_deposit(
    banquet_id: UUID,
    request: Request,
    svc: BanquetPaymentService = Depends(_svc),
):
    """获取定金状态"""
    try:
        tenant_id = UUID(_get_tenant_id(request))
        deposit = await svc.get_deposit(banquet_id=banquet_id, tenant_id=tenant_id)
        if deposit is None:
            return _err("定金记录不存在", "NOT_FOUND")
        return _ok(deposit.model_dump(mode="json"))
    except ValueError as exc:
        return _err(str(exc))


@router.post("/{banquet_id}/deposit/wechat-pay")
async def initiate_wechat_pay(
    banquet_id: UUID,
    body: WechatPayReq,
    request: Request,
    db: AsyncSession = Depends(_get_db),
    user: UserContext = Depends(require_role_audited("banquet.deposit.wechat_pay", "store_manager", "admin")),
):
    """发起微信小程序支付（JSAPI模式；仅店长/管理员）

    先调用 POST /{banquet_id}/deposit 创建定金记录，获取 deposit_id，
    再调用本接口发起支付，前端使用返回的 jsapi_params 调起微信支付。
    """
    try:
        tenant_id = UUID(_get_tenant_id(request))
        svc = BanquetPaymentService(tenant_id=str(tenant_id), db=db)
        # 取该宴席最新定金记录 id
        deposit = await svc.get_deposit(banquet_id=banquet_id, tenant_id=tenant_id)
        if deposit is None:
            return _err("定金记录不存在，请先创建定金", "NOT_FOUND")

        result = await svc.initiate_wechat_pay(
            deposit_id=deposit.id,
            tenant_id=tenant_id,
            openid=body.openid,
            notify_url=body.notify_url,
        )
        await write_audit(
            db,
            tenant_id=str(tenant_id),
            store_id=user.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="banquet.deposit.wechat_pay",
            target_type="banquet_deposit",
            target_id=str(deposit.id),
            amount_fen=getattr(deposit, "total_deposit_fen", None),
            client_ip=user.client_ip,
        )
        return _ok(result.model_dump(mode="json"))
    except ValueError as exc:
        return _err(str(exc))


@router.post("/deposit/callback")
async def wechat_payment_callback(
    request: Request,
    db: AsyncSession = Depends(_get_db_no_tenant),
):
    """微信支付回调（无需 X-Tenant-ID，验签后处理）

    审计 S-04（P0）修复：强制走 WechatPayService.verify_callback —— V3 RSA-SHA256
    签名校验 + AES-256-GCM 解密。原本的 ``WechatCallbackReq`` 直接接受未验签 JSON，
    任何能猜到 ``payment_no`` 的人都可伪造回调确认押金或触发开票（Tier 1 零容忍）。
    生产环境若未配置微信公钥，``WechatPayService.__init__`` 已 fail-closed，
    除非显式设置 ``TX_WECHAT_PAY_ALLOW_MOCK=1``（仅限灰度演练）。

    步骤1：读原始 body + headers，调 verify_callback（验签 + 解密）。失败 → 400。
    步骤2：从解密后通知取 out_trade_no / transaction_id / amount.payer_total / success_time。
    步骤3：用 payment_no 跨租户查 tenant_id（db 已跳过 RLS）。
    步骤4：用真实 tenant_id 建立租户隔离 session，调 handle_payment_callback。

    返回：成功必须回 ``{"code":"SUCCESS","message":"成功"}``（微信 V3 约定，否则会重试）。
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from sqlalchemy import text as _text

    from shared.integrations.wechat_pay import get_wechat_pay_service

    body_bytes = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # 步骤1：验签 + 解密（fail-closed）
    try:
        notify = await get_wechat_pay_service().verify_callback(headers, body_bytes)
    except ValueError as exc:
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(
            "banquet_deposit.callback_signature_invalid",
            error=str(exc),
            ip=client_ip,
        )
        # 验签/时间戳/解密失败统一 400，微信端按指数退避重试
        raise HTTPException(status_code=400, detail="invalid signature")
    except RuntimeError as exc:
        # 生产 mock 配置缺失（理论上 __init__ 已阻止启动；保险起见）
        logger.error("banquet_deposit.callback_service_misconfigured", error=str(exc))
        raise HTTPException(status_code=500, detail="payment service misconfigured")

    payment_no = str(notify.get("out_trade_no") or "")
    wechat_transaction_id = str(notify.get("transaction_id") or "")
    amount_obj = notify.get("amount") or {}
    paid_fen_raw = amount_obj.get("payer_total") if isinstance(amount_obj, dict) else None
    success_time_raw = notify.get("success_time") or ""

    if not payment_no or not wechat_transaction_id or paid_fen_raw is None:
        logger.warning(
            "banquet_deposit.callback_missing_fields",
            has_payment_no=bool(payment_no),
            has_txn_id=bool(wechat_transaction_id),
            has_amount=paid_fen_raw is not None,
        )
        raise HTTPException(status_code=400, detail="malformed callback payload")

    try:
        paid_fen = int(paid_fen_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid amount in callback") from None

    if success_time_raw:
        try:
            paid_at = _dt.fromisoformat(str(success_time_raw).replace("Z", "+00:00"))
        except ValueError:
            paid_at = _dt.now(_tz.utc)
    else:
        paid_at = _dt.now(_tz.utc)

    logger.info(
        "banquet_deposit.callback_verified",
        payment_no=payment_no,
        wechat_transaction_id=wechat_transaction_id,
        paid_fen=paid_fen,
    )

    # 步骤3：跨租户查询 tenant_id（db 已跳过 RLS）
    row = await db.execute(
        _text("SELECT tenant_id FROM banquet_deposits WHERE payment_no = :pno LIMIT 1"),
        {"pno": payment_no},
    )
    record = row.mappings().first()
    if not record:
        logger.warning("banquet_deposit.callback_no_match", payment_no=payment_no)
        # 微信约定：未找到也按"已处理"回 SUCCESS，避免无意义重试
        return {"code": "SUCCESS", "message": "成功"}

    tenant_id = str(record["tenant_id"])

    # 步骤4：用真实 tenant_id 建立租户隔离 session，调用业务处理
    try:
        async for tenant_db in get_db_with_tenant(tenant_id):
            svc = BanquetPaymentService(tenant_id=tenant_id, db=tenant_db)
            await svc.handle_payment_callback(
                payment_no=payment_no,
                wechat_transaction_id=wechat_transaction_id,
                paid_fen=paid_fen,
                paid_at=paid_at,
            )
    except ValueError as exc:
        logger.error(
            "banquet_deposit.callback_handle_failed",
            payment_no=payment_no,
            tenant_id=tenant_id,
            error=str(exc),
        )
        # 业务异常仍回 400 让微信重试（避免单次失败永久丢消息）
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "banquet_deposit.callback_processed",
        payment_no=payment_no,
        tenant_id=tenant_id,
        paid_fen=paid_fen,
    )
    return {"code": "SUCCESS", "message": "成功"}


# ─── 电子确认单端点 ──────────────────────────────────────────────────────────


@router.post("/{banquet_id}/confirmation")
async def create_confirmation(
    banquet_id: UUID,
    body: CreateConfirmationReq,
    request: Request,
    db: AsyncSession = Depends(_get_db),
    user: UserContext = Depends(require_role_audited("banquet.confirmation.create", "store_manager", "admin")),
):
    """创建电子确认单（仅店长/管理员）

    menu_items 格式：
    [{"dish_id": "...", "dish_name": "...", "quantity": 2,
      "unit_price_fen": 5800, "subtotal_fen": 11600}]
    """
    try:
        tenant_id = UUID(_get_tenant_id(request))
        svc = BanquetPaymentService(tenant_id=str(tenant_id), db=db)
        confirmation = await svc.create_confirmation(
            banquet_id=banquet_id,
            tenant_id=tenant_id,
            menu_items=body.menu_items,
            guest_count=body.guest_count,
            confirmed_by_name=body.confirmed_by_name,
            confirmed_by_phone=body.confirmed_by_phone,
            special_requirements=body.special_requirements,
        )
        await write_audit(
            db,
            tenant_id=str(tenant_id),
            store_id=user.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="banquet.confirmation.create",
            target_type="banquet",
            target_id=str(banquet_id),
            amount_fen=None,
            client_ip=user.client_ip,
        )
        return _ok(confirmation.model_dump(mode="json"))
    except ValueError as exc:
        return _err(str(exc))


@router.get("/{banquet_id}/confirmation")
async def get_confirmation(
    banquet_id: UUID,
    request: Request,
    svc: BanquetPaymentService = Depends(_svc),
):
    """获取确认单"""
    try:
        tenant_id = UUID(_get_tenant_id(request))
        confirmation = await svc.get_confirmation(banquet_id=banquet_id, tenant_id=tenant_id)
        if confirmation is None:
            return _err("确认单不存在", "NOT_FOUND")
        return _ok(confirmation.model_dump(mode="json"))
    except ValueError as exc:
        return _err(str(exc))


@router.post("/{banquet_id}/confirmation/sign")
async def sign_confirmation(
    banquet_id: UUID,
    body: SignConfirmationReq,
    request: Request,
    db: AsyncSession = Depends(_get_db),
    user: UserContext = Depends(require_role_audited("banquet.confirmation.sign", "store_manager", "admin")),
):
    """顾客确认签字，将确认单状态更新为 confirmed（仅店长/管理员代签）"""
    try:
        tenant_id = UUID(_get_tenant_id(request))
        svc = BanquetPaymentService(tenant_id=str(tenant_id), db=db)
        # 取最新确认单 id
        confirmation = await svc.get_confirmation(banquet_id=banquet_id, tenant_id=tenant_id)
        if confirmation is None:
            return _err("确认单不存在", "NOT_FOUND")

        signed = await svc.confirm_with_signature(
            confirmation_id=confirmation.id,
            tenant_id=tenant_id,
            signature_data=body.signature_data,
        )
        await write_audit(
            db,
            tenant_id=str(tenant_id),
            store_id=user.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="banquet.confirmation.sign",
            target_type="banquet_confirmation",
            target_id=str(confirmation.id),
            amount_fen=None,
            client_ip=user.client_ip,
        )
        return _ok(signed.model_dump(mode="json"))
    except ValueError as exc:
        return _err(str(exc))


@router.get("/{banquet_id}/confirmation/summary")
async def get_confirmation_summary(
    banquet_id: UUID,
    request: Request,
    svc: BanquetPaymentService = Depends(_svc),
):
    """确认单摘要（用于前端展示/PDF导出）"""
    try:
        tenant_id = UUID(_get_tenant_id(request))
        # 取最新确认单 id
        confirmation = await svc.get_confirmation(banquet_id=banquet_id, tenant_id=tenant_id)
        if confirmation is None:
            return _err("确认单不存在", "NOT_FOUND")

        summary = await svc.generate_confirmation_summary(
            confirmation_id=confirmation.id,
            tenant_id=tenant_id,
        )
        return _ok(summary.model_dump(mode="json"))
    except ValueError as exc:
        return _err(str(exc))
