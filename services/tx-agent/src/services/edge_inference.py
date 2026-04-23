"""edge_inference.py — Python 调用 CoreML Bridge 的边缘推理客户端

CoreML Bridge 运行在 Mac mini M4 上（Swift Vapor，port 8100）。
所有推理调用设置 1 秒超时，失败时 graceful fallback 到统计规则——
不抛异常，不影响上层业务逻辑。

环境变量：
    COREML_BRIDGE_URL: CoreML Bridge 地址，默认 http://localhost:8100
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()

# 默认值：Mac mini 与 Python 服务在同一台机器上
_DEFAULT_BRIDGE_URL = "http://localhost:8100"
# 所有请求强制 1 秒超时（边缘推理要求低延迟）
_TIMEOUT_SECONDS = 1.0


class EdgeInferenceClient:
    """Python 调用 coreml-bridge 的异步客户端

    使用方式：
        client = EdgeInferenceClient()

        # 在 async 上下文中调用
        result = await client.predict_dish_time("dish_001", 12, "weekday", 3)
        is_up = await client.is_available()
    """

    def __init__(self, bridge_url: Optional[str] = None) -> None:
        self._base_url = (bridge_url or os.environ.get("COREML_BRIDGE_URL", _DEFAULT_BRIDGE_URL)).rstrip("/")

    # ─── 出餐时间预测 ─────────────────────────────────────────────

    async def predict_dish_time(
        self,
        dish_id: str,
        hour: int,
        day_type: str,
        queue_length: int,
    ) -> dict:
        """调用 /predict/dish-time，失败时 fallback 到统计基准。

        Args:
            dish_id: 菜品ID
            hour: 当前小时（0-23）
            day_type: "weekday" | "weekend"
            queue_length: 当前队列长度（单数）

        Returns:
            dict 包含:
                predicted_seconds (int): 预测出餐秒数
                confidence (float): 置信度 0-1
                model (str): 使用的模型名称
                source (str): "edge" | "fallback"
        """
        payload = {
            "dish_id": dish_id,
            "hour": hour,
            "day_type": day_type,
            "queue_length": queue_length,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{self._base_url}/predict/dish-time",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                data["source"] = "edge"
                logger.info(
                    "edge_inference_dish_time",
                    dish_id=dish_id,
                    predicted_seconds=data.get("predicted_seconds"),
                    source="edge",
                )
                return data
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            logger.warning(
                "edge_inference_fallback",
                endpoint="dish-time",
                reason=str(exc),
            )
            return self._fallback_dish_time(hour, day_type, queue_length)

    # ─── 折扣风险评分 ─────────────────────────────────────────────

    async def predict_discount_risk(
        self,
        discount_rate: float,
        order_amount: float,
        member_level: str,
    ) -> dict:
        """调用 /predict/discount-risk，失败时 fallback 到规则引擎。

        Args:
            discount_rate: 折扣率（0.0-1.0，例如 0.35 = 65折）
            order_amount: 订单金额（元）
            member_level: 会员等级 "regular" | "silver" | "gold" | "platinum"

        Returns:
            dict 包含:
                risk_score (float): 风险分 0-1
                risk_level (str): "low" | "medium" | "high"
                reason (str): 风险原因
                source (str): "edge" | "fallback"
        """
        payload = {
            "discount_rate": discount_rate,
            "order_amount": order_amount,
            "member_level": member_level,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{self._base_url}/predict/discount-risk",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                data["source"] = "edge"
                logger.info(
                    "edge_inference_discount_risk",
                    discount_rate=discount_rate,
                    risk_level=data.get("risk_level"),
                    source="edge",
                )
                return data
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            logger.warning(
                "edge_inference_fallback",
                endpoint="discount-risk",
                reason=str(exc),
            )
            return self._fallback_discount_risk(discount_rate, order_amount, member_level)

    # ─── 客流量预测 ───────────────────────────────────────────────

    async def predict_traffic(
        self,
        store_id: str,
        date: str,
        hour: int,
    ) -> dict:
        """调用 /predict/traffic，失败时返回历史均值。

        Args:
            store_id: 门店ID
            date: 日期字符串 "yyyy-MM-dd"
            hour: 目标小时（0-23）

        Returns:
            dict 包含:
                predicted_covers (int): 预测到店桌数/人次
                confidence (float): 置信度 0-1
                source (str): "edge" | "fallback"
        """
        payload = {
            "store_id": store_id,
            "date": date,
            "hour": hour,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{self._base_url}/predict/traffic",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                data["source"] = "edge"
                logger.info(
                    "edge_inference_traffic",
                    store_id=store_id,
                    predicted_covers=data.get("predicted_covers"),
                    source="edge",
                )
                return data
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            logger.warning(
                "edge_inference_fallback",
                endpoint="traffic",
                reason=str(exc),
            )
            return self._fallback_traffic(hour)

    # ─── 健康检查 ─────────────────────────────────────────────────

    async def is_available(self) -> bool:
        """检查 CoreML Bridge 是否在线（GET /health）。

        Returns:
            True 表示 bridge 在线且响应正常，False 表示不可用
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code == 200
        except (httpx.TimeoutException, httpx.ConnectError):
            return False

    # ─── Fallback 统计规则 ────────────────────────────────────────

    def _fallback_dish_time(
        self,
        hour: int,
        day_type: str,
        queue_length: int,
    ) -> dict:
        """出餐时间 fallback：基于队列和时段的统计公式"""
        peak_hours = {11, 12, 13, 17, 18, 19, 20}
        base = 300  # 5分钟基准
        queue_wait = queue_length * 90  # 每单90秒等待
        peak_bonus = 120 if hour in peak_hours else 0
        weekend_bonus = 60 if day_type == "weekend" else 0
        total = base + queue_wait + peak_bonus + weekend_bonus
        confidence = 0.72 if queue_length >= 5 else 0.80

        return {
            "predicted_seconds": total,
            "confidence": confidence,
            "model": "dish_time_v1_statistical",
            "source": "fallback",
        }

    def _fallback_discount_risk(
        self,
        discount_rate: float,
        order_amount: float,
        member_level: str,
    ) -> dict:
        """折扣风险 fallback：规则引擎"""
        max_allowed = {
            "platinum": 0.40,
            "gold": 0.30,
            "silver": 0.20,
            "regular": 0.10,
        }.get(member_level.lower(), 0.10)

        excess = max(0.0, discount_rate - max_allowed)
        risk_score = min(1.0, excess * 2.0 + (0.15 if order_amount > 500 else 0.0))

        if risk_score >= 0.7:
            risk_level = "high"
            reason = "discount_rate_exceeds_member_limit" if excess > 0 else "discount_rate_too_high"
        elif risk_score >= 0.4:
            risk_level = "medium"
            reason = "discount_rate_near_limit"
        else:
            risk_level = "low"
            reason = "within_normal_range"

        return {
            "risk_score": round(risk_score, 4),
            "risk_level": risk_level,
            "reason": reason,
            "source": "fallback",
        }

    def _fallback_traffic(self, hour: int) -> dict:
        """客流量 fallback：时段历史均值"""
        hour_weights = {
            6: 0.05,
            7: 0.10,
            8: 0.15,
            9: 0.20,
            10: 0.30,
            11: 0.80,
            12: 1.00,
            13: 0.90,
            14: 0.50,
            15: 0.30,
            16: 0.25,
            17: 0.70,
            18: 1.00,
            19: 0.95,
            20: 0.80,
            21: 0.50,
            22: 0.20,
        }
        weight = hour_weights.get(hour, 0.10)
        base = 40.0
        predicted = max(0, int(round(base * weight)))
        confidence = 0.65  # fallback 置信度低于 edge

        return {
            "predicted_covers": predicted,
            "confidence": confidence,
            "source": "fallback",
        }
