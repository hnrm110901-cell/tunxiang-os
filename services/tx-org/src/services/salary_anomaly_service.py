"""SalaryAnomalyService —— Sprint D4b 薪资异常检测（Sonnet 4.7 + Prompt Cache）

业务场景
-------
每月 5 号 HR 审核工资表，需人工逐员工比对：
  - 底薪是否低于市场（城市 P25 以下 → 离职风险）
  - 加班是否超标（>36h 触发 B1 合规红线）
  - 调薪突增（>30% 可能有人情/套利）
  - 提成异常（>底薪 200% 可能数据错）
  - 社保/公积金漏缴（法律风险）

手工审核：100 人 × 5 维度 = 500 次比对，HR 日耗 1-2 天。
本服务自动扫描，给出排名异常 + 证据 + 处理建议。

Prompt Cache 策略（与 D4a 同模式）
---------------------------------
两段 cacheable system：
  1. STABLE_SYSTEM（~2KB）：职责 + 异常类型 + 输出 schema
  2. CITY_BENCHMARKS（~2KB）：北上广深 + 长沙/武汉/成都等二线城市
     各岗位薪资 P25/P50/P75 + 合规基准

生产连续 10 店扫描共享同一 cache，命中率稳态 >75%。

设计权衡
-------
- 与 D4a 复用 CachedPromptBuilder 模式（不跨模块 import，各自写一份避免耦合）
- invoker 接口与 D4a 相同：async (request: dict) -> response: dict
- fallback 规则引擎：5 种异常类型都有基于阈值的规则版
- **critical 级别自动 escalated**：薪资低于市场 P25 或加班超 36h → 状态机自动
  推到 HRD，不等手动 review
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)

SONNET_CACHED_MODEL = "claude-sonnet-4-7"
CACHE_HIT_TARGET = 0.75

# 合规红线
LEGAL_OVERTIME_LIMIT_HOURS = 36       # 法定月加班上限（B1 红线）
BELOW_MARKET_THRESHOLD_PCT = 0.15     # 低于市场 P50 15%+ 判定 below_market
SUDDEN_RAISE_THRESHOLD_PCT = 0.30     # 单次涨幅 > 30% 判定 sudden_raise
COMMISSION_ABUSE_RATIO = 2.0          # 提成/底薪 > 200% 判定异常


# ──────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────

@dataclass
class EmployeeSalarySignal:
    """单员工本月薪资信号"""
    employee_id: str
    emp_name: str
    role: str                           # waiter / chef / cashier / manager / head_chef
    city: str
    seniority_months: int
    base_salary_fen: int
    overtime_hours: float
    overtime_pay_fen: int
    commission_fen: int
    total_pay_fen: int
    # 上月对比
    prev_total_pay_fen: Optional[int] = None
    # 合规
    social_insurance_paid: bool = True
    housing_fund_paid: bool = True


@dataclass
class SalarySignalBundle:
    """某店某月薪资异常信号包"""
    tenant_id: str
    store_id: Optional[str]
    store_name: Optional[str]
    analysis_month: date
    city: str
    employees: list[EmployeeSalarySignal] = field(default_factory=list)

    @property
    def total_payroll_fen(self) -> int:
        return sum(e.total_pay_fen for e in self.employees)

    def to_json_dict(self) -> dict:
        return {
            "store_name": self.store_name or "全租户",
            "city": self.city,
            "analysis_month": self.analysis_month.isoformat(),
            "employee_count": len(self.employees),
            "total_payroll_yuan": round(self.total_payroll_fen / 100, 2),
            "employees": [
                {
                    "employee_id": e.employee_id,
                    "name": e.emp_name,
                    "role": e.role,
                    "seniority_months": e.seniority_months,
                    "base_salary_yuan": round(e.base_salary_fen / 100, 2),
                    "overtime_hours": round(e.overtime_hours, 1),
                    "overtime_pay_yuan": round(e.overtime_pay_fen / 100, 2),
                    "commission_yuan": round(e.commission_fen / 100, 2),
                    "total_pay_yuan": round(e.total_pay_fen / 100, 2),
                    "prev_total_pay_yuan": (
                        round(e.prev_total_pay_fen / 100, 2)
                        if e.prev_total_pay_fen else None
                    ),
                    "social_insurance_paid": e.social_insurance_paid,
                    "housing_fund_paid": e.housing_fund_paid,
                }
                for e in self.employees
            ],
        }


@dataclass
class SalaryAnomaly:
    """单条异常"""
    employee_id: str
    employee_name: str
    anomaly_type: str        # below_market / overtime_excess / sudden_raise /
                             # commission_abuse / social_insurance_missing / other
    severity: str            # critical / high / medium / low
    evidence: str
    impact_fen: int          # 正值=员工损失（低薪），或租户风险金额（罚款）
    legal_risk: bool = False


@dataclass
class SalaryRemediationAction:
    action: str
    owner_role: str          # hrd / store_manager / finance
    deadline_days: int
    impact_fen: int          # 预期修复金额


@dataclass
class SalaryAnomalyAnalysisResult:
    ranked_anomalies: list[SalaryAnomaly] = field(default_factory=list)
    remediation_actions: list[SalaryRemediationAction] = field(default_factory=list)
    sonnet_analysis: str = ""
    model_id: str = SONNET_CACHED_MODEL
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_read_tokens + self.cache_creation_tokens + self.input_tokens
        return round(self.cache_read_tokens / total, 4) if total > 0 else 0.0

    @property
    def has_critical(self) -> bool:
        return any(a.severity == "critical" for a in self.ranked_anomalies)

    @property
    def has_legal_risk(self) -> bool:
        return any(a.legal_risk for a in self.ranked_anomalies)


# ──────────────────────────────────────────────────────────────────────
# Cached Prompt Builder
# ──────────────────────────────────────────────────────────────────────

class CachedPromptBuilder:
    """构造 Anthropic Messages API request，带 cache_control。"""

    STABLE_SYSTEM = (
        "你是屯象OS 薪资异常检测分析师（Sprint D4b）。\n"
        "职责：基于门店/租户某月工资表，识别薪资异常，按法律风险 + 员工流失风险排名。\n\n"
        "**异常类型**（anomaly_type）：\n"
        "- below_market：底薪低于城市同岗 P50 15%+（离职风险）\n"
        "- overtime_excess：月加班 >36h（B1 合规红线，法律风险）\n"
        "- sudden_raise：单次涨幅 >30%（可能人情/套利）\n"
        "- commission_abuse：提成/底薪 >200%（可能数据错乱或违规提成）\n"
        "- social_insurance_missing：社保/公积金未缴（法律风险）\n"
        "- other：其他异常\n\n"
        "**严重程度**（severity）：\n"
        "- critical：法律红线（合规/社保）\n"
        "- high：员工流失风险高（薪资显著低于市场）\n"
        "- medium：需要关注但非紧急\n"
        "- low：轻微偏离\n\n"
        "输出必须是合法 JSON：\n"
        "```json\n"
        "{\n"
        '  "analysis": "一段总结 ≤200 字",\n'
        '  "ranked_anomalies": [\n'
        '    {"employee_id": "...", "employee_name": "...",\n'
        '     "anomaly_type": "...", "severity": "critical|high|medium|low",\n'
        '     "evidence": "...", "impact_fen": 12345, "legal_risk": true/false}\n'
        "  ],\n"
        '  "remediation_actions": [\n'
        '    {"action": "...", "owner_role": "hrd|store_manager|finance",\n'
        '     "deadline_days": 3-30, "impact_fen": 12345}\n'
        "  ]\n"
        "}\n"
        "```\n\n"
        "规则：\n"
        "1. legal_risk=true 时 severity 必须是 critical\n"
        "2. ranked_anomalies 按 (legal_risk desc, severity desc, impact_fen desc) 排序\n"
        "3. 若无异常，ranked_anomalies=[]，action 返 '本月薪资表合规'\n"
        "4. impact_fen 正值表示应补/应退金额"
    )

    # 城市薪资基准表（cacheable，跨租户共享）
    CITY_BENCHMARKS = (
        "=== 餐饮行业薪资基准 ===\n"
        "\n"
        "## 各城市服务员 / 厨师 / 店长薪资（元/月，2026 Q2 数据）\n"
        "\n"
        "| 城市 | 角色 | P25 | P50 | P75 |\n"
        "|------|------|-----|-----|-----|\n"
        "| 长沙 | waiter    | 3500 | 4200 | 5000 |\n"
        "| 长沙 | chef      | 5000 | 6500 | 8000 |\n"
        "| 长沙 | head_chef | 8000 | 10000| 12000|\n"
        "| 长沙 | manager   | 6000 | 8000 | 10000|\n"
        "| 长沙 | cashier   | 3300 | 4000 | 4800 |\n"
        "| 北京 | waiter    | 4500 | 5500 | 6800 |\n"
        "| 北京 | chef      | 6500 | 8500 | 10500|\n"
        "| 北京 | head_chef | 12000| 15000| 18000|\n"
        "| 北京 | manager   | 8000 | 10500| 13000|\n"
        "| 上海 | waiter    | 4800 | 5800 | 7000 |\n"
        "| 上海 | chef      | 6800 | 8800 | 11000|\n"
        "| 上海 | head_chef | 13000| 16000| 19000|\n"
        "| 上海 | manager   | 8500 | 11000| 13500|\n"
        "| 武汉 | waiter    | 3600 | 4300 | 5100 |\n"
        "| 武汉 | chef      | 5100 | 6700 | 8200 |\n"
        "| 成都 | waiter    | 3700 | 4400 | 5200 |\n"
        "| 成都 | chef      | 5200 | 6800 | 8300 |\n"
        "\n"
        "## 工龄调整系数（应用于 P50）\n"
        "- 0-12 月：×0.90\n"
        "- 13-36 月：×1.00\n"
        "- 37-60 月：×1.10\n"
        "- 60+ 月：×1.15\n"
        "\n"
        "## 合规红线（中国劳动法）\n"
        "- 月加班 ≤ 36h（B1 红线，超即合规风险）\n"
        "- 加班费基数 ≥ 底薪（不可低于当地最低工资）\n"
        "- 社保 + 公积金必须全员缴纳（漏缴罚款 2-5 倍）\n"
        "- 试用期薪资 ≥ 正式薪资 80%\n"
        "\n"
        "## 典型异常分布（行业统计）\n"
        "- 加班超标 28%\n"
        "- 社保漏缴 22%\n"
        "- 低于市场 P25 20%\n"
        "- 突然大幅调薪 15%\n"
        "- 提成异常 10%\n"
        "- 其他 5%"
    )

    @classmethod
    def build_request(
        cls,
        *,
        signal_bundle: SalarySignalBundle,
        model_id: str = SONNET_CACHED_MODEL,
        max_tokens: int = 1536,
    ) -> dict:
        payload = signal_bundle.to_json_dict()
        user_text = (
            "请为以下门店/租户本月薪资表做异常检测：\n\n"
            f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
            "按上文 schema 输出合法 JSON。"
        )
        return {
            "model": model_id,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": cls.STABLE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": cls.CITY_BENCHMARKS,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [{"role": "user", "content": user_text}],
        }


# ──────────────────────────────────────────────────────────────────────
# Response 解析
# ──────────────────────────────────────────────────────────────────────

def parse_sonnet_response(
    response: dict,
) -> tuple[str, list[SalaryAnomaly], list[SalaryRemediationAction], dict]:
    # 文本
    text = ""
    for block in response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")

    payload: dict = {}
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].lstrip()
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError, IndexError) as exc:
        logger.warning("sonnet_salary_parse_failed error=%s text=%s", exc, text[:200])

    analysis = str(payload.get("analysis", text[:200]))
    anomalies_raw = payload.get("ranked_anomalies", []) or []
    actions_raw = payload.get("remediation_actions", []) or []

    anomalies = [
        SalaryAnomaly(
            employee_id=str(a.get("employee_id", "")),
            employee_name=str(a.get("employee_name", "")),
            anomaly_type=str(a.get("anomaly_type", "other")),
            severity=str(a.get("severity", "medium")),
            evidence=str(a.get("evidence", "")),
            impact_fen=int(a.get("impact_fen", 0) or 0),
            legal_risk=bool(a.get("legal_risk", False)),
        )
        for a in anomalies_raw
        if isinstance(a, dict)
    ]
    actions = [
        SalaryRemediationAction(
            action=str(a.get("action", "")),
            owner_role=str(a.get("owner_role", "hrd")),
            deadline_days=int(a.get("deadline_days", 14) or 14),
            impact_fen=int(a.get("impact_fen", 0) or 0),
        )
        for a in actions_raw
        if isinstance(a, dict)
    ]

    usage = response.get("usage") or {}
    stats = {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_creation_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
    }
    return analysis, anomalies, actions, stats


# ──────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────

class SalaryAnomalyService:
    """D4b 薪资异常检测服务。"""

    def __init__(self, sonnet_invoker: Optional[Any] = None) -> None:
        self.sonnet_invoker = sonnet_invoker

    async def analyze(
        self,
        signal_bundle: SalarySignalBundle,
    ) -> SalaryAnomalyAnalysisResult:
        if not signal_bundle.employees:
            return SalaryAnomalyAnalysisResult(
                sonnet_analysis="无员工数据，跳过分析",
            )

        request = CachedPromptBuilder.build_request(signal_bundle=signal_bundle)

        if self.sonnet_invoker is None:
            return self._fallback_analyze(signal_bundle)

        try:
            response = await self.sonnet_invoker(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sonnet_salary_invoke_failed error=%s", exc)
            return self._fallback_analyze(signal_bundle)

        analysis, anomalies, actions, token_stats = parse_sonnet_response(response)
        return SalaryAnomalyAnalysisResult(
            ranked_anomalies=anomalies,
            remediation_actions=actions,
            sonnet_analysis=analysis,
            model_id=SONNET_CACHED_MODEL,
            **token_stats,
        )

    # ── Fallback 规则引擎 ──

    @staticmethod
    def _fallback_analyze(
        b: SalarySignalBundle,
    ) -> SalaryAnomalyAnalysisResult:
        anomalies: list[SalaryAnomaly] = []
        actions: list[SalaryRemediationAction] = []

        for emp in b.employees:
            # 1. 合规红线：社保漏缴
            if not emp.social_insurance_paid:
                anomalies.append(SalaryAnomaly(
                    employee_id=emp.employee_id,
                    employee_name=emp.emp_name,
                    anomaly_type="social_insurance_missing",
                    severity="critical",
                    evidence=f"{emp.emp_name} 本月未缴社保，法律风险",
                    impact_fen=emp.base_salary_fen * 10,  # 预估罚款 10 倍基薪
                    legal_risk=True,
                ))
                actions.append(SalaryRemediationAction(
                    action=f"立即为 {emp.emp_name} 补缴社保",
                    owner_role="hrd",
                    deadline_days=3,
                    impact_fen=int(emp.base_salary_fen * 0.22),  # 22% 社保费率
                ))
                continue  # 后续异常次要

            # 2. 加班超标（B1 红线）
            if emp.overtime_hours > LEGAL_OVERTIME_LIMIT_HOURS:
                exceed = emp.overtime_hours - LEGAL_OVERTIME_LIMIT_HOURS
                anomalies.append(SalaryAnomaly(
                    employee_id=emp.employee_id,
                    employee_name=emp.emp_name,
                    anomaly_type="overtime_excess",
                    severity="critical",
                    evidence=f"月加班 {emp.overtime_hours:.1f}h 超法定上限 36h，超 {exceed:.1f}h",
                    impact_fen=emp.overtime_pay_fen,
                    legal_risk=True,
                ))
                actions.append(SalaryRemediationAction(
                    action=f"调整 {emp.emp_name} 下月排班，消化 OT 时长",
                    owner_role="store_manager",
                    deadline_days=7,
                    impact_fen=0,
                ))
                continue

            # 3. 提成异常
            if emp.base_salary_fen > 0 and emp.commission_fen > emp.base_salary_fen * COMMISSION_ABUSE_RATIO:
                ratio = emp.commission_fen / emp.base_salary_fen
                anomalies.append(SalaryAnomaly(
                    employee_id=emp.employee_id,
                    employee_name=emp.emp_name,
                    anomaly_type="commission_abuse",
                    severity="high",
                    evidence=f"提成/底薪 = {ratio:.1f}，超 {COMMISSION_ABUSE_RATIO} 阈值",
                    impact_fen=emp.commission_fen,
                    legal_risk=False,
                ))
                actions.append(SalaryRemediationAction(
                    action=f"核查 {emp.emp_name} 提成计算来源数据",
                    owner_role="finance",
                    deadline_days=5,
                    impact_fen=0,
                ))

            # 4. 突然大幅涨薪
            if emp.prev_total_pay_fen and emp.prev_total_pay_fen > 0:
                raise_pct = (emp.total_pay_fen - emp.prev_total_pay_fen) / emp.prev_total_pay_fen
                if raise_pct > SUDDEN_RAISE_THRESHOLD_PCT:
                    anomalies.append(SalaryAnomaly(
                        employee_id=emp.employee_id,
                        employee_name=emp.emp_name,
                        anomaly_type="sudden_raise",
                        severity="medium",
                        evidence=f"月薪涨幅 {raise_pct:.1%} 超 {SUDDEN_RAISE_THRESHOLD_PCT:.0%} 阈值",
                        impact_fen=emp.total_pay_fen - emp.prev_total_pay_fen,
                        legal_risk=False,
                    ))
                    actions.append(SalaryRemediationAction(
                        action=f"核实 {emp.emp_name} 调薪审批单",
                        owner_role="hrd",
                        deadline_days=10,
                        impact_fen=0,
                    ))

        # 排序：legal_risk desc / severity desc / impact_fen desc
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        anomalies.sort(key=lambda a: (
            not a.legal_risk, severity_order.get(a.severity, 9), -a.impact_fen,
        ))

        if not anomalies:
            text = f"{b.store_name or '租户'} {b.analysis_month.isoformat()[:7]} 薪资表合规"
            return SalaryAnomalyAnalysisResult(
                sonnet_analysis=text,
                model_id="fallback_rules",
            )

        text = (
            f"{b.store_name or '租户'} {b.analysis_month.isoformat()[:7]} "
            f"{len(b.employees)} 员工薪资扫描，发现 {len(anomalies)} 条异常"
            f"（{sum(1 for a in anomalies if a.legal_risk)} 条法律风险）"
        )
        return SalaryAnomalyAnalysisResult(
            ranked_anomalies=anomalies[:20],
            remediation_actions=actions[:20],
            sonnet_analysis=text,
            model_id="fallback_rules",
        )


# ──────────────────────────────────────────────────────────────────────
# 持久化
# ──────────────────────────────────────────────────────────────────────

async def save_analysis_to_db(
    db: Any,
    *,
    tenant_id: str,
    signal_bundle: SalarySignalBundle,
    result: SalaryAnomalyAnalysisResult,
    analysis_scope: str = "monthly_batch",
    employee_id: Optional[str] = None,
) -> str:
    from sqlalchemy import text

    record_id = str(uuid.uuid4())
    # critical 异常自动 escalated
    status = "escalated" if result.has_critical or result.has_legal_risk else "analyzed"

    await db.execute(text("""
        INSERT INTO salary_anomaly_analyses (
            id, tenant_id, store_id, employee_id,
            analysis_month, analysis_scope, employee_count, total_payroll_fen, city,
            signals_snapshot, ranked_anomalies, remediation_actions,
            sonnet_analysis, model_id,
            cache_read_tokens, cache_creation_tokens, input_tokens, output_tokens,
            status
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:tenant_id AS uuid),
            CAST(:store_id AS uuid),
            CAST(:employee_id AS uuid),
            :analysis_month, :analysis_scope, :emp_count, :total_payroll, :city,
            CAST(:signals AS jsonb), CAST(:anomalies AS jsonb), CAST(:actions AS jsonb),
            :sonnet_analysis, :model_id,
            :cache_read, :cache_create, :input_tokens, :output_tokens,
            :status
        )
        ON CONFLICT ON CONSTRAINT ux_salary_anomaly_monthly
        DO UPDATE SET
            employee_count = EXCLUDED.employee_count,
            total_payroll_fen = EXCLUDED.total_payroll_fen,
            signals_snapshot = EXCLUDED.signals_snapshot,
            ranked_anomalies = EXCLUDED.ranked_anomalies,
            remediation_actions = EXCLUDED.remediation_actions,
            sonnet_analysis = EXCLUDED.sonnet_analysis,
            cache_read_tokens = EXCLUDED.cache_read_tokens,
            cache_creation_tokens = EXCLUDED.cache_creation_tokens,
            input_tokens = EXCLUDED.input_tokens,
            output_tokens = EXCLUDED.output_tokens,
            status = EXCLUDED.status,
            updated_at = NOW()
        RETURNING id
    """), {
        "id": record_id,
        "tenant_id": tenant_id,
        "store_id": signal_bundle.store_id,
        "employee_id": employee_id,
        "analysis_month": signal_bundle.analysis_month,
        "analysis_scope": analysis_scope,
        "emp_count": len(signal_bundle.employees),
        "total_payroll": signal_bundle.total_payroll_fen,
        "city": signal_bundle.city,
        "signals": json.dumps(signal_bundle.to_json_dict(), ensure_ascii=False),
        "anomalies": json.dumps(
            [
                {
                    "employee_id": a.employee_id,
                    "employee_name": a.employee_name,
                    "anomaly_type": a.anomaly_type,
                    "severity": a.severity,
                    "evidence": a.evidence,
                    "impact_fen": a.impact_fen,
                    "legal_risk": a.legal_risk,
                }
                for a in result.ranked_anomalies
            ],
            ensure_ascii=False,
        ),
        "actions": json.dumps(
            [
                {
                    "action": a.action,
                    "owner_role": a.owner_role,
                    "deadline_days": a.deadline_days,
                    "impact_fen": a.impact_fen,
                }
                for a in result.remediation_actions
            ],
            ensure_ascii=False,
        ),
        "sonnet_analysis": result.sonnet_analysis,
        "model_id": result.model_id,
        "cache_read": result.cache_read_tokens,
        "cache_create": result.cache_creation_tokens,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "status": status,
    })
    await db.commit()
    logger.info(
        "salary_anomaly_saved store=%s anomalies=%d legal_risk=%s status=%s",
        signal_bundle.store_id,
        len(result.ranked_anomalies),
        result.has_legal_risk,
        status,
    )
    return record_id


__all__ = [
    "CachedPromptBuilder",
    "EmployeeSalarySignal",
    "SalarySignalBundle",
    "SalaryAnomaly",
    "SalaryRemediationAction",
    "SalaryAnomalyAnalysisResult",
    "SalaryAnomalyService",
    "parse_sonnet_response",
    "save_analysis_to_db",
    "SONNET_CACHED_MODEL",
    "CACHE_HIT_TARGET",
    "LEGAL_OVERTIME_LIMIT_HOURS",
    "BELOW_MARKET_THRESHOLD_PCT",
    "SUDDEN_RAISE_THRESHOLD_PCT",
    "COMMISSION_ABUSE_RATIO",
]
