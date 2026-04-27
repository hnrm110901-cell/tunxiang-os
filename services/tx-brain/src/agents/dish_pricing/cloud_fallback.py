"""D3c — Cloud fallback for dish pricing when edge is unavailable.

调用 ModelRouter（Sonnet 默认），prompt 中嵌入毛利底线红线。
即使云端模型返回的价格突破毛利底线，service 层会再次 sanity-check 并夹回。
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import structlog

from .schemas import DishPricingRequest

logger = structlog.get_logger(__name__)


_CLOUD_FALLBACK_PROMPT = """你是屯象OS的菜品动态定价助手。基于以下信号给出推荐价格（单位：分）。

【铁律 — 毛利底线】
推荐价 - 成本价 ≥ 推荐价 × 15%
等价：推荐价 ≥ 成本价 / 0.85
**绝对不能低于这条线**，即使所有信号都建议大幅降价。

【输入信号】
- 基准价：{base_price_fen} 分
- 成本价：{cost_fen} 分
- 时段：{time_of_day}（lunch_peak/dinner_peak +0%, off_peak -3%）
- 客流：{traffic_forecast}（high +5%, low -5%）
- 库存：{inventory_status}（near_expiry -10%, low_stock +3%）

【输出严格 JSON】
{{
  "recommended_price_fen": <int>,
  "confidence": <0.0-1.0 float>,
  "reasoning": "<30字以内中文，说明主要驱动因素>",
  "signals": [{{"name": "<信号名>", "delta": "<如 +0.05>"}}, ...]
}}

只返回 JSON，不要任何 markdown 围栏或前置文字。
"""


class DishPricingCloudFallback:
    """云端定价 fallback — 通过 ModelRouter 调用 Sonnet/Qwen Max。

    设计为可注入的结构以便测试：
        fb = DishPricingCloudFallback(model_router=mock_router)
        result = await fb.recommend(req)
    """

    def __init__(self, model_router: Optional[Any] = None) -> None:
        """注入 ModelRouter（CLAUDE.md §14：所有模型调用必须通过 ModelRouter）。

        Args:
            model_router: 拥有 async complete(tenant_id, task_type, messages) -> LLMResponse 方法的对象。
                          为 None 时返回纯规则降级（生产环境 main.py 启动时注入）。
        """
        self.model_router = model_router

    async def recommend(self, req: DishPricingRequest) -> dict[str, Any]:
        """生成云端定价建议（与边缘响应同结构 dict）。

        永不抛异常 — 即使 ModelRouter 故障也降级到纯规则版本。
        """
        # ── 模型不可注入时：直接规则降级（不调云）─────────────────
        if self.model_router is None:
            return self._rule_based_fallback(req, reason="no_model_router")

        prompt = _CLOUD_FALLBACK_PROMPT.format(
            base_price_fen=req.base_price_fen,
            cost_fen=req.cost_fen,
            time_of_day=req.time_of_day,
            traffic_forecast=req.traffic_forecast,
            inventory_status=req.inventory_status,
        )

        try:
            response = await self.model_router.complete(
                tenant_id=req.tenant_id,
                task_type="standard_analysis",  # Sonnet/Qwen Max 等
                messages=[{"role": "user", "content": prompt}],
            )
        except (ValueError, RuntimeError, TimeoutError) as exc:
            logger.warning("dish_pricing_cloud_router_failed", error=str(exc), dish_id=req.dish_id)
            return self._rule_based_fallback(req, reason="cloud_router_error")

        text = getattr(response, "text", None) or str(response)

        try:
            parsed = json.loads(text)
        except (ValueError, TypeError) as exc:
            logger.warning("dish_pricing_cloud_parse_failed", error=str(exc), preview=text[:120])
            return self._rule_based_fallback(req, reason="cloud_parse_error")

        # 标准化为统一 schema
        return {
            "recommended_price_fen": int(parsed.get("recommended_price_fen", req.base_price_fen)),
            "confidence": float(parsed.get("confidence", 0.50)),
            "reasoning_signals": parsed.get("signals", []) or [
                {"name": "cloud_reasoning", "delta": parsed.get("reasoning", "n/a")}
            ],
            "model_version": "cloud-fallback-v0",
            "computed_at_ms": int(time.time() * 1000),
            "floor_protected": False,  # service 层会再 check
        }

    def _rule_based_fallback(self, req: DishPricingRequest, reason: str) -> dict[str, Any]:
        """无模型可用时：复用与边缘相同的规则（保证行为一致）"""
        multiplier = 1.0
        signals: list[dict[str, str]] = []

        if req.time_of_day == "off_peak":
            multiplier -= 0.03
            signals.append({"name": "off_peak", "delta": "-0.03"})
        if req.traffic_forecast == "high":
            multiplier += 0.05
            signals.append({"name": "traffic", "delta": "+0.05"})
        elif req.traffic_forecast == "low":
            multiplier -= 0.05
            signals.append({"name": "traffic", "delta": "-0.05"})
        if req.inventory_status == "near_expiry":
            multiplier -= 0.10
            signals.append({"name": "near_expiry", "delta": "-0.10"})
        elif req.inventory_status == "low_stock":
            multiplier += 0.03
            signals.append({"name": "low_stock", "delta": "+0.03"})

        recommended = int(round(req.base_price_fen * multiplier))
        signals.append({"name": "fallback_reason", "delta": reason})

        return {
            "recommended_price_fen": recommended,
            "confidence": 0.50,  # 纯规则置信度低
            "reasoning_signals": signals,
            "model_version": "cloud-rule-fallback-v0",
            "computed_at_ms": int(time.time() * 1000),
            "floor_protected": False,
        }
