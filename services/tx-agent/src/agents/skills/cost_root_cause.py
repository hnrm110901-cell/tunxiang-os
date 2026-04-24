"""Sprint D4a — 成本根因 Skill Agent（Claude Sonnet 4.7 + Prompt Cache）

职责：
  - 识别异动成本科目，定位 Top3 根因，给出可执行建议
  - 解释毛利漂移：价/量/成本三维拆解

双层推理：
  - 云端 Claude Sonnet 4.7（task_type="cost_root_cause"），走 ModelRouter.complete_with_cache
  - 系统提示走 Anthropic Prompt Cache（见 prompts/cost_root_cause.py），目标命中率 ≥ 0.75

自治等级：Level 1（仅建议，人工确认）
约束 scope：{"margin"}（毛利底线）
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
    from ...prompts.cost_root_cause import build_cached_system_blocks
except ImportError:
    # 顶层运行兜底（例如 pytest 将 src 直接加入 sys.path 时）
    from prompts.cost_root_cause import build_cached_system_blocks  # type: ignore[no-redef]


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 输出模型 —— 严格校验 LLM 返回的 JSON
# ─────────────────────────────────────────────────────────────────────────────


class RootCauseItem(BaseModel):
    """单个根因条目。"""

    cause_code: str = Field(..., description="根因代码，如 food_price_surge / labor_over_schedule")
    cause_label: str = Field(..., description="根因中文标签，≤ 20 字")
    category: str = Field(..., description="所属一级科目：food_cost / labor_cost / utility_cost / ...")
    impact_fen: int = Field(..., description="影响金额（分），正值为超支")
    impact_pct: float = Field(..., ge=0.0, le=1.0, description="影响占异动总额比例（0-1）")
    evidence: str = Field(..., description="支撑证据一句话（≤ 80 字）")


class Recommendation(BaseModel):
    """单条改进建议。"""

    action: str = Field(..., description="动作描述，≤ 30 字")
    responsible_role: str = Field(..., description="负责角色：店长 / 主厨 / 采购 / 营运 / CFO")
    estimated_saving_fen: int = Field(..., ge=0, description="预期月节省，分")
    verification_kpi: str = Field(..., description="验证指标，如 food_cost_rate ≤ 33%")
    deadline_days: int = Field(..., ge=1, description="完成期限（天）")
    risk_flag: str = Field(..., description="触碰约束：margin / safety / experience / none")


class CostRootCauseOutput(BaseModel):
    """成本根因分析输出 —— 两个 action 共用。"""

    summary: str = Field(..., description="一句话摘要")
    root_causes: list[RootCauseItem] = Field(..., description="Top 根因列表（最多 5 个）")
    recommendations: list[Recommendation] = Field(..., description="改进建议（最多 5 条）")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")


# ─────────────────────────────────────────────────────────────────────────────
# Skill Agent
# ─────────────────────────────────────────────────────────────────────────────


class CostRootCauseAgent(SkillAgent):
    """成本根因分析 Skill —— 云端 Sonnet 4.7 + Prompt Cache"""

    agent_id = "cost_root_cause"
    agent_name = "成本根因分析"
    description = "定位成本异动根因，解释毛利漂移，给出可执行降本建议（Level 1 建议级）"
    priority = "P1"
    run_location = "cloud"
    agent_level = 1  # 仅建议

    # D4a：毛利底线相关，声明 margin scope
    constraint_scope = {"margin"}

    # LLM 输出 max_tokens
    _MAX_TOKENS = 2048
    _TEMPERATURE = 0.3

    def get_supported_actions(self) -> list[str]:
        return [
            "analyze_cost_spike",
            "explain_margin_drop",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "analyze_cost_spike": self._analyze_cost_spike,
            "explain_margin_drop": self._explain_margin_drop,
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
    # Action 1: analyze_cost_spike — 成本异动根因分析
    # ────────────────────────────────────────────────────────────────────

    async def _analyze_cost_spike(self, params: dict[str, Any]) -> AgentResult:
        """成本异动根因分析

        params:
            store_id:       门店ID
            period:         当期（如 "2026-04"）
            baseline:       基准期 dict（含各科目成本 fen + revenue_fen）
            current:        当期 dict（含各科目成本 fen + revenue_fen）
            bom_variance:   可选 BOM 对账摘要
            narrative:      可选 用户额外描述（如 "本月水产有 3 次大量报废"）
        """
        user_prompt = self._build_cost_spike_prompt(params)
        return await self._invoke_llm_and_parse(
            action="analyze_cost_spike",
            user_prompt=user_prompt,
            params=params,
        )

    # ────────────────────────────────────────────────────────────────────
    # Action 2: explain_margin_drop — 毛利漂移解释
    # ────────────────────────────────────────────────────────────────────

    async def _explain_margin_drop(self, params: dict[str, Any]) -> AgentResult:
        """毛利漂移解释（价/量/成本三维拆解）

        params:
            store_id:          门店ID
            period:            当期（如 "2026-04"）
            baseline_margin:   基准期毛利率（0-1）
            current_margin:    当期毛利率（0-1）
            revenue_breakdown: 分渠道营收 dict
            cost_breakdown:    分科目成本 dict
            narrative:         可选 用户额外描述
        """
        user_prompt = self._build_margin_drop_prompt(params)
        return await self._invoke_llm_and_parse(
            action="explain_margin_drop",
            user_prompt=user_prompt,
            params=params,
        )

    # ────────────────────────────────────────────────────────────────────
    # 内部：LLM 调用 + Pydantic 解析 + 留痕
    # ────────────────────────────────────────────────────────────────────

    async def _invoke_llm_and_parse(
        self,
        action: str,
        user_prompt: str,
        params: dict[str, Any],
    ) -> AgentResult:
        """统一 LLM 调用逻辑：

        1. 通过 ModelRouter.complete_with_cache() 调用 Sonnet 4.7
        2. Pydantic 校验输出
        3. 决策留痕（含 ROI 估算）
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
                task_type="cost_root_cause",
                system_blocks=system_blocks,
                messages=messages,
                max_tokens=self._MAX_TOKENS,
                temperature=self._TEMPERATURE,
                db=self._db,
            )
        except (ValueError, RuntimeError) as exc:
            # ValueError = system_blocks 非法；RuntimeError = 重试耗尽
            logger.error(
                "cost_root_cause_llm_call_failed",
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
        parsed = self._parse_llm_output(text)
        if parsed is None:
            return AgentResult(
                success=False,
                action=action,
                error="LLM 输出无法解析为 JSON / 未通过 Pydantic 校验",
                reasoning=f"raw_text_preview={text[:200]}",
                confidence=0.0,
                data={"usage": usage, "raw_text": text[:500]},
            )

        # ROI 估算：
        #   prevented_loss_fen ≈ sum(recommendations.estimated_saving_fen)
        #   saved_labor_hours  ≈ 根因定位节省的财务分析人时（粗估 0.5h / 根因）
        prevented_loss_fen = sum(r.estimated_saving_fen for r in parsed.recommendations)
        saved_labor_hours = round(0.5 * len(parsed.root_causes), 2)
        roi: dict[str, Any] = {
            "saved_labor_hours": saved_labor_hours,
            "prevented_loss_fen": prevented_loss_fen,
            "roi_evidence": {
                "source": f"cost_root_cause.{action}",
                "cause_count": len(parsed.root_causes),
                "recommendation_count": len(parsed.recommendations),
                "cache_hit_ratio": usage.get("cache_hit_ratio", 0.0),
            },
        }

        result = AgentResult(
            success=True,
            action=action,
            data={
                "summary": parsed.summary,
                "root_causes": [c.model_dump() for c in parsed.root_causes],
                "recommendations": [r.model_dump() for r in parsed.recommendations],
                "usage": usage,
                "roi": roi,
                # 透传给 ConstraintContext.from_data 以便 margin scope 校验；
                # 若无价格数据，则保持空 dict（base.py 会标为 n/a）
                "price_fen": params.get("price_fen"),
                "cost_fen": params.get("cost_fen"),
            },
            reasoning=parsed.summary,
            confidence=parsed.confidence,
            inference_layer="cloud",
        )

        # 留痕（DB 可用时）
        await self._write_decision_log(action=action, params=params, result=result, roi=roi)

        return result

    @staticmethod
    def _parse_llm_output(text: str) -> Optional[CostRootCauseOutput]:
        """解析 LLM 输出到 Pydantic 模型；失败返回 None。

        容错：
          - 兼容 LLM 偶尔把 JSON 包在 ```json ... ``` 代码块里
          - 只截取第一个 { 到最后一个 } 的子串
        """
        cleaned = text.strip()
        # 去掉 markdown 代码块围栏
        if cleaned.startswith("```"):
            # 寻找第一个换行后的内容，以及最后一段 ```
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
            logger.warning("cost_root_cause_json_decode_failed", error=str(exc))
            return None

        try:
            return CostRootCauseOutput(**payload)
        except ValidationError as exc:
            logger.warning("cost_root_cause_pydantic_validation_failed", error=str(exc))
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
            logger.debug("cost_root_cause_decision_log_skip", reason=str(exc))

    # ────────────────────────────────────────────────────────────────────
    # Prompt 构造
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_cost_spike_prompt(params: dict[str, Any]) -> str:
        store_id = params.get("store_id", "unknown")
        period = params.get("period", "unknown")
        baseline = params.get("baseline", {})
        current = params.get("current", {})
        bom_variance = params.get("bom_variance", {})
        narrative = params.get("narrative", "")

        return (
            "【任务】成本异动根因分析\n"
            f"门店：{store_id}；当期：{period}\n"
            f"基准期数据：{json.dumps(baseline, ensure_ascii=False)}\n"
            f"当期数据：{json.dumps(current, ensure_ascii=False)}\n"
            f"BOM 对账摘要：{json.dumps(bom_variance, ensure_ascii=False)}\n"
            f"用户补充：{narrative or '（无）'}\n\n"
            "请定位 Top3-5 根因，给出 3-5 条改进建议。\n"
            "严格按以下 JSON schema 返回，不要输出任何额外解释：\n"
            '{"summary":"","root_causes":[{"cause_code":"","cause_label":"",'
            '"category":"","impact_fen":0,"impact_pct":0.0,"evidence":""}],'
            '"recommendations":[{"action":"","responsible_role":"",'
            '"estimated_saving_fen":0,"verification_kpi":"","deadline_days":0,'
            '"risk_flag":"none"}],"confidence":0.0}'
        )

    @staticmethod
    def _build_margin_drop_prompt(params: dict[str, Any]) -> str:
        store_id = params.get("store_id", "unknown")
        period = params.get("period", "unknown")
        baseline_margin = params.get("baseline_margin", 0.0)
        current_margin = params.get("current_margin", 0.0)
        revenue_breakdown = params.get("revenue_breakdown", {})
        cost_breakdown = params.get("cost_breakdown", {})
        narrative = params.get("narrative", "")

        return (
            "【任务】毛利漂移解释（价/量/成本三维拆解）\n"
            f"门店：{store_id}；当期：{period}\n"
            f"基准毛利率：{baseline_margin:.4f}；当期毛利率：{current_margin:.4f}\n"
            f"分渠道营收：{json.dumps(revenue_breakdown, ensure_ascii=False)}\n"
            f"分科目成本：{json.dumps(cost_breakdown, ensure_ascii=False)}\n"
            f"用户补充：{narrative or '（无）'}\n\n"
            "请按 价（菜单结构/折扣/渠道）、量（客流/客单）、成本（BOM/损耗/人效）"
            "三维拆解，给出 Top 根因与建议。\n"
            "严格按以下 JSON schema 返回，不要输出任何额外解释：\n"
            '{"summary":"","root_causes":[{"cause_code":"","cause_label":"",'
            '"category":"","impact_fen":0,"impact_pct":0.0,"evidence":""}],'
            '"recommendations":[{"action":"","responsible_role":"",'
            '"estimated_saving_fen":0,"verification_kpi":"","deadline_days":0,'
            '"risk_flag":"none"}],"confidence":0.0}'
        )
