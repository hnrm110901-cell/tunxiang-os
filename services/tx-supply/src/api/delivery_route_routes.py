"""配送路线规划 API

中央厨房 → 多门店配送路线规划、司机任务单、配送进度追踪。

路由前缀：/api/v1/supply/delivery-route
认证头：X-Tenant-ID（所有接口必填）

端点列表：
  POST /plan                              路线规划（中央厨房 → 多门店，支持高德/贪心双模式）
  GET  /{route_id}/driver-task           司机工作任务单（按顺序显示各门店配送内容）
  POST /{route_id}/progress              更新配送进度（departed/arrived/delivered）
  POST /{route_id}/optimize              重新优化已有配送单路线
"""

from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/delivery-route",
    tags=["delivery_route"],
)

_svc = None  # lazy singleton，避免循环导入


def _get_svc():
    global _svc
    if _svc is None:
        from ..services.delivery_route_service import DeliveryRouteService

        _svc = DeliveryRouteService()
    return _svc


# ─── 请求体模型（Pydantic V2） ─────────────────────────────────────────────────


class PlanRouteRequest(BaseModel):
    """路线规划请求。"""

    kitchen_id: str = Field(..., description="中央厨房 ID（出发点）")
    store_ids: List[str] = Field(..., min_length=1, description="目标门店 ID 列表")
    plan_date: Optional[str] = Field(default=None, description="配送日期（YYYY-MM-DD），留空取今日")


class UpdateProgressRequest(BaseModel):
    """配送进度更新请求。"""

    store_id: str = Field(..., description="本次更新的门店 ID")
    status: str = Field(
        ...,
        description="新状态：departed（已出发）/ arrived（已到达）/ delivered（已送达）",
    )
    operator_id: Optional[str] = Field(default=None, description="操作人员工 ID")


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("/plan", summary="配送路线规划", status_code=201)
async def plan_route(
    body: PlanRouteRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """中央厨房 → 多门店配送路线规划。

    - 有 AMAP_API_KEY 环境变量：调用高德驾车路径规划 API，获取真实距离/时间
    - 无 AMAP_API_KEY（默认）：贪心算法，Haversine 距离最近邻排序
    - 返回路线 ID、访问顺序、预估总距离、所用算法
    """
    try:
        result = await _get_svc().plan_route(
            kitchen_id=body.kitchen_id,
            store_ids=body.store_ids,
            tenant_id=x_tenant_id,
            plan_date=body.plan_date,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{route_id}/driver-task", summary="司机工作任务单")
async def get_driver_task(
    route_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """按顺序返回每个门店的配送内容，包含地址/坐标/配送明细/当前状态。
    司机端 App 使用此接口驱动导航和签收流程。
    """
    try:
        result = await _get_svc().get_driver_task(
            route_id=route_id,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{route_id}/progress", summary="更新配送进度")
async def update_delivery_progress(
    route_id: str,
    body: UpdateProgressRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """实时更新单个门店的配送状态：
    - departed：司机已从上一站出发
    - arrived：司机已到达本门店
    - delivered：配送完成（货物已交接）

    所有门店均 delivered 后路线状态自动变为 completed。
    """
    try:
        result = await _get_svc().update_delivery_progress(
            route_id=route_id,
            store_id=body.store_id,
            status=body.status,
            tenant_id=x_tenant_id,
            operator_id=body.operator_id,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{route_id}/optimize", summary="重新优化路线")
async def optimize_route(
    route_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """对已存在的配送单重新做路线优化。
    优先调用高德 API；不可用时降级为地理聚类排序；
    无坐标数据时按 sort_order 顺序。
    """
    try:
        result = await _get_svc().optimize_route(
            trip_id=route_id,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
