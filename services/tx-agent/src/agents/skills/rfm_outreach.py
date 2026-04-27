"""Sprint D3a — RFM 触达 Skill Agent（Claude Haiku 4.5 + Prompt Cache）

职责：
  - 为不同 RFM 分层客户群生成召回/唤醒/激活/升级触达文案（多版本 + 推送时段 + 预估响应率）
  - 从业务目标（如"复购率提升 5pp"）推导 RFM 筛选条件与预计触达人数

双层推理：
  - 云端 Claude Haiku 4.5（task_type="rfm_outreach"），走 ModelRouter.complete_with_cache
  - 系统提示走 Anthropic Prompt Cache（见 prompts/rfm_outreach.py），目标命中率 ≥ 0.75
  - 选择 Haiku 4.5 的理由：触达文案属于高频轻量场景（每日可能 500+ 次调用），
    Haiku 4.5 价格为 Sonnet 的 1/3.75，足以胜任文案生成 + 结构化输出。

自治等级：Level 1（仅建议，人工确认后推送）
约束 scope：{"margin", "experience"}
  - margin：触达常带优惠券，面额可能冲击毛利
  - experience：高频推送会骚扰客户、影响体验，必须拦截
"""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field, ValidationError

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()

# 相对导入 prompts（避免在打包/测试环境出现不同 package root 问题）
try:
    from ...prompts.rfm_outreach import build_cached_system_blocks
except ImportError:
    # 顶层运行兜底（例如 pytest 将 src 直接加入 sys.path 时）
    from prompts.rfm_outreach import build_cached_system_blocks  # type: ignore[no-redef]


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 输出模型 —— 严格校验 LLM 返回的 JSON
# ─────────────────────────────────────────────────────────────────────────────


class OutreachCopyVersion(BaseModel):
    """单个文案版本（A/B/C 测试用）。"""

    version_code: str = Field(..., description="版本代码：A / B / C")
    style: str = Field(..., description="风格：rational / emotional / fomo")
    channel: str = Field(
        ...,
        description="渠道：wechat_template / sms / wework_1v1 / miniapp_push",
    )
    title: str = Field(..., description="标题（按渠道长度限制）")
    body: str = Field(..., description="正文（按渠道长度限制）")
    cta: str = Field(..., description="行动按钮文案（按渠道长度限制）")
    estimated_open_rate: float = Field(..., ge=0.0, le=1.0, description="预估开启率 0-1")
    estimated_click_rate: float = Field(..., ge=0.0, le=1.0, description="预估点击率 0-1")
    estimated_conversion_rate: float = Field(..., ge=0.0, le=1.0, description="预估转化率 0-1")


class OutreachCopyOutput(BaseModel):
    """generate_outreach_copy 的结构化输出。"""

    summary: str = Field(..., description="一句话摘要")
    segment_code: str = Field(..., description="目标分群代码，如 RFM_155")
    scene: str = Field(..., description="场景：recall / reactivate / activate / upgrade")
    push_time: str = Field(..., description="推荐推送时段 HH:MM（24 小时制）")
    versions: list[OutreachCopyVersion] = Field(
        ..., min_length=1, description="A/B/C 多版本文案（至少 1 个，建议 3 个）"
    )
    compliance_check: dict[str, Any] = Field(
        default_factory=dict,
        description="合规自检：{forbidden_words_hit: [], frequency_cap_ok: bool}",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")


class RFMFilter(BaseModel):
    """RFM 筛选条件。"""

    recency_max_days: Optional[int] = Field(None, ge=0, description="最近消费天数上限（天）")
    recency_min_days: Optional[int] = Field(None, ge=0, description="最近消费天数下限（天）")
    frequency_min_count: Optional[int] = Field(
        None, ge=0, description="90 天内下单次数下限"
    )
    frequency_max_count: Optional[int] = Field(
        None, ge=0, description="90 天内下单次数上限"
    )
    monetary_min_fen: Optional[int] = Field(
        None, ge=0, description="90 天累计消费下限（分）"
    )
    monetary_max_fen: Optional[int] = Field(
        None, ge=0, description="90 天累计消费上限（分）"
    )


class TargetSegmentOutput(BaseModel):
    """select_target_segment 的结构化输出。"""

    summary: str = Field(..., description="一句话摘要")
    segment_code: str = Field(..., description="分群代码，如 RFM_155 / RFM_511")
    segment_name: str = Field(..., description="分群名称，如 '流失高价值'")
    rfm_filter: RFMFilter = Field(..., description="RFM 筛选条件")
    estimated_size: int = Field(..., ge=0, description="预计触达人数")
    segment_rationale: str = Field(..., description="选择该分群的理由（一句话）")
    expected_delta_pct: float = Field(
        ..., description="预期 KPI 提升百分点（如复购率 +5pp 填 5.0）"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")


# ─────────────────────────────────────────────────────────────────────────────
# Skill Agent
# ─────────────────────────────────────────────────────────────────────────────


class RfmOutreachAgent(SkillAgent):
    """RFM 触达 Skill —— 云端 Haiku 4.5 + Prompt Cache"""

    agent_id = "rfm_outreach"
    agent_name = "RFM 触达文案"
    description = (
        "基于 RFM 分层为客户群生成多版本触达文案 + 推送时段建议 + 分群筛选（Level 1 建议级）"
    )
    priority = "P1"
    run_location = "cloud"
    agent_level = 1  # 仅建议

    # D3a：触达带券影响毛利 + 高频推送骚扰影响体验
    constraint_scope = {"margin", "experience"}

    # LLM 输出 max_tokens（Haiku 成本敏感，文案场景 1536 够用）
    _MAX_TOKENS = 1536
    _TEMPERATURE = 0.7  # 文案生成需要多样性

    def get_supported_actions(self) -> list[str]:
        return [
            "generate_outreach_copy",
            "select_target_segment",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "generate_outreach_copy": self._generate_outreach_copy,
            "select_target_segment": self._select_target_segment,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(
                success=False,
                action=action,
                error=f"Unsupported action: {action}. Supported: {list(dispatch.keys())}",
            )
        return await handler(params)

    # ────────────────────────────────────────────────────────────────────
    # Action 1: generate_outreach_copy — 生成多版本触达文案
    # ────────────────────────────────────────────────────────────────────

    async def _generate_outreach_copy(self, params: dict[str, Any]) -> AgentResult:
        """生成多版本触达文案 + 推送时段建议

        params:
            segment_code:       目标分群代码（如 RFM_155）
            scene:              场景：recall / reactivate / activate / upgrade
            channel:            渠道：wechat_template / sms / wework_1v1 / miniapp_push
            segment_size:       目标分群规模（可选，辅助置信度判断）
            avg_ticket_fen:     分群平均客单价（分），用于券额上限校验（margin 约束）
            coupon_cap_fen:     优惠券面额上限（分），若未提供则按 avg_ticket_fen * 0.3 推断
            last_touch_days:    该分群上次触达距今天数（可选，触达频控辅助）
            narrative:          可选 用户补充
        """
        user_prompt = self._build_copy_prompt(params)
        return await self._invoke_llm_and_parse(
            action="generate_outreach_copy",
            user_prompt=user_prompt,
            params=params,
            output_model=OutreachCopyOutput,
        )

    # ────────────────────────────────────────────────────────────────────
    # Action 2: select_target_segment — 从业务目标推导 RFM 筛选
    # ────────────────────────────────────────────────────────────────────

    async def _select_target_segment(self, params: dict[str, Any]) -> AgentResult:
        """从业务目标推导 RFM 分群筛选条件 + 预计触达人数

        params:
            business_goal:        业务目标（如 "复购率提升 5pp" / "月活唤醒 1000 人"）
            target_delta_pct:     目标 KPI 提升百分点（如 5.0 代表 +5pp）
            target_metric:        目标指标（如 repurchase_rate / mau / gmv）
            rfm_distribution:     可选 当前 RFM 分布 dict（各象限人数）
            total_member_count:   可选 会员总量（用于估算 segment size）
            budget_fen:           可选 本次触达总预算（分，影响分群规模选择）
            narrative:            可选 用户补充
        """
        user_prompt = self._build_segment_prompt(params)
        return await self._invoke_llm_and_parse(
            action="select_target_segment",
            user_prompt=user_prompt,
            params=params,
            output_model=TargetSegmentOutput,
        )

    # ────────────────────────────────────────────────────────────────────
    # 内部：LLM 调用 + Pydantic 解析 + 留痕
    # ────────────────────────────────────────────────────────────────────

    async def _invoke_llm_and_parse(
        self,
        action: str,
        user_prompt: str,
        params: dict[str, Any],
        output_model: type[BaseModel],
    ) -> AgentResult:
        """统一 LLM 调用逻辑：

        1. 通过 ModelRouter.complete_with_cache() 调用 Haiku 4.5
        2. Pydantic 校验输出
        3. 决策留痕（含 improved_kpi ROI 估算）
        """
        router = self._router
        if router is None:
            return AgentResult(
                success=False,
                action=action,
                error="ModelRouter 未注入，无法调用 LLM",
                reasoning="初始化 Agent 时未传入 model_router 实例",
                confidence=0.0,
            )

        system_blocks = build_cached_system_blocks()
        messages = [{"role": "user", "content": user_prompt}]

        try:
            text, usage = await router.complete_with_cache(
                tenant_id=self.tenant_id,
                task_type="rfm_outreach",
                system_blocks=system_blocks,
                messages=messages,
                max_tokens=self._MAX_TOKENS,
                temperature=self._TEMPERATURE,
                db=self._db,
            )
        except (ValueError, RuntimeError) as exc:
            # ValueError = system_blocks 非法；RuntimeError = 重试耗尽
            logger.error(
                "rfm_outreach_llm_call_failed",
                action=action,
                error=str(exc),
                exc_info=True,
            )
            return AgentResult(
                success=False,
                action=action,
                error=f"LLM 调用失败: {exc}",
                reasoning=str(exc),
                confidence=0.0,
            )

        # Pydantic 校验
        parsed = self._parse_llm_output(text, output_model)
        if parsed is None:
            return AgentResult(
                success=False,
                action=action,
                error="LLM 输出无法解析为 JSON / 未通过 Pydantic 校验",
                reasoning=f"raw_text_preview={text[:200]}",
                confidence=0.0,
                data={"usage": usage, "raw_text": text[:500]},
            )

        # ROI：D3a 目标复购率 +5pp（规划文档 L55）
        #   improved_kpi：触达直接影响 repurchase_rate
        #   prevented_loss_fen：留空（触达是"增长"而非"防损"）
        #   saved_labor_hours：运营省下的文案撰写 + 分群筛选时间（每次约 0.3h）
        delta_pct: float = 5.0
        if isinstance(parsed, TargetSegmentOutput):
            delta_pct = float(parsed.expected_delta_pct)

        roi: dict[str, Any] = {
            "saved_labor_hours": 0.3,
            "prevented_loss_fen": None,  # 触达不防损
            "improved_kpi": {
                "metric": "repurchase_rate",
                "delta_pct": delta_pct,
            },
            "roi_evidence": {
                "source": f"rfm_outreach.{action}",
                "cache_hit_ratio": usage.get("cache_hit_ratio", 0.0),
                "model": "claude-haiku-4-5-20251001",
            },
        }

        result_data: dict[str, Any] = {
            "summary": parsed.summary,
            "usage": usage,
            "roi": roi,
        }
        # 根据输出类型补充结构化字段
        if isinstance(parsed, OutreachCopyOutput):
            result_data.update(
                {
                    "segment_code": parsed.segment_code,
                    "scene": parsed.scene,
                    "push_time": parsed.push_time,
                    "versions": [v.model_dump() for v in parsed.versions],
                    "compliance_check": parsed.compliance_check,
                }
            )
        elif isinstance(parsed, TargetSegmentOutput):
            result_data.update(
                {
                    "segment_code": parsed.segment_code,
                    "segment_name": parsed.segment_name,
                    "rfm_filter": parsed.rfm_filter.model_dump(),
                    "estimated_size": parsed.estimated_size,
                    "segment_rationale": parsed.segment_rationale,
                    "expected_delta_pct": parsed.expected_delta_pct,
                }
            )

        result = AgentResult(
            success=True,
            action=action,
            data=result_data,
            reasoning=parsed.summary,
            confidence=parsed.confidence,
            inference_layer="cloud",
        )

        # 留痕（DB 可用时）
        await self._write_decision_log(action=action, params=params, result=result, roi=roi)

        return result

    @staticmethod
    def _parse_llm_output(
        text: str, output_model: type[BaseModel]
    ) -> Optional[BaseModel]:
        """解析 LLM 输出到指定 Pydantic 模型；失败返回 None。

        容错：
          - 兼容 LLM 偶尔把 JSON 包在 ```json ... ``` 代码块里
          - 只截取第一个 { 到最后一个 } 的子串
        """
        cleaned = text.strip()
        # 去掉 markdown 代码块围栏
        if cleaned.startswith("```"):
            first_nl = cleaned.find("\n")
            if first_nl > 0:
                cleaned = cleaned[first_nl + 1 :]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None

        json_str = cleaned[start : end + 1]
        try:
            payload = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("rfm_outreach_json_decode_failed", error=str(exc))
            return None

        try:
            return output_model(**payload)
        except ValidationError as exc:
            logger.warning(
                "rfm_outreach_pydantic_validation_failed",
                model=output_model.__name__,
                error=str(exc),
            )
            return None

    async def _write_decision_log(
        self,
        action: str,
        params: dict[str, Any],
        result: AgentResult,
        roi: dict[str, Any],
    ) -> None:
        """走 DecisionLogService.log_skill_result 留痕。DB 不可用时静默跳过。"""
        if self._db is None:
            return
        try:
            from ...services.decision_log_service import DecisionLogService

            await DecisionLogService.log_skill_result(
                db=self._db,
                tenant_id=self.tenant_id,
                agent_id=self.agent_id,
                action=action,
                input_context={k: v for k, v in params.items() if k != "_session_id"},
                result=result,
                store_id=self.store_id,
                roi=roi,
            )
        except (ImportError, AttributeError, TypeError) as exc:
            logger.debug("rfm_outreach_decision_log_skip", reason=str(exc))

    # ────────────────────────────────────────────────────────────────────
    # Prompt 构造
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_copy_prompt(params: dict[str, Any]) -> str:
        segment_code = params.get("segment_code", "RFM_333")
        scene = params.get("scene", "recall")
        channel = params.get("channel", "wechat_template")
        segment_size = params.get("segment_size", "未提供")
        avg_ticket_fen = params.get("avg_ticket_fen", "未提供")
        coupon_cap_fen = params.get("coupon_cap_fen", "未提供")
        last_touch_days = params.get("last_touch_days", "未提供")
        narrative = params.get("narrative", "")

        return (
            "【任务】为指定 RFM 分群生成多版本触达文案\n"
            f"目标分群：{segment_code}；场景：{scene}；渠道：{channel}\n"
            f"分群规模：{segment_size}；平均客单价（分）：{avg_ticket_fen}；"
            f"券额上限（分）：{coupon_cap_fen}\n"
            f"上次触达距今天数：{last_touch_days}\n"
            f"用户补充：{narrative or '（无）'}\n\n"
            "请生成至少 3 个版本（A/B/C，风格分别为 rational / emotional / fomo），\n"
            "并给出推荐推送时段（HH:MM）与合规自检（是否命中禁词、是否触达频控上限）。\n"
            "严格按以下 JSON schema 返回，不要输出任何额外解释：\n"
            '{"summary":"","segment_code":"","scene":"","push_time":"HH:MM",'
            '"versions":[{"version_code":"A","style":"rational","channel":"",'
            '"title":"","body":"","cta":"","estimated_open_rate":0.0,'
            '"estimated_click_rate":0.0,"estimated_conversion_rate":0.0}],'
            '"compliance_check":{"forbidden_words_hit":[],"frequency_cap_ok":true},'
            '"confidence":0.0}'
        )

    @staticmethod
    def _build_segment_prompt(params: dict[str, Any]) -> str:
        business_goal = params.get("business_goal", "复购率提升 5pp")
        target_delta_pct = params.get("target_delta_pct", 5.0)
        target_metric = params.get("target_metric", "repurchase_rate")
        rfm_distribution = params.get("rfm_distribution", {})
        total_member_count = params.get("total_member_count", "未提供")
        budget_fen = params.get("budget_fen", "未提供")
        narrative = params.get("narrative", "")

        return (
            "【任务】从业务目标推导 RFM 分群筛选条件 + 预计触达人数\n"
            f"业务目标：{business_goal}\n"
            f"目标指标：{target_metric}；目标提升：{target_delta_pct} pp\n"
            f"会员总量：{total_member_count}；本次预算（分）：{budget_fen}\n"
            f"当前 RFM 分布：{json.dumps(rfm_distribution, ensure_ascii=False)}\n"
            f"用户补充：{narrative or '（无）'}\n\n"
            "请选择最能达成目标的单一 RFM 象限（如 RFM_155 流失高价值 / RFM_511 新客潜力），\n"
            "给出 recency / frequency / monetary 三维筛选条件（至少 2 维）、\n"
            "预计触达人数（整数）、选择理由（一句话）。\n"
            "严格按以下 JSON schema 返回，不要输出任何额外解释：\n"
            '{"summary":"","segment_code":"","segment_name":"",'
            '"rfm_filter":{"recency_max_days":null,"recency_min_days":null,'
            '"frequency_min_count":null,"frequency_max_count":null,'
            '"monetary_min_fen":null,"monetary_max_fen":null},'
            '"estimated_size":0,"segment_rationale":"",'
            '"expected_delta_pct":0.0,"confidence":0.0}'
        )
