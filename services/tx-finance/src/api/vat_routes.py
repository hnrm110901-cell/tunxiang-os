"""企业增值税 API — 9 个端点（v102）

端点：
1. POST   /api/v1/finance/vat/declarations              创建/重算申报单
2. GET    /api/v1/finance/vat/declarations              申报单列表
3. GET    /api/v1/finance/vat/declarations/{id}         申报单详情（含进项发票）
4. POST   /api/v1/finance/vat/declarations/{id}/submit  提交申报
5. POST   /api/v1/finance/vat/declarations/{id}/pay     记录已缴税
6. POST   /api/v1/finance/vat/declarations/{id}/invoices  录入进项发票
7. GET    /api/v1/finance/vat/declarations/{id}/invoices  进项发票列表
8. POST   /api/v1/finance/vat/invoices/{id}/verify      验证进项发票
9. GET    /api/v1/finance/vat/tax-rates                 查看适用税率参考
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.vat_service import DEFAULT_VAT_RATE, VALID_INVOICE_TYPES, VATService

router = APIRouter(prefix="/api/v1/finance/vat", tags=["enterprise_vat"])


# ─── DB 依赖 ──────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class CreateDeclarationRequest(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    period: str = Field(..., description="申报期间 YYYY-MM")
    period_type: str = Field("monthly", description="monthly/quarterly")
    tax_rate: float = Field(DEFAULT_VAT_RATE, ge=0.01, le=0.17, description="适用税率，默认 6%")
    note: Optional[str] = Field(None, description="备注")
    created_by: Optional[str] = Field(None, description="创建人员工 ID")


class SubmitDeclarationRequest(BaseModel):
    nuonuo_declaration_no: Optional[str] = Field(None, description="诺诺申报编号（对接诺诺API后获得）")


class MarkPaidRequest(BaseModel):
    paid_tax_fen: int = Field(..., ge=0, description="实际缴税金额（分）")


class AddInputInvoiceRequest(BaseModel):
    invoice_no: str = Field(..., description="发票号码")
    invoice_date: str = Field(..., description="开票日期 YYYY-MM-DD")
    supplier_name: str = Field(..., min_length=1, max_length=200, description="供应商名称")
    amount_fen: int = Field(..., gt=0, description="发票金额（含税，分）")
    tax_rate: float = Field(DEFAULT_VAT_RATE, ge=0.01, le=0.17, description="发票税率")
    invoice_type: str = Field("vat_special", description="发票类型: vat_special/vat_ordinary/electronic_vat_special")
    supplier_tax_no: Optional[str] = Field(None, description="供应商税号")


class VerifyInvoiceRequest(BaseModel):
    verified: bool = Field(..., description="True=验证通过，False=驳回")
    rejection_reason: Optional[str] = Field(None, description="驳回原因（verified=False 时填写）")


# ─── 1. 创建/重算申报单 ───────────────────────────────────────────────────────

@router.post("/declarations", summary="创建/重算增值税申报单", status_code=201)
async def create_declaration(
    body: CreateDeclarationRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """创建月度增值税申报草稿，自动从订单收入计算销项税额。

    同(门店+期间)重复提交则重算销项税（进项发票不变）。
    """
    svc = VATService(db, x_tenant_id)
    try:
        decl = await svc.create_declaration(
            store_id=body.store_id,
            period=body.period,
            period_type=body.period_type,
            tax_rate=body.tax_rate,
            note=body.note,
            created_by=body.created_by,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": decl}


# ─── 2. 申报单列表 ────────────────────────────────────────────────────────────

@router.get("/declarations", summary="增值税申报单列表")
async def list_declarations(
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    period: Optional[str] = Query(None, description="按期间过滤 YYYY-MM"),
    status: Optional[str] = Query(None, description="状态: draft/reviewing/filed/paid"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询增值税申报单列表。"""
    svc = VATService(db, x_tenant_id)
    items = await svc.list_declarations(store_id=store_id, period=period, status=status)
    return {"ok": True, "data": {"items": items, "total": len(items)}}


# ─── 3. 申报单详情 ────────────────────────────────────────────────────────────

@router.get("/declarations/{declaration_id}", summary="申报单详情（含进项发票）")
async def get_declaration(
    declaration_id: str = Path(..., description="申报单 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """获取申报单完整详情，含所有进项发票列表。"""
    svc = VATService(db, x_tenant_id)
    detail = await svc.get_declaration_detail(declaration_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"申报单不存在: {declaration_id}")
    return {"ok": True, "data": detail}


# ─── 4. 提交申报 ──────────────────────────────────────────────────────────────

@router.post("/declarations/{declaration_id}/submit", summary="提交增值税申报")
async def submit_declaration(
    declaration_id: str = Path(..., description="申报单 ID"),
    body: SubmitDeclarationRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """将 draft/reviewing 状态申报单提交为 filed。

    nuonuo_declaration_no：对接诺诺 API 申报后返回的编号，可选。
    """
    svc = VATService(db, x_tenant_id)
    try:
        decl = await svc.submit_declaration(
            declaration_id=declaration_id,
            nuonuo_declaration_no=body.nuonuo_declaration_no,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": decl}


# ─── 5. 记录已缴税 ────────────────────────────────────────────────────────────

@router.post("/declarations/{declaration_id}/pay", summary="记录实际缴税")
async def mark_paid(
    declaration_id: str = Path(..., description="申报单 ID"),
    body: MarkPaidRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """记录实际缴税金额，将 filed 状态申报单更新为 paid。"""
    svc = VATService(db, x_tenant_id)
    try:
        decl = await svc.mark_paid(declaration_id, body.paid_tax_fen)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": decl}


# ─── 6. 录入进项发票 ──────────────────────────────────────────────────────────

@router.post("/declarations/{declaration_id}/invoices", summary="录入进项发票", status_code=201)
async def add_input_invoice(
    declaration_id: str = Path(..., description="申报单 ID"),
    body: AddInputInvoiceRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """录入供应商增值税专票，自动减少应纳税额。

    input_tax = amount_fen × tax_rate / (1 + tax_rate)  （价税合并拆分）
    """
    svc = VATService(db, x_tenant_id)
    try:
        result = await svc.add_input_invoice(
            declaration_id=declaration_id,
            invoice_no=body.invoice_no,
            invoice_date=body.invoice_date,
            supplier_name=body.supplier_name,
            amount_fen=body.amount_fen,
            tax_rate=body.tax_rate,
            invoice_type=body.invoice_type,
            supplier_tax_no=body.supplier_tax_no,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": result}


# ─── 7. 进项发票列表 ──────────────────────────────────────────────────────────

@router.get("/declarations/{declaration_id}/invoices", summary="进项发票列表")
async def list_input_invoices(
    declaration_id: str = Path(..., description="申报单 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询申报单下的所有进项发票。"""
    svc = VATService(db, x_tenant_id)
    invoices = await svc.list_input_invoices(declaration_id)
    total_input = sum(i["input_tax_fen"] for i in invoices if i["status"] != "rejected")
    return {
        "ok": True,
        "data": {
            "declaration_id": declaration_id,
            "items": invoices,
            "total": len(invoices),
            "effective_input_tax_fen": total_input,
            "effective_input_tax_yuan": round(total_input / 100, 2),
        },
    }


# ─── 8. 验证进项发票 ──────────────────────────────────────────────────────────

@router.post("/invoices/{invoice_id}/verify", summary="验证/驳回进项发票")
async def verify_invoice(
    invoice_id: str = Path(..., description="进项发票 ID"),
    body: VerifyInvoiceRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """税务专员验证进项发票真实性。

    - verified=True：更新为 verified，计入抵扣
    - verified=False：更新为 rejected，排除出抵扣计算
    """
    svc = VATService(db, x_tenant_id)
    try:
        result = await svc.verify_input_invoice(
            invoice_id=invoice_id,
            verified=body.verified,
            rejection_reason=body.rejection_reason,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": result}


# ─── 9. 税率参考 ──────────────────────────────────────────────────────────────

@router.get("/tax-rates", summary="增值税率参考表")
async def get_tax_rates(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """返回餐饮行业适用增值税率参考（仅供参考，实际税率以税务局核定为准）。"""
    return {
        "ok": True,
        "data": {
            "rates": [
                {"type": "一般纳税人-餐饮服务", "rate": 0.06, "description": "年收入≥500万，适用6%税率"},
                {"type": "小规模纳税人", "rate": 0.03, "description": "年收入<500万，适用3%征收率（2023年起优惠1%）"},
                {"type": "餐饮外卖-增值税", "rate": 0.06, "description": "通过第三方平台销售适用6%"},
            ],
            "invoice_types": list(VALID_INVOICE_TYPES),
            "default_rate": DEFAULT_VAT_RATE,
            "note": "税率参考仅供系统配置使用，以当地税务局核定为准",
        },
    }
