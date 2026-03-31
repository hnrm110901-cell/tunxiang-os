"""
Phase 3-A: 出餐时间预测 + 翻台时机预测 — Core ML 接口 Stub

此文件是 Core ML 推理接口的占位实现，返回合理的模拟数据。
当 coreml-bridge (Swift, port 8100) 尚未就绪时，本 stub 可挂载到
mac-station FastAPI 的 /predict/* 路由，作为本地推理的过渡方案。

TODO: 真正集成后替换为 Core ML 模型调用：
  import coremltools as ct
  model = ct.models.MLModel("DishTimePrediction.mlpackage")

路由注册方式（在 main.py 中添加）:
  from prediction_stub import router as prediction_stub_router
  app.include_router(prediction_stub_router)
"""
from __future__ import annotations

import random
from typing import Any

import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/predict", tags=["prediction-stub"])


# ─── 菜品基准时间（秒），Core ML 集成后替换 ───
_DISH_BASE_SECONDS: dict[str, float] = {
    "default":       600.0,   # 10分钟
    "mock_dish_1":   480.0,   # 8分钟
    "mock_dish_2":   720.0,   # 12分钟
    "noodle":        300.0,   # 5分钟
    "stew":          900.0,   # 15分钟
    "cold_dish":     120.0,   # 2分钟
    "soup":          540.0,   # 9分钟
    "rice":          180.0,   # 3分钟
}

# ─── 桌台平均就餐分钟数（按座位数） ───
_TABLE_AVG_MINUTES: dict[int, float] = {
    2: 42.0,
    4: 52.0,
    6: 68.0,
    8: 82.0,
    12: 98.0,
}


@router.post("/dish-time")
async def predict_dish_time_stub(data: dict) -> dict:
    """
    出餐时间预测 Stub。

    输入:
      dish_id: str
      queue_depth: int

    返回:
      estimated_seconds: float
      confidence: 'high' | 'medium' | 'low'
      source: 'stub'

    TODO: 替换为 Core ML 模型调用
      model_input = ct.Array(np.array([[dish_embedding, queue_depth, hour_of_day]]))
      pred = model.predict({"input": model_input})
      return pred["estimated_seconds"]
    """
    dish_id = data.get("dish_id", "default")
    queue_depth = int(data.get("queue_depth", 0))

    base = _DISH_BASE_SECONDS.get(dish_id, _DISH_BASE_SECONDS["default"])
    # 队列压力系数：每个额外任务增加 15-30 秒随机浮动
    queue_penalty = queue_depth * random.uniform(15.0, 30.0)
    # 轻微随机噪声模拟模型预测误差
    noise = random.uniform(-30.0, 30.0)
    estimated_seconds = max(60.0, base + queue_penalty + noise)

    logger.info(
        "dish_time_stub_predict",
        dish_id=dish_id,
        queue_depth=queue_depth,
        estimated_seconds=round(estimated_seconds, 1),
    )

    return {
        "ok": True,
        "estimated_seconds": round(estimated_seconds, 1),
        "confidence": "medium",
        "source": "stub",
    }


@router.post("/table-turn")
async def predict_table_turn_stub(data: dict) -> dict:
    """
    翻台剩余时间预测 Stub。

    输入:
      table_no: str
      seats: int
      elapsed_minutes: int

    返回:
      estimated_finish_minutes: int
      confidence: 'high' | 'medium' | 'low'
      source: 'stub'

    TODO: 替换为 Core ML 模型调用（基于就餐时序特征序列预测）
    """
    seats = int(data.get("seats", 4))
    elapsed_minutes = int(data.get("elapsed_minutes", 0))
    table_no = data.get("table_no", "")

    # 找最近匹配的座位数
    keys = sorted(_TABLE_AVG_MINUTES.keys())
    avg_minutes = _TABLE_AVG_MINUTES.get(seats, None)
    if avg_minutes is None:
        best = keys[0]
        for k in keys:
            if k <= seats:
                best = k
        avg_minutes = _TABLE_AVG_MINUTES[best]

    # 剩余预测时间 + 轻微随机噪声
    remaining = max(0.0, avg_minutes - elapsed_minutes + random.uniform(-5.0, 5.0))
    estimated_finish_minutes = max(0, round(remaining))

    # 置信度：就餐时长占均值比例越高，置信度越高
    ratio = elapsed_minutes / avg_minutes if avg_minutes > 0 else 0
    if ratio >= 0.8:
        confidence = "high"
    elif ratio >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"

    logger.info(
        "table_turn_stub_predict",
        table_no=table_no,
        seats=seats,
        elapsed_minutes=elapsed_minutes,
        estimated_finish_minutes=estimated_finish_minutes,
        confidence=confidence,
    )

    return {
        "ok": True,
        "estimated_finish_minutes": estimated_finish_minutes,
        "confidence": confidence,
        "source": "stub",
    }


@router.get("/health")
async def prediction_stub_health() -> dict:
    """Prediction stub 健康检查"""
    return {
        "ok": True,
        "data": {
            "service": "prediction-stub",
            "mode": "stub",
            "note": "Replace with Core ML model when available",
        },
    }
