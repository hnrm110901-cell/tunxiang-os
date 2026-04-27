"""Sprint D4b — 薪资异常 Skill Agent（Claude Sonnet 4.7 + Prompt Cache）

职责：
  - 识别加班时长异常（法规硬红线 / 连续作战 / 同岗位极值 / 与营业强度背离 / 刷卡异常 / 补卡过频）
  - 识别薪资环比异常（员工级涨/跌幅 / 岗位级漂移 / 加班占比异常 / 最低工资 / 社保基数 / 提成异常）

双层推理：
  - 云端 Claude Sonnet 4.7（task_type="salary_anomaly"），走 ModelRouter.complete_with_cache
  - 系统提示走 Anthropic Prompt Cache（见 prompts/salary_anomaly.py），目标命中率 ≥ 0.75

自治等级：Level 1（仅建议，人工复核）
约束 scope：{"margin"}（薪资异常直接冲击人力成本率 → 毛利底线）
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
    from ...prompts.salary_anomaly import build_cached_system_blocks
except ImportError:
    # 顶层运行兜底（例如 pytest 将 src 直接加入 sys.path 时）
    from prompts.salary_anomaly import build_cached_system_blocks  # type: ignore[no-redef]


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 输出模型 —— 严格校验 LLM 返回的 JSON
# ─────────────────────────────────────────────────────────────────────────────


class AnomalyItem(BaseModel):
    """单个薪资/考勤异常项。"""

    anomaly_code: str = Field(..., description="异常代码，如 overtime_hard_red_line / employee_spike")
    anomaly_label: str = Field(..., description="异常中文标签，≤ 20 字")
    employee_id: str = Field(..., description="被疑员工 ID（UUID 或 E-xxxx），禁用姓名（PII 保护）")
    category: str = Field(..., description="异常类别：overtime / payroll_variance / structure / attendance_fraud")
    impact_fen: int = Field(..., description="影响金额（分），正值为超支")
    evidence: str = Field(..., description="支撑证据一句话，≤ 100 字")
    severity: str = Field(..., description="严重度：info / warning / high / critical")


class SalaryRecommendation(BaseModel):
    """单条处置建议。"""

    action: str = Field(..., description="动作描述，≤ 30 字")
    responsible_role: str = Field(..., description="负责角色：店长 / 人事 / 财务 / HRD / 审计 / CFO")
    verification_kpi: str = Field(..., description="验证指标，如 'overtime_hours ≤ 36'")
    deadline_days: int = Field(..., ge=1, description="完成期限（天）")
    risk_flag: str = Field(..., description="触碰约束：margin / safety / experience / none")
    prevented_loss_fen: int = Field(..., ge=0, description="可拦截的错发工资估算，分（无则 0）")


class SalaryAnomalyOutput(BaseModel):
    """薪资异常分析输出 —— 两个 action 共用。"""

    summary: str = Field(..., description="一句话摘要")
    anomalies: list[AnomalyItem] = Field(..., description="异常项列表（最多 10 个）")
    suspect_employee_ids: list[str] = Field(..., description="可疑员工 ID 去重列表（employee_id，禁用姓名）")
    recommendations: list[SalaryRecommendation] = Field(..., description="处置建议（最多 5 条）")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")


# ─────────────────────────────────────────────────────────────────────────────
# Skill Agent
# ─────────────────────────────────────────────────────────────────────────────


class SalaryAnomalyAgent(SkillAgent):
    """薪资异常 Skill —— 云端 Sonnet 4.7 + Prompt Cache"""

    agent_id = "salary_anomaly"
    agent_name = "薪资异常稽核"
    description = "识别加班时长与薪资环比异常，拦截错发工资并给出复核建议（Level 1 建议级）"
    priority = "P1"
    run_location = "cloud"
    agent_level = 1  # 仅建议

    # D4b：薪资异常直接冲击人力成本率 → 毛利底线
    constraint_scope = {"margin"}

    # LLM 输出 max_tokens
    _MAX_TOKENS = 2048
    _TEMPERATURE = 0.2  # 薪资稽核比成本根因更要求确定性

    def get_supported_actions(self) -> list[str]:
        return [
            "detect_overtime_anomaly",
            "detect_payroll_variance",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "detect_overtime_anomaly": self._detect_overtime_anomaly,
            "detect_payroll_variance": self._detect_payroll_variance,
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
    # Action 1: detect_overtime_anomaly — 加班时长异常
    # ────────────────────────────────────────────────────────────────────

    async def _detect_overtime_anomaly(self, params: dict[str, Any]) -> AgentResult:
        """加班时长异常识别

        params:
            store_id:          门店ID
            period:            当期（如 "2026-04"）
            attendance_summary: 考勤汇总 dict（员工级 overtime_hours / continuous_days /
                                manual_correction_count）
            role_baseline:     可选 同岗位 7 日/30 日 p50/p90 基准
            revenue_trend:     可选 门店营收环比（用于 labor_revenue_divergence）
            narrative:         可选 用户额外描述（如 "本月春节高峰连续作战多"）
        """
        user_prompt = self._build_overtime_prompt(params)
        return await self._invoke_llm_and_parse(
            action="detect_overtime_anomaly",
            user_prompt=user_prompt,
            params=params,
        )

    # ────────────────────────────────────────────────────────────────────
    # Action 2: detect_payroll_variance — 薪资环比异常
    # ────────────────────────────────────────────────────────────────────

    async def _detect_payroll_variance(self, params: dict[str, Any]) -> AgentResult:
        """薪资环比异常识别（员工/岗位级涨幅 > 阈值）

        params:
            store_id:          门店ID
            period:            当期（如 "2026-04"）
            current_payroll:   当期薪资 dict（employee_id → gross_fen/base_fen/overtime_fen/...）
            baseline_payroll:  过去 3 个月均值/中位数基准 dict
            role_salary_band:  可选 岗位薪资带（role_code → [min_fen, max_fen]）
            local_min_wage_fen:可选 当地最低工资（分）
            narrative:         可选 用户额外描述（如 "本月晋升 2 名员工"）
        """
        user_prompt = self._build_payroll_variance_prompt(params)
        return await self._invoke_llm_and_parse(
            action="detect_payroll_variance",
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
        3. 决策留痕（含 ROI：prevented_loss_fen + labor_cost_ratio delta）
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
                task_type="salary_anomaly",
                system_blocks=system_blocks,
                messages=messages,
                max_tokens=self._MAX_TOKENS,
                temperature=self._TEMPERATURE,
                db=self._db,
            )
        except (ValueError, RuntimeError) as exc:
            # ValueError = system_blocks 非法；RuntimeError = 重试耗尽
            logger.error(
                "salary_anomaly_llm_call_failed",
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
        #     —— 每条建议声明可拦截的错发金额，合计即本轮稽核保住的现金
        #   improved_kpi     ≈ 人力成本率改善（delta_pct，粗估 0.3pp / high+critical 异常）
        #   saved_labor_hours ≈ HR 手动稽核一个门店约 2h；本 Agent 顶替
        prevented_loss_fen = sum(r.prevented_loss_fen for r in parsed.recommendations)
        high_severity_count = sum(1 for a in parsed.anomalies if a.severity in ("high", "critical"))
        delta_pct = round(0.3 * high_severity_count, 2)
        roi: dict[str, Any] = {
            "saved_labor_hours": 2.0,
            "prevented_loss_fen": prevented_loss_fen,
            "improved_kpi": {
                "metric": "labor_cost_ratio",
                "delta_pct": delta_pct,
            },
            "roi_evidence": {
                "source": f"salary_anomaly.{action}",
                "anomaly_count": len(parsed.anomalies),
                "suspect_count": len(parsed.suspect_employee_ids),
                "recommendation_count": len(parsed.recommendations),
                "cache_hit_ratio": usage.get("cache_hit_ratio", 0.0),
                "model": "claude-sonnet-4-7-20250929",
            },
        }

        result = AgentResult(
            success=True,
            action=action,
            data={
                "summary": parsed.summary,
                "anomalies": [a.model_dump() for a in parsed.anomalies],
                "suspect_employee_ids": list(parsed.suspect_employee_ids),
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
    def _parse_llm_output(text: str) -> Optional[SalaryAnomalyOutput]:
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
            logger.warning("salary_anomaly_json_decode_failed", error=str(exc))
            return None

        try:
            return SalaryAnomalyOutput(**payload)
        except ValidationError as exc:
            logger.warning("salary_anomaly_pydantic_validation_failed", error=str(exc))
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
            logger.debug("salary_anomaly_decision_log_skip", reason=str(exc))

    # ────────────────────────────────────────────────────────────────────
    # Prompt 构造
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_overtime_prompt(params: dict[str, Any]) -> str:
        store_id = params.get("store_id", "unknown")
        period = params.get("period", "unknown")
        attendance_summary = params.get("attendance_summary", {})
        role_baseline = params.get("role_baseline", {})
        revenue_trend = params.get("revenue_trend", {})
        narrative = params.get("narrative", "")

        return (
            "【任务】加班时长异常识别\n"
            f"门店：{store_id}；当期：{period}\n"
            f"考勤汇总：{json.dumps(attendance_summary, ensure_ascii=False)}\n"
            f"同岗位基准（p50/p90/7d/30d）：{json.dumps(role_baseline, ensure_ascii=False)}\n"
            f"门店营收环比：{json.dumps(revenue_trend, ensure_ascii=False)}\n"
            f"用户补充：{narrative or '（无）'}\n\n"
            "请按以下顺序识别异常：\n"
            "1) 法规硬红线：单月加班 > 36 小时 或 连续 > 6 天\n"
            "2) 同岗位极端值：员工加班 > 同岗位 p90 × 1.3\n"
            "3) 与营业强度背离：加班 +50% 但 revenue −10%\n"
            "4) 刷卡异常：同日打卡 > 4 次或间隔 < 1 分钟\n"
            "5) 补卡过频：单月补卡 > 3 次\n"
            "给出异常项 + 可疑员工 ID + Top 3-5 条处置建议。\n"
            "严格按以下 JSON schema 返回，不要输出任何额外解释：\n"
            '{"summary":"","anomalies":[{"anomaly_code":"","anomaly_label":"",'
            '"employee_id":"","category":"","impact_fen":0,"evidence":"",'
            '"severity":"warning"}],"suspect_employee_ids":[],'
            '"recommendations":[{"action":"","responsible_role":"",'
            '"verification_kpi":"","deadline_days":0,"risk_flag":"none",'
            '"prevented_loss_fen":0}],"confidence":0.0}'
        )

    @staticmethod
    def _build_payroll_variance_prompt(params: dict[str, Any]) -> str:
        store_id = params.get("store_id", "unknown")
        period = params.get("period", "unknown")
        current_payroll = params.get("current_payroll", {})
        baseline_payroll = params.get("baseline_payroll", {})
        role_salary_band = params.get("role_salary_band", {})
        local_min_wage_fen = params.get("local_min_wage_fen", 0)
        narrative = params.get("narrative", "")

        return (
            "【任务】薪资环比异常识别\n"
            f"门店：{store_id}；当期：{period}\n"
            f"当地最低工资（分）：{local_min_wage_fen}\n"
            f"当期薪资（employee_id → gross/base/overtime/bonus）："
            f"{json.dumps(current_payroll, ensure_ascii=False)}\n"
            f"基准薪资（过去 3 月均值/中位数）："
            f"{json.dumps(baseline_payroll, ensure_ascii=False)}\n"
            f"岗位薪资带：{json.dumps(role_salary_band, ensure_ascii=False)}\n"
            f"用户补充：{narrative or '（无）'}\n\n"
            "请按以下顺序识别异常：\n"
            "1) 员工级涨幅 > 30%（无晋升证据）→ employee_spike\n"
            "2) 员工级跌幅 > 30%（无缺勤证据）→ employee_dip\n"
            "3) 岗位级均薪环比 > 15% → role_drift\n"
            "4) 加班占比 > 25% → overtime_ratio_high\n"
            "5) 基本工资 < 当地最低 → minimum_wage_violation\n"
            "6) 社保基数 < 应发 × 60% → social_insurance_base_underreport\n"
            "7) 单月提成 > 基本 × 2 → bonus_outlier\n"
            "给出异常项 + 可疑员工 ID + Top 3-5 条处置建议。\n"
            "严格按以下 JSON schema 返回，不要输出任何额外解释：\n"
            '{"summary":"","anomalies":[{"anomaly_code":"","anomaly_label":"",'
            '"employee_id":"","category":"","impact_fen":0,"evidence":"",'
            '"severity":"warning"}],"suspect_employee_ids":[],'
            '"recommendations":[{"action":"","responsible_role":"",'
            '"verification_kpi":"","deadline_days":0,"risk_flag":"none",'
            '"prevented_loss_fen":0}],"confidence":0.0}'
        )
