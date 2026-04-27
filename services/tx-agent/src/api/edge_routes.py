"""Edge inference routes — 边缘 ML 推理状态与代理接口

Prefix: /api/v1/edge

Endpoints:
  GET  /status               — 边缘推理可用性 + 模型状态 + 调用统计
  POST /predict/{predict_type} — 代理预测请求（用于测试/调试）
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..services.edge_inference_client import EdgeInferenceClient

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/edge",
    tags=["edge-inference"],
)

# Module-level singleton (shared across requests)
_edge_client: EdgeInferenceClient | None = None


def _get_client() -> EdgeInferenceClient:
    global _edge_client
    if _edge_client is None:
        _edge_client = EdgeInferenceClient()
    return _edge_client


# ─── Request Models ─────────────────────────────────────────────────────────


class DishTimePredictBody(BaseModel):
    dish_id: str = Field("", description="菜品 ID（用于日志）")
    store_id: str = Field("", description="门店 ID（用于日志）")
    dish_category: str = Field("hot_dishes", description="菜品大类")
    dish_complexity: int = Field(3, ge=1, le=5, description="复杂度 1-5")
    current_queue_depth: int = Field(0, ge=0, description="当前后厨队列深度")
    hour_of_day: int = Field(12, ge=0, le=23, description="当前小时")
    concurrent_orders: int = Field(1, ge=1, description="同时在制订单数")


class DiscountRiskPredictBody(BaseModel):
    discount_rate: float = Field(0.0, ge=0.0, le=1.0, description="折扣率")
    hour_of_day: int = Field(12, ge=0, le=23, description="当前小时")
    order_amount_fen: int = Field(0, ge=0, description="订单金额（分）")
    employee_id: str = Field("", description="操作员 ID")
    table_id: str = Field("", description="桌台 ID")


class TrafficPredictBody(BaseModel):
    store_id: str = Field("", description="门店 ID")
    date: str = Field("", description="日期 YYYY-MM-DD")
    hour: int = Field(12, ge=0, le=23, description="预测时段")


# ─── GET /status ────────────────────────────────────────────────────────────


@router.get("/status")
async def edge_status(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """Check edge inference availability, model status, and prediction stats.

    Returns:
        ok: bool
        data:
            available: bool — 边缘推理是否可达
            base_url: str — CoreML Bridge 地址
            model_status: dict | null — 各模型推理方式（coreml/rule_fallback）
            prediction_stats: dict — 各预测类型的成功/失败计数
    """
    client = _get_client()

    available = await client.is_available()
    model_status = None
    if available:
        model_status = await client.get_model_status()

    return {
        "ok": True,
        "data": {
            "available": available,
            "base_url": client.base_url,
            "model_status": model_status,
            "prediction_stats": client.get_stats(),
        },
    }


# ─── POST /predict/{predict_type} ──────────────────────────────────────────


@router.post("/predict/dish-time")
async def proxy_predict_dish_time(
    body: DishTimePredictBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """Proxy dish-time prediction through tx-agent to CoreML Bridge."""
    client = _get_client()
    result = await client.predict_dish_time(
        dish_id=body.dish_id,
        store_id=body.store_id,
        context={
            "dish_category": body.dish_category,
            "dish_complexity": body.dish_complexity,
            "current_queue_depth": body.current_queue_depth,
            "hour_of_day": body.hour_of_day,
            "concurrent_orders": body.concurrent_orders,
        },
    )
    if result is None:
        return {
            "ok": False,
            "data": None,
            "error": {"code": "EDGE_UNAVAILABLE", "message": "Edge inference unavailable"},
        }
    return {"ok": True, "data": result}


@router.post("/predict/discount-risk")
async def proxy_predict_discount_risk(
    body: DiscountRiskPredictBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """Proxy discount-risk prediction through tx-agent to CoreML Bridge."""
    client = _get_client()
    result = await client.predict_discount_risk(
        order_data={
            "discount_rate": body.discount_rate,
            "hour_of_day": body.hour_of_day,
            "order_amount_fen": body.order_amount_fen,
            "employee_id": body.employee_id,
            "table_id": body.table_id,
        },
    )
    if result is None:
        return {
            "ok": False,
            "data": None,
            "error": {"code": "EDGE_UNAVAILABLE", "message": "Edge inference unavailable"},
        }
    return {"ok": True, "data": result}


@router.post("/predict/traffic")
async def proxy_predict_traffic(
    body: TrafficPredictBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """Proxy traffic prediction through tx-agent to CoreML Bridge."""
    client = _get_client()
    result = await client.predict_traffic(
        store_id=body.store_id,
        date=body.date,
        hour=body.hour,
    )
    if result is None:
        return {
            "ok": False,
            "data": None,
            "error": {"code": "EDGE_UNAVAILABLE", "message": "Edge inference unavailable"},
        }
    return {"ok": True, "data": result}
