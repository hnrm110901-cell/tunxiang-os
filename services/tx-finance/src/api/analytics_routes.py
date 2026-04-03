"""财务分析 API 端点 (D5)

5 个端点：营收构成、折扣结构、优惠券成本、门店利润、财务稽核
所有硬编码0已替换为真实 finance_analytics 服务调用。
"""
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from services.finance_analytics import (
    coupon_cost_analysis,
    discount_structure,
    financial_audit_view,
    revenue_composition,
    store_profit_analysis,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/finance/analytics", tags=["finance-analytics"])


# ── 依赖注入 ──────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    return x_tenant_id


# ── 1. 营收构成分析 ──────────────────────────────────────────

@router.get("/revenue-composition")
async def get_revenue_composition(
    store_id: str = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """营收构成分析 — 按来源(堂食/外卖/宴席)、按支付方式(微信/支付宝/现金/会员/挂账)"""
    try:
        data = await revenue_composition(
            store_id=store_id,
            date_range=(start_date, end_date),
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_revenue_composition.failed",
            store_id=store_id, error=str(exc), exc_info=True,
        )
        raise HTTPException(status_code=500, detail="营收构成分析失败") from exc

    return {"ok": True, "data": data}


# ── 2. 折扣结构分析 ──────────────────────────────────────────

@router.get("/discount-structure")
async def get_discount_structure(
    store_id: str = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """折扣结构分析 — 会员折扣/活动/赠菜/员工餐"""
    try:
        data = await discount_structure(
            store_id=store_id,
            date_range=(start_date, end_date),
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_discount_structure.failed",
            store_id=store_id, error=str(exc), exc_info=True,
        )
        raise HTTPException(status_code=500, detail="折扣结构分析失败") from exc

    return {"ok": True, "data": data}


# ── 3. 优惠券成本分析 ────────────────────────────────────────

@router.get("/coupon-cost")
async def get_coupon_cost_analysis(
    store_id: str = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """优惠券成本与 ROI 分析"""
    try:
        data = await coupon_cost_analysis(
            store_id=store_id,
            date_range=(start_date, end_date),
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_coupon_cost_analysis.failed",
            store_id=store_id, error=str(exc), exc_info=True,
        )
        raise HTTPException(status_code=500, detail="优惠券成本分析失败") from exc

    return {"ok": True, "data": data}


# ── 4. 门店利润分析 ──────────────────────────────────────────

@router.get("/store-profit")
async def get_store_profit_analysis(
    store_id: str = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店利润分析 — 营收、食材成本、人力、租金、利润率"""
    try:
        data = await store_profit_analysis(
            store_id=store_id,
            date_range=(start_date, end_date),
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_store_profit_analysis.failed",
            store_id=store_id, error=str(exc), exc_info=True,
        )
        raise HTTPException(status_code=500, detail="门店利润分析失败") from exc

    return {"ok": True, "data": data}


# ── 5. 财务稽核视图 ──────────────────────────────────────────

@router.get("/audit-view")
async def get_financial_audit_view(
    store_id: str = Query(..., description="门店 ID"),
    date: str = Query(..., description="稽核日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """财务稽核视图 — 当日收支明细、退菜、赠菜、异常订单"""
    try:
        data = await financial_audit_view(
            store_id=store_id,
            audit_date=date,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_financial_audit_view.failed",
            store_id=store_id, error=str(exc), exc_info=True,
        )
        raise HTTPException(status_code=500, detail="财务稽核视图生成失败") from exc

    return {"ok": True, "data": data}
