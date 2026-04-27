"""
CoreML Bridge Python 层 — FastAPI 服务
端口: 8100（与 Swift 层同端口，Python 版用于非 macOS 环境或测试）

端点列表：
  GET  /health                  — 健康检查
  POST /predict/dish-time       — 出餐时间预测（CoreML + 规则降级）
  POST /predict/discount-risk   — 折扣异常检测评分（CoreML + 规则降级）
  POST /predict/traffic         — 客流量预测（规则引擎）
  GET  /model-status            — 各模型当前推理方式（coreml / rule_fallback）
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .dish_time_predictor import (
    PredictionInput,
    get_predictor,
)
from .rule_fallback import (
    DiscountRiskInput,
    RuleBasedDiscountRisk,
    RuleBasedTrafficPredict,
    TrafficPredictInput,
)

log = structlog.get_logger(__name__)

app = FastAPI(
    title="CoreML Bridge — 屯象OS 边缘AI推理层",
    description="出餐时间预测 + 折扣风险检测 + 客流量预测（CoreML / 规则降级）",
    version="1.0.0-y-k3",
)

# 模块级单例
_discount_risk = RuleBasedDiscountRisk()
_traffic_predict = RuleBasedTrafficPredict()


# ─── Request / Response Models ───────────────────────────────────────────────


class DishTimePredictRequest(BaseModel):
    dish_category: str = Field(..., description="菜品大类: hot_dishes/cold_dishes/noodles/grill/dessert")
    dish_complexity: int = Field(..., ge=1, le=5, description="复杂度 1-5")
    current_queue_depth: int = Field(0, ge=0, description="当前后厨队列深度")
    hour_of_day: int = Field(..., ge=0, le=23, description="当前小时 0-23")
    concurrent_orders: int = Field(1, ge=1, description="同时在制订单数")


class DiscountRiskRequest(BaseModel):
    discount_rate: float = Field(..., ge=0.0, le=1.0, description="折扣率 0.0-1.0")
    hour_of_day: int = Field(..., ge=0, le=23, description="当前小时 0-23")
    order_amount_fen: int = Field(0, ge=0, description="订单金额（分）")
    employee_id: str = Field("", description="操作员 ID")
    table_id: str = Field("", description="桌台 ID")


class TrafficPredictRequest(BaseModel):
    hour_of_day: int = Field(..., ge=0, le=23, description="预测时段 0-23")
    day_of_week: int = Field(..., ge=0, le=6, description="星期几（0=周一, 6=周日）")
    seats_total: int = Field(80, ge=1, description="门店总座位数")
    weather_score: float = Field(1.0, gt=0.0, description="天气系数（0.5=极端天气, 1.2=节假日）")


# ─── Health ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "coreml-bridge-python",
        "version": "1.0.0-y-k3",
    }


# ─── Model Status ─────────────────────────────────────────────────────────────


@app.get("/model-status")
async def model_status() -> dict[str, Any]:
    """GET /model-status — 返回各模型当前推理方式

    coreml: CoreML 模型已加载，使用 M4 Neural Engine
    rule_fallback: 规则引擎降级（CoreML 不可用）
    """
    predictor = get_predictor()
    dish_time_method = "coreml" if predictor._coreml_available else "rule_fallback"

    return {
        "ok": True,
        "data": {
            "models": {
                "dish_time_predictor": {
                    "method": dish_time_method,
                    "coreml_available": predictor._coreml_available,
                    "description": "出餐时间预测",
                },
                "discount_risk": {
                    "method": "rule_fallback",
                    "coreml_available": False,
                    "description": "折扣风险检测（规则引擎）",
                },
                "traffic_predict": {
                    "method": "rule_fallback",
                    "coreml_available": False,
                    "description": "客流量预测（规则引擎）",
                },
            }
        },
    }


# ─── Predict: Dish Time ──────────────────────────────────────────────────────


@app.post("/predict/dish-time")
async def predict_dish_time(req: DishTimePredictRequest) -> dict[str, Any]:
    """POST /predict/dish-time — 出餐时间预测

    优先使用 CoreML（M4 Neural Engine，<5ms），
    不可用时自动降级为规则引擎。
    """
    predictor = get_predictor()
    inp = PredictionInput(
        dish_category=req.dish_category,
        dish_complexity=req.dish_complexity,
        current_queue_depth=req.current_queue_depth,
        hour_of_day=req.hour_of_day,
        concurrent_orders=req.concurrent_orders,
    )

    try:
        result = predictor.predict(inp)
    except (ValueError, RuntimeError) as e:
        log.error("dish_time_predict_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"code": "PREDICT_FAILED", "message": str(e)},
        )

    log.info(
        "dish_time_predicted",
        dish_category=req.dish_category,
        method=result.method,
        estimated_minutes=result.estimated_minutes,
        inference_ms=result.inference_ms,
    )

    return {
        "ok": True,
        "data": {
            "estimated_minutes": result.estimated_minutes,
            "confidence": result.confidence,
            "method": result.method,
            "p95_minutes": result.p95_minutes,
            "inference_ms": round(result.inference_ms, 3),
        },
    }


# ─── Predict: Discount Risk ──────────────────────────────────────────────────


@app.post("/predict/discount-risk")
async def predict_discount_risk(req: DiscountRiskRequest) -> dict[str, Any]:
    """POST /predict/discount-risk — 折扣异常检测评分

    使用规则引擎（CoreML 折扣风险模型待训练）。
    """
    inp = DiscountRiskInput(
        discount_rate=req.discount_rate,
        hour_of_day=req.hour_of_day,
        order_amount_fen=req.order_amount_fen,
        employee_id=req.employee_id,
        table_id=req.table_id,
    )

    try:
        result = _discount_risk.evaluate_discount(inp)
    except (ValueError, KeyError) as e:
        log.error("discount_risk_eval_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"code": "EVAL_FAILED", "message": str(e)},
        )

    return {
        "ok": True,
        "data": {
            "risk_level": result.risk_level,
            "risk_score": result.risk_score,
            "method": result.method,
            "reasons": result.reasons,
            "should_alert": result.should_alert,
        },
    }


# ─── Predict: Traffic ────────────────────────────────────────────────────────


@app.post("/predict/traffic")
async def predict_traffic(req: TrafficPredictRequest) -> dict[str, Any]:
    """POST /predict/traffic — 客流量预测（规则引擎）"""
    inp = TrafficPredictInput(
        hour_of_day=req.hour_of_day,
        day_of_week=req.day_of_week,
        seats_total=req.seats_total,
        weather_score=req.weather_score,
    )

    try:
        result = _traffic_predict.predict_traffic(inp)
    except (ValueError, KeyError) as e:
        log.error("traffic_predict_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"code": "PREDICT_FAILED", "message": str(e)},
        )

    return {
        "ok": True,
        "data": {
            "expected_covers": result.expected_covers,
            "turnover_rate": result.turnover_rate,
            "confidence": result.confidence,
            "method": result.method,
            "peak_label": result.peak_label,
        },
    }
