"""金蝶ERP对接 API 路由 — 8个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需要 X-Tenant-ID header。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/kingdee", tags=["kingdee"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MonthExportRequest(BaseModel):
    store_id: str
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")


class DailyExportRequest(BaseModel):
    store_id: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")


class RetryRequest(BaseModel):
    export_id: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  依赖注入占位
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _get_db():
    """数据库会话依赖 — 由 main.py 覆盖"""
    raise NotImplementedError("DB session dependency not configured")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 采购入库汇总导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/purchase-receipt")
async def api_export_purchase_receipt(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """采购入库汇总 → 金蝶凭证"""
    from services.kingdee_bridge import export_purchase_receipt

    try:
        result = await export_purchase_receipt(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 成本结转导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/cost-transfer")
async def api_export_cost_transfer(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """成本结转汇总 → 金蝶凭证"""
    from services.kingdee_bridge import export_cost_transfer

    try:
        result = await export_cost_transfer(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 调拨出入库导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/transfer")
async def api_export_transfer(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """调拨出入库汇总 → 金蝶凭证"""
    from services.kingdee_bridge import export_transfer_in_out

    try:
        result = await export_transfer_in_out(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 工资计提导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/salary-accrual")
async def api_export_salary_accrual(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """工资计提 → 金蝶凭证"""
    from services.kingdee_bridge import export_salary_accrual

    try:
        result = await export_salary_accrual(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 收营日报导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/daily-revenue")
async def api_export_daily_revenue(
    req: DailyExportRequest,
    x_tenant_id: str = Header(...),
):
    """收营日报 → 金蝶凭证"""
    from services.kingdee_bridge import export_daily_revenue

    try:
        result = await export_daily_revenue(
            req.store_id, req.date, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 销售出库导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/sales-delivery")
async def api_export_sales_delivery(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """销售出库汇总 → 金蝶凭证"""
    from services.kingdee_bridge import export_sales_delivery

    try:
        result = await export_sales_delivery(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 导出历史
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/export/history")
async def api_export_history(
    x_tenant_id: str = Header(...),
    store_id: Optional[str] = None,
    export_type: Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    """查询金蝶导出历史"""
    from services.kingdee_bridge import get_export_history

    result = await get_export_history(
        x_tenant_id, _get_db,
        store_id=store_id,
        export_type=export_type,
        page=page,
        page_size=size,
    )
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 重试失败导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/retry")
async def api_retry_export(
    req: RetryRequest,
    x_tenant_id: str = Header(...),
):
    """重试失败的金蝶导出"""
    from services.kingdee_bridge import retry_failed_export

    try:
        result = await retry_failed_export(
            req.export_id, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
