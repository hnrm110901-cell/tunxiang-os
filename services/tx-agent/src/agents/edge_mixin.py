"""Edge-aware Agent mixin — 为 Agent 提供边缘 ML 推理能力

使用方式：
    class MyAgent(EdgeAwareMixin, SkillAgent):
        async def execute(self, action, params):
            # 尝试边缘推理
            edge_result = await self.get_edge_prediction("discount-risk", order_data=params)
            if edge_result and edge_result.get("confidence", 0) > 0.8:
                return edge_result  # 高置信度，直接使用边缘结果
            # 否则 fallthrough 到 Claude API
"""

from __future__ import annotations

from typing import Any

import structlog

from ..services.edge_inference_client import EdgeInferenceClient

logger = structlog.get_logger(__name__)


class EdgeAwareMixin:
    """Mixin for agents that can use edge ML predictions.

    Provides a lazily-initialized EdgeInferenceClient and a unified
    get_edge_prediction() dispatch method with automatic logging.
    Each agent instance gets its own client (set on the instance, not the class).
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    @property
    def edge(self) -> EdgeInferenceClient:
        """Lazily create and return the EdgeInferenceClient (per instance)."""
        try:
            client = self.__dict__["_edge_client"]
        except KeyError:
            client = EdgeInferenceClient()
            self.__dict__["_edge_client"] = client
        return client

    async def get_edge_prediction(
        self,
        predict_type: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Get edge prediction with automatic cloud fallback logging.

        Args:
            predict_type: One of "dish-time", "discount-risk", "traffic"
            **kwargs: Arguments forwarded to the appropriate predict method

        Returns:
            Prediction dict on success, None if edge unavailable or prediction failed.
            Callers should fall through to Claude API when None is returned.
        """
        if not await self.edge.is_available():
            logger.info(
                "edge_unavailable",
                predict_type=predict_type,
                agent_id=getattr(self, "agent_id", "unknown"),
            )
            return None

        try:
            if predict_type == "dish-time":
                return await self.edge.predict_dish_time(
                    dish_id=kwargs.get("dish_id", ""),
                    store_id=kwargs.get("store_id", ""),
                    context=kwargs.get("context", kwargs),
                )
            elif predict_type == "discount-risk":
                return await self.edge.predict_discount_risk(
                    order_data=kwargs.get("order_data", kwargs),
                )
            elif predict_type == "traffic":
                return await self.edge.predict_traffic(
                    store_id=kwargs.get("store_id", ""),
                    date=kwargs.get("date", ""),
                    hour=kwargs.get("hour", 12),
                )
            else:
                logger.warning(
                    "edge_unknown_predict_type",
                    predict_type=predict_type,
                    agent_id=getattr(self, "agent_id", "unknown"),
                )
                return None

        except Exception as exc:  # noqa: BLE001 — edge mixin最外层兜底，不影响Agent主流程
            logger.warning(
                "edge_prediction_error",
                predict_type=predict_type,
                agent_id=getattr(self, "agent_id", "unknown"),
                error=str(exc),
                exc_info=True,
            )
            return None
