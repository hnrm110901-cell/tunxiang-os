"""预制量智能推荐 API 路由"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.kds_prep_recommendation import get_prep_recommendations

router = APIRouter(prefix="/api/v1/kds/prep", tags=["kds-prep"])


@router.get("/recommendations")
async def api_prep_recommendations(
    store_id: str,
    dept_id: Optional[str] = Query(default=None),
    target_date: Optional[date] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取当日备料推荐。

    算法：历史4周同星期平均销量 × 节假日系数 × 预订加成 × 1.1安全系数。

    - dept_id: 按档口过滤（可选，不传则返回全店所有档口）
    - target_date: 目标日期（可选，默认今天）
    """
    items = await get_prep_recommendations(
        tenant_id=x_tenant_id,
        store_id=store_id,
        dept_id=dept_id,
        target_date=target_date,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
            "target_date": (target_date or date.today()).isoformat(),
        },
    }
