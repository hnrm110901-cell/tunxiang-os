"""投影器管理 API

端点：
  GET  /api/v1/projectors/status            — 所有投影器运行状态
  POST /api/v1/projectors/rebuild/{name}    — 重建指定投影器视图
  GET  /api/v1/projectors/discount-health   — 折扣健康视图快照（Phase 3 验证接口）
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from ..services.projector_runner import get_runner

router = APIRouter(prefix="/api/v1/projectors", tags=["projectors"])


@router.get("/status")
async def get_projector_status(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """返回所有投影器的运行状态。"""
    runner = get_runner()
    statuses = runner.get_status()
    # 只返回当前租户的状态
    tenant_statuses = [s for s in statuses if s["tenant_id"] == x_tenant_id]
    return {"ok": True, "data": tenant_statuses}


@router.post("/rebuild/{projector_name}")
async def rebuild_projector(
    projector_name: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """从事件流完整重建指定投影器的物化视图。

    当视图数据异常或需要从头重建时调用。
    注意：重建时间取决于事件总量，可能需要数秒到数分钟。
    """
    runner = get_runner()
    try:
        result = await runner.rebuild(projector_name, x_tenant_id)
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/discount-health")
async def get_discount_health_snapshot(
    store_id: str = Query(..., description="门店ID"),
    stat_date: Optional[date] = Query(None, description="统计日期，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """直接读取 mv_discount_health 视图数据（Phase 3 验证）。

    这是最快路径：无跨服务调用，直接从投影视图读取。
    用于验证 Phase 3 切换效果（vs 旧的跨服务查询模式）。
    """
    import os
    import asyncpg

    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tunxiang")
    today = stat_date or date.today()

    try:
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, TRUE)",
                x_tenant_id,
            )
            row = await conn.fetchrow(
                """
                SELECT
                    total_orders, discounted_orders, discount_rate,
                    total_discount_fen, unauthorized_count, threshold_breaches,
                    leak_types, updated_at
                FROM mv_discount_health
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                x_tenant_id,
                store_id,
                today,
            )
        finally:
            await conn.close()

        if not row:
            return {
                "ok": True,
                "data": {
                    "store_id": store_id,
                    "stat_date": today.isoformat(),
                    "message": "暂无数据，投影器可能尚未处理今日事件",
                },
            }

        data = dict(row)
        data["stat_date"] = today.isoformat()
        data["store_id"] = store_id
        data["total_discount_yuan"] = round(int(data.get("total_discount_fen", 0)) / 100, 2)
        data["source"] = "mv_discount_health"
        if data.get("updated_at"):
            data["updated_at"] = data["updated_at"].isoformat()

        return {"ok": True, "data": data}

    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取物化视图失败: {exc}")
