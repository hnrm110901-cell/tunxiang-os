"""Sonnet 叙述 Service（D3b）

把 Prophet + 增量模型的数字结果转译为门店经理可读的中文叙述。

调用约定：
- 只通过 ModelRouter（MultiProviderRouter / ModelRouterCompat）。不直接 import anthropic SDK
- task_type 选 "agent_decision"（路由首选 Sonnet，FAILOVER 到 qwen-max / deepseek）
- Prompt Cache 提示：把"系统 Prompt + 商户档案"打成静态 cacheable 块，
  活动具体信息为 dynamic 部分（ModelRouter 当前未透传 cache_control，
  但调用结构已对齐 Anthropic 官方推荐——TODO 等 router 增加 cache_control 透传）
- 失败 fallback：返回模板化中文文本，不让用户看到错误
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


# ─── 系统 Prompt（cacheable 静态块） ─────────────────────────────────────────

SYSTEM_PROMPT_STATIC = """你是屯象OS的活动 ROI 解读专家，服务中国连锁餐饮门店经理。

你的输出必须严格符合以下规则：
1. 仅输出合法 JSON，不带 markdown 代码块标记，不带任何前后缀文本
2. JSON schema:
   {
     "narrative": "<3-5 句中文，先结论后理由，提及预算与预期 lift 的对比>",
     "caveats": ["<风险点 1>", "<风险点 2>", ...]   // 至少 1 条，最多 5 条
   }
3. narrative 必须包含：
   - 是否建议启动（启动/谨慎启动/不建议）
   - 预期增量 GMV 与活动成本对比（用元，不用分）
   - 至少一项业务风险（假动作/客流稀释/毛利侵蚀/品牌折损）
4. 语言克制、专业，不使用感叹号或营销话术
5. 严禁编造数字。若 input 缺字段，narrative 应说明"数据不足"
"""


# ─── ModelRouter 协议（最小依赖面） ──────────────────────────────────────────


class ModelRouterLike(Protocol):
    """匹配 ModelRouterCompat / MultiProviderRouter 的子集。"""

    async def complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        system: str | None = ...,
        urgency: str = ...,
        max_tokens: int = ...,
        timeout_s: int = ...,
        request_id: str | None = ...,
        db: Any = ...,
    ) -> Any:
        """调用模型。返回 LLMResponse 或 str（兼容层）。"""
        ...


# ─── 解析与校验 ──────────────────────────────────────────────────────────────


class _NarratorOutput(BaseModel):
    """Sonnet 返回 JSON 的强校验。"""

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(..., min_length=1, max_length=2000)
    caveats: list[str] = Field(..., min_length=1, max_length=5)


# ─── 主 Service ──────────────────────────────────────────────────────────────


class ActivityROINarrator:
    """活动 ROI 叙述生成器，基于 Sonnet 4.7（通过 ModelRouter）。"""

    def __init__(
        self,
        model_router: ModelRouterLike,
        *,
        max_tokens: int = 600,
        timeout_s: int = 25,
    ) -> None:
        self._router = model_router
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s

    async def narrate(
        self,
        *,
        tenant_id: UUID,
        request_id: UUID,
        prediction: dict[str, Any],
        merchant_profile: dict[str, Any] | None = None,
    ) -> tuple[str, float | None]:
        """生成中文叙述。

        Args:
            tenant_id:        租户 UUID
            request_id:       请求 UUID（幂等键）
            prediction:       拼装后的预测 dict（含 lift_gmv_fen / cost_budget_fen / roi_ratio
                              / activity_type / start_at / end_at / mape_estimate / window_days）
            merchant_profile: 商户档案（品牌/城市/客单价等，cache 友好；可为 None）

        Returns:
            (narrative_zh, cache_hit_ratio_estimate)
            cache_hit_ratio 仅作估计：当 merchant_profile 不变时下次调用应命中静态前缀
        """
        merchant_profile = merchant_profile or {}

        # 静态部分（系统 prompt + 商户档案）——若 ModelRouter 未来支持 cache_control，
        # 这两块应被打成 cacheable 块。当前实现把它们拼到 system 字段里。
        merchant_block = self._format_merchant_block(merchant_profile)
        full_system = SYSTEM_PROMPT_STATIC + "\n\n[商户档案]\n" + merchant_block

        # 动态部分（活动具体数字）
        user_prompt = self._format_user_prompt(prediction)

        try:
            raw = await self._router.complete(
                tenant_id=str(tenant_id),
                task_type="agent_decision",
                messages=[{"role": "user", "content": user_prompt}],
                system=full_system,
                urgency="normal",
                max_tokens=self._max_tokens,
                timeout_s=self._timeout_s,
                request_id=str(request_id),
            )
        except (TimeoutError, RuntimeError, OSError) as exc:
            logger.warning(
                "activity_roi_narrator_router_failed: %s tenant=%s req=%s",
                type(exc).__name__,
                tenant_id,
                request_id,
            )
            return self._fallback_narrative(prediction), None

        # ModelRouterCompat 返回 str；MultiProviderRouter 返回 LLMResponse
        text = raw if isinstance(raw, str) else getattr(raw, "text", str(raw))

        try:
            parsed = self._parse_json(text)
            narrative_text = parsed.narrative
            if parsed.caveats:
                narrative_text += "\n\n风险提示：" + "；".join(parsed.caveats) + "。"
        except (ValueError, ValidationError) as exc:
            logger.warning(
                "activity_roi_narrator_parse_failed: %s tenant=%s",
                exc,
                tenant_id,
            )
            return self._fallback_narrative(prediction), None

        # 估算 cache hit ratio：当 merchant_profile 非空时下次调用预期高于 0.75
        cache_ratio = 0.75 if merchant_profile else None
        return narrative_text, cache_ratio

    # ── 私有 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_merchant_block(profile: dict[str, Any]) -> str:
        """商户档案稳定格式化，便于 prompt cache 命中。"""
        if not profile:
            return "(未提供)"
        keys = sorted(profile.keys())
        lines = [f"- {k}: {profile[k]}" for k in keys]
        return "\n".join(lines)

    @staticmethod
    def _format_user_prompt(prediction: dict[str, Any]) -> str:
        """活动具体信息（dynamic）。金额转元便于人类阅读。"""

        def fen_to_yuan(v: int | float | None) -> str:
            if v is None:
                return "未知"
            return f"{v / 100:.2f}元"

        return (
            "请基于以下活动预测数据，按系统 schema 输出 JSON。\n\n"
            f"- 活动类型: {prediction.get('activity_type', '未知')}\n"
            f"- 时间窗口: {prediction.get('start_at', '?')} → {prediction.get('end_at', '?')} "
            f"({prediction.get('window_days', '?')}天)\n"
            f"- 活动预算: {fen_to_yuan(prediction.get('cost_budget_fen'))}\n"
            f"- 预期增量 GMV: {fen_to_yuan(prediction.get('lift_gmv_fen'))}\n"
            f"- 预期增量毛利: {fen_to_yuan(prediction.get('lift_gross_margin_fen'))}\n"
            f"- ROI 比率: {prediction.get('roi_ratio', 0):.2f}\n"
            f"- 历史回测 MAPE: {prediction.get('mape_estimate', 0):.1%}\n"
            f"- 80% 置信区间: ROI ∈ {prediction.get('confidence_interval', (0, 0))}\n"
        )

    @staticmethod
    def _parse_json(text: str) -> _NarratorOutput:
        """容忍少量噪声（去 markdown 围栏），但仍要求 JSON 主体合法。"""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # 去除 ```json ... ``` 围栏
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        data = json.loads(cleaned)
        return _NarratorOutput.model_validate(data)

    @staticmethod
    def _fallback_narrative(prediction: dict[str, Any]) -> str:
        """模型不可达或解析失败时的兜底。仍要包含数字与风险提示。"""
        cost = prediction.get("cost_budget_fen", 0) or 0
        lift = prediction.get("lift_gmv_fen", 0) or 0
        margin = prediction.get("lift_gross_margin_fen", 0) or 0
        roi = prediction.get("roi_ratio", 0.0) or 0.0
        verdict = "建议启动" if roi >= 1.2 else ("谨慎启动" if roi >= 1.0 else "不建议启动")
        return (
            f"基于历史数据测算（fallback 模式），本次{prediction.get('activity_type', '活动')}"
            f"预算 {cost / 100:.2f} 元，预期带来增量 GMV 约 {lift / 100:.2f} 元，"
            f"增量毛利约 {margin / 100:.2f} 元，ROI 约 {roi:.2f}。{verdict}。"
            "\n\n风险提示：模型叙述生成失败，本次结果仅基于数值规则；"
            "实际执行前请人工复核客流稀释、假动作与毛利侵蚀风险。"
        )
