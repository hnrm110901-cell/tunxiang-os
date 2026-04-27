"""Sprint D4c — 预算预测 Skill Agent（Claude Sonnet 4.7 + Prompt Cache）

职责：
  - 基于历史数据 + 季节性 + 门店画像预测下月各成本科目预算
  - 识别实际 vs 预算偏差超阈值（±5/10/15%）并输出根因 + 建议

双层推理：
  - 云端 Claude Sonnet 4.7（task_type="budget_forecast"），走 ModelRouter.complete_with_cache
  - 系统提示走 Anthropic Prompt Cache（见 prompts/budget_forecast.py），目标命中率 ≥ 0.75

自治等级：Level 1（仅建议，人工复核）
约束 scope：{"margin"}（预算预测直接影响成本决策 → 毛利底线）
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
    from ...prompts.budget_forecast import build_cached_system_blocks
except ImportError:
    # 顶层运行兜底（例如 pytest 将 src 直接加入 sys.path 时）
    from prompts.budget_forecast import build_cached_system_blocks  # type: ignore[no-redef]


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 输出模型 —— 严格校验 LLM 返回的 JSON
# ─────────────────────────────────────────────────────────────────────────────


class ForecastItem(BaseModel):
    """单个科目的预测条目（含 80%/95% 置信区间）。"""

    category: str = Field(
        ...,
        description="一级科目：food_cost / labor_cost / utility_cost / rent_cost / marketing_cost / depreciation_cost",
    )
    forecast_fen: int = Field(..., ge=0, description="点预测值，分")
    ci_80_lower_fen: int = Field(..., ge=0, description="80% 置信区间下界，分")
    ci_80_upper_fen: int = Field(..., ge=0, description="80% 置信区间上界，分")
    ci_95_lower_fen: int = Field(..., ge=0, description="95% 置信区间下界，分")
    ci_95_upper_fen: int = Field(..., ge=0, description="95% 置信区间上界，分")
    expected_rate: float = Field(..., ge=0.0, le=1.0, description="占营收比例 0-1")
    drivers: list[str] = Field(..., description="关键驱动因子（最多 5 项）")


class VarianceItem(BaseModel):
    """单个科目的预算偏差条目。"""

    category: str = Field(..., description="一级科目")
    budget_fen: int = Field(..., ge=0, description="原预算，分")
    actual_fen: int = Field(..., ge=0, description="实际发生，分")
    delta_fen: int = Field(..., description="actual − budget，正值超支，分")
    delta_pct: float = Field(..., ge=-1.0, le=10.0, description="偏差百分比 -1~10 小数")
    severity: str = Field(..., description="严重度：info / warning / high / critical")
    root_cause_code: str = Field(
        ...,
        description="根因代码：volume_mix / unit_price / waste / labor_overtime / energy_spike / rent_adjustment / marketing_surge / depreciation_catch_up",
    )
    evidence: str = Field(..., description="证据一句话，≤ 100 字")


class BudgetRecommendation(BaseModel):
    """单条改进建议。"""

    action: str = Field(..., description="动作描述，≤ 30 字")
    responsible_role: str = Field(..., description="负责角色：店长 / 财务 / CFO / 采购 / 营运 / HRD / 主厨")
    verification_kpi: str = Field(..., description="验证指标，如 'food_cost_rate ≤ 33%'")
    deadline_days: int = Field(..., ge=1, description="完成期限（天）")
    risk_flag: str = Field(..., description="触碰约束：margin / safety / experience / none")
    prevented_loss_fen: int = Field(..., ge=0, description="可拦截的超预算支出（分），无则 0")


class BudgetRisk(BaseModel):
    """单条风险项。"""

    risk_code: str = Field(..., description="风险代码")
    risk_label: str = Field(..., description="风险中文标签 ≤ 20 字")
    impact: str = Field(..., description="对预测的影响描述 ≤ 80 字")
    mitigation: str = Field(..., description="建议缓解措施 ≤ 50 字")


class BudgetForecastOutput(BaseModel):
    """预算预测/偏差分析输出 —— 两个 action 共用。"""

    summary: str = Field(..., description="一句话摘要")
    forecasts: list[ForecastItem] = Field(default_factory=list, description="forecast_monthly_budget 的科目预测列表")
    variances: list[VarianceItem] = Field(default_factory=list, description="detect_budget_variance 的偏差列表")
    recommendations: list[BudgetRecommendation] = Field(..., description="改进/调整建议（最多 5 条）")
    risks: list[BudgetRisk] = Field(default_factory=list, description="风险列表（最多 5 条）")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")


# ─────────────────────────────────────────────────────────────────────────────
# Skill Agent
# ─────────────────────────────────────────────────────────────────────────────


class BudgetForecastAgent(SkillAgent):
    """预算预测 Skill —— 云端 Sonnet 4.7 + Prompt Cache"""

    agent_id = "budget_forecast"
    agent_name = "预算预测"
    description = "基于历史数据/季节性/门店画像预测下月预算，并识别预算偏差（Level 1 建议级）"
    priority = "P1"
    run_location = "cloud"
    agent_level = 1  # 仅建议

    # D4c：预算预测直接影响成本决策 → 毛利底线
    constraint_scope = {"margin"}

    # LLM 输出 max_tokens
    _MAX_TOKENS = 2048
    _TEMPERATURE = 0.2  # 预测类对确定性要求高

    def get_supported_actions(self) -> list[str]:
        return [
            "forecast_monthly_budget",
            "detect_budget_variance",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "forecast_monthly_budget": self._forecast_monthly_budget,
            "detect_budget_variance": self._detect_budget_variance,
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
    # Action 1: forecast_monthly_budget — 月度预算预测
    # ────────────────────────────────────────────────────────────────────

    async def _forecast_monthly_budget(self, params: dict[str, Any]) -> AgentResult:
        """月度预算预测

        params:
            store_id:           门店ID
            target_period:      目标月（如 "2026-05"）
            history_months:     历史数据 dict（month → {revenue_fen, food_cost_fen, labor_cost_fen, ...}）
            store_profile:      门店画像（业态 / 地段 / 开业时长 / 面积）
            seasonality_hints:  可选 季节性因子提示（如 "5月五一旅游季"）
            business_plan:      可选 业务计划（新品上市/大促/门店改造）
            narrative:          可选 用户额外描述
        """
        user_prompt = self._build_forecast_prompt(params)
        return await self._invoke_llm_and_parse(
            action="forecast_monthly_budget",
            user_prompt=user_prompt,
            params=params,
        )

    # ────────────────────────────────────────────────────────────────────
    # Action 2: detect_budget_variance — 预算偏差识别
    # ────────────────────────────────────────────────────────────────────

    async def _detect_budget_variance(self, params: dict[str, Any]) -> AgentResult:
        """预算偏差识别（actual vs budget 超阈值告警 + 根因）

        params:
            store_id:           门店ID
            period:             当期（如 "2026-04"）
            budget_plan:        当月预算 dict（category → budget_fen）
            actual_cost:        当月实际 dict（category → actual_fen）
            revenue_actual_fen: 实际营收（分，用于计算成本率）
            context_events:     可选 当月业务事件（大促/员工变动/供应商换签）
            narrative:          可选 用户额外描述
        """
        user_prompt = self._build_variance_prompt(params)
        return await self._invoke_llm_and_parse(
            action="detect_budget_variance",
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
        3. 决策留痕（含 ROI：prevented_loss_fen + budget_accuracy_pct delta）
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
                task_type="budget_forecast",
                system_blocks=system_blocks,
                messages=messages,
                max_tokens=self._MAX_TOKENS,
                temperature=self._TEMPERATURE,
                db=self._db,
            )
        except (ValueError, RuntimeError) as exc:
            # ValueError = system_blocks 非法；RuntimeError = 重试耗尽
            logger.error(
                "budget_forecast_llm_call_failed",
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
        #   prevented_loss_fen ≈ sum(recommendations.prevented_loss_fen)
        #     —— 每条建议声明可拦截的超预算支出，合计即本轮预测/告警保住的现金
        #   improved_kpi     ≈ budget_accuracy_pct 改善（高严重度偏差拦截每条 +0.5pp）
        #   saved_labor_hours ≈ 财务手动编制预算/稽核偏差约 3h；本 Agent 顶替
        prevented_loss_fen = sum(r.prevented_loss_fen for r in parsed.recommendations)
        high_severity_count = sum(1 for v in parsed.variances if v.severity in ("high", "critical"))
        delta_pct = round(0.5 * high_severity_count, 2)
        roi: dict[str, Any] = {
            "saved_labor_hours": 3.0,
            "prevented_loss_fen": prevented_loss_fen,
            "improved_kpi": {
                "metric": "budget_accuracy_pct",
                "delta_pct": delta_pct,
            },
            "roi_evidence": {
                "source": f"budget_forecast.{action}",
                "forecast_count": len(parsed.forecasts),
                "variance_count": len(parsed.variances),
                "recommendation_count": len(parsed.recommendations),
                "risk_count": len(parsed.risks),
                "cache_hit_ratio": usage.get("cache_hit_ratio", 0.0),
                "model": "claude-sonnet-4-7-20250929",
            },
        }

        result = AgentResult(
            success=True,
            action=action,
            data={
                "summary": parsed.summary,
                "forecasts": [f.model_dump() for f in parsed.forecasts],
                "variances": [v.model_dump() for v in parsed.variances],
                "recommendations": [r.model_dump() for r in parsed.recommendations],
                "risks": [r.model_dump() for r in parsed.risks],
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
    def _parse_llm_output(text: str) -> Optional[BudgetForecastOutput]:
        """解析 LLM 输出到 Pydantic 模型；失败返回 None。

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
            logger.warning("budget_forecast_json_decode_failed", error=str(exc))
            return None

        try:
            return BudgetForecastOutput(**payload)
        except ValidationError as exc:
            logger.warning("budget_forecast_pydantic_validation_failed", error=str(exc))
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
            logger.debug("budget_forecast_decision_log_skip", reason=str(exc))

    # ────────────────────────────────────────────────────────────────────
    # Prompt 构造
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_forecast_prompt(params: dict[str, Any]) -> str:
        store_id = params.get("store_id", "unknown")
        target_period = params.get("target_period", "unknown")
        history_months = params.get("history_months", {})
        store_profile = params.get("store_profile", {})
        seasonality_hints = params.get("seasonality_hints", "")
        business_plan = params.get("business_plan", {})
        narrative = params.get("narrative", "")

        return (
            "【任务】月度预算预测\n"
            f"门店：{store_id}；目标月：{target_period}\n"
            f"历史数据（月 → 营收/六大成本科目）：{json.dumps(history_months, ensure_ascii=False)}\n"
            f"门店画像：{json.dumps(store_profile, ensure_ascii=False)}\n"
            f"季节性提示：{seasonality_hints or '（无）'}\n"
            f"业务计划：{json.dumps(business_plan, ensure_ascii=False)}\n"
            f"用户补充：{narrative or '（无）'}\n\n"
            "请按以下顺序预测下月预算：\n"
            "1) 六大成本科目点预测（food_cost / labor_cost / utility_cost / rent_cost / "
            "marketing_cost / depreciation_cost）\n"
            "2) 每科目 80% / 95% 置信区间（lower_fen / upper_fen）\n"
            "3) 每科目关键驱动因子（≤ 5 项，如 seasonality_spring_peak / ingredient_price_surge）\n"
            "4) 与行业基准对比（食材 30-35% / 人力 20-25% / 能耗 3-5% 等），超出必须在 risks 声明\n"
            "5) Top 3-5 条调整建议 + Top 3-5 条风险\n"
            "严格按以下 JSON schema 返回，不要输出任何额外解释：\n"
            '{"summary":"","forecasts":[{"category":"","forecast_fen":0,'
            '"ci_80_lower_fen":0,"ci_80_upper_fen":0,"ci_95_lower_fen":0,"ci_95_upper_fen":0,'
            '"expected_rate":0.0,"drivers":[]}],"variances":[],'
            '"recommendations":[{"action":"","responsible_role":"","verification_kpi":"",'
            '"deadline_days":0,"risk_flag":"none","prevented_loss_fen":0}],'
            '"risks":[{"risk_code":"","risk_label":"","impact":"","mitigation":""}],'
            '"confidence":0.0}'
        )

    @staticmethod
    def _build_variance_prompt(params: dict[str, Any]) -> str:
        store_id = params.get("store_id", "unknown")
        period = params.get("period", "unknown")
        budget_plan = params.get("budget_plan", {})
        actual_cost = params.get("actual_cost", {})
        revenue_actual_fen = params.get("revenue_actual_fen", 0)
        context_events = params.get("context_events", [])
        narrative = params.get("narrative", "")

        return (
            "【任务】预算偏差识别（实际 vs 预算）\n"
            f"门店：{store_id}；当期：{period}\n"
            f"实际营收（分）：{revenue_actual_fen}\n"
            f"当月预算（category → budget_fen）：{json.dumps(budget_plan, ensure_ascii=False)}\n"
            f"当月实际（category → actual_fen）：{json.dumps(actual_cost, ensure_ascii=False)}\n"
            f"当月业务事件：{json.dumps(context_events, ensure_ascii=False)}\n"
            f"用户补充：{narrative or '（无）'}\n\n"
            "请按以下顺序识别偏差：\n"
            "1) 计算 delta_fen = actual − budget；delta_pct = delta_fen / budget（保留 4 位小数）\n"
            "2) 分档：|Δ|≤5% info / 5-10% warning / 10-15% high / >15% critical\n"
            "3) 定位根因（volume_mix / unit_price / waste / labor_overtime / energy_spike / "
            "rent_adjustment / marketing_surge / depreciation_catch_up）\n"
            "4) 每条异常附证据（引用具体数值）\n"
            "5) Top 3-5 条整改建议（含责任角色 + deadline + KPI + prevented_loss_fen）\n"
            "严格按以下 JSON schema 返回，不要输出任何额外解释：\n"
            '{"summary":"","forecasts":[],"variances":[{"category":"","budget_fen":0,'
            '"actual_fen":0,"delta_fen":0,"delta_pct":0.0,"severity":"warning",'
            '"root_cause_code":"","evidence":""}],'
            '"recommendations":[{"action":"","responsible_role":"","verification_kpi":"",'
            '"deadline_days":0,"risk_flag":"none","prevented_loss_fen":0}],'
            '"risks":[],"confidence":0.0}'
        )
