"""E7 员工绩效 API 路由

端点:
  POST /api/v1/ops/performance/calculate    计算员工当日绩效
  GET  /api/v1/ops/performance              查询员工绩效
  GET  /api/v1/ops/performance/ranking      员工当日排行

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/performance", tags=["ops-performance"])
log = structlog.get_logger(__name__)

_VALID_ROLES = {"cashier", "chef", "waiter", "runner"}

# ─── 内存存储────────────────────────────────────────────────────────────────
# key: f"{tenant_id}:{store_id}:{perf_date}:{employee_id}"
_performance: Dict[str, Dict[str, Any]] = {}


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


async def _aggregate_cashier_performance(
    store_id: str, perf_date: date, tenant_id: str
) -> List[Dict[str, Any]]:
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


async def _aggregate_chef_performance(
    store_id: str, perf_date: date, tenant_id: str
) -> List[Dict[str, Any]]:
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


async def _aggregate_waiter_performance(
    store_id: str, perf_date: date, tenant_id: str
) -> List[Dict[str, Any]]:
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
) -> Dict[str, Any]:
    """E7: 员工当日绩效排行。按基础提成降序。"""
    if role and role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role 必须是 {_VALID_ROLES} 之一")

    date_str = perf_date.isoformat()
    items = [
        p for p in _performance.values()
        if p["tenant_id"] == x_tenant_id
        and p["perf_date"] == date_str
        and (store_id is None or p["store_id"] == store_id)
        and (role is None or p["role"] == role)
    ]

    items.sort(key=lambda p: p["base_commission_fen"], reverse=True)
    ranked = items[:top_n]
    for i, p in enumerate(ranked):
        p["rank"] = i + 1

    return {
        "ok": True,
        "data": {
            "perf_date": date_str,
            "role": role,
            "store_id": store_id,
            "total_employees": len(items),
            "ranking": ranked,
        },
    }


@router.post("/calculate", status_code=201)
async def calculate_performance(
    body: CalculatePerformanceRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """
    E7: 计算指定门店某日所有员工绩效。
    从 KDS 任务 / 订单聚合数据，写入 employee_daily_performance 表。
    """
    now = datetime.now(tz=timezone.utc)
    date_str = body.perf_date.isoformat()
    created_count = 0
    updated_count = 0

    # 各角色聚合
    cashier_data = await _aggregate_cashier_performance(
        body.store_id, body.perf_date, x_tenant_id
    )
    chef_data = await _aggregate_chef_performance(
        body.store_id, body.perf_date, x_tenant_id
    )
    waiter_data = await _aggregate_waiter_performance(
        body.store_id, body.perf_date, x_tenant_id
    )

    all_employees: List[tuple[str, List[Dict[str, Any]]]] = [
        ("cashier", cashier_data),
        ("chef", chef_data),
        ("waiter", waiter_data),
    ]

    result_ids: List[str] = []

    for role, emp_list in all_employees:
        for emp in emp_list:
            employee_id = emp["employee_id"]
            key = f"{x_tenant_id}:{body.store_id}:{date_str}:{employee_id}"
            existing = _performance.get(key)

            if existing and not body.recalculate:
                result_ids.append(existing["id"])
                continue

            commission = _calc_commission_fen(role, emp)
            perf_id = existing["id"] if existing else str(uuid.uuid4())

            record: Dict[str, Any] = {
                "id": perf_id,
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "perf_date": date_str,
                "employee_id": employee_id,
                "employee_name": emp.get("employee_name", ""),
                "role": role,
                "orders_handled": emp.get("orders_handled", 0),
                "revenue_generated_fen": emp.get("revenue_generated_fen", 0),
                "dishes_completed": emp.get("dishes_completed", 0),
                "tables_served": emp.get("tables_served", 0),
                "avg_service_score": emp.get("avg_service_score"),
                "base_commission_fen": commission,
                "created_at": existing["created_at"] if existing else now.isoformat(),
                "updated_at": now.isoformat(),
            }
            _performance[key] = record
            result_ids.append(perf_id)

            if existing:
                updated_count += 1
            else:
                created_count += 1

    log.info("performance_calculated", store_id=body.store_id,
             perf_date=date_str, created=created_count, updated=updated_count,
             tenant_id=x_tenant_id)

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
) -> Dict[str, Any]:
    """E7: 查询门店员工绩效列表。"""
    if role and role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role 必须是 {_VALID_ROLES} 之一")

    target_date = (perf_date or date.today()).isoformat()

    items = [
        p for p in _performance.values()
        if p["tenant_id"] == x_tenant_id
        and p["store_id"] == store_id
        and p["perf_date"] == target_date
        and (role is None or p["role"] == role)
    ]

    items.sort(key=lambda p: p["base_commission_fen"], reverse=True)

    total = len(items)
    start = (page - 1) * size
    paginated = items[start: start + size]

    return {"ok": True, "data": {"items": paginated, "total": total, "page": page, "size": size}}
