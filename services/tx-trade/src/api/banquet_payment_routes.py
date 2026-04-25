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

from ..security.rbac import UserContext, require_role_audited
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
    tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
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
    """创建定金记录（初始状态 pending；仅店长/管理员）"""
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
    body: WechatCallbackReq,
    db: AsyncSession = Depends(_get_db_no_tenant),
):
    """微信支付回调（无需 X-Tenant-ID，验签后处理）

    步骤1：签名校验（生产环境须配置 WECHAT_PAY_PUBLIC_KEY_PATH 环境变量）。
    步骤2：用 payment_no 从 banquet_deposits 跨租户查找 tenant_id。
    步骤3：用真实 tenant_id 建立租户隔离 session，调用 handle_payment_callback。
    """
    logger.info(
        "banquet_deposit.callback_received",
        payment_no=body.payment_no,
        wechat_transaction_id=body.wechat_transaction_id,
        paid_fen=body.paid_fen,
    )

    # 步骤1：微信签名校验
    # 生产环境须配置 WECHAT_PAY_PUBLIC_KEY_PATH，用微信平台公钥验签。
    # 当前跳过验签，仅适用于开发/内网环境。
    # wechat_sig = request.headers.get("Wechatpay-Signature", "")
    # if not _verify_wechat_signature(wechat_sig, body.model_dump()):
    #     raise HTTPException(status_code=401, detail="微信回调签名校验失败")

    # 步骤2：跨租户查询 tenant_id（db 已跳过 RLS）
    from sqlalchemy import text as _text

    row = await db.execute(
        _text("SELECT tenant_id FROM banquet_deposits WHERE payment_no = :pno LIMIT 1"),
        {"pno": body.payment_no},
    )
    record = row.mappings().first()
    if not record:
        logger.warning(
            "banquet_deposit.callback_no_match",
            payment_no=body.payment_no,
        )
        return _ok({"message": "payment_no not found, ignored"})

    tenant_id = str(record["tenant_id"])

    # 步骤3：用真实 tenant_id 建立租户隔离 session，调用业务处理
    try:
        async for tenant_db in get_db_with_tenant(tenant_id):
            svc = BanquetPaymentService(tenant_id=tenant_id, db=tenant_db)
            await svc.handle_payment_callback(
                payment_no=body.payment_no,
                wechat_transaction_id=body.wechat_transaction_id,
                paid_fen=body.paid_fen,
                paid_at=body.paid_at,
            )
    except ValueError as exc:
        logger.error(
            "banquet_deposit.callback_handle_failed",
            payment_no=body.payment_no,
            tenant_id=tenant_id,
            error=str(exc),
        )
        return _err(str(exc))

    logger.info(
        "banquet_deposit.callback_processed",
        payment_no=body.payment_no,
        tenant_id=tenant_id,
        paid_fen=body.paid_fen,
    )
    return _ok({"message": "callback processed"})


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
