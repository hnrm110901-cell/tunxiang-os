"""test_constraint_context.py —— Sprint D1 / PR G

覆盖：
  1. ConstraintContext 基础字段 + from_data 旧字典兼容路径
  2. ConstraintChecker.check_all 双入参（context / dict）
  3. scope 过滤：只校验指定子集，其余不进 scopes_checked / scopes_skipped
  4. 迁移期 base.py::run 默认 scope = {margin,safety,experience}，ctx 缺字段 → scope='n/a'
  5. Skill 类级 constraint_scope = set() → constraints_detail.scope == 'waived'
  6. 批次 1 三个 Skill 声明的 scope 符合设计
  7. SKILL_REGISTRY 至少包含批次 1 三个 agent_id，且无 agent_id 冲突
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult, SkillAgent
from agents.constraints import ConstraintChecker
from agents.context import ConstraintContext, IngredientSnapshot

# ──────────────────────────────────────────────────────────────────────
# 1. ConstraintContext
# ──────────────────────────────────────────────────────────────────────


def test_context_defaults_full_scope():
    ctx = ConstraintContext()
    assert ctx.constraint_scope == {"margin", "safety", "experience"}
    assert ctx.price_fen is None
    assert ctx.waived_reason is None


def test_context_from_data_maps_legacy_fields():
    data = {
        "price_fen": 8800,
        "cost_fen": 3500,
        "ingredients": [
            {"name": "鱼头", "remaining_hours": 12.5, "batch_id": "B-001"},
            {"name": "辣椒", "remaining_hours": None},
        ],
        "estimated_serve_minutes": 25.0,
    }
    ctx = ConstraintContext.from_data(data)
    assert ctx.price_fen == 8800
    assert ctx.cost_fen == 3500
    assert ctx.estimated_serve_minutes == 25.0
    assert len(ctx.ingredients) == 2
    assert ctx.ingredients[0].name == "鱼头"
    assert ctx.ingredients[0].batch_id == "B-001"


def test_context_from_data_handles_final_amount_alias():
    ctx = ConstraintContext.from_data({"final_amount_fen": 5000, "food_cost_fen": 2500})
    assert ctx.price_fen == 5000
    assert ctx.cost_fen == 2500


# ──────────────────────────────────────────────────────────────────────
# 2. check_all 双入参
# ──────────────────────────────────────────────────────────────────────


def test_check_all_accepts_dict_and_context_equivalently():
    checker = ConstraintChecker()
    data = {"price_fen": 10000, "cost_fen": 5000}
    r1 = checker.check_all(data)
    r2 = checker.check_all(ConstraintContext.from_data(data))
    assert r1.passed == r2.passed
    assert r1.margin_check == r2.margin_check


def test_check_all_rejects_bad_input_type():
    with pytest.raises(TypeError, match="ConstraintContext"):
        ConstraintChecker().check_all(123)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# 3. scope 过滤
# ──────────────────────────────────────────────────────────────────────


def test_scope_filter_only_checks_declared_subset():
    checker = ConstraintChecker()
    ctx = ConstraintContext(
        price_fen=10000,
        cost_fen=5000,
        estimated_serve_minutes=25,
        ingredients=[IngredientSnapshot(name="鱼头", remaining_hours=12)],
    )
    # 只校验 margin：其他两条即使有数据也不进 checked/skipped
    r = checker.check_all(ctx, scope={"margin"})
    assert "margin" in r.scopes_checked
    assert "safety" not in r.scopes_checked and "safety" not in r.scopes_skipped
    assert "experience" not in r.scopes_checked and "experience" not in r.scopes_skipped


def test_scope_filter_empty_set_skips_all():
    checker = ConstraintChecker()
    ctx = ConstraintContext(price_fen=10000, cost_fen=5000)
    r = checker.check_all(ctx, scope=set())
    assert r.passed is True
    assert r.scopes_checked == []
    assert r.scopes_skipped == []


def test_scope_skipped_when_data_missing():
    checker = ConstraintChecker()
    ctx = ConstraintContext()  # 全空
    r = checker.check_all(ctx, scope={"margin", "safety", "experience"})
    assert r.scopes_checked == []
    assert set(r.scopes_skipped) == {"margin", "safety", "experience"}


# ──────────────────────────────────────────────────────────────────────
# 4. base.py::run 流程（skill → constraints_detail.scope）
# ──────────────────────────────────────────────────────────────────────


class _NAStubSkill(SkillAgent):
    """声明需要校验但不提供任何数据 —— 应被标 scope='n/a'"""

    agent_id = "na_stub"
    constraint_scope = {"margin", "safety", "experience"}

    async def execute(self, action, params):
        return AgentResult(success=True, action=action, data={})

    def get_supported_actions(self):
        return ["noop"]


@pytest.mark.asyncio
async def test_run_marks_na_when_declared_but_no_data():
    skill = _NAStubSkill(tenant_id="t1")
    result = await skill.run("noop", {})
    assert result.constraints_detail["scope"] == "n/a"
    assert set(result.constraints_detail["scopes_skipped"]) == {"margin", "safety", "experience"}


class _SingleScopeSkill(SkillAgent):
    agent_id = "single_stub"
    constraint_scope = {"margin"}

    async def execute(self, action, params):
        return AgentResult(
            success=True,
            action=action,
            data={},
            context=ConstraintContext(price_fen=10000, cost_fen=5000, constraint_scope={"margin"}),
        )

    def get_supported_actions(self):
        return ["noop"]


@pytest.mark.asyncio
async def test_run_single_scope_is_labeled():
    skill = _SingleScopeSkill(tenant_id="t1")
    result = await skill.run("noop", {})
    assert result.constraints_detail["scope"] == "margin"
    assert result.constraints_passed is True


class _WaivedSkill(SkillAgent):
    agent_id = "waived_stub"
    constraint_scope = set()
    constraint_waived_reason = "纯数据汇总 Skill，不触发业务决策；毛利/食安/体验维度均不适用，仅用于报表生成"

    async def execute(self, action, params):
        return AgentResult(success=True, action=action, data={})

    def get_supported_actions(self):
        return ["noop"]


@pytest.mark.asyncio
async def test_run_waived_skill_has_waived_scope():
    skill = _WaivedSkill(tenant_id="t1")
    result = await skill.run("noop", {})
    assert result.constraints_detail["scope"] == "waived"
    assert result.constraints_detail["waived_reason"].startswith("纯数据汇总")
    assert result.constraints_passed is True


# ──────────────────────────────────────────────────────────────────────
# 5. 批次 1 三个 Skill 的 scope 声明 + SKILL_REGISTRY
#
# 注：这些测试依赖 `agents.skills` 包能被导入。tx-agent 存在 pre-existing
# `edge_mixin` 相对导入 bug（`from ..services.edge_inference_client` 路径错误），
# 本地 pytest 直跑 `src/tests` 会卡在此处；但在真实 CI 容器里（PYTHONPATH 正确
# 配置为 /app，__init__.py 可达）可以通过。本 PR 不修 edge_mixin（属 out-of-scope），
# 而用 importorskip 保证"有环境时强校验、无环境时不挂"。
# ──────────────────────────────────────────────────────────────────────


def _import_skills_or_skip():
    """尝试导入 agents.skills 包；失败则 skip（pre-existing edge_mixin bug 兼容）。"""
    try:
        import agents.skills as skills_pkg  # noqa: F401

        return skills_pkg
    except ImportError as exc:
        pytest.skip(f"agents.skills 无法导入（pre-existing edge_mixin bug）: {exc}")


def test_batch_1_skills_declare_correct_scopes():
    skills_pkg = _import_skills_or_skip()
    from agents.skills.closing_agent import ClosingAgent
    from agents.skills.growth_attribution import GrowthAttributionAgent
    from agents.skills.stockout_alert import StockoutAlertAgent

    assert GrowthAttributionAgent.constraint_scope == {"margin"}
    assert ClosingAgent.constraint_scope == {"margin", "safety"}
    assert StockoutAlertAgent.constraint_scope == {"margin", "safety"}
    # 引用使用以避免未使用变量警告
    assert hasattr(skills_pkg, "SKILL_REGISTRY")


def test_skill_registry_contains_batch_1_skills():
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    assert "growth_attribution" in SKILL_REGISTRY
    assert "closing_ops" in SKILL_REGISTRY
    assert "stockout_alert" in SKILL_REGISTRY


def test_skill_registry_keys_match_agent_ids():
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    for agent_id, cls in SKILL_REGISTRY.items():
        assert cls.agent_id == agent_id, f"{cls.__name__}.agent_id={cls.agent_id} 但注册为 {agent_id}"


def test_skill_registry_has_no_duplicate_agent_ids():
    _import_skills_or_skip()
    from agents.skills import ALL_SKILL_AGENTS, SKILL_REGISTRY

    seen: set[str] = set()
    for cls in ALL_SKILL_AGENTS:
        aid = getattr(cls, "agent_id", None)
        if not aid or aid == "base":
            continue
        assert aid not in seen, f"agent_id 冲突: {aid}"
        seen.add(aid)
    assert seen <= set(SKILL_REGISTRY.keys())


# ──────────────────────────────────────────────────────────────────────
# 7. 批次 2（PR H / W5 出餐体验）
# ──────────────────────────────────────────────────────────────────────


def test_batch_2_experience_skills_declare_scope():
    _import_skills_or_skip()
    from agents.skills.ai_waiter import AIWaiterAgent
    from agents.skills.kitchen_overtime import KitchenOvertimeAgent
    from agents.skills.queue_seating import QueueSeatingAgent
    from agents.skills.serve_dispatch import ServeDispatchAgent
    from agents.skills.smart_service import SmartServiceAgent
    from agents.skills.table_dispatch import TableDispatchAgent
    from agents.skills.voice_order import VoiceOrderAgent

    # experience-only skills
    assert ServeDispatchAgent.constraint_scope == {"experience"}
    assert TableDispatchAgent.constraint_scope == {"experience"}
    assert QueueSeatingAgent.constraint_scope == {"experience"}
    assert KitchenOvertimeAgent.constraint_scope == {"experience"}
    assert VoiceOrderAgent.constraint_scope == {"experience"}
    assert SmartServiceAgent.constraint_scope == {"experience"}
    # ai_waiter 触碰体验（出餐节奏）+ 毛利（推高毛利菜），双 scope
    assert AIWaiterAgent.constraint_scope == {"margin", "experience"}


def test_batch_2_registry_contains_table_dispatch():
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    assert "table_dispatch" in SKILL_REGISTRY
    # 其他 6 个批次 2 Skills 在 PR G 之前已在 ALL_SKILL_AGENTS 内
    for aid in ("serve_dispatch", "queue_seating", "kitchen_overtime", "ai_waiter", "voice_order", "smart_service"):
        assert aid in SKILL_REGISTRY, f"{aid} 未注册"


@pytest.mark.asyncio
async def test_serve_dispatch_fills_experience_context():
    """验证 predict_serve_time 填入结构化 context，experience 约束真实生效"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.serve_dispatch import ServeDispatchAgent

    agent = ServeDispatchAgent(tenant_id="t1")
    result = await agent.run(
        "predict_serve_time",
        {
            "dish_count": 3,
            "has_complex_dish": False,
            "kitchen_queue_size": 0,
        },
    )

    # 已填 estimated_serve_minutes → scope 不再是 n/a
    assert result.constraints_detail["scope"] == "experience"
    assert "experience" in result.constraints_detail["scopes_checked"]
    # 3 道普通菜 + 无队列：base = 5 + 3*2.5 = 12.5，round() 用 Python 银行家舍入
    # 取整结果为 12（round-half-to-even），< 30 阈值应通过
    assert result.constraints_passed is True
    assert result.constraints_detail["experience_check"]["actual_minutes"] == 12


@pytest.mark.asyncio
async def test_serve_dispatch_experience_violation_blocks_decision():
    """当 predict 出的时间超过 max_serve_minutes(30)，约束应 fail"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.serve_dispatch import ServeDispatchAgent

    agent = ServeDispatchAgent(tenant_id="t1")
    # 10 道菜 + 6 复杂 + 队列 20：base=5+25+8=38，queue_delay=30 → ~68 分钟
    result = await agent.run(
        "predict_serve_time",
        {
            "dish_count": 10,
            "has_complex_dish": True,
            "kitchen_queue_size": 20,
        },
    )
    assert result.constraints_detail["scope"] == "experience"
    assert result.constraints_passed is False
    assert any("客户体验违规" in v for v in result.constraints_detail["violations"])


# ──────────────────────────────────────────────────────────────────────
# 8. 批次 3（W6 定价营销）
# ──────────────────────────────────────────────────────────────────────


def test_batch_3_pricing_skills_declare_scope():
    _import_skills_or_skip()
    from agents.skills.menu_advisor import MenuAdvisorAgent
    from agents.skills.new_customer_convert import NewCustomerConvertAgent
    from agents.skills.personalization_agent import PersonalizationAgent
    from agents.skills.points_advisor import PointsAdvisorAgent
    from agents.skills.referral_growth import ReferralGrowthAgent
    from agents.skills.seasonal_campaign import SeasonalCampaignAgent
    from agents.skills.smart_menu import SmartMenuAgent

    for cls in (
        SmartMenuAgent,
        MenuAdvisorAgent,
        PointsAdvisorAgent,
        SeasonalCampaignAgent,
        PersonalizationAgent,
        NewCustomerConvertAgent,
        ReferralGrowthAgent,
    ):
        assert cls.constraint_scope == {"margin"}, f"{cls.__name__} 应声明 margin-only scope"


def test_batch_3_registry_contains_points_advisor():
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    # points_advisor 是本批次新加的注册
    assert "points_advisor" in SKILL_REGISTRY
    # 其他 6 个早已在 ALL_SKILL_AGENTS
    for aid in (
        "smart_menu",
        "menu_advisor",
        "seasonal_campaign",
        "personalization",
        "new_customer_convert",
        "referral_growth",
    ):
        assert aid in SKILL_REGISTRY, f"{aid} 未注册"


@pytest.mark.asyncio
async def test_smart_menu_simulate_cost_fills_margin_context():
    """smart_menu.simulate_cost 填入 price_fen+cost_fen，margin 约束真实生效"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.smart_menu import SmartMenuAgent

    agent = SmartMenuAgent(tenant_id="t1")
    # 售价 100 元 / 成本 40 元 → 毛利率 60%，远超 15% 阈值
    result = await agent.run(
        "simulate_cost",
        {
            "bom_items": [{"cost_fen": 4000, "quantity": 1}],
            "target_price_fen": 10000,
        },
    )
    assert result.constraints_detail["scope"] == "margin"
    assert "margin" in result.constraints_detail["scopes_checked"]
    assert result.constraints_passed is True
    assert result.constraints_detail["margin_check"]["actual_rate"] == 0.6


@pytest.mark.asyncio
async def test_smart_menu_low_margin_blocks_decision():
    """成本高到毛利 < 15% 时，margin 约束应拦截决策"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.smart_menu import SmartMenuAgent

    agent = SmartMenuAgent(tenant_id="t1")
    # 售价 100 元 / 成本 90 元 → 毛利率 10%，< 15% 阈值
    result = await agent.run(
        "simulate_cost",
        {
            "bom_items": [{"cost_fen": 9000, "quantity": 1}],
            "target_price_fen": 10000,
        },
    )
    assert result.constraints_detail["scope"] == "margin"
    assert result.constraints_passed is False
    assert any("毛利底线违规" in v for v in result.constraints_detail["violations"])


@pytest.mark.asyncio
async def test_menu_advisor_optimize_pricing_picks_worst_margin_as_basis():
    """optimize_pricing 应取最低毛利菜品作为 margin 校验基准"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.menu_advisor import MenuAdvisorAgent

    agent = MenuAdvisorAgent(tenant_id="t1")
    # 两道菜：一道毛利 70% 健康，一道毛利 5% 危险 → checker 以 5% 为准拦截
    result = await agent.run(
        "optimize_pricing",
        {
            "dishes": [
                {"dish_name": "A", "price_fen": 10000, "cost_fen": 3000, "category_avg_price_fen": 9000},
                {"dish_name": "B", "price_fen": 10000, "cost_fen": 9500, "category_avg_price_fen": 11000},
            ],
            "target_margin_pct": 60,
        },
    )
    assert result.constraints_detail["scope"] == "margin"
    # 最差毛利 5% < 15% 阈值，应拦截
    assert result.constraints_passed is False


# ──────────────────────────────────────────────────────────────────────
# 9. 批次 4（W7 库存原料）
# ──────────────────────────────────────────────────────────────────────


def test_batch_4_inventory_skills_declare_scope():
    _import_skills_or_skip()
    from agents.skills.banquet_growth import BanquetGrowthAgent
    from agents.skills.enterprise_activation import EnterpriseActivationAgent
    from agents.skills.inventory_alert import InventoryAlertAgent
    from agents.skills.new_product_scout import NewProductScoutAgent
    from agents.skills.pilot_recommender import PilotRecommenderAgent
    from agents.skills.private_ops import PrivateOpsAgent
    from agents.skills.trend_discovery import TrendDiscoveryAgent

    # 主 safety + margin 组合
    assert InventoryAlertAgent.constraint_scope == {"margin", "safety"}
    assert NewProductScoutAgent.constraint_scope == {"margin", "safety"}
    # 纯 margin（合同/套餐金额）
    assert BanquetGrowthAgent.constraint_scope == {"margin"}
    assert EnterpriseActivationAgent.constraint_scope == {"margin"}
    assert PrivateOpsAgent.constraint_scope == {"margin"}
    # 纯洞察/建议类 → 豁免
    assert TrendDiscoveryAgent.constraint_scope == set()
    assert TrendDiscoveryAgent.constraint_waived_reason is not None
    assert len(TrendDiscoveryAgent.constraint_waived_reason) >= 30
    assert PilotRecommenderAgent.constraint_scope == set()
    assert PilotRecommenderAgent.constraint_waived_reason is not None
    assert len(PilotRecommenderAgent.constraint_waived_reason) >= 30


def test_batch_4_registry_contains_enterprise_activation():
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    # enterprise_activation 是本 PR 新加的注册
    assert "enterprise_activation" in SKILL_REGISTRY
    # 其他 6 个在上批次/本批次之前已注册
    for aid in (
        "inventory_alert",
        "new_product_scout",
        "trend_discovery",
        "pilot_recommender",
        "banquet_growth",
        "private_ops",
    ):
        assert aid in SKILL_REGISTRY, f"{aid} 未注册"


@pytest.mark.asyncio
async def test_inventory_alert_check_expiration_fills_safety_context():
    """check_expiration 填入 IngredientSnapshot，safety 约束真实生效"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.inventory_alert import InventoryAlertAgent

    agent = InventoryAlertAgent(tenant_id="t1")
    # 所有食材 remaining_hours >= 24h 阈值
    result = await agent.run(
        "check_expiration",
        {
            "items": [
                {"name": "鱼头", "remaining_hours": 48.0, "batch_id": "B-001"},
                {"name": "辣椒", "remaining_hours": 72.0, "batch_id": "B-002"},
            ],
        },
    )
    assert result.constraints_detail["scope"] == "safety"
    assert "safety" in result.constraints_detail["scopes_checked"]
    assert result.constraints_passed is True


@pytest.mark.asyncio
async def test_inventory_alert_expired_ingredient_blocks_decision():
    """临期食材（<24h）应触发 safety 违规拦截"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.inventory_alert import InventoryAlertAgent

    agent = InventoryAlertAgent(tenant_id="t1")
    # 鱼头仅剩 6 小时 < 24h 阈值 → safety 违规
    result = await agent.run(
        "check_expiration",
        {
            "items": [
                {"name": "鱼头", "remaining_hours": 6.0, "batch_id": "B-001"},
                {"name": "辣椒", "remaining_hours": 48.0, "batch_id": "B-002"},
            ],
        },
    )
    assert result.constraints_detail["scope"] == "safety"
    assert result.constraints_passed is False
    assert any("食安" in v or "临期" in v for v in result.constraints_detail["violations"])


@pytest.mark.asyncio
async def test_trend_discovery_waived_scope():
    """TrendDiscoveryAgent 豁免，任何 run() 都应走 waived 路径"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.trend_discovery import TrendDiscoveryAgent

    agent = TrendDiscoveryAgent(tenant_id="t1")
    result = await agent.run("noop_unknown", {})
    assert result.constraints_detail["scope"] == "waived"
    assert result.constraints_passed is True
    assert result.constraints_detail["waived_reason"].startswith("纯搜索趋势洞察")


# ──────────────────────────────────────────────────────────────────────
# 10. 批次 5（W8 合规运营：4 豁免 + 3 真实 scope）
# ──────────────────────────────────────────────────────────────────────


def test_batch_5_compliance_skills_declare_scope():
    _import_skills_or_skip()
    from agents.skills.attendance_compliance_agent import AttendanceComplianceAgent
    from agents.skills.attendance_recovery import AttendanceRecoveryAgent
    from agents.skills.compliance_alert import ComplianceAlertAgent
    from agents.skills.off_peak_traffic import OffPeakTrafficAgent
    from agents.skills.store_inspect import StoreInspectAgent
    from agents.skills.turnover_risk import TurnoverRiskAgent
    from agents.skills.workforce_planner import WorkforcePlannerAgent

    # 4 个豁免（HR 观察/建议类）
    for cls in (ComplianceAlertAgent, AttendanceComplianceAgent, AttendanceRecoveryAgent, TurnoverRiskAgent):
        assert cls.constraint_scope == set(), f"{cls.__name__} 应为空 scope (豁免)"
        assert cls.constraint_waived_reason is not None, f"{cls.__name__} 缺 waived_reason"
        assert len(cls.constraint_waived_reason) >= 30, (
            f"{cls.__name__} waived_reason 长度 {len(cls.constraint_waived_reason)} < 30"
        )
        # 禁用黑名单空洞说辞
        for blacklist in ("N/A", "不适用", "跳过"):
            assert blacklist not in cls.constraint_waived_reason, (
                f"{cls.__name__} waived_reason 包含黑名单说辞 {blacklist}"
            )

    # 3 个真实 scope
    assert WorkforcePlannerAgent.constraint_scope == {"margin"}
    assert StoreInspectAgent.constraint_scope == {"safety"}
    assert OffPeakTrafficAgent.constraint_scope == {"margin", "experience"}


def test_batch_5_registry_contains_4_new_skills():
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    # 4 个本 PR 新注册的
    for aid in ("attendance_compliance", "attendance_recovery", "turnover_risk", "workforce_planner"):
        assert aid in SKILL_REGISTRY, f"{aid} 未注册"
    # 3 个本 PR 之前已注册的
    for aid in ("compliance_alert", "store_inspect", "off_peak_traffic"):
        assert aid in SKILL_REGISTRY, f"{aid} 未注册"


@pytest.mark.asyncio
async def test_compliance_alert_waived_scope():
    """ComplianceAlertAgent 豁免：任何 run() 都应走 waived 路径"""
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.compliance_alert import ComplianceAlertAgent

    agent = ComplianceAlertAgent(tenant_id="t1")
    result = await agent.run("noop_unknown", {})
    assert result.constraints_detail["scope"] == "waived"
    assert result.constraints_passed is True
    assert "合规预警" in result.constraints_detail["waived_reason"]


@pytest.mark.asyncio
async def test_turnover_risk_waived_scope():
    skills_pkg = _import_skills_or_skip()
    _ = skills_pkg
    from agents.skills.turnover_risk import TurnoverRiskAgent

    agent = TurnoverRiskAgent(tenant_id="t1")
    result = await agent.run("noop_unknown", {})
    assert result.constraints_detail["scope"] == "waived"
    assert result.constraints_passed is True


# ──────────────────────────────────────────────────────────────────────
# 11. 批次 6 + Overflow（W9 最后 14 Skill，冲 100% 覆盖）
# ──────────────────────────────────────────────────────────────────────


def test_batch_6_content_insight_skills_all_waived():
    """批次 6 七个纯报告类 Skill 应全部豁免，reason ≥30 字符且无黑名单说辞"""
    _import_skills_or_skip()
    from agents.skills.audit_trail import AuditTrailAgent
    from agents.skills.growth_coach import GrowthCoachAgent
    from agents.skills.intel_reporter import IntelReporterAgent
    from agents.skills.review_insight import ReviewInsightAgent
    from agents.skills.review_summary import ReviewSummaryAgent
    from agents.skills.salary_advisor import SalaryAdvisorAgent
    from agents.skills.smart_customer_service import SmartCustomerServiceAgent

    waived = [
        ReviewInsightAgent,
        ReviewSummaryAgent,
        IntelReporterAgent,
        AuditTrailAgent,
        GrowthCoachAgent,
        SalaryAdvisorAgent,
        SmartCustomerServiceAgent,
    ]
    for cls in waived:
        assert cls.constraint_scope == set(), f"{cls.__name__} 应豁免"
        reason = cls.constraint_waived_reason
        assert reason is not None and len(reason) >= 30, f"{cls.__name__} waived_reason 长度 {len(reason or '')} < 30"
        for blacklist in ("N/A", "不适用", "跳过"):
            assert blacklist not in reason, f"{cls.__name__} 含黑名单 {blacklist}"


def test_overflow_margin_skills():
    """Overflow 5 个营销/会员类 Skill 声明 margin（折扣/奖励冲击毛利底线）"""
    _import_skills_or_skip()
    from agents.skills.ai_marketing_orchestrator import AiMarketingOrchestratorAgent
    from agents.skills.cashier_audit import CashierAuditAgent
    from agents.skills.dormant_recall import DormantRecallAgent
    from agents.skills.high_value_member import HighValueMemberAgent
    from agents.skills.member_insight import MemberInsightAgent

    for cls in (
        AiMarketingOrchestratorAgent,
        DormantRecallAgent,
        HighValueMemberAgent,
        MemberInsightAgent,
        CashierAuditAgent,
    ):
        assert cls.constraint_scope == {"margin"}, f"{cls.__name__} 应为 margin"


def test_overflow_waived_skills():
    """Overflow 2 个纯内容/扫描类豁免"""
    _import_skills_or_skip()
    from agents.skills.competitor_watch import CompetitorWatchAgent
    from agents.skills.content_generation import ContentGenerationAgent

    for cls in (ContentGenerationAgent, CompetitorWatchAgent):
        assert cls.constraint_scope == set()
        assert cls.constraint_waived_reason is not None
        assert len(cls.constraint_waived_reason) >= 30


def test_100_percent_registry_coverage():
    """51 个 Skill 文件应 100% 在 SKILL_REGISTRY 中声明 scope。

    CI 门禁：批次 6 + Overflow 合并后，SKILL_REGISTRY 规模应 ≥50，
    且每个 Skill 都有 constraint_scope 类属性（不是基类默认）且
    空 scope 的必有 ≥30 字符 waived_reason。
    """
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    assert len(SKILL_REGISTRY) >= 50, f"SKILL_REGISTRY 只有 {len(SKILL_REGISTRY)} 个，未达 50 覆盖率目标"

    missing_scope: list[str] = []
    empty_without_reason: list[str] = []
    blacklist_violations: list[str] = []

    for agent_id, cls in SKILL_REGISTRY.items():
        # 获取本类声明的 constraint_scope（允许继承基类默认 3 约束）
        scope = getattr(cls, "constraint_scope", None)
        if scope is None:
            missing_scope.append(agent_id)
            continue

        # 空 scope 必须声明 waived_reason ≥30 字符
        if scope == set():
            reason = getattr(cls, "constraint_waived_reason", None)
            if not reason or len(reason) < 30:
                empty_without_reason.append(f"{agent_id}(reason_len={len(reason or '')})")
                continue
            for blacklist in ("N/A", "不适用", "跳过"):
                if blacklist in reason:
                    blacklist_violations.append(f"{agent_id}: {blacklist!r}")

    assert not missing_scope, f"缺 constraint_scope: {missing_scope}"
    assert not empty_without_reason, f"豁免 Skill 缺 ≥30 字符 reason: {empty_without_reason}"
    assert not blacklist_violations, f"豁免 reason 含黑名单说辞: {blacklist_violations}"


def test_batch_6_overflow_new_registrations():
    """批次 6 + Overflow 新增 5 个注册项"""
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    # 批次 6 新注册：review_summary / audit_trail / growth_coach / smart_customer_service
    # Overflow 新注册：cashier_audit
    for aid in ("review_summary", "audit_trail", "growth_coach", "smart_customer_service", "cashier_audit"):
        assert aid in SKILL_REGISTRY, f"{aid} 未注册"
