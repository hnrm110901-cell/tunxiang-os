"""马来西亚 SST 税引擎 API 端点（Sprint 1.3）

3 个端点：
  - POST /api/v1/sst/calculate   计算 SST
  - GET  /api/v1/sst/rates       查询当前税率表
  - GET  /api/v1/sst/categories  查询 SST 分类选项
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.sst_service import SSTService

router = APIRouter(prefix="/api/v1/sst", tags=["sst"])


# ── 请求/响应模型 ─────────────────────────────────────────────


class SSTItem(BaseModel):
    """SST 计算请求中的单条明细"""

    amount_fen: int = Field(..., description="该项金额（分）")
    sst_category: str = Field(default="standard", description="SST分类: standard/specific/exempt")


class SSTCalculateRequest(BaseModel):
    """SST 计算请求"""

    items: list[SSTItem] = Field(..., min_length=1, description="订单明细列表")


class SSTCalculateResponse(BaseModel):
    """SST 计算结果"""

    standard_6_fen: int = Field(..., description="总 6% SST 金额（分）")
    specific_8_fen: int = Field(..., description="总 8% SST 金额（分）")
    exempt_fen: int = Field(..., description="总豁免金额（分）")
    total_sst_fen: int = Field(..., description="应付 SST 总额（分）")

    class Config:
        json_schema_extra = {
            "example": {
                "standard_6_fen": 566,
                "specific_8_fen": 0,
                "exempt_fen": 0,
                "total_sst_fen": 566,
            }
        }


# ── 端点 ──────────────────────────────────────────────────────


@router.post("/calculate", response_model=SSTCalculateResponse)
async def calculate_sst(
    req: SSTCalculateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """计算整单 SST

    根据每条明细的 SST 分类分别计算 6%、8% 或豁免金额。
    所有金额单位为分（整数）。
    SST 采用价内税模式：SST = price × rate / (1 + rate)
    """
    try:
        sst = SSTService(db=db, tenant_id=x_tenant_id)
        items_data = [item.model_dump() for item in req.items]
        result = await sst.calculate_invoice_sst(items_data)
        return SSTCalculateResponse(
            standard_6_fen=result["standard_6_fen"],
            specific_8_fen=result["specific_8_fen"],
            exempt_fen=result["exempt_fen"],
            total_sst_fen=result["total_sst_fen"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rates")
async def get_sst_rates():
    """查询当前 SST 税率表"""
    return {"ok": True, "data": SSTService.get_rates()}


@router.get("/categories")
async def get_sst_categories():
    """查询 SST 分类选项"""
    return {"ok": True, "data": {"categories": SSTService.get_categories()}}
