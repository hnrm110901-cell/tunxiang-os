"""成本计算 API 路由

# ROUTER REGISTRATION (在tx-finance/src/main.py中添加):
# from .api.cost_routes import router as cost_router
# app.include_router(cost_router, prefix="/api/v1/costs")

端点：
  GET  /costs/order/{order_id}          - 单订单成本明细
  GET  /costs/summary?store_id=&date=   - 日成本汇总
  POST /costs/recompute?store_id=&date= - 触发批量重算
"""
import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from services.tx_finance.src.services.cost_engine import CostEngine

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["costs"])

_engine = CostEngine()


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    """从 X-Tenant-ID header 提取 tenant_id 并返回带 RLS 的 DB session"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 X-Tenant-ID: {x_tenant_id}") from exc


def _parse_date_param(d: str) -> date:
    if d == "today":
        return date.today()
    try:
        return date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {d}，请使用 YYYY-MM-DD") from exc


# ─── GET /costs/order/{order_id} ─────────────────────────────────────────────

@router.get("/order/{order_id}", summary="单订单成本明细")
async def get_order_cost(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取单笔订单的完整成本明细

    - 优先从 cost_snapshots 缓存读取
    - 快照不存在时实时计算并写入缓存
    - 返回每道菜的原料成本、毛利率及BOM版本

    响应字段：
    - items[].dish_id: 菜品ID
    - items[].raw_material_cost: 原料成本（分）
    - items[].gross_margin_rate: 毛利率（0-1）
    - items[].cost_source: 成本来源（bom | standard_cost）
    """
    try:
        oid = uuid.UUID(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 order_id: {order_id}") from exc

    try:
        tid = uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 X-Tenant-ID") from exc

    try:
        margin = await _engine.get_order_margin(oid, tid, db)
    except Exception as exc:
        logger.error("get_order_cost.failed", order_id=order_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="成本计算失败") from exc

    return {"ok": True, "data": margin}


# ─── GET /costs/summary ───────────────────────────────────────────────────────

@router.get("/summary", summary="日成本汇总")
async def get_cost_summary(
    store_id: str = Query(..., description="门店ID"),
    date: str = Query("today", description="业务日期 YYYY-MM-DD 或 today"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店日成本汇总

    从 cost_snapshots 聚合当天所有订单的：
    - 总原料成本
    - 平均毛利率
    - 各菜品成本排行（Top10）
    """
    try:
        sid = uuid.UUID(store_id)
        tid = uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"参数格式错误: {exc}") from exc

    biz_date = _parse_date_param(date)

    try:
        result = await db.execute(
            __import__("sqlalchemy").text("""
                SELECT
                    COUNT(DISTINCT cs.order_id)          AS order_count,
                    COALESCE(SUM(cs.raw_material_cost), 0) AS total_raw_cost,
                    COALESCE(AVG(cs.gross_margin_rate), 0) AS avg_margin,
                    COUNT(cs.id)                         AS snapshot_count
                FROM cost_snapshots cs
                JOIN orders o ON o.id = cs.order_id
                WHERE o.store_id = :store_id::UUID
                  AND cs.tenant_id = :tenant_id::UUID
                  AND DATE(cs.computed_at AT TIME ZONE 'UTC') = :biz_date::DATE
            """),
            {
                "store_id": str(sid),
                "tenant_id": str(tid),
                "biz_date": str(biz_date),
            },
        )
        row = result.fetchone()
    except Exception as exc:
        logger.error("get_cost_summary.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询成本汇总失败") from exc

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "biz_date": str(biz_date),
            "order_count": int(row.order_count) if row else 0,
            "total_raw_cost_fen": int(row.total_raw_cost) if row else 0,
            "avg_gross_margin_rate": float(row.avg_margin) if row else 0.0,
            "snapshot_count": int(row.snapshot_count) if row else 0,
        },
    }


# ─── POST /costs/recompute ───────────────────────────────────────────────────

@router.post("/recompute", summary="触发批量重算")
async def recompute_costs(
    store_id: str = Query(..., description="门店ID"),
    date: str = Query(..., description="业务日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """触发指定门店指定日期的成本批量重算

    适用场景：
    - 采购价格修正后重算历史成本
    - BOM版本更新后刷新成本快照
    - 人工触发数据修复

    此接口为异步写入，可能耗时较长（大店数百笔订单）。
    生产环境建议通过夜批任务调用，而非实时触发。
    """
    try:
        sid = uuid.UUID(store_id)
        tid = uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"参数格式错误: {exc}") from exc

    biz_date = _parse_date_param(date)

    try:
        result = await _engine.batch_recompute_date(sid, biz_date, tid, db)
    except Exception as exc:
        logger.error(
            "recompute_costs.failed",
            store_id=store_id,
            biz_date=str(biz_date),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="批量重算失败") from exc

    return {"ok": True, "data": result}
