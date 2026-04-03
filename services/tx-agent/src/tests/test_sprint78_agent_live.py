"""Sprint 7-8 测试 — Agent 三级自治 + 门店P&L + 离职结算

覆盖：
- Agent 三级自治机制（Level 1/2/3）
- discount_guard live 执行
- 回滚窗口（30分钟内/超时）
- Agent 升级条件校验
- 企微推送
- 门店 P&L 日/周/月报表 + 异常检测 + 多门店合并
- 离职结算：resign(0), mutual(N), dismiss_no_fault(N+1)
- 年假折算 + 13薪折算
- 补偿金个税计算

使用长沙真实餐饮数据。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta

# 将各服务的 src 目录加入 sys.path
_here = os.path.dirname(__file__)
_agent_src = os.path.join(_here, "..")
_finance_src = os.path.abspath(os.path.join(_here, "..", "..", "..", "tx-finance", "src"))
_org_src = os.path.abspath(os.path.join(_here, "..", "..", "..", "tx-org", "src"))

for p in (_agent_src, _finance_src, _org_src):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest

# ── Agent 相关 ────────────────────────────────────────────────
from agents.skills.discount_guard import DiscountGuardAgent
from services.agent_live_service import (
    AgentLiveService,
)

# ── 离职结算相关 ──────────────────────────────────────────────
from services.separation_settlement import (
    CHANGSHA_AVG_MONTHLY_SALARY_YUAN,
    SeparationSettlementService,
    _compute_compensation_tax_fen,
    _compute_n_years,
)

# ── P&L 相关 ─────────────────────────────────────────────────
from services.store_pnl import StorePnLService

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FIXTURES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.fixture
def live_service():
    svc = AgentLiveService()
    agent = DiscountGuardAgent(tenant_id="tenant_001", store_id="store_cs_001")
    svc.register_agent_instance("discount_guard", agent)
    return svc


@pytest.fixture
def pnl_service():
    return StorePnLService()


@pytest.fixture
def sep_service():
    return SeparationSettlementService()


def _changsha_daily_pnl_data(
    dine_in: int = 1_200_000,
    takeaway: int = 350_000,
    delivery: int = 180_000,
    food_cost_ratio: float = 0.32,
) -> dict:
    """构造长沙门店一日营业数据（分）

    默认数据：堂食 12000 元 + 外卖 3500 元 + 外送 1800 元
    典型长沙湘菜馆 80 座左右。
    """
    total_rev = dine_in + takeaway + delivery
    food_cost = int(total_rev * food_cost_ratio)
    return {
        "revenue": {
            "dine_in": dine_in,
            "takeaway": takeaway,
            "delivery": delivery,
            "banquet": 0,
            "other": 15_000,  # 茶位费/餐具费
        },
        "cogs": {
            "food_cost": food_cost,
            "beverage_cost": 25_000,   # 250 元饮品成本
            "waste_spoilage": 18_000,  # 180 元损耗
        },
        "opex": {
            "labor": 380_000,       # 3800 元/日人力
            "rent": 166_667,        # 5 万/月 ÷ 30
            "utilities": 50_000,    # 500 元/日水电气
            "marketing": 30_000,    # 300 元/日
            "platform_commission": int(delivery * 0.20),  # 外送平台 20%
            "payment_processing": int(total_rev * 0.006), # 支付手续费 0.6%
            "supplies": 15_000,     # 耗材 150 元/日
        },
        "other": {
            "depreciation": 33_333,      # 100 万设备 / 30 月 / 30 天
            "admin_allocation": 20_000,  # 总部管理费分摊
        },
        "meta": {
            "seats": 80,
            "operating_hours": 12,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. Agent 三级自治机制
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAgentLevels:
    """三级自治: Level 1=suggest, Level 2=auto+rollback, Level 3=autonomous"""

    @pytest.mark.asyncio
    async def test_level1_suggest_only(self, live_service: AgentLiveService):
        """Level 1: 仅返回建议，不真正执行"""
        result = await live_service.execute_live(
            agent_id="discount_guard",
            action="detect_discount_anomaly",
            params={
                "order": {
                    "total_amount_fen": 50000,
                    "discount_amount_fen": 30000,
                    "cost_fen": 15000,
                },
            },
            store_id="store_cs_001",
        )

        assert result["ok"] is True
        assert result["level"] == 1
        assert result["status"] == "suggested"
        assert "建议" in result["message"]
        assert result["result"]["success"] is True
        assert result["result"]["data"]["is_anomaly"] is True

    @pytest.mark.asyncio
    async def test_level2_auto_with_rollback(self, live_service: AgentLiveService):
        """Level 2: 自动执行 + 30分钟回滚窗口"""
        live_service.activate_agent("discount_guard", level=2)

        result = await live_service.execute_live(
            agent_id="discount_guard",
            action="detect_discount_anomaly",
            params={
                "order": {
                    "total_amount_fen": 50000,
                    "discount_amount_fen": 30000,
                    "cost_fen": 15000,
                },
            },
            store_id="store_cs_001",
        )

        assert result["ok"] is True
        assert result["level"] == 2
        assert result["status"] == "executed"
        assert result["rollback_id"] != ""
        assert result["rollback_window_min"] == 30
        assert "回滚" in result["message"]

    @pytest.mark.asyncio
    async def test_level3_fully_autonomous(self, live_service: AgentLiveService):
        """Level 3: 完全自主执行"""
        live_service.activate_agent("discount_guard", level=3)

        result = await live_service.execute_live(
            agent_id="discount_guard",
            action="detect_discount_anomaly",
            params={
                "order": {
                    "total_amount_fen": 50000,
                    "discount_amount_fen": 5000,
                    "cost_fen": 15000,
                },
            },
            store_id="store_cs_001",
        )

        assert result["ok"] is True
        assert result["level"] == 3
        assert result["status"] == "executed"
        assert "自主" in result["message"]


class TestAgentResultLevels:
    """AgentResult 中的三级标注"""

    @pytest.mark.asyncio
    async def test_result_level_annotation(self):
        """AgentResult 携带自治等级和回滚信息"""
        agent = DiscountGuardAgent(tenant_id="t1", store_id="s1")
        agent.agent_level = 2

        result = await agent.run("detect_discount_anomaly", {
            "order": {
                "total_amount_fen": 10000,
                "discount_amount_fen": 2000,
                "cost_fen": 3000,
            },
        })

        assert result.agent_level == 2
        assert result.rollback_window_min == 30
        assert result.rollback_id != ""

    @pytest.mark.asyncio
    async def test_result_level1_no_rollback_id(self):
        """Level 1 无回滚 ID"""
        agent = DiscountGuardAgent(tenant_id="t1", store_id="s1")
        agent.agent_level = 1

        result = await agent.run("detect_discount_anomaly", {
            "order": {
                "total_amount_fen": 10000,
                "discount_amount_fen": 2000,
                "cost_fen": 3000,
            },
        })

        assert result.agent_level == 1
        assert result.rollback_id == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. discount_guard live 执行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestDiscountGuardLive:
    """discount_guard 上线 — 真实订单数据"""

    @pytest.mark.asyncio
    async def test_normal_discount_pass(self, live_service: AgentLiveService):
        """正常折扣（20%）不触发异常"""
        result = await live_service.execute_live(
            agent_id="discount_guard",
            action="detect_discount_anomaly",
            params={
                "order": {
                    "total_amount_fen": 38800,   # 388 元（长沙4人均消费）
                    "discount_amount_fen": 7760,  # 20% 折扣
                    "cost_fen": 12424,            # 32% 食材成本
                },
            },
            store_id="store_cs_001",
        )

        assert result["ok"] is True
        assert result["result"]["data"]["is_anomaly"] is False

    @pytest.mark.asyncio
    async def test_high_discount_anomaly(self, live_service: AgentLiveService):
        """异常高折扣（75%）触发告警"""
        result = await live_service.execute_live(
            agent_id="discount_guard",
            action="detect_discount_anomaly",
            params={
                "order": {
                    "total_amount_fen": 88000,    # 880 元
                    "discount_amount_fen": 66000,  # 75% 折扣
                    "cost_fen": 28160,
                    "waiter_discount_count": 8,
                },
            },
            store_id="store_cs_001",
        )

        assert result["ok"] is True
        data = result["result"]["data"]
        assert data["is_anomaly"] is True
        assert data["discount_rate"] > 0.7
        assert len(data["risk_factors"]) >= 2

    @pytest.mark.asyncio
    async def test_inactive_agent_rejected(self, live_service: AgentLiveService):
        """未激活的 Agent 拒绝执行"""
        result = await live_service.execute_live(
            agent_id="inventory_alert",
            action="check_stock",
            params={},
            store_id="store_cs_001",
        )

        assert result["ok"] is False
        assert "未激活" in result["error"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 回滚机制
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestRollback:
    """Level 2 回滚 — 30分钟窗口"""

    @pytest.mark.asyncio
    async def test_rollback_within_window(self, live_service: AgentLiveService):
        """30分钟内回滚成功"""
        live_service.activate_agent("discount_guard", level=2)

        result = await live_service.execute_live(
            agent_id="discount_guard",
            action="detect_discount_anomaly",
            params={"order": {"total_amount_fen": 10000, "discount_amount_fen": 6000, "cost_fen": 3000}},
            store_id="store_cs_001",
        )

        rollback_id = result["rollback_id"]
        rb_result = live_service.rollback_decision(rollback_id)

        assert rb_result["ok"] is True
        assert rb_result["status"] == "rolled_back"
        assert rb_result["elapsed_min"] < 1  # 几乎立即回滚

    @pytest.mark.asyncio
    async def test_rollback_after_window_expires(self, live_service: AgentLiveService):
        """30分钟后回滚失败"""
        live_service.activate_agent("discount_guard", level=2)

        result = await live_service.execute_live(
            agent_id="discount_guard",
            action="detect_discount_anomaly",
            params={"order": {"total_amount_fen": 10000, "discount_amount_fen": 6000, "cost_fen": 3000}},
            store_id="store_cs_001",
        )

        rollback_id = result["rollback_id"]

        # 模拟时间流逝：将 created_at 设置为 31 分钟前
        record = live_service._rollback_index[rollback_id]
        record["created_at"] = time.time() - 31 * 60

        rb_result = live_service.rollback_decision(rollback_id)

        assert rb_result["ok"] is False
        assert "过期" in rb_result["error"]

    @pytest.mark.asyncio
    async def test_double_rollback_rejected(self, live_service: AgentLiveService):
        """重复回滚被拒绝"""
        live_service.activate_agent("discount_guard", level=2)

        result = await live_service.execute_live(
            agent_id="discount_guard",
            action="detect_discount_anomaly",
            params={"order": {"total_amount_fen": 10000, "discount_amount_fen": 6000, "cost_fen": 3000}},
            store_id="store_cs_001",
        )

        rollback_id = result["rollback_id"]
        live_service.rollback_decision(rollback_id)
        rb2 = live_service.rollback_decision(rollback_id)

        assert rb2["ok"] is False
        assert "已被回滚" in rb2["error"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. Agent 升级条件
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAgentUpgrade:
    """升级条件：100+ Level-1 决策，采纳率 > 80%"""

    def test_insufficient_decisions_blocks_upgrade(self, live_service: AgentLiveService):
        """决策不足 100 次不允许升级"""
        readiness = live_service.get_agent_readiness("discount_guard")
        assert readiness["ready_for_upgrade"] is False
        assert readiness["decision_count"] == 0

        upgrade = live_service.upgrade_agent_level("discount_guard", 2)
        assert upgrade["ok"] is False

    def test_low_adoption_rate_blocks_upgrade(self, live_service: AgentLiveService):
        """采纳率 < 80% 不允许升级"""
        # 注入 120 条决策，其中 70 条被采纳（58.3%）
        decisions = []
        for i in range(120):
            decisions.append({
                "decision_id": f"d_{i}",
                "agent_id": "discount_guard",
                "action": "detect_discount_anomaly",
                "params": {},
                "store_id": "store_cs_001",
                "level": 1,
                "rollback_id": "",
                "created_at": time.time(),
                "rolled_back": False,
                "result": {"success": True, "confidence": 0.9, "data": {}},
                "status": "executed" if i < 70 else "ignored",
            })
        live_service._inject_decisions(decisions)

        readiness = live_service.get_agent_readiness("discount_guard")
        assert readiness["decision_count"] == 120
        assert readiness["adoption_rate"] < 80
        assert readiness["ready_for_upgrade"] is False

    def test_upgrade_succeeds_when_ready(self, live_service: AgentLiveService):
        """满足条件允许升级"""
        # 注入 110 条决策，其中 95 条被采纳（86.4%）
        decisions = []
        for i in range(110):
            decisions.append({
                "decision_id": f"d_{i}",
                "agent_id": "discount_guard",
                "action": "detect_discount_anomaly",
                "params": {},
                "store_id": "store_cs_001",
                "level": 1,
                "rollback_id": "",
                "created_at": time.time(),
                "rolled_back": False,
                "result": {"success": True, "confidence": 0.92, "data": {}},
                "status": "executed" if i < 95 else "ignored",
            })
        live_service._inject_decisions(decisions)

        readiness = live_service.get_agent_readiness("discount_guard")
        assert readiness["decision_count"] == 110
        assert readiness["adoption_rate"] > 80
        assert readiness["ready_for_upgrade"] is True

        upgrade = live_service.upgrade_agent_level("discount_guard", 2)
        assert upgrade["ok"] is True
        assert upgrade["new_level"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 企微推送
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestWeComPush:
    """企业微信推送"""

    def test_critical_push(self, live_service: AgentLiveService):
        """紧急推送立即发送"""
        result = live_service.push_to_wecom(
            store_id="store_cs_001",
            decision_summary="折扣异常：服务员张三连续8单高折扣",
            urgency="critical",
        )

        assert result["ok"] is True
        assert result["sent"] is True
        assert result["channel"] == "wecom_bot"
        assert result["urgency"] == "critical"

    def test_normal_push_batched(self, live_service: AgentLiveService):
        """普通推送走批量通道"""
        result = live_service.push_to_wecom(
            store_id="store_cs_001",
            decision_summary="今日库存预警：辣椒库存低于安全线",
            urgency="normal",
        )

        assert result["ok"] is True
        assert result["channel"] == "wecom_batch"

    def test_push_history(self, live_service: AgentLiveService):
        """推送历史记录"""
        live_service.push_to_wecom("store_cs_001", "推送1", "normal")
        live_service.push_to_wecom("store_cs_001", "推送2", "critical")
        live_service.push_to_wecom("store_cs_002", "推送3", "normal")

        history = live_service.get_push_history("store_cs_001", days=7)
        assert len(history) == 2
        assert all(h["store_id"] == "store_cs_001" for h in history)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 门店 P&L
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestStorePnL:
    """门店 P&L 自动生成 — 长沙湘菜馆数据"""

    def test_daily_pnl_all_line_items(self, pnl_service: StorePnLService):
        """每日P&L包含所有科目"""
        data = _changsha_daily_pnl_data()
        pnl = pnl_service.generate_daily_pnl("store_cs_001", "2026-03-26", data)

        # 验证结构完整
        assert pnl["store_id"] == "store_cs_001"
        assert pnl["biz_date"] == "2026-03-26"
        assert pnl["period_type"] == "daily"

        # Revenue
        rev = pnl["revenue"]
        assert rev["dine_in"] == 1_200_000
        assert rev["takeaway"] == 350_000
        assert rev["delivery"] == 180_000
        assert rev["total"] > 0

        # COGS
        assert pnl["cogs"]["food_cost"] > 0
        assert pnl["cogs"]["beverage_cost"] == 25_000
        assert pnl["cogs"]["waste_spoilage"] == 18_000

        # Gross Profit
        assert pnl["gross_profit"] == rev["total"] - pnl["cogs"]["total"]

        # OpEx
        opex = pnl["opex"]
        assert opex["labor"] == 380_000
        assert opex["rent"] == 166_667
        assert opex["total"] > 0

        # Operating Profit
        assert pnl["operating_profit"] == pnl["gross_profit"] - opex["total"]

        # Net Profit
        other = pnl["other_expenses"]
        assert pnl["net_profit"] == pnl["operating_profit"] - other["total"]

        # KPIs
        kpi = pnl["kpi"]
        assert 0 < kpi["gross_margin"] < 1
        assert 0 < kpi["food_cost_ratio"] < 1
        assert 0 < kpi["labor_cost_ratio"] < 1
        assert kpi["revpash"] > 0

    def test_daily_pnl_realistic_margins(self, pnl_service: StorePnLService):
        """长沙湘菜馆典型利润率验证"""
        data = _changsha_daily_pnl_data()
        pnl = pnl_service.generate_daily_pnl("store_cs_001", "2026-03-26", data)
        kpi = pnl["kpi"]

        # 长沙湘菜馆典型：毛利 60-68%，食材成本 32-38%
        assert 0.55 <= kpi["gross_margin"] <= 0.75, f"毛利率 {kpi['gross_margin']:.1%} 偏离"
        assert 0.28 <= kpi["food_cost_ratio"] <= 0.40, f"食材成本率 {kpi['food_cost_ratio']:.1%} 偏离"

    def test_weekly_pnl_aggregation(self, pnl_service: StorePnLService):
        """周报表聚合7天数据"""
        daily_pnls = []
        for i in range(7):
            d = _changsha_daily_pnl_data(
                dine_in=1_200_000 + i * 50_000,  # 周末生意更好
            )
            dt = date(2026, 3, 23) + timedelta(days=i)
            pnl = pnl_service.generate_daily_pnl("store_cs_001", dt.isoformat(), d)
            daily_pnls.append(pnl)

        weekly = pnl_service.generate_weekly_pnl("store_cs_001", "2026-03-23", daily_pnls)

        assert weekly["period_type"] == "weekly"
        assert weekly["days_count"] == 7
        assert weekly["revenue"]["total"] == sum(p["revenue"]["total"] for p in daily_pnls)

    def test_monthly_pnl(self, pnl_service: StorePnLService):
        """月报表聚合30天数据"""
        daily_pnls = []
        for i in range(30):
            d = _changsha_daily_pnl_data()
            dt = date(2026, 3, 1) + timedelta(days=i)
            pnl = pnl_service.generate_daily_pnl("store_cs_001", dt.isoformat(), d)
            daily_pnls.append(pnl)

        monthly = pnl_service.generate_monthly_pnl("store_cs_001", "2026-03", daily_pnls)

        assert monthly["period_type"] == "monthly"
        assert monthly["days_count"] == 30
        assert monthly["net_profit"] > 0  # 应该盈利

    def test_pnl_anomaly_food_cost_over_35(self, pnl_service: StorePnLService):
        """食材成本超 35% 触发异常"""
        data = _changsha_daily_pnl_data(food_cost_ratio=0.40)
        pnl = pnl_service.generate_daily_pnl("store_cs_001", "2026-03-26", data)

        anomalies = pnl_service.detect_pnl_anomalies(pnl)
        food_anomaly = [a for a in anomalies if a["metric"] == "food_cost_ratio"]

        assert len(food_anomaly) == 1
        assert food_anomaly[0]["severity"] == "high"
        assert food_anomaly[0]["value"] > 0.35

    def test_pnl_anomaly_low_net_margin(self, pnl_service: StorePnLService):
        """净利率 < 5% 触发 critical 告警"""
        # 构造高成本低利润场景
        data = _changsha_daily_pnl_data()
        data["opex"]["labor"] = 600_000  # 6000 元/日人力，明显偏高
        data["opex"]["rent"] = 300_000   # 3000 元/日租金
        pnl = pnl_service.generate_daily_pnl("store_cs_001", "2026-03-26", data)

        anomalies = pnl_service.detect_pnl_anomalies(pnl)
        margin_anomaly = [a for a in anomalies if a["metric"] == "net_margin"]

        assert len(margin_anomaly) == 1
        assert margin_anomaly[0]["severity"] == "critical"

    def test_multi_store_consolidated_pnl(self, pnl_service: StorePnLService):
        """多门店合并报表"""
        store_pnls = []
        for store_id in ["store_cs_001", "store_cs_002", "store_cs_003"]:
            data = _changsha_daily_pnl_data(
                dine_in=1_200_000 if store_id == "store_cs_001" else 800_000,
            )
            pnl = pnl_service.generate_daily_pnl(store_id, "2026-03-26", data)
            store_pnls.append(pnl)

        result = pnl_service.get_multi_store_pnl(store_pnls)

        assert result["store_count"] == 3
        assert len(result["per_store"]) == 3
        consolidated = result["consolidated"]
        assert consolidated["revenue"]["total"] == sum(p["revenue"]["total"] for p in store_pnls)

    def test_pnl_compare(self, pnl_service: StorePnLService):
        """期间对比分析"""
        data_a = _changsha_daily_pnl_data(dine_in=1_000_000)
        data_b = _changsha_daily_pnl_data(dine_in=1_300_000)
        pnl_a = pnl_service.generate_daily_pnl("store_cs_001", "2026-03-25", data_a)
        pnl_b = pnl_service.generate_daily_pnl("store_cs_001", "2026-03-26", data_b)

        comparison = pnl_service.compare_pnl("store_cs_001", pnl_a, pnl_b)

        rev_var = comparison["variance"]["total_revenue"]
        assert rev_var["change"] > 0
        assert rev_var["pct"] > 0

    def test_pnl_trend(self, pnl_service: StorePnLService):
        """P&L 趋势数据"""
        monthly_pnls = []
        for m in range(1, 7):
            data = _changsha_daily_pnl_data(dine_in=1_000_000 + m * 50_000)
            pnl = pnl_service.generate_daily_pnl("store_cs_001", f"2026-{m:02d}", data)
            monthly_pnls.append(pnl)

        trend = pnl_service.get_pnl_trend(monthly_pnls)
        assert len(trend) == 6
        # 营收应逐月增长
        for i in range(1, len(trend)):
            assert trend[i]["total_revenue"] >= trend[i - 1]["total_revenue"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 离职结算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSeparationSettlement:
    """离职结算 — 经济补偿金"""

    def test_resign_zero_compensation(self, sep_service: SeparationSettlementService):
        """主动辞职：无补偿"""
        result = sep_service.calculate_compensation(
            employee_id="emp_001",
            separation_type="resign",
            hire_date=date(2023, 6, 1),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[650_000] * 12,  # 月薪 6500 元
        )

        assert result["ok"] is True
        assert result["compensation_fen"] == 0
        assert result["notice_pay_fen"] == 0
        assert result["total_compensation_fen"] == 0

    def test_dismiss_fault_zero_compensation(self, sep_service: SeparationSettlementService):
        """过失性辞退：无补偿"""
        result = sep_service.calculate_compensation(
            employee_id="emp_002",
            separation_type="dismiss_fault",
            hire_date=date(2022, 1, 1),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[800_000] * 12,
        )

        assert result["ok"] is True
        assert result["total_compensation_fen"] == 0

    def test_mutual_n_compensation(self, sep_service: SeparationSettlementService):
        """协商解除：N * 月薪"""
        # 入职 2023-06-01 至 2026-03-27 = 2年9个月26天 → N=3
        result = sep_service.calculate_compensation(
            employee_id="emp_003",
            separation_type="mutual",
            hire_date=date(2023, 6, 1),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[700_000] * 12,  # 月薪 7000 元
        )

        assert result["ok"] is True
        n = result["n_years"]
        assert n == 3.0  # 2年+9个月26天 ≈ 2年+300天 → 300天/365=0.82 ≥ 6个月 → 进1 = 3
        assert result["compensation_fen"] == 3 * 700_000  # 2,100,000 分 = 21,000 元
        assert result["notice_pay_fen"] == 0  # 协商解除无代通知金

    def test_dismiss_no_fault_n_plus_1(self, sep_service: SeparationSettlementService):
        """无过失性辞退：(N+1) * 月薪"""
        # 入职 2021-01-15 至 2026-03-27 = 5年2个月12天 → N=5.5
        result = sep_service.calculate_compensation(
            employee_id="emp_004",
            separation_type="dismiss_no_fault",
            hire_date=date(2021, 1, 15),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[850_000] * 12,  # 月薪 8500 元
        )

        assert result["ok"] is True
        n = result["n_years"]
        # 5*365 + ~72天 = 1897天, 1897/365=5年72天残余, 72天<183天 → N=5.5
        assert n == 5.5
        assert result["compensation_fen"] == int(5.5 * 850_000)
        assert result["notice_pay_fen"] == 850_000  # +1 个月代通知金
        total = result["total_compensation_fen"]
        assert total == int(5.5 * 850_000) + 850_000  # N+1

    def test_layoff_n_compensation(self, sep_service: SeparationSettlementService):
        """经济性裁员：N * 月薪"""
        result = sep_service.calculate_compensation(
            employee_id="emp_005",
            separation_type="layoff",
            hire_date=date(2020, 4, 1),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[900_000] * 12,
        )

        assert result["ok"] is True
        assert result["compensation_fen"] > 0
        assert result["notice_pay_fen"] == 0

    def test_contract_expire_compensation(self, sep_service: SeparationSettlementService):
        """合同到期不续：N * 月薪"""
        result = sep_service.calculate_compensation(
            employee_id="emp_006",
            separation_type="contract_expire",
            hire_date=date(2023, 4, 1),
            last_work_date=date(2026, 3, 31),
            last_12_months_salary_fen=[600_000] * 12,
        )

        assert result["ok"] is True
        assert result["compensation_fen"] > 0

    def test_high_salary_cap_applied(self, sep_service: SeparationSettlementService):
        """高薪封顶：月薪超社平3倍 → 封顶3倍 + N最多12年"""
        # 月薪 30000 元，远超长沙社平3倍(约24642元)
        result = sep_service.calculate_compensation(
            employee_id="emp_007",
            separation_type="mutual",
            hire_date=date(2010, 1, 1),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[3_000_000] * 12,  # 3 万/月
        )

        assert result["ok"] is True
        assert result["is_salary_capped"] is True
        cap_fen = CHANGSHA_AVG_MONTHLY_SALARY_YUAN * 3 * 100
        assert result["capped_monthly_salary_fen"] == cap_fen
        # 16年+工龄但封顶到12年
        assert result["capped_n"] == 12.0


class TestSeparationNCalculation:
    """N值计算精确测试"""

    def test_n_less_than_6_months(self):
        """不满6个月 → N=0.5"""
        n = _compute_n_years(date(2026, 1, 1), date(2026, 4, 1))
        assert n == 0.5

    def test_n_exactly_6_months(self):
        """恰好6个月 → N=1（183天 >= 183天进1）"""
        n = _compute_n_years(date(2026, 1, 1), date(2026, 7, 3))  # ~183 天
        assert n == 1.0

    def test_n_one_year_exactly(self):
        """整1年 → N=1"""
        n = _compute_n_years(date(2025, 3, 27), date(2026, 3, 27))
        assert n == 1.0

    def test_n_three_years_two_months(self):
        """3年2个月 → N=3.5（残余<6个月）"""
        n = _compute_n_years(date(2023, 1, 1), date(2026, 3, 1))
        # 1155 天 / 365 = 3年60天残余, 60<183 → 3+0.5=3.5
        assert n == 3.5


class TestFinalPay:
    """最终结算薪资"""

    def test_final_pay_with_leave_payout(self, sep_service: SeparationSettlementService):
        """含年假折算"""
        compensation = sep_service.calculate_compensation(
            employee_id="emp_010",
            separation_type="mutual",
            hire_date=date(2023, 6, 1),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[700_000] * 12,
        )

        final = sep_service.calculate_final_pay(
            employee_id="emp_010",
            last_work_date=date(2026, 3, 27),
            monthly_salary_fen=700_000,
            work_days_in_month=22,
            worked_days=19,  # 3月27日离职，出勤19天
            unused_annual_leave_days=3.5,  # 3.5天未休年假
            daily_salary_fen=31_818,  # 700000/22
            prorated_13th_month_fen=175_000,  # 3/12 * 700000
            social_insurance_deduction_fen=85_000,
            housing_fund_deduction_fen=70_000,
            compensation_result=compensation,
        )

        assert final["ok"] is True
        assert final["base_prorate_fen"] == int(700_000 * 19 / 22)
        assert final["leave_payout_fen"] == int(3.5 * 31_818 * 2)  # 200%
        assert final["prorated_13th_month_fen"] == 175_000
        assert final["compensation_fen"] == compensation["total_compensation_fen"]
        assert final["net_final_pay_fen"] > 0

    def test_final_pay_resign_no_compensation(self, sep_service: SeparationSettlementService):
        """主动辞职：无补偿金，只有出勤工资 + 年假折算"""
        compensation = sep_service.calculate_compensation(
            employee_id="emp_011",
            separation_type="resign",
            hire_date=date(2024, 6, 1),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[500_000] * 12,
        )

        final = sep_service.calculate_final_pay(
            employee_id="emp_011",
            last_work_date=date(2026, 3, 27),
            monthly_salary_fen=500_000,
            work_days_in_month=22,
            worked_days=19,
            unused_annual_leave_days=2.0,
            daily_salary_fen=22_727,
            social_insurance_deduction_fen=60_000,
            housing_fund_deduction_fen=50_000,
            compensation_result=compensation,
        )

        assert final["ok"] is True
        assert final["compensation_fen"] == 0
        assert final["leave_payout_fen"] == int(2.0 * 22_727 * 2)


class TestCompensationTax:
    """补偿金个税计算"""

    def test_small_compensation_no_tax(self):
        """小额补偿金（低于免税额）不交税"""
        # 免税额 ≈ 295,704 元 ≈ 29,570,400 分
        tax = _compute_compensation_tax_fen(10_000_000, 3.0)  # 10万 < 免税额
        assert tax == 0

    def test_large_compensation_has_tax(self):
        """大额补偿金（超过免税额）需缴税"""
        # 50 万元 = 50,000,000 分，远超免税额
        tax = _compute_compensation_tax_fen(50_000_000, 5.0)
        assert tax > 0

        # 验证税额合理范围
        # 应税 = 50万 - 29.57万 = 20.43万
        # 折算月收入 = 204300 / 5 = 40860 元
        # 40860 元对应 30% 档 → 月税 = 40860*0.30-4410 = 7848
        # 总税 = 7848*5 = 39240 元 = 3,924,000 分
        assert 3_000_000 < tax < 5_000_000

    def test_zero_compensation_zero_tax(self):
        """零补偿金零个税"""
        tax = _compute_compensation_tax_fen(0, 3.0)
        assert tax == 0


class TestSeparationStats:
    """离职统计"""

    def test_stats_by_type(self, sep_service: SeparationSettlementService):
        """按类型统计"""
        separations = [
            {"separation_type": "resign", "n_years": 1.5, "total_compensation_fen": 0},
            {"separation_type": "resign", "n_years": 0.5, "total_compensation_fen": 0},
            {"separation_type": "mutual", "n_years": 3.0, "total_compensation_fen": 2_100_000},
            {"separation_type": "dismiss_no_fault", "n_years": 5.0, "total_compensation_fen": 5_100_000},
            {"separation_type": "layoff", "n_years": 2.0, "total_compensation_fen": 1_600_000},
        ]

        stats = sep_service.get_separation_stats(separations)

        assert stats["total"] == 5
        assert stats["by_type"]["resign"]["count"] == 2
        assert stats["by_type"]["mutual"]["count"] == 1
        assert stats["avg_tenure_years"] == round((1.5 + 0.5 + 3.0 + 5.0 + 2.0) / 5, 1)
        assert stats["avg_compensation_fen"] == int((2_100_000 + 5_100_000 + 1_600_000) / 3)


class TestSettlementDocument:
    """离职结算单生成"""

    def test_generate_document(self, sep_service: SeparationSettlementService):
        """生成完整结算单"""
        compensation = sep_service.calculate_compensation(
            employee_id="emp_020",
            separation_type="dismiss_no_fault",
            hire_date=date(2022, 4, 1),
            last_work_date=date(2026, 3, 27),
            last_12_months_salary_fen=[800_000] * 12,
        )

        final = sep_service.calculate_final_pay(
            employee_id="emp_020",
            last_work_date=date(2026, 3, 27),
            monthly_salary_fen=800_000,
            work_days_in_month=22,
            worked_days=19,
            unused_annual_leave_days=4.0,
            daily_salary_fen=36_364,
            prorated_13th_month_fen=200_000,
            social_insurance_deduction_fen=95_000,
            housing_fund_deduction_fen=80_000,
            compensation_result=compensation,
        )

        doc = sep_service.generate_settlement_document(
            employee_id="emp_020",
            employee_name="李大厨",
            compensation_result=compensation,
            final_pay_result=final,
        )

        assert doc["ok"] is True
        assert doc["document_type"] == "separation_settlement"
        assert doc["employee_name"] == "李大厨"
        assert doc["separation_type"] == "dismiss_no_fault"
        assert doc["compensation_detail"]["total_fen"] > 0
        assert doc["final_pay_detail"]["net_fen"] > 0
