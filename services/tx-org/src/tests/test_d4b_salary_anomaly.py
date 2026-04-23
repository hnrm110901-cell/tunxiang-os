"""test_d4b_salary_anomaly.py —— Sprint D4b 薪资异常检测测试

覆盖：
  1. SalarySignalBundle.to_json_dict 序列化
  2. CachedPromptBuilder 结构 + cache_control + city benchmarks 内容
  3. parse_sonnet_response：JSON / code fence / 损坏降级
  4. Fallback 规则引擎：5 种异常类型
  5. 排序：legal_risk desc / severity desc / impact_fen desc
  6. has_critical / has_legal_risk 属性
  7. invoker 成功 + 失败降级
  8. cache_hit_rate 计算
  9. v280 迁移静态校验
  10. ModelRouter 注册 salary_anomaly_detection
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.salary_anomaly_service import (  # noqa: E402
    CACHE_HIT_TARGET,
    COMMISSION_ABUSE_RATIO,
    LEGAL_OVERTIME_LIMIT_HOURS,
    SONNET_CACHED_MODEL,
    SUDDEN_RAISE_THRESHOLD_PCT,
    CachedPromptBuilder,
    EmployeeSalarySignal,
    SalaryAnomalyAnalysisResult,
    SalaryAnomalyService,
    SalarySignalBundle,
    parse_sonnet_response,
)

# ──────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────

def _emp(
    employee_id: str = "e1",
    emp_name: str = "张三",
    role: str = "waiter",
    city: str = "长沙",
    seniority_months: int = 18,
    base_salary_fen: int = 400000,  # 4000 元
    overtime_hours: float = 10.0,
    overtime_pay_fen: int = 100000,
    commission_fen: int = 50000,
    total_pay_fen: int = 550000,
    prev_total_pay_fen: int | None = 500000,
    social_insurance_paid: bool = True,
    housing_fund_paid: bool = True,
) -> EmployeeSalarySignal:
    return EmployeeSalarySignal(
        employee_id=employee_id, emp_name=emp_name, role=role, city=city,
        seniority_months=seniority_months, base_salary_fen=base_salary_fen,
        overtime_hours=overtime_hours, overtime_pay_fen=overtime_pay_fen,
        commission_fen=commission_fen, total_pay_fen=total_pay_fen,
        prev_total_pay_fen=prev_total_pay_fen,
        social_insurance_paid=social_insurance_paid, housing_fund_paid=housing_fund_paid,
    )


def _bundle(employees: list | None = None) -> SalarySignalBundle:
    return SalarySignalBundle(
        tenant_id="00000000-0000-0000-0000-000000000001",
        store_id="00000000-0000-0000-0000-000000000002",
        store_name="五一店",
        analysis_month=date(2026, 3, 1),
        city="长沙",
        employees=employees or [_emp()],
    )


def _mock_response(payload: dict, usage: dict | None = None) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "usage": usage or {},
    }


# ──────────────────────────────────────────────────────────────────────
# 1. SalarySignalBundle 序列化
# ──────────────────────────────────────────────────────────────────────

def test_bundle_serializes():
    b = _bundle()
    d = b.to_json_dict()
    assert d["city"] == "长沙"
    assert d["employee_count"] == 1
    assert d["total_payroll_yuan"] == 5500.0
    assert d["employees"][0]["name"] == "张三"


def test_bundle_total_payroll_property():
    b = _bundle([
        _emp(total_pay_fen=500000),
        _emp(employee_id="e2", total_pay_fen=300000),
    ])
    assert b.total_payroll_fen == 800000


# ──────────────────────────────────────────────────────────────────────
# 2. CachedPromptBuilder
# ──────────────────────────────────────────────────────────────────────

def test_builder_request_structure():
    req = CachedPromptBuilder.build_request(signal_bundle=_bundle())
    assert req["model"] == SONNET_CACHED_MODEL
    assert isinstance(req["system"], list) and len(req["system"]) == 2
    for block in req["system"]:
        assert block["cache_control"] == {"type": "ephemeral"}
        assert len(block["text"]) > 100
    assert len(req["messages"]) == 1
    assert "五一店" in req["messages"][0]["content"]


def test_builder_system_contains_city_benchmarks():
    req = CachedPromptBuilder.build_request(signal_bundle=_bundle())
    system_text = "\n".join(b["text"] for b in req["system"])
    # 异常类型
    assert "below_market" in system_text
    assert "overtime_excess" in system_text
    assert "sudden_raise" in system_text
    assert "commission_abuse" in system_text
    assert "social_insurance_missing" in system_text
    # 城市基准
    assert "长沙" in system_text
    assert "P50" in system_text
    # 合规红线
    assert "36h" in system_text


# ──────────────────────────────────────────────────────────────────────
# 3. parse_sonnet_response
# ──────────────────────────────────────────────────────────────────────

def test_parse_valid_json():
    payload = {
        "analysis": "一切合规",
        "ranked_anomalies": [
            {
                "employee_id": "e1", "employee_name": "张三",
                "anomaly_type": "overtime_excess", "severity": "critical",
                "evidence": "加班 50h", "impact_fen": 200000, "legal_risk": True,
            },
        ],
        "remediation_actions": [
            {
                "action": "调整排班", "owner_role": "store_manager",
                "deadline_days": 7, "impact_fen": 0,
            },
        ],
    }
    usage = {
        "input_tokens": 1000, "output_tokens": 400,
        "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 0,
    }
    analysis, anomalies, actions, stats = parse_sonnet_response(_mock_response(payload, usage))
    assert analysis == "一切合规"
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "overtime_excess"
    assert anomalies[0].legal_risk is True
    assert actions[0].owner_role == "store_manager"
    assert stats["cache_read_tokens"] == 3000


def test_parse_code_fence():
    inner = {
        "analysis": "test", "ranked_anomalies": [],
        "remediation_actions": [{"action": "ok", "owner_role": "hrd",
                                 "deadline_days": 7, "impact_fen": 0}],
    }
    wrapped = f"```json\n{json.dumps(inner)}\n```"
    response = {"content": [{"type": "text", "text": wrapped}], "usage": {}}
    analysis, _, actions, _ = parse_sonnet_response(response)
    assert analysis == "test"
    assert len(actions) == 1


def test_parse_broken_falls_back():
    response = {"content": [{"type": "text", "text": "非 JSON"}], "usage": {}}
    analysis, anomalies, actions, _ = parse_sonnet_response(response)
    assert analysis  # 非空
    assert anomalies == []
    assert actions == []


# ──────────────────────────────────────────────────────────────────────
# 4. Fallback 规则引擎（5 种异常类型）
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_social_insurance_missing_critical():
    """漏缴社保 → critical + legal_risk"""
    service = SalaryAnomalyService()
    b = _bundle([_emp(social_insurance_paid=False)])
    result = await service.analyze(b)
    types = [a.anomaly_type for a in result.ranked_anomalies]
    assert "social_insurance_missing" in types
    miss = next(a for a in result.ranked_anomalies if a.anomaly_type == "social_insurance_missing")
    assert miss.severity == "critical"
    assert miss.legal_risk is True


@pytest.mark.asyncio
async def test_fallback_overtime_excess():
    service = SalaryAnomalyService()
    b = _bundle([_emp(overtime_hours=LEGAL_OVERTIME_LIMIT_HOURS + 10)])  # 46h > 36h
    result = await service.analyze(b)
    types = [a.anomaly_type for a in result.ranked_anomalies]
    assert "overtime_excess" in types
    a = next(a for a in result.ranked_anomalies if a.anomaly_type == "overtime_excess")
    assert a.severity == "critical"
    assert a.legal_risk is True


@pytest.mark.asyncio
async def test_fallback_commission_abuse():
    """提成 > 底薪 200% → commission_abuse high"""
    service = SalaryAnomalyService()
    b = _bundle([_emp(
        base_salary_fen=300000,
        commission_fen=700000,  # 700/300 = 2.33x > 2.0
        total_pay_fen=1000000,
        prev_total_pay_fen=800000,  # 避免触发 sudden_raise
    )])
    result = await service.analyze(b)
    types = [a.anomaly_type for a in result.ranked_anomalies]
    assert "commission_abuse" in types


@pytest.mark.asyncio
async def test_fallback_sudden_raise():
    """涨薪 > 30% → sudden_raise medium"""
    service = SalaryAnomalyService()
    b = _bundle([_emp(
        total_pay_fen=700000,
        prev_total_pay_fen=500000,  # 40% 涨幅
        # 避免触发其他异常
        commission_fen=50000, base_salary_fen=600000,
    )])
    result = await service.analyze(b)
    types = [a.anomaly_type for a in result.ranked_anomalies]
    assert "sudden_raise" in types


@pytest.mark.asyncio
async def test_fallback_no_anomalies_returns_clean():
    """一切合规"""
    service = SalaryAnomalyService()
    result = await service.analyze(_bundle())  # 默认无异常
    assert result.ranked_anomalies == []
    assert "合规" in result.sonnet_analysis
    assert result.model_id == "fallback_rules"


@pytest.mark.asyncio
async def test_fallback_empty_employees_returns_skip():
    service = SalaryAnomalyService()
    result = await service.analyze(
        SalarySignalBundle(
            tenant_id="x", store_id=None, store_name=None,
            analysis_month=date(2026, 3, 1), city="长沙", employees=[],
        ),
    )
    assert result.ranked_anomalies == []
    assert "跳过" in result.sonnet_analysis or "无员工" in result.sonnet_analysis


# ──────────────────────────────────────────────────────────────────────
# 5. 排序（legal_risk desc / severity desc）
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_sorts_legal_risk_first():
    """2 员工：一个社保漏缴 + 一个提成异常 → 社保漏缴排第一"""
    service = SalaryAnomalyService()
    b = _bundle([
        _emp(employee_id="e1", emp_name="张三",
             base_salary_fen=300000, commission_fen=700000, total_pay_fen=1000000,
             prev_total_pay_fen=900000,
             social_insurance_paid=True),  # commission_abuse (high)
        _emp(employee_id="e2", emp_name="李四",
             social_insurance_paid=False),  # critical + legal_risk
    ])
    result = await service.analyze(b)
    assert len(result.ranked_anomalies) >= 2
    # 第一条必须是社保漏缴
    assert result.ranked_anomalies[0].legal_risk is True
    assert result.ranked_anomalies[0].anomaly_type == "social_insurance_missing"


# ──────────────────────────────────────────────────────────────────────
# 6. has_critical / has_legal_risk
# ──────────────────────────────────────────────────────────────────────

def test_result_critical_and_legal_risk_properties():
    from services.salary_anomaly_service import SalaryAnomaly
    r = SalaryAnomalyAnalysisResult(
        ranked_anomalies=[
            SalaryAnomaly(employee_id="e1", employee_name="n",
                          anomaly_type="other", severity="critical",
                          evidence="x", impact_fen=0, legal_risk=False),
        ],
    )
    assert r.has_critical is True
    assert r.has_legal_risk is False

    r.ranked_anomalies[0].legal_risk = True
    assert r.has_legal_risk is True


# ──────────────────────────────────────────────────────────────────────
# 7. invoker 成功 + 失败降级
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invoker_success_path():
    invoked = []

    async def mock_sonnet(request: dict) -> dict:
        invoked.append(request)
        return _mock_response(
            {
                "analysis": "Sonnet 输出",
                "ranked_anomalies": [
                    {
                        "employee_id": "e1", "employee_name": "张三",
                        "anomaly_type": "below_market", "severity": "high",
                        "evidence": "底薪 3500 低于长沙 P50 4200",
                        "impact_fen": 7000, "legal_risk": False,
                    },
                ],
                "remediation_actions": [
                    {
                        "action": "涨薪至市场 P50", "owner_role": "hrd",
                        "deadline_days": 30, "impact_fen": 7000,
                    },
                ],
            },
            usage={"input_tokens": 500, "output_tokens": 300,
                   "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 0},
        )

    service = SalaryAnomalyService(sonnet_invoker=mock_sonnet)
    result = await service.analyze(_bundle())

    assert len(invoked) == 1
    req = invoked[0]
    assert req["model"] == SONNET_CACHED_MODEL
    assert len(req["system"]) == 2
    assert result.sonnet_analysis == "Sonnet 输出"
    assert len(result.ranked_anomalies) == 1
    assert result.ranked_anomalies[0].anomaly_type == "below_market"
    assert result.cache_read_tokens == 3000


@pytest.mark.asyncio
async def test_invoker_failure_falls_back_to_rules():
    async def boom(request):
        raise RuntimeError("API 503")

    service = SalaryAnomalyService(sonnet_invoker=boom)
    result = await service.analyze(_bundle([_emp(social_insurance_paid=False)]))
    assert result.model_id == "fallback_rules"
    assert any(a.anomaly_type == "social_insurance_missing" for a in result.ranked_anomalies)


# ──────────────────────────────────────────────────────────────────────
# 8. cache_hit_rate 计算
# ──────────────────────────────────────────────────────────────────────

def test_cache_hit_rate_zero_when_no_cache():
    r = SalaryAnomalyAnalysisResult(input_tokens=1000, output_tokens=500)
    assert r.cache_hit_rate == 0.0


def test_cache_hit_rate_high():
    r = SalaryAnomalyAnalysisResult(
        cache_read_tokens=3000, cache_creation_tokens=0,
        input_tokens=1000, output_tokens=500,
    )
    # 3000 / 4000 = 0.75
    assert r.cache_hit_rate == pytest.approx(0.75, abs=0.001)


def test_cache_hit_target_constant():
    assert CACHE_HIT_TARGET == 0.75


def test_thresholds_match_design():
    assert LEGAL_OVERTIME_LIMIT_HOURS == 36
    assert SUDDEN_RAISE_THRESHOLD_PCT == 0.30
    assert COMMISSION_ABUSE_RATIO == 2.0


# ──────────────────────────────────────────────────────────────────────
# 9. v280 迁移静态校验
# ──────────────────────────────────────────────────────────────────────

_MIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "shared", "db-migrations", "versions", "v280_salary_anomaly_analyses.py"
)


def _read_mig() -> str:
    if not os.path.exists(_MIG_PATH):
        pytest.skip("v280 不存在")
    with open(_MIG_PATH, encoding="utf-8") as f:
        return f.read()


def test_v280_creates_table_with_required_columns():
    content = _read_mig()
    for col in (
        "analysis_month", "analysis_scope", "employee_count", "total_payroll_fen",
        "city", "signals_snapshot", "ranked_anomalies", "remediation_actions",
        "sonnet_analysis", "model_id",
        "cache_read_tokens", "cache_creation_tokens",
        "input_tokens", "output_tokens",
        "status", "reviewed_by", "reviewed_at",
        "employee_id",
    ):
        assert col in content, f"缺列 {col}"


def test_v280_status_and_scope_enums():
    content = _read_mig()
    for s in ("pending", "analyzed", "acted_on", "dismissed", "escalated", "error"):
        assert s in content, f"缺 status={s}"
    for t in ("monthly_batch", "single_employee", "anomaly_triggered", "manual"):
        assert t in content, f"缺 analysis_scope={t}"


def test_v280_has_unique_monthly_batch_index():
    content = _read_mig()
    assert "ux_salary_anomaly_monthly" in content
    assert "analysis_scope = 'monthly_batch'" in content


def test_v280_has_rls_and_indexes():
    content = _read_mig()
    assert "ENABLE ROW LEVEL SECURITY" in content
    assert "salary_anomaly_tenant_isolation" in content
    assert "app.tenant_id" in content
    assert "idx_salary_anomaly_tenant_status" in content
    assert "idx_salary_anomaly_employee_history" in content


def test_v280_down_revision_chains_to_v279():
    content = _read_mig()
    assert 'down_revision = "v279_cost_root_cause"' in content


# ──────────────────────────────────────────────────────────────────────
# 10. ModelRouter 注册
# ──────────────────────────────────────────────────────────────────────

def test_model_router_registers_salary_anomaly_detection():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "services", "tunxiang-api", "src", "shared", "core", "model_router.py"
    )
    if not os.path.exists(path):
        pytest.skip("model_router.py 不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert '"salary_anomaly_detection": TaskComplexity.COMPLEX' in content
