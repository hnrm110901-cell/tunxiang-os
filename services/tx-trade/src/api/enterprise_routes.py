"""企业挂账与协议客户中心（B6）— API 路由

10个端点覆盖企业建档、额度管理、签单授权、月结结算全流程。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.enterprise_account import EnterpriseAccountService
from ..services.enterprise_billing import EnterpriseBillingService

router = APIRouter(prefix="/api/v1/enterprise", tags=["enterprise"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    raise HTTPException(status_code=code, detail={"ok": False, "data": None, "error": {"message": msg}})


# ─── 请求模型 ───


class CreateEnterpriseReq(BaseModel):
    name: str = Field(..., min_length=1, description="企业名称")
    contact: str = Field(..., min_length=1, description="联系人")
    credit_limit_fen: int = Field(..., gt=0, description="授信额度(分)")
    billing_cycle: str = Field(default="monthly", description="账期: monthly/bi_monthly/quarterly")


class UpdateEnterpriseReq(BaseModel):
    name: Optional[str] = None
    contact: Optional[str] = None
    credit_limit_fen: Optional[int] = Field(default=None, gt=0)
    billing_cycle: Optional[str] = None
    status: Optional[str] = None


class SetAgreementPriceReq(BaseModel):
    dish_id: str
    price_fen: int = Field(..., ge=0, description="协议价(分)")


class AuthorizeSignReq(BaseModel):
    order_id: str
    signer_name: str = Field(..., min_length=1, description="签单授权人姓名")
    amount_fen: int = Field(..., gt=0, description="签单金额(分)")


class ConfirmPaymentReq(BaseModel):
    payment_method: str = Field(..., description="支付方式: bank_transfer/check/cash/wechat")
    amount_fen: Optional[int] = Field(default=None, gt=0, description="收款金额(分)，默认全额")


# ─── 1. 创建企业客户 ───


@router.post("/accounts")
async def create_enterprise(
    req: CreateEnterpriseReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建企业挂账客户"""
    svc = EnterpriseAccountService(db, _get_tenant_id(request))
    try:
        result = await svc.create_enterprise(
            name=req.name,
            contact=req.contact,
            credit_limit_fen=req.credit_limit_fen,
            billing_cycle=req.billing_cycle,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 2. 更新企业信息 ───


@router.put("/accounts/{enterprise_id}")
async def update_enterprise(
    enterprise_id: str,
    req: UpdateEnterpriseReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新企业信息"""
    svc = EnterpriseAccountService(db, _get_tenant_id(request))
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        _err("无更新内容")
    try:
        result = await svc.update_enterprise(enterprise_id, updates)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 3. 查询企业详情 ───


@router.get("/accounts/{enterprise_id}")
async def get_enterprise(
    enterprise_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询企业详情"""
    svc = EnterpriseAccountService(db, _get_tenant_id(request))
    try:
        result = await svc.get_enterprise(enterprise_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e), 404)


# ─── 4. 企业列表 ───


@router.get("/accounts")
async def list_enterprises(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询所有企业客户"""
    svc = EnterpriseAccountService(db, _get_tenant_id(request))
    result = await svc.list_enterprises()
    return _ok(result)


# ─── 5. 设置协议价 ───


@router.post("/accounts/{enterprise_id}/agreement-prices")
async def set_agreement_price(
    enterprise_id: str,
    req: SetAgreementPriceReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """设置企业协议价"""
    svc = EnterpriseAccountService(db, _get_tenant_id(request))
    try:
        result = await svc.set_agreement_price(
            enterprise_id=enterprise_id,
            dish_id=req.dish_id,
            price_fen=req.price_fen,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 6. 签单授权 ───


@router.post("/accounts/{enterprise_id}/sign")
async def authorize_sign(
    enterprise_id: str,
    req: AuthorizeSignReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """签单授权 — 企业客户挂账"""
    svc = EnterpriseAccountService(db, _get_tenant_id(request))
    try:
        result = await svc.authorize_sign(
            enterprise_id=enterprise_id,
            order_id=req.order_id,
            signer_name=req.signer_name,
            amount_fen=req.amount_fen,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 7. 额度检查 ───


@router.get("/accounts/{enterprise_id}/credit")
async def check_credit(
    enterprise_id: str,
    amount_fen: int = Query(..., gt=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """检查企业挂账额度"""
    svc = EnterpriseAccountService(db, _get_tenant_id(request))
    try:
        result = await svc.check_credit(enterprise_id, amount_fen)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 8. 生成月结账单 ───


@router.post("/accounts/{enterprise_id}/bills")
async def generate_monthly_bill(
    enterprise_id: str,
    month: str = Query(..., description="账期月份 YYYY-MM"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """生成企业月结账单"""
    svc = EnterpriseBillingService(db, _get_tenant_id(request))
    try:
        result = await svc.generate_monthly_bill(enterprise_id, month)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 9. 确认收款 ───


@router.post("/bills/{bill_id}/payment")
async def confirm_payment(
    bill_id: str,
    req: ConfirmPaymentReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """确认企业账单收款"""
    svc = EnterpriseBillingService(db, _get_tenant_id(request))
    try:
        result = await svc.confirm_payment(
            bill_id=bill_id,
            payment_method=req.payment_method,
            amount_fen=req.amount_fen,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 10. 对账单 + 未结账单 + 消费分析 ───


@router.get("/accounts/{enterprise_id}/statement")
async def get_statement(
    enterprise_id: str,
    month: str = Query(..., description="账期月份 YYYY-MM"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """生成企业对账单（PDF数据）"""
    svc = EnterpriseBillingService(db, _get_tenant_id(request))
    try:
        result = await svc.generate_statement(enterprise_id, month)
        return _ok(result)
    except ValueError as e:
        _err(str(e))
