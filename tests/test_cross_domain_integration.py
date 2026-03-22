"""全链路跨域集成测试

验证从 Agent 决策 → 约束校验 → 业务 Service → 数据一致性的完整链路。
"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Use spec_from_file_location to avoid 'services' namespace conflicts
import importlib.util

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_root = os.path.join(os.path.dirname(__file__), "..")
_sh = _load("_store_health", os.path.join(_root, "services/tx-analytics/src/services/store_health_service.py"))
compute_health_score = _sh.compute_health_score
classify_health = _sh.classify_health
score_revenue_completion = _sh.score_revenue_completion
score_cost_rate = _sh.score_cost_rate

_ne = _load("_narrative", os.path.join(_root, "services/tx-analytics/src/services/narrative_engine.py"))
compose_brief = _ne.compose_brief

_wg = _load("_waste", os.path.join(_root, "services/tx-supply/src/services/waste_guard_service.py"))
build_waste_rate_summary = _wg.build_waste_rate_summary
build_top5_item = _wg.build_top5_item
action_for_causes = _wg.action_for_causes

# Agent framework
sys.path.insert(0, os.path.join(_root, "services", "tx-agent", "src"))
from agents.master import MasterAgent
from agents.skills import ALL_SKILL_AGENTS
from agents.constraints import ConstraintChecker
from agents.memory_bus import MemoryBus, Finding

TID = "00000000-0000-0000-0000-000000000001"


class TestFullAgentPipeline:
    """Master Agent 编排 → 全部 9 Agent 注册 → 多 Agent 并行执行"""

    def _create_master(self) -> MasterAgent:
        master = MasterAgent(tenant_id=TID)
        for cls in ALL_SKILL_AGENTS:
            master.register(cls(tenant_id=TID))
        return master

    def test_all_9_agents_registered(self):
        master = self._create_master()
        agents = master.list_agents()
        assert len(agents) == 9

    def test_multi_agent_parallel(self):
        master = self._create_master()
        results = asyncio.run(master.multi_agent_execute([
            {"agent_id": "discount_guard", "action": "detect_discount_anomaly",
             "params": {"order": {"total_amount_fen": 10000, "discount_amount_fen": 1000}}},
            {"agent_id": "smart_menu", "action": "classify_quadrant",
             "params": {"total_sales": 200, "margin_rate": 0.5, "avg_sales": 100, "avg_margin": 0.3}},
            {"agent_id": "inventory_alert", "action": "predict_consumption",
             "params": {"daily_usage": [10, 12, 11, 13, 10, 14, 12], "days_ahead": 3, "current_stock": 50}},
        ]))
        assert len(results) == 3
        assert all(r.success for r in results)
        assert results[0].data["is_anomaly"] is False
        assert results[1].data["quadrant"] == "star"
        assert results[2].data["total_predicted"] > 0


class TestConstraintIntegration:
    """约束校验与 Agent 决策的集成"""

    def test_margin_constraint_blocks_discount(self):
        checker = ConstraintChecker(min_margin_rate=0.3)
        result = checker.check_all({"price_fen": 1000, "cost_fen": 800})
        assert not result.passed
        assert any("毛利底线" in v for v in result.violations)

    def test_food_safety_constraint_blocks_expired(self):
        checker = ConstraintChecker(expiry_buffer_hours=24)
        result = checker.check_all({
            "ingredients": [{"name": "鲈鱼", "remaining_hours": 6}]
        })
        assert not result.passed
        assert any("食安" in v for v in result.violations)

    def test_agent_result_contains_constraint_check(self):
        """Agent 执行结果必须包含约束校验"""
        master = MasterAgent(tenant_id=TID)
        from agents.skills.serve_dispatch import ServeDispatchAgent
        master.register(ServeDispatchAgent(tenant_id=TID))

        result = asyncio.run(master.dispatch("serve_dispatch", "predict_serve_time", {"dish_count": 3}))
        assert result.constraints_passed is not None
        assert "passed" in result.constraints_detail


class TestMemoryBusIntegration:
    """Memory Bus 跨 Agent 洞察传递"""

    def test_cross_agent_finding(self):
        bus = MemoryBus()
        bus.clear()

        # 库存 Agent 发现低库存
        bus.publish(Finding(
            agent_id="inventory_alert", finding_type="low_stock",
            data={"item": "鲈鱼", "days_left": 1}, confidence=0.9, store_id="store1",
        ))

        # 排菜 Agent 读取库存告警
        ctx = bus.get_peer_context(exclude_agent="smart_menu", store_id="store1")
        assert len(ctx) == 1
        assert ctx[0]["data"]["item"] == "鲈鱼"


class TestAnalyticsIntegration:
    """健康度 + 叙事引擎 + 损耗联动"""

    def test_health_to_narrative_pipeline(self):
        """门店健康度 → 经营简报 全链路"""
        # 1. 计算健康度
        dims = {
            "revenue_completion": score_revenue_completion(350000, 100000, 30),
            "table_turnover": 85.0,
            "cost_rate": score_cost_rate("warning"),
            "complaint_rate": 95.0,
            "staff_efficiency": 80.0,
        }
        score = compute_health_score(dims)
        status = classify_health(score)
        assert score > 0
        assert status in ("excellent", "good", "warning", "critical")

        # 2. 构建损耗数据
        waste_item = build_top5_item(1, "鲈鱼", 32000, 5.0, 100000,
                                     [{"root_cause": "over_prep", "event_count": 3}])
        assert waste_item["action"] == action_for_causes([{"root_cause": "over_prep"}])

        # 3. 生成经营简报
        brief = compose_brief(
            "芙蓉路店",
            {"revenue_yuan": 8560, "actual_cost_pct": 35, "cost_rate_label": "偏高", "cost_rate_status": "warning"},
            {"approved": 1, "total": 2},
            [waste_item],
        )
        assert len(brief) <= 200
        assert "芙蓉路店" in brief
        assert "鲈鱼" in brief

    def test_waste_rate_to_constraint(self):
        """损耗率 → 场景识别 → Agent 联动"""
        summary = build_waste_rate_summary(8000, 100000, 5000, "2026-03-15", "2026-03-22")
        assert summary["waste_rate_status"] == "critical"

        # 场景识别
        master = MasterAgent(tenant_id=TID)
        from agents.skills.finance_audit import FinanceAuditAgent
        master.register(FinanceAuditAgent(tenant_id=TID))

        result = asyncio.run(master.dispatch("finance_audit", "match_scenario", {
            "waste_rate_pct": summary["waste_rate_pct"],
            "cost_rate_pct": 30,
        }))
        assert result.data["scenario"] == "high_waste"


class TestP0AgentCompleteness:
    """P0 Agent 所有 action 均可调用"""

    def test_discount_guard_all_actions(self):
        master = MasterAgent(tenant_id=TID)
        from agents.skills.discount_guard import DiscountGuardAgent
        agent = DiscountGuardAgent(tenant_id=TID)
        master.register(agent)

        for action in agent.get_supported_actions():
            result = asyncio.run(master.dispatch("discount_guard", action, {
                "order": {"total_amount_fen": 10000, "discount_amount_fen": 500},
                "licenses": [], "stores": [], "report_type": "period_summary",
                "voucher_id": "V001", "date": "today",
            }))
            assert result.success, f"discount_guard.{action} failed: {result.error}"

    def test_smart_menu_all_actions(self):
        master = MasterAgent(tenant_id=TID)
        from agents.skills.smart_menu import SmartMenuAgent
        agent = SmartMenuAgent(tenant_id=TID)
        master.register(agent)

        params_map = {
            "simulate_cost": {"bom_items": [{"cost_fen": 500, "quantity": 1}], "target_price_fen": 2000},
            "recommend_pilot_stores": {"stores": [{"name": "A店", "customer_base": 300, "popular_categories": [], "staff_skill_avg": 85}]},
            "run_dish_review": {"total_sales": 100, "return_count": 2, "bad_review_count": 3, "margin_rate": 0.35, "category_avg_sales": 80},
            "check_launch_readiness": {"completed_items": ["配方定版", "成本核算"]},
            "scan_dish_risks": {"dishes": [{"name": "测试菜", "cost_over_target_pct": 10, "return_rate_pct": 8}]},
            "inspect_dish_quality": {"dish_name": "测试菜", "mock_score": 85},
            "classify_quadrant": {"total_sales": 200, "margin_rate": 0.5, "avg_sales": 100, "avg_margin": 0.3},
            "optimize_menu": {"dishes": [
                {"name": "A菜", "total_sales": 200, "margin_rate": 0.5},
                {"name": "B菜", "total_sales": 20, "margin_rate": 0.1},
            ]},
        }

        for action in agent.get_supported_actions():
            result = asyncio.run(master.dispatch("smart_menu", action, params_map.get(action, {})))
            assert result.success, f"smart_menu.{action} failed: {result.error}"
