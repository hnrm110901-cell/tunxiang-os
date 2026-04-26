"""
出餐时间预测器 — 边缘 AI 核心模块

两层推理策略：
1. 优先：CoreML .mlmodel 推理（M4 Neural Engine，<5ms）
2. 降级：规则引擎（当 .mlmodel 不可用或推理失败时）

模型特征：
- dish_category (str): 菜品大类 (hot_dishes/cold_dishes/noodles/grill/dessert)
- dish_complexity (int): 复杂度 1-5
- current_queue_depth (int): 当前后厨队列深度
- hour_of_day (int): 当前小时 0-23（高峰期加权）
- concurrent_orders (int): 同时在制订单数

预测输出：
- estimated_minutes (float): 预计出餐分钟数
- confidence (float): 0-1 置信度
- method (str): "coreml" | "rule_fallback"
- p95_minutes (float): 95百分位上限
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# 规则引擎参数（当 CoreML 不可用时使用）
_BASE_TIMES: dict[str, float] = {
    "hot_dishes": 12.0,
    "cold_dishes": 5.0,
    "noodles": 8.0,
    "grill": 15.0,
    "dessert": 6.0,
    "default": 10.0,
}

_COMPLEXITY_MULTIPLIER: dict[int, float] = {1: 0.7, 2: 0.85, 3: 1.0, 4: 1.3, 5: 1.6}
_PEAK_HOURS = frozenset(range(11, 14)) | frozenset(range(17, 21))  # 午市+晚市


@dataclass
class PredictionInput:
    dish_category: str
    dish_complexity: int  # 1-5
    current_queue_depth: int
    hour_of_day: int  # 0-23
    concurrent_orders: int = 1


@dataclass
class PredictionResult:
    estimated_minutes: float
    confidence: float
    method: str  # "coreml" | "rule_fallback"
    p95_minutes: float
    inference_ms: float


class DishTimePredictor:
    """出餐时间预测器，支持 CoreML 降级到规则引擎"""

    def __init__(self) -> None:
        self._coreml_available = False
        self._model = None
        self._try_load_model()

    def _try_load_model(self) -> None:
        """尝试加载 CoreML 模型（M4 设备可用时）"""
        model_path = os.environ.get("DISH_TIME_MODEL_PATH", "models/dish_time_v1.mlpackage")
        try:
            import coremltools as ct  # type: ignore[import]

            if os.path.exists(model_path):
                self._model = ct.models.MLModel(model_path)
                self._coreml_available = True
                log.info("coreml_model_loaded", path=model_path)
            else:
                log.warning("coreml_model_not_found", path=model_path, fallback="rule_engine")
        except ImportError:
            log.info("coremltools_not_installed", fallback="rule_engine")
        except OSError as e:
            log.warning("coreml_model_load_failed", error=str(e), fallback="rule_engine")

    def predict(self, inp: PredictionInput) -> PredictionResult:
        """预测出餐时间"""
        start = time.perf_counter()

        if self._coreml_available and self._model is not None:
            try:
                result = self._predict_coreml(inp)
                result.inference_ms = (time.perf_counter() - start) * 1000
                return result
            except (ValueError, RuntimeError, KeyError) as e:
                log.warning("coreml_inference_failed", error=str(e), fallback="rule_engine")

        result = self._predict_rules(inp)
        result.inference_ms = (time.perf_counter() - start) * 1000
        return result

    def _predict_coreml(self, inp: PredictionInput) -> PredictionResult:
        """CoreML 推理路径（M4 Neural Engine）"""
        # 真实部署时传入特征向量给 .mlmodel
        prediction = self._model.predict(
            {  # type: ignore[union-attr]
                "dish_category": inp.dish_category,
                "dish_complexity": float(inp.dish_complexity),
                "queue_depth": float(inp.current_queue_depth),
                "hour_of_day": float(inp.hour_of_day),
                "concurrent_orders": float(inp.concurrent_orders),
            }
        )
        estimated = float(prediction["estimated_minutes"])
        return PredictionResult(
            estimated_minutes=estimated,
            confidence=float(prediction.get("confidence", 0.85)),
            method="coreml",
            p95_minutes=estimated * 1.4,
            inference_ms=0.0,
        )

    def _predict_rules(self, inp: PredictionInput) -> PredictionResult:
        """规则引擎降级路径"""
        base = _BASE_TIMES.get(inp.dish_category, _BASE_TIMES["default"])
        complexity_mult = _COMPLEXITY_MULTIPLIER.get(max(1, min(5, inp.dish_complexity)), 1.0)
        queue_penalty = min(inp.current_queue_depth * 0.8, 8.0)
        concurrent_penalty = max(0.0, (inp.concurrent_orders - 3) * 0.5)
        peak_penalty = 2.0 if inp.hour_of_day in _PEAK_HOURS else 0.0

        estimated = base * complexity_mult + queue_penalty + concurrent_penalty + peak_penalty
        estimated = max(3.0, estimated)  # 最少3分钟

        # 高峰期置信度稍低（规则引擎对高峰期估算误差更大）
        confidence = 0.75 if inp.hour_of_day in _PEAK_HOURS else 0.85

        return PredictionResult(
            estimated_minutes=round(estimated, 1),
            confidence=confidence,
            method="rule_fallback",
            p95_minutes=round(estimated * 1.5, 1),
            inference_ms=0.0,
        )


# 单例
_predictor: Optional[DishTimePredictor] = None


def get_predictor() -> DishTimePredictor:
    global _predictor
    if _predictor is None:
        _predictor = DishTimePredictor()
    return _predictor
