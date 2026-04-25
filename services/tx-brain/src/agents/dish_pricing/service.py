"""D3c — DishPricingService 流水线。

调用顺序：
    1. edge_client（200ms 超时）→ 拿到推荐价
    2. 失败/超时 → cloud_fallback（ModelRouter）
    3. **每条建议必经毛利底线再校验**（即使边缘说已 protected，云端再 sanity-check）
    4. 写一条 AgentDecisionLog（简易版 — 用现有字段，不扩展 schema）

CLAUDE.md §6 三条硬约束之首：毛利底线（margin >= 15%）。
"""

from __future__ import annotations

import time
from typing import Any, Optional

import structlog

from .cloud_fallback import DishPricingCloudFallback
from .edge_client import DishPricingEdgeClient, EdgeUnavailableError
from .schemas import DishPricingRequest, DishPricingResponse, PricingSignal

logger = structlog.get_logger(__name__)


# 三条硬约束之首：margin = (price - cost) / price >= 15%
# 等价：price >= cost / (1 - 0.15) = cost / 0.85
GROSS_MARGIN_FLOOR: float = 0.15


def _margin_floor_price_fen(cost_fen: int) -> int:
    """计算保 GROSS_MARGIN_FLOOR 毛利率所需的最低价（分，向上取整）"""
    if cost_fen <= 0:
        return 1
    # ceil(cost / (1 - floor))
    raw = cost_fen / (1.0 - GROSS_MARGIN_FLOOR)
    return int(-(-int(raw * 100) // 100))  # ceil to integer fen


def _ceil_int(value: float) -> int:
    """向上取整到整数（避免 import math 单依赖）"""
    int_val = int(value)
    return int_val if int_val == value else int_val + (1 if value > 0 else 0)


class DishPricingService:
    """菜品动态定价主流水线"""

    def __init__(
        self,
        edge_client: Optional[DishPricingEdgeClient] = None,
        cloud_fallback: Optional[DishPricingCloudFallback] = None,
        decision_log_writer: Optional[Any] = None,
    ) -> None:
        """所有依赖均可注入便于测试。

        Args:
            edge_client: 默认 DishPricingEdgeClient()
            cloud_fallback: 默认 DishPricingCloudFallback(model_router=None)（即纯规则降级）
            decision_log_writer: 拥有 async write(record_dict) 方法的对象；
                                 None 时只 logger.info 不写库（测试默认）
        """
        self.edge_client = edge_client or DishPricingEdgeClient()
        self.cloud_fallback = cloud_fallback or DishPricingCloudFallback()
        self.decision_log_writer = decision_log_writer

    async def recommend(self, req: DishPricingRequest) -> DishPricingResponse:
        """主入口：边缘优先 → 云端降级 → 毛利底线 sanity check → 留痕。"""

        # ── 输入级 sanity：cost 必须严格小于 base ───────────────
        if req.cost_fen >= req.base_price_fen:
            raise ValueError("cost_fen must be strictly less than base_price_fen")

        source: str = "edge"
        raw: dict[str, Any]

        # ── Step 1: 试边缘 ──────────────────────────────────────
        try:
            raw = await self.edge_client.predict(req)
        except EdgeUnavailableError as exc:
            logger.info(
                "dish_pricing_falling_back_to_cloud",
                dish_id=req.dish_id,
                store_id=req.store_id,
                edge_error=str(exc),
            )
            # ── Step 2: cloud fallback ─────────────────────────
            raw = await self.cloud_fallback.recommend(req)
            source = "cloud"

        # ── Step 3: 毛利底线再校验（service 层兜底，无论 edge 还是 cloud）
        recommended_fen = int(raw.get("recommended_price_fen", req.base_price_fen))
        floor_price_fen = _ceil_int(req.cost_fen / (1.0 - GROSS_MARGIN_FLOOR))
        floor_protected = bool(raw.get("floor_protected", False))

        if recommended_fen < floor_price_fen:
            logger.warning(
                "dish_pricing_floor_clamp_at_service_layer",
                dish_id=req.dish_id,
                source=source,
                upstream_price_fen=recommended_fen,
                floor_price_fen=floor_price_fen,
                cost_fen=req.cost_fen,
            )
            recommended_fen = floor_price_fen
            floor_protected = True

        # 价格上限保护（防输入污染：multiplier 失控的下游模型）
        # 上限：基准价 1.5 倍（业务需要可调，先写常量）
        max_price_fen = int(req.base_price_fen * 1.5)
        if recommended_fen > max_price_fen:
            logger.warning(
                "dish_pricing_ceiling_clamp",
                dish_id=req.dish_id,
                upstream_price_fen=recommended_fen,
                max_price_fen=max_price_fen,
            )
            recommended_fen = max_price_fen

        # ── 转换 signals ───────────────────────────────────────
        signals_raw = raw.get("reasoning_signals") or {}
        signals: list[PricingSignal] = []
        if isinstance(signals_raw, dict):
            for k, v in signals_raw.items():
                signals.append(PricingSignal(name=str(k), delta=str(v)))
        elif isinstance(signals_raw, list):
            for item in signals_raw:
                if isinstance(item, dict) and "name" in item and "delta" in item:
                    signals.append(PricingSignal(name=str(item["name"]), delta=str(item["delta"])))

        if floor_protected and not any(s.name == "margin_floor_clamp" for s in signals):
            signals.append(PricingSignal(name="margin_floor_clamp", delta="applied"))

        response = DishPricingResponse(
            recommended_price_fen=recommended_fen,
            confidence=float(raw.get("confidence", 0.5)),
            reasoning_signals=signals,
            model_version=str(raw.get("model_version", "unknown")),
            computed_at_ms=int(raw.get("computed_at_ms") or int(time.time() * 1000)),
            floor_protected=floor_protected,
            source=source,  # type: ignore[arg-type]
        )

        # ── Step 4: 决策留痕（best-effort）──────────────────────
        await self._write_decision_log(req, response)

        return response

    async def _write_decision_log(
        self,
        req: DishPricingRequest,
        response: DishPricingResponse,
    ) -> None:
        """写 AgentDecisionLog（best-effort，留痕失败不阻断业务）。

        Note: 用现有字段（D2 ROI 4 列扩展待签字，不依赖）。
        """
        try:
            record = {
                "agent_id": "dish_pricing_v0",
                "decision_type": "dynamic_price_recommendation",
                "tenant_id": req.tenant_id,
                "store_id": req.store_id,
                "input_context": {
                    "dish_id": req.dish_id,
                    "base_price_fen": req.base_price_fen,
                    "cost_fen": req.cost_fen,
                    "time_of_day": req.time_of_day,
                    "traffic_forecast": req.traffic_forecast,
                    "inventory_status": req.inventory_status,
                },
                "output_action": {
                    "recommended_price_fen": response.recommended_price_fen,
                    "model_version": response.model_version,
                    "source": response.source,
                },
                "constraints_check": {
                    "margin_ok": True,  # 一定为 True — 不通过会被夹回
                    "floor_protected": response.floor_protected,
                    "floor_threshold_pct": int(GROSS_MARGIN_FLOOR * 100),
                },
                "confidence": response.confidence,
                "inference_layer": response.source,
                "model_id": response.model_version,
            }

            if self.decision_log_writer is not None:
                await self.decision_log_writer.write(record)
            else:
                logger.info("dish_pricing_decision", **record)

        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning(
                "dish_pricing_decision_log_failed",
                dish_id=req.dish_id,
                error=str(exc),
            )
