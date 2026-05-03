"""印度尼西亚 PPN 税引擎 API 端点（Phase 3 Sprint 3.4）

4 个端点：
  - POST /api/v1/ppn/calculate   计算 PPN
  - GET  /api/v1/ppn/rates       查询当前税率表
  - GET  /api/v1/ppn/categories  查询 PPN 分类选项
  - POST /api/v1/ppn/validate-npwp  验证 NPWP 税号格式
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.ppn_service import PPNService

router = APIRouter(prefix="/api/v1/ppn", tags=["ppn"])


# ── 请求/响应模型 ─────────────────────────────────────────────


class PPNItem(BaseModel):
    """PPN 计算请求中的单条明细"""

    amount_fen: int = Field(..., description="该项金额（分）")
    ppn_category: str = Field(default="standard", description="PPN分类: standard/luxury/export/exempt")


class PPNCalculateRequest(BaseModel):
    """PPN 计算请求"""

    items: list[PPNItem] = Field(..., min_length=1, description="订单明细列表")


class PPNCalculateResponse(BaseModel):
    """PPN 计算结果"""

    standard_11_fen: int = Field(..., description="总 11% PPN 金额（分）")
    luxury_12_fen: int = Field(..., description="总 12% PPN 金额（分）")
    export_fen: int = Field(..., description="总出口金额（分）")
    exempt_fen: int = Field(..., description="总豁免金额（分）")
    total_ppn_fen: int = Field(..., description="应付 PPN 总额（分）")

    class Config:
        json_schema_extra = {
            "example": {
                "standard_11_fen": 9910,
                "luxury_12_fen": 0,
                "export_fen": 0,
                "exempt_fen": 0,
                "total_ppn_fen": 9910,
            }
        }


class NPWPValidateRequest(BaseModel):
    """NPWP 验证请求"""

    npwp: str = Field(..., description="NPWP 税号")


class NPWPValidateResponse(BaseModel):
    """NPWP 验证结果"""

    valid: bool = Field(..., description="是否合法格式")
    npwp: str = Field(..., description="原始 NPWP")
    npwp_digits: str = Field(..., description="纯数字 NPWP")


# ── 端点 ──────────────────────────────────────────────────────


@router.post("/calculate", response_model=PPNCalculateResponse)
async def calculate_ppn(
    req: PPNCalculateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """计算整单 PPN

    根据每条明细的 PPN 分类分别计算 11%、12% 或豁免金额。
    所有金额单位为分（整数）。
    PPN 采用价内税模式：PPN = amount × rate / (1 + rate)
    """
    try:
        ppn = PPNService(db=db, tenant_id=x_tenant_id)
        items_data = [item.model_dump() for item in req.items]
        result = await ppn.calculate_invoice_ppn(items_data)
        return PPNCalculateResponse(
            standard_11_fen=result["standard_11_fen"],
            luxury_12_fen=result["luxury_12_fen"],
            export_fen=result["export_fen"],
            exempt_fen=result["exempt_fen"],
            total_ppn_fen=result["total_ppn_fen"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rates")
async def get_ppn_rates():
    """查询当前 PPN 税率表"""
    return {"ok": True, "data": PPNService.get_rates()}


@router.get("/categories")
async def get_ppn_categories():
    """查询 PPN 分类选项"""
    return {"ok": True, "data": {"categories": PPNService.get_categories()}}


@router.post("/validate-npwp", response_model=NPWPValidateResponse)
async def validate_npwp(req: NPWPValidateRequest):
    """验证印尼 NPWP 税号格式

    NPWP 格式：15 位数字（法人）或 16 位数字（个人，2024 新规）。
    本端点仅验证格式，不校验 DJP 注册状态。
    """
    digits = req.npwp.replace(".", "").replace("-", "")
    valid = PPNService.validate_npwp(req.npwp)
    return NPWPValidateResponse(
        valid=valid,
        npwp=req.npwp,
        npwp_digits=digits,
    )
