"""厨师绩效计件服务

功能：
  1. 每次厨师完成出品时，实时累加其当日绩效（upsert chef_performance_daily）
  2. 查询厨师绩效排行（当日/本周/本月）
  3. 查询单个厨师的绩效明细
  4. 班次结束时汇总结算

绩效维度：
  - dish_count    出品菜品数量（最直接的计件依据）
  - dish_amount   出品菜品金额合计（与计件单价联动）
  - avg_cook_sec  平均制作时长（衡量效率）
  - rush_handled  处理催菜次数
  - remake_count  返工次数（负绩效参考）
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chef_performance_daily import ChefPerformanceDaily

logger = structlog.get_logger()


async def record_dish_completed(
    tenant_id: str,
    store_id: str,
    dept_id: str,
    operator_id: str,
    cook_sec: int,
    dish_amount: Decimal,
    db: AsyncSession,
) -> None:
    """厨师完成出品时调用，累加当日绩效。使用 UPSERT 保证幂等。"""
    today = date.today()

    # PostgreSQL UPSERT：冲突时累加字段
    stmt = pg_insert(ChefPerformanceDaily).values(
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(store_id),
        dept_id=uuid.UUID(dept_id),
        operator_id=uuid.UUID(operator_id),
        perf_date=today,
        dish_count=1,
        dish_amount=dish_amount,
        avg_cook_sec=cook_sec,
        rush_handled=0,
        remake_count=0,
    ).on_conflict_do_update(
        constraint="uq_chef_perf_daily",
        set_={
            # 累加菜品数和金额
            "dish_count": ChefPerformanceDaily.dish_count + 1,
            "dish_amount": ChefPerformanceDaily.dish_amount + dish_amount,
            # 滚动平均制作时长
            "avg_cook_sec": (
                (ChefPerformanceDaily.avg_cook_sec * ChefPerformanceDaily.dish_count + cook_sec)
                / (ChefPerformanceDaily.dish_count + 1)
            ).cast(type_=type(ChefPerformanceDaily.avg_cook_sec.type)),
            "updated_at": datetime.now(timezone.utc),
        }
    )
    await db.execute(stmt)
    # 注意：调用方负责 commit


async def record_rush_handled(
    tenant_id: str,
    operator_id: str,
    dept_id: str,
    db: AsyncSession,
) -> None:
    """厨师处理催菜时累加 rush_handled 计数。"""
    today = date.today()
    await db.execute(
        text("""
            UPDATE chef_performance_daily
            SET rush_handled = rush_handled + 1,
                updated_at   = NOW()
            WHERE tenant_id  = :tenant_id
              AND operator_id = :operator_id
              AND dept_id     = :dept_id
              AND perf_date   = :today
        """),
        {
            "tenant_id": tenant_id,
            "operator_id": operator_id,
            "dept_id": dept_id,
            "today": today,
        },
    )


async def record_remake(
    tenant_id: str,
    operator_id: str,
    dept_id: str,
    db: AsyncSession,
) -> None:
    """记录返工次数（负向指标）。"""
    today = date.today()
    await db.execute(
        text("""
            UPDATE chef_performance_daily
            SET remake_count = remake_count + 1,
                updated_at   = NOW()
            WHERE tenant_id  = :tenant_id
              AND operator_id = :operator_id
              AND dept_id     = :dept_id
              AND perf_date   = :today
        """),
        {
            "tenant_id": tenant_id,
            "operator_id": operator_id,
            "dept_id": dept_id,
            "today": today,
        },
    )


async def get_leaderboard(
    tenant_id: str,
    store_id: str,
    period: str,  # 'today' | 'week' | 'month'
    dept_id: Optional[str],
    db: AsyncSession,
) -> list[dict]:
    """厨师绩效排行榜。"""
    today = date.today()
    if period == "today":
        start_date = today
    elif period == "week":
        start_date = today - timedelta(days=today.weekday())
    else:  # month
        start_date = today.replace(day=1)

    conditions = [
        ChefPerformanceDaily.tenant_id == uuid.UUID(tenant_id),
        ChefPerformanceDaily.store_id == uuid.UUID(store_id),
        ChefPerformanceDaily.perf_date >= start_date,
        ChefPerformanceDaily.is_deleted.is_(False),
    ]
    if dept_id:
        conditions.append(ChefPerformanceDaily.dept_id == uuid.UUID(dept_id))

    result = await db.execute(
        select(
            ChefPerformanceDaily.operator_id,
            func.sum(ChefPerformanceDaily.dish_count).label("total_dishes"),
            func.sum(ChefPerformanceDaily.dish_amount).label("total_amount"),
            func.avg(ChefPerformanceDaily.avg_cook_sec).label("avg_cook_sec"),
            func.sum(ChefPerformanceDaily.rush_handled).label("rush_handled"),
            func.sum(ChefPerformanceDaily.remake_count).label("remake_count"),
        )
        .where(*conditions)
        .group_by(ChefPerformanceDaily.operator_id)
        .order_by(func.sum(ChefPerformanceDaily.dish_count).desc())
        .limit(20)
    )
    rows = result.all()
    return [
        {
            "operator_id": str(r.operator_id),
            "total_dishes": int(r.total_dishes or 0),
            "total_amount": float(r.total_amount or 0),
            "avg_cook_sec": int(r.avg_cook_sec or 0),
            "rush_handled": int(r.rush_handled or 0),
            "remake_count": int(r.remake_count or 0),
        }
        for r in rows
    ]


async def get_chef_daily_detail(
    tenant_id: str,
    operator_id: str,
    start_date: date,
    end_date: date,
    db: AsyncSession,
) -> list[dict]:
    """查询单个厨师的每日绩效明细。"""
    result = await db.execute(
        select(ChefPerformanceDaily)
        .where(
            ChefPerformanceDaily.tenant_id == uuid.UUID(tenant_id),
            ChefPerformanceDaily.operator_id == uuid.UUID(operator_id),
            ChefPerformanceDaily.perf_date >= start_date,
            ChefPerformanceDaily.perf_date <= end_date,
            ChefPerformanceDaily.is_deleted.is_(False),
        )
        .order_by(ChefPerformanceDaily.perf_date.desc())
    )
    rows = result.scalars().all()
    return [
        {
            "date": r.perf_date.isoformat(),
            "dept_id": str(r.dept_id),
            "dish_count": r.dish_count,
            "dish_amount": float(r.dish_amount),
            "avg_cook_sec": r.avg_cook_sec,
            "rush_handled": r.rush_handled,
            "remake_count": r.remake_count,
        }
        for r in rows
    ]
