"""E7 员工绩效 API 路由

端点:
  POST /api/v1/ops/performance/calculate    计算员工当日绩效
  GET  /api/v1/ops/performance              查询员工绩效
  GET  /api/v1/ops/performance/ranking      员工当日排行

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/performance", tags=["ops-performance"])
log = structlog.get_logger(__name__)

_VALID_ROLES = {"cashier", "chef", "waiter", "runner"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CalculatePerformanceRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    perf_date: date = Field(..., description="绩效日期")
    recalculate: bool = Field(False, description="已存在时是否强制重算")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  聚合查询（生产替换为 asyncpg）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _aggregate_cashier_performance(store_id: str, perf_date: date, tenant_id: str) -> List[Dict[str, Any]]:
    """
    收银员绩效聚合。
    生产替换为 asyncpg:
      SELECT cashier_id AS employee_id,
             cashier_name AS employee_name,
             COUNT(*) AS orders_handled,
             SUM(actual_amount_fen) AS revenue_generated_fen
      FROM orders
      WHERE store_id = $1
        AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = $2
        AND cashier_id IS NOT NULL
        AND tenant_id = current_setting('app.tenant_id')::uuid
        AND is_deleted = false
      GROUP BY cashier_id, cashier_name;
    """
    return []


async def _aggregate_chef_performance(store_id: str, perf_date: date, tenant_id: str) -> List[Dict[str, Any]]:
    """
    厨师绩效聚合。
    生产替换为 asyncpg:
      SELECT assigned_chef_id AS employee_id,
             assigned_chef_name AS employee_name,
             COUNT(*) AS dishes_completed
      FROM kds_tasks
      WHERE store_id = $1
        AND DATE(finished_at AT TIME ZONE 'Asia/Shanghai') = $2
        AND status = 'done'
        AND assigned_chef_id IS NOT NULL
        AND tenant_id = current_setting('app.tenant_id')::uuid
        AND is_deleted = false
      GROUP BY assigned_chef_id, assigned_chef_name;
    """
    return []


async def _aggregate_waiter_performance(store_id: str, perf_date: date, tenant_id: str) -> List[Dict[str, Any]]:
    """
    服务员绩效聚合。
    生产替换为 asyncpg:
      SELECT waiter_id AS employee_id,
             waiter_name AS employee_name,
             COUNT(DISTINCT table_id) AS tables_served,
             COUNT(*) AS orders_handled,
             AVG(service_score) AS avg_service_score
      FROM orders
      WHERE store_id = $1
        AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = $2
        AND waiter_id IS NOT NULL
        AND tenant_id = current_setting('app.tenant_id')::uuid
        AND is_deleted = false
      GROUP BY waiter_id, waiter_name;
    """
    return []


def _calc_commission_fen(role: str, data: Dict[str, Any]) -> int:
    """基础提成计算（简单规则，生产可替换为复杂佣金引擎）。"""
    if role == "cashier":
        # 经手金额的 0.1%
        return int(data.get("revenue_generated_fen", 0) * 0.001)
    if role == "chef":
        # 每完成一道菜 5 分
        return data.get("dishes_completed", 0) * 500
    if role == "waiter":
        # 每服务一桌 10 分
        return data.get("tables_served", 0) * 1000
    return 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  注意：ranking 路由必须在通用 GET 前定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/ranking")
async def get_performance_ranking(
    perf_date: date = Query(..., description="绩效日期"),
    store_id: Optional[str] = Query(None, description="门店ID，为空则跨门店排名"),
    role: Optional[str] = Query(None, description="角色筛选"),
    top_n: int = Query(10, ge=1, le=50, description="取前N名"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E7: 员工当日绩效排行。按基础提成降序。"""
    if role and role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role 必须是 {_VALID_ROLES} 之一")

    try:
        await _set_tenant(db, x_tenant_id)

        filters = ["stat_date = :perf_date", "is_deleted = false"]
        params: Dict[str, Any] = {"perf_date": perf_date, "top_n": top_n}

        if store_id:
            filters.append("store_id = :store_id")
            params["store_id"] = store_id
        if role:
            filters.append("role = :role")
            params["role"] = role

        where_clause = " AND ".join(filters)

        # 先查总数
        count_sql = text(f"SELECT COUNT(*) FROM staff_performance_records WHERE {where_clause}")
        total_result = await db.execute(count_sql, params)
        total_employees: int = total_result.scalar_one()

        # 取排名
        ranking_sql = text(
            f"""
            SELECT id, tenant_id::text, store_id::text, stat_date::text,
                   employee_id::text, employee_name, role,
                   orders_handled, revenue_generated_fen,
                   dishes_completed, tables_served,
                   avg_service_score, base_commission_fen,
                   created_at::text, updated_at::text
            FROM staff_performance_records
            WHERE {where_clause}
            ORDER BY base_commission_fen DESC
            LIMIT :top_n
            """
        )
        rows = await db.execute(ranking_sql, params)
        keys = rows.keys()
        ranked = [dict(zip(keys, row)) for row in rows.fetchall()]
        for i, p in enumerate(ranked):
            p["rank"] = i + 1

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("get_performance_ranking_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库查询失败")

    return {
        "ok": True,
        "data": {
            "perf_date": perf_date.isoformat(),
            "role": role,
            "store_id": store_id,
            "total_employees": total_employees,
            "ranking": ranked,
        },
    }


@router.post("/calculate", status_code=201)
async def calculate_performance(
    body: CalculatePerformanceRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    E7: 计算指定门店某日所有员工绩效。
    从 KDS 任务 / 订单聚合数据，写入 staff_performance_records 表。
    """
    now = datetime.now(tz=timezone.utc)
    date_str = body.perf_date.isoformat()
    created_count = 0
    updated_count = 0
    result_ids: List[str] = []

    # 各角色聚合
    cashier_data = await _aggregate_cashier_performance(body.store_id, body.perf_date, x_tenant_id)
    chef_data = await _aggregate_chef_performance(body.store_id, body.perf_date, x_tenant_id)
    waiter_data = await _aggregate_waiter_performance(body.store_id, body.perf_date, x_tenant_id)

    all_employees: List[tuple[str, List[Dict[str, Any]]]] = [
        ("cashier", cashier_data),
        ("chef", chef_data),
        ("waiter", waiter_data),
    ]

    try:
        await _set_tenant(db, x_tenant_id)

        for role, emp_list in all_employees:
            for emp in emp_list:
                employee_id = emp["employee_id"]
                commission = _calc_commission_fen(role, emp)

                if body.recalculate:
                    # UPSERT：强制重算时始终覆盖
                    upsert_sql = text("""
                        INSERT INTO staff_performance_records (
                            tenant_id, store_id, stat_date, employee_id, employee_name,
                            role, orders_handled, revenue_generated_fen,
                            dishes_completed, tables_served, avg_service_score,
                            base_commission_fen, updated_at
                        ) VALUES (
                            :tenant_id::uuid, :store_id::uuid, :stat_date, :employee_id::uuid,
                            :employee_name, :role, :orders_handled, :revenue_generated_fen,
                            :dishes_completed, :tables_served, :avg_service_score,
                            :base_commission_fen, :now
                        )
                        ON CONFLICT (tenant_id, store_id, stat_date, employee_id)
                        DO UPDATE SET
                            employee_name         = EXCLUDED.employee_name,
                            role                  = EXCLUDED.role,
                            orders_handled        = EXCLUDED.orders_handled,
                            revenue_generated_fen = EXCLUDED.revenue_generated_fen,
                            dishes_completed      = EXCLUDED.dishes_completed,
                            tables_served         = EXCLUDED.tables_served,
                            avg_service_score     = EXCLUDED.avg_service_score,
                            base_commission_fen   = EXCLUDED.base_commission_fen,
                            updated_at            = EXCLUDED.updated_at
                        RETURNING id::text,
                            (xmax = 0) AS was_inserted
                    """)
                else:
                    # INSERT only（已存在则跳过）
                    upsert_sql = text("""
                        INSERT INTO staff_performance_records (
                            tenant_id, store_id, stat_date, employee_id, employee_name,
                            role, orders_handled, revenue_generated_fen,
                            dishes_completed, tables_served, avg_service_score,
                            base_commission_fen, updated_at
                        ) VALUES (
                            :tenant_id::uuid, :store_id::uuid, :stat_date, :employee_id::uuid,
                            :employee_name, :role, :orders_handled, :revenue_generated_fen,
                            :dishes_completed, :tables_served, :avg_service_score,
                            :base_commission_fen, :now
                        )
                        ON CONFLICT (tenant_id, store_id, stat_date, employee_id)
                        DO NOTHING
                        RETURNING id::text,
                            true AS was_inserted
                    """)

                row = await db.execute(
                    upsert_sql,
                    {
                        "tenant_id": x_tenant_id,
                        "store_id": body.store_id,
                        "stat_date": body.perf_date,
                        "employee_id": employee_id,
                        "employee_name": emp.get("employee_name", ""),
                        "role": role,
                        "orders_handled": emp.get("orders_handled", 0),
                        "revenue_generated_fen": emp.get("revenue_generated_fen", 0),
                        "dishes_completed": emp.get("dishes_completed", 0),
                        "tables_served": emp.get("tables_served", 0),
                        "avg_service_score": emp.get("avg_service_score"),
                        "base_commission_fen": commission,
                        "now": now,
                    },
                )
                fetched = row.fetchone()
                if fetched:
                    perf_id, was_inserted = fetched
                    result_ids.append(perf_id)
                    if was_inserted:
                        created_count += 1
                    else:
                        updated_count += 1
                # DO NOTHING 时 fetched 为 None（记录已存在且不强制重算），不计入统计

        await db.commit()

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error(
            "calculate_performance_db_error",
            error=str(exc),
            store_id=body.store_id,
            perf_date=date_str,
            tenant_id=x_tenant_id,
        )
        raise HTTPException(status_code=500, detail="绩效写入失败")

    log.info(
        "performance_calculated",
        store_id=body.store_id,
        perf_date=date_str,
        created=created_count,
        updated=updated_count,
        tenant_id=x_tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "perf_date": date_str,
            "employee_count": len(result_ids),
            "created": created_count,
            "updated": updated_count,
            "performance_ids": result_ids,
        },
    }


@router.get("")
async def list_performance(
    store_id: str = Query(..., description="门店ID"),
    perf_date: Optional[date] = Query(None, description="绩效日期，默认今日"),
    role: Optional[str] = Query(None, description="角色筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E7: 查询门店员工绩效列表。"""
    if role and role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role 必须是 {_VALID_ROLES} 之一")

    target_date = perf_date or date.today()

    try:
        await _set_tenant(db, x_tenant_id)

        filters = ["store_id = :store_id", "stat_date = :stat_date", "is_deleted = false"]
        params: Dict[str, Any] = {
            "store_id": store_id,
            "stat_date": target_date,
            "offset": (page - 1) * size,
            "size": size,
        }

        if role:
            filters.append("role = :role")
            params["role"] = role

        where_clause = " AND ".join(filters)

        count_sql = text(f"SELECT COUNT(*) FROM staff_performance_records WHERE {where_clause}")
        total_result = await db.execute(count_sql, params)
        total: int = total_result.scalar_one()

        list_sql = text(
            f"""
            SELECT id::text, tenant_id::text, store_id::text, stat_date::text,
                   employee_id::text, employee_name, role,
                   orders_handled, revenue_generated_fen,
                   dishes_completed, tables_served,
                   avg_service_score, base_commission_fen,
                   created_at::text, updated_at::text
            FROM staff_performance_records
            WHERE {where_clause}
            ORDER BY base_commission_fen DESC
            LIMIT :size OFFSET :offset
            """
        )
        rows = await db.execute(list_sql, params)
        keys = rows.keys()
        items = [dict(zip(keys, row)) for row in rows.fetchall()]

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("list_performance_db_error", error=str(exc), store_id=store_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库查询失败")

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
    }
