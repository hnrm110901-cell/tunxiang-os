"""厨师绩效计件 API 路由"""
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.kds_chef_stats import get_chef_daily_detail, get_leaderboard

router = APIRouter(prefix="/api/v1/kds/chef-stats", tags=["kds-chef-stats"])


@router.get("/leaderboard")
async def api_chef_leaderboard(
    store_id: str,
    period: Literal["today", "week", "month"] = Query(default="today"),
    dept_id: Optional[str] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """厨师绩效排行榜。

    - period: today/week/month
    - dept_id: 按档口过滤（可选）

    返回按出品数量倒序的厨师排行，含出品数、金额、平均制作时长、催菜处理数、返工数。
    """
    leaderboard = await get_leaderboard(
        tenant_id=x_tenant_id,
        store_id=store_id,
        period=period,
        dept_id=dept_id,
        db=db,
    )
    return {"ok": True, "data": {"items": leaderboard, "period": period}}


@router.get("/{operator_id}")
async def api_chef_detail(
    operator_id: str,
    days: int = Query(default=30, ge=1, le=90),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询单个厨师的每日绩效明细（最近N天）。"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    detail = await get_chef_daily_detail(
        tenant_id=x_tenant_id,
        operator_id=operator_id,
        start_date=start_date,
        end_date=end_date,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "operator_id": operator_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "items": detail,
        },
    }
