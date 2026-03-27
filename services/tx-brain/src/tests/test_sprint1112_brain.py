"""Sprint 11-12 Tests — Voice AI + CFO Dashboard + 2030 Evolution

覆盖场景：
- Voice: 16种意图识别 (中文餐饮场景)
- Voice: 多轮对话 (槽位补全)
- Voice: 完整流水线 (audio → text → intent → action → response)
- CFO: 现金流/合并报表/税务/KPI/预算对比/预测/高管摘要
- 2030: Feature Flags/Multi-region/Currency/Agent Levels
"""
from __future__ import annotations

import pytest

from ..services.voice_orchestrator import VoiceOrchestrator, _chinese_num_to_int
from ..services.voice_session import VoiceSessionManager
from ..services.cfo_dashboard import CFODashboardService
from ..services.evolution_2030 import Evolution2030Service


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def orchestrator() -> VoiceOrchestrator:
    return VoiceOrchestrator()


@pytest.fixture
def session_mgr() -> VoiceSessionManager:
    return VoiceSessionManager()


@pytest.fixture
def cfo() -> CFODashboardService:
    return CFODashboardService()


@pytest.fixture
def evo() -> Evolution2030Service:
    return Evolution2030Service()


# ═══════════════════════════════════════════════════════════════════
# Voice: 完整流水线测试
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_voice_full_pipeline_order_add(orchestrator: VoiceOrchestrator) -> None:
    """三号桌加一份酸菜鱼微辣 → full pipeline → order added"""
    # 模拟 NLU 直接测试（因 Whisper 不可用时用 mock）
    nlu = await orchestrator.understand("三号桌加一份酸菜鱼微辣")
    assert nlu["intent"] == "order_add"
    assert nlu["entities"]["table_no"] == 3
    assert nlu["entities"]["dish_name"] == "酸菜鱼"
    assert nlu["entities"]["quantity"] == 1
    assert nlu["entities"]["spice_level"] == "mild"

    # 执行动作
    action = await orchestrator.execute_action(
        "order_add",
        nlu["entities"],
        store_id="S001",
        employee_id="E001",
    )
    assert action["ok"] is True
    assert action["data"]["dish_name"] == "酸菜鱼"
    assert action["data"]["status"] == "added"

    # 生成回复
    response = await orchestrator.generate_response(action)
    assert "酸菜鱼" in response["response_text"]
    assert "3号桌" in response["response_text"]


@pytest.mark.asyncio
async def test_voice_full_pipeline_query_revenue(orchestrator: VoiceOrchestrator) -> None:
    """今天营收多少 → query → 营收回复"""
    nlu = await orchestrator.understand("今天营收多少")
    assert nlu["intent"] == "query_revenue"
    assert nlu["entities"]["date_ref"] == "今天"

    action = await orchestrator.execute_action(
        "query_revenue",
        nlu["entities"],
        store_id="S001",
        employee_id="E001",
    )
    assert action["ok"] is True
    assert action["data"]["total_revenue_fen"] > 0

    response = await orchestrator.generate_response(action)
    assert "营收" in response["response_text"]
    assert "元" in response["response_text"]
    assert "增长" in response["response_text"] or "下降" in response["response_text"] or "单" in response["response_text"]


@pytest.mark.asyncio
async def test_voice_full_pipeline_report_waste(orchestrator: VoiceOrchestrator) -> None:
    """鲈鱼损耗两斤记一下 → waste recorded"""
    nlu = await orchestrator.understand("鲈鱼损耗两斤记一下")
    assert nlu["intent"] == "report_waste"
    assert nlu["entities"]["ingredient"] == "鲈鱼"
    assert nlu["entities"]["weight"] == 2
    assert nlu["entities"]["unit"] == "斤"

    action = await orchestrator.execute_action(
        "report_waste",
        nlu["entities"],
        store_id="S001",
        employee_id="E003",
    )
    assert action["ok"] is True
    assert action["data"]["status"] == "recorded"

    response = await orchestrator.generate_response(action)
    assert "鲈鱼" in response["response_text"]
    assert "损耗" in response["response_text"]


# ═══════════════════════════════════════════════════════════════════
# Voice: 多轮对话测试
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_voice_multi_turn_dialog(
    orchestrator: VoiceOrchestrator, session_mgr: VoiceSessionManager
) -> None:
    """多轮对话: "加菜" → "什么菜？" → "酸菜鱼" → "辣度？" → confirmed"""
    # 创建会话
    session = session_mgr.create_session("E001", "S001")
    sid = session["session_id"]

    # Turn 1: "加菜" — 缺少菜名
    nlu1 = await orchestrator.understand("加菜")
    assert nlu1["intent"] == "order_add"
    dialog1 = await orchestrator.manage_dialog(sid, nlu1)
    assert dialog1["complete"] is False
    assert dialog1["missing_slot"] == "dish_name"
    assert "什么菜" in dialog1["prompt_text"]

    # 记录轮次
    session_mgr.add_turn(sid, "user", "加菜")
    session_mgr.add_turn(sid, "system", dialog1["prompt_text"])

    # Turn 2: "酸菜鱼" — 补全菜名，上下文接续
    session_mgr.update_context(sid, {
        "last_intent": "order_add",
        "entities": {"dish_name": "酸菜鱼"},
    })
    ctx = session_mgr.get_context(sid)
    nlu2 = await orchestrator.understand("酸菜鱼", context=ctx)
    # 上下文补全应该识别出 order_add
    assert nlu2["intent"] in ("order_add", "order_modify")

    # Turn 3: 最终确认 — 完整信息
    nlu_final = await orchestrator.understand("三号桌加一份酸菜鱼微辣")
    dialog_final = await orchestrator.manage_dialog(sid, nlu_final)
    assert dialog_final["complete"] is True
    assert dialog_final["action"] == "execute"

    # 关闭会话
    close_result = session_mgr.close_session(sid)
    assert close_result["ok"] is True
    assert close_result["total_turns"] == 2


# ═══════════════════════════════════════════════════════════════════
# Voice: 15种意图全覆盖
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected_intent",
    [
        ("三号桌加一份酸菜鱼", "order_add"),
        ("来两份红烧肉", "order_add"),
        ("退一份水煮鱼", "order_remove"),
        ("酸菜鱼不要了", "order_remove"),
        ("酸菜鱼改成微辣", "order_modify"),
        ("A05桌结账", "checkout"),
        ("买单", "checkout"),
        ("5号桌开台", "open_table"),
        ("今天营收多少", "query_revenue"),
        ("本月流水怎么样", "query_revenue"),
        ("鲈鱼还有多少", "query_inventory"),
        ("3号桌怎么样了", "query_order_status"),
        ("鲈鱼损耗两斤", "report_waste"),
        ("叫服务员", "call_service"),
        ("3号桌催菜", "rush_order"),
        ("预订四位", "reserve_table"),
        ("谁在上班", "query_staff"),
        ("出日报", "daily_report"),
        ("3号桌换到5号桌", "switch_table"),
        ("3号桌和5号桌合并", "merge_table"),
    ],
)
async def test_voice_all_intents(
    orchestrator: VoiceOrchestrator, text: str, expected_intent: str
) -> None:
    """测试所有16种意图识别"""
    nlu = await orchestrator.understand(text)
    assert nlu["intent"] == expected_intent, (
        f"Text '{text}' expected intent '{expected_intent}' but got '{nlu['intent']}'"
    )
    assert nlu["confidence"] > 0


# ═══════════════════════════════════════════════════════════════════
# Voice: 实体抽取细节
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_voice_entity_extraction(orchestrator: VoiceOrchestrator) -> None:
    """测试实体抽取: 桌号/菜名/数量/辣度/口味"""
    nlu = await orchestrator.understand("三号桌加两份酸菜鱼微辣")
    entities = nlu["entities"]
    assert entities["table_no"] == 3
    assert entities["dish_name"] == "酸菜鱼"
    assert entities["quantity"] == 2
    assert entities["spice_level"] == "mild"


@pytest.mark.asyncio
async def test_voice_alphanumeric_table(orchestrator: VoiceOrchestrator) -> None:
    """支持字母+数字混合桌号: A05桌结账"""
    nlu = await orchestrator.understand("A05桌结账")
    assert nlu["intent"] == "checkout"
    assert nlu["entities"]["table_no"] == "A05"


def test_chinese_num_conversion() -> None:
    """中文数字转换"""
    assert _chinese_num_to_int("一") == 1
    assert _chinese_num_to_int("两") == 2
    assert _chinese_num_to_int("十") == 10
    assert _chinese_num_to_int("十二") == 12
    assert _chinese_num_to_int("三十") == 30
    assert _chinese_num_to_int("5") == 5
    assert _chinese_num_to_int("23") == 23


# ═══════════════════════════════════════════════════════════════════
# Voice: Session Management
# ═══════════════════════════════════════════════════════════════════

def test_voice_session_lifecycle(session_mgr: VoiceSessionManager) -> None:
    """会话完整生命周期"""
    # 创建
    sess = session_mgr.create_session("E001", "S001", "pos")
    sid = sess["session_id"]
    assert sid.startswith("VS-")
    assert sess["status"] == "active"

    # 获取
    info = session_mgr.get_session(sid)
    assert info["ok"] is True
    assert info["turn_count"] == 0

    # 添加轮次
    t1 = session_mgr.add_turn(sid, "user", "三号桌加菜")
    assert t1["ok"] is True
    assert t1["turn_index"] == 0

    t2 = session_mgr.add_turn(sid, "system", "请问要什么菜？")
    assert t2["ok"] is True
    assert t2["turn_index"] == 1

    # 更新上下文
    session_mgr.update_context(sid, {"current_table": 3, "last_intent": "order_add"})
    ctx = session_mgr.get_context(sid)
    assert ctx["current_table"] == 3
    assert ctx["last_intent"] == "order_add"

    # 活跃会话列表
    active = session_mgr.get_active_sessions("S001")
    assert len(active) == 1
    assert active[0]["session_id"] == sid

    # 关闭
    close = session_mgr.close_session(sid)
    assert close["ok"] is True
    assert close["total_turns"] == 2

    # 关闭后获取
    info2 = session_mgr.get_session(sid)
    assert info2.get("ok") is False


# ═══════════════════════════════════════════════════════════════════
# Voice: Process Voice Command (Full Pipeline with audio bytes)
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_process_voice_command_mock(orchestrator: VoiceOrchestrator) -> None:
    """完整流水线（Mock ASR）"""
    result = await orchestrator.process_voice_command(
        audio_bytes=b"fake_audio_data",
        session_id="VS-TEST001",
        store_id="S001",
        employee_id="E001",
        language="zh",
    )

    assert result["transcription"]["source"] == "mock"
    assert result["session_id"] == "VS-TEST001"
    assert result["response_text"]  # 有回复文本
    assert result["needs_followup"] is False


# ═══════════════════════════════════════════════════════════════════
# CFO Dashboard: Cash Flow
# ═══════════════════════════════════════════════════════════════════

def test_cfo_cash_flow(cfo: CFODashboardService) -> None:
    """现金流量表结构完整性"""
    data = {
        "operating": {
            "revenue": 500_0000_00,
            "cogs": 150_0000_00,
            "opex": 200_0000_00,
            "tax_paid": 30_0000_00,
            "working_capital_change": 10_0000_00,
        },
        "investing": {
            "equipment_purchase": 50_0000_00,
            "renovation": 20_0000_00,
            "asset_disposal": 5_0000_00,
        },
        "financing": {
            "loan_proceeds": 100_0000_00,
            "loan_repayment": 30_0000_00,
            "equity_injection": 0,
            "dividends": 10_0000_00,
        },
        "opening_cash": 200_0000_00,
    }

    cf = cfo.get_cash_flow("B001", "2026-03", data)

    # 经营现金流 = 500 - 150 - 200 - 30 - 10 = 110万
    assert cf["operating"]["net_operating_cf"] == 110_0000_00
    # 投资现金流 = 5 - 50 - 20 = -65万
    assert cf["investing"]["net_investing_cf"] == -65_0000_00
    # 筹资现金流 = 100 - 30 + 0 - 10 = 60万
    assert cf["financing"]["net_financing_cf"] == 60_0000_00
    # 净现金变动 = 110 - 65 + 60 = 105万
    assert cf["summary"]["net_cash_change"] == 105_0000_00
    # 期末现金 = 200 + 105 = 305万
    assert cf["summary"]["closing_cash"] == 305_0000_00


# ═══════════════════════════════════════════════════════════════════
# CFO Dashboard: Multi-brand Consolidation
# ═══════════════════════════════════════════════════════════════════

def test_cfo_multi_brand_consolidation(cfo: CFODashboardService) -> None:
    """3个品牌合并报表"""
    brand_pnls = [
        {
            "brand_id": "尝在一起",
            "revenue": {"total": 300_0000_00},
            "cogs": {"total": 90_0000_00},
            "opex": {"total": 120_0000_00},
            "other_expenses": {"total": 15_0000_00},
            "gross_profit": 210_0000_00,
            "operating_profit": 90_0000_00,
            "net_profit": 75_0000_00,
            "inter_brand_revenue": 5_0000_00,
            "inter_brand_cogs": 3_0000_00,
            "store_count": 12,
        },
        {
            "brand_id": "最黔线",
            "revenue": {"total": 200_0000_00},
            "cogs": {"total": 70_0000_00},
            "opex": {"total": 80_0000_00},
            "other_expenses": {"total": 10_0000_00},
            "gross_profit": 130_0000_00,
            "operating_profit": 50_0000_00,
            "net_profit": 40_0000_00,
            "inter_brand_revenue": 3_0000_00,
            "inter_brand_cogs": 2_0000_00,
            "store_count": 8,
        },
        {
            "brand_id": "尚宫厨",
            "revenue": {"total": 150_0000_00},
            "cogs": {"total": 50_0000_00},
            "opex": {"total": 60_0000_00},
            "other_expenses": {"total": 8_0000_00},
            "gross_profit": 100_0000_00,
            "operating_profit": 40_0000_00,
            "net_profit": 32_0000_00,
            "inter_brand_revenue": 2_0000_00,
            "inter_brand_cogs": 1_0000_00,
            "store_count": 5,
        },
    ]

    result = cfo.consolidate_brands(
        brand_ids=["尝在一起", "最黔线", "尚宫厨"],
        period="2026-03",
        brand_pnls=brand_pnls,
    )

    # 合并后 revenue = (300+200+150) - (5+3+2) = 640万
    assert result["consolidated"]["revenue"] == 640_0000_00
    # 合并后 COGS = (90+70+50) - (3+2+1) = 204万
    assert result["consolidated"]["cogs"] == 204_0000_00
    # 品牌数量
    assert result["brand_count"] == 3
    assert len(result["brand_breakdown"]) == 3
    # 抵消金额
    assert result["eliminations"]["inter_brand_revenue"] == 10_0000_00
    assert result["eliminations"]["inter_brand_cogs"] == 6_0000_00
    # 毛利率 > 0
    assert result["consolidated"]["gross_margin"] > 0


# ═══════════════════════════════════════════════════════════════════
# CFO Dashboard: Tax Summary
# ═══════════════════════════════════════════════════════════════════

def test_cfo_tax_summary_vat_and_corporate(cfo: CFODashboardService) -> None:
    """税务总览: 增值税 + 企业所得税"""
    data = {
        "revenue": 500_0000_00,
        "taxable_income": 80_0000_00,
        "payroll_total": 60_0000_00,
        "property_value": 200_0000_00,
        "deductible_items": [
            {"name": "进项税", "type": "vat_input", "amount": 10_0000_00},
            {"name": "研发加计扣除", "type": "deduction", "amount": 5_0000_00},
        ],
    }

    tax = cfo.get_tax_summary("B001", "2026-03", data)

    # 增值税: 销项 = 500万 * 6% / 1.06
    assert tax["vat"]["rate"] == 0.06
    assert tax["vat"]["output_tax"] > 0
    assert tax["vat"]["input_tax"] == 10_0000_00
    assert tax["vat"]["payable"] >= 0

    # 企业所得税: 应纳税所得额 80万 - 15万抵扣 = 65万
    # 小微优惠 5%
    assert tax["corporate_income_tax"]["effective_rate"] == 0.05
    assert tax["corporate_income_tax"]["tax_amount"] > 0

    # 社保
    assert tax["payroll_taxes"]["social_insurance"] == int(60_0000_00 * 0.30)

    # 总税负
    assert tax["total_tax"] > 0
    assert tax["effective_tax_rate"] > 0


# ═══════════════════════════════════════════════════════════════════
# CFO Dashboard: Financial KPIs
# ═══════════════════════════════════════════════════════════════════

def test_cfo_financial_kpis(cfo: CFODashboardService) -> None:
    """财务KPI计算"""
    data = {
        "revenue": 500_0000_00,
        "cogs": 150_0000_00,
        "opex": 200_0000_00,
        "depreciation": 20_0000_00,
        "amortization": 5_0000_00,
        "interest_expense": 3_0000_00,
        "tax_expense": 15_0000_00,
        "net_profit": 107_0000_00,
        "total_investment": 800_0000_00,
        "same_store_revenue_current": 400_0000_00,
        "same_store_revenue_prior": 360_0000_00,
        "new_store_revenue": 100_0000_00,
        "current_assets": 200_0000_00,
        "current_liabilities": 100_0000_00,
        "accounts_receivable": 30_0000_00,
        "accounts_payable": 40_0000_00,
        "daily_revenue": 500_0000_00 // 30,
        "daily_cogs": 150_0000_00 // 30,
    }

    kpis = cfo.get_financial_kpis("B001", "2026-03", data)

    # EBITDA = (500-150-200) + 20 + 5 = 175万
    assert kpis["profitability"]["ebitda"] == 175_0000_00
    assert kpis["profitability"]["ebitda_margin"] > 0

    # ROI
    assert kpis["returns"]["roi"] > 0
    assert kpis["returns"]["payback_months"] > 0

    # 同店增长 = (400-360)/360
    assert kpis["growth"]["same_store_growth"] > 0

    # 营运资金 = 200 - 100 = 100万
    assert kpis["liquidity"]["working_capital"] == 100_0000_00
    assert kpis["liquidity"]["current_ratio"] == 2.0

    # 应收天数
    assert kpis["efficiency"]["accounts_receivable_days"] > 0


# ═══════════════════════════════════════════════════════════════════
# CFO Dashboard: Budget vs Actual
# ═══════════════════════════════════════════════════════════════════

def test_cfo_budget_vs_actual(cfo: CFODashboardService) -> None:
    """预算 vs 实际差异分析"""
    data = {
        "budget": {
            "revenue": 500_0000_00,
            "cogs": 150_0000_00,
            "labor": 100_0000_00,
            "rent": 50_0000_00,
            "marketing": 20_0000_00,
            "utilities": 10_0000_00,
            "net_profit": 100_0000_00,
        },
        "actual": {
            "revenue": 520_0000_00,
            "cogs": 160_0000_00,
            "labor": 95_0000_00,
            "rent": 50_0000_00,
            "marketing": 25_0000_00,
            "utilities": 12_0000_00,
            "net_profit": 108_0000_00,
        },
    }

    result = cfo.compare_budget("B001", "2026-03", data)

    # 收入超额
    rev_v = next(v for v in result["variances"] if v["item"] == "revenue")
    assert rev_v["status"] == "favorable"
    assert rev_v["variance"] == 20_0000_00

    # 人工成本节约
    labor_v = next(v for v in result["variances"] if v["item"] == "labor")
    assert labor_v["status"] == "favorable"  # actual < budget

    # 净利润超额
    np_v = next(v for v in result["variances"] if v["item"] == "net_profit")
    assert np_v["status"] == "favorable"

    # 总体评估: 增收增利
    assert result["overall_assessment"] == "超额完成"


# ═══════════════════════════════════════════════════════════════════
# CFO Dashboard: Forecast
# ═══════════════════════════════════════════════════════════════════

def test_cfo_forecast(cfo: CFODashboardService) -> None:
    """财务预测（3个月）"""
    historical = [
        {"month": "2026-01", "revenue": 400_0000_00, "cogs": 120_0000_00,
         "opex": 160_0000_00, "net_profit": 80_0000_00},
        {"month": "2026-02", "revenue": 420_0000_00, "cogs": 126_0000_00,
         "opex": 165_0000_00, "net_profit": 86_0000_00},
        {"month": "2026-03", "revenue": 450_0000_00, "cogs": 130_0000_00,
         "opex": 170_0000_00, "net_profit": 95_0000_00},
    ]

    result = cfo.generate_forecast("B001", months_ahead=3, historical_data=historical)

    assert len(result["forecasts"]) == 3
    assert result["forecasts"][0]["month"] == "2026-04"
    assert result["forecasts"][1]["month"] == "2026-05"
    assert result["forecasts"][2]["month"] == "2026-06"

    # 预测收入应该呈增长趋势
    assert result["forecasts"][0]["revenue"] > 0
    assert result["growth_rates"]["revenue"] > 0
    assert result["method"] == "linear_trend"


# ═══════════════════════════════════════════════════════════════════
# CFO Dashboard: Executive Summary
# ═══════════════════════════════════════════════════════════════════

def test_cfo_executive_summary(cfo: CFODashboardService) -> None:
    """高管摘要自动生成"""
    data = {
        "consolidated_revenue": 650_0000_00,
        "consolidated_net_profit": 147_0000_00,
        "yoy_revenue_growth": 0.12,
        "yoy_profit_growth": 0.08,
        "store_count": 25,
        "new_stores": 3,
        "closed_stores": 1,
        "same_store_growth": 0.05,
        "top_brand": {"brand_id": "尝在一起", "net_margin": 0.25},
        "bottom_brand": {"brand_id": "尚宫厨", "net_margin": 0.08},
        "cash_position": 300_0000_00,
        "debt_total": 100_0000_00,
        "alerts": ["尚宫厨净利率下降"],
        "achievements": ["新开3家门店"],
    }

    summary = cfo.generate_executive_summary(
        brand_ids=["尝在一起", "最黔线", "尚宫厨"],
        period="2026-03",
        data=data,
    )

    assert summary["brand_count"] == 3
    assert "营收" in summary["headline"]
    assert "增长" in summary["headline"]
    assert summary["key_metrics"]["revenue"]["value"] == 650_0000_00
    assert summary["key_metrics"]["stores"]["total"] == 25
    assert summary["key_metrics"]["stores"]["net_change"] == 2
    assert len(summary["recommendations"]) > 0
    assert summary["generated_by"] == "CFO Dashboard AI"


# ═══════════════════════════════════════════════════════════════════
# 2030 Evolution: Feature Flags
# ═══════════════════════════════════════════════════════════════════

def test_evolution_feature_flags_by_store_type(evo: Evolution2030Service) -> None:
    """按业态初始化功能集"""
    # 大店Pro
    evo.init_store_by_type("S001", "大店Pro")
    flags = evo.get_feature_flags("S001")
    assert flags["features"]["voice_ordering"] is True
    assert flags["features"]["banquet_module"] is True
    assert flags["features"]["multi_floor_management"] is True
    assert flags["store_type"] == "大店Pro"

    # 小店Lite
    evo.init_store_by_type("S002", "小店Lite")
    flags2 = evo.get_feature_flags("S002")
    assert flags2["features"]["voice_ordering"] is True
    assert flags2["features"]["banquet_module"] is False
    assert flags2["features"]["smart_kitchen_dispatch"] is False

    # 外卖
    evo.init_store_by_type("S003", "外卖")
    flags3 = evo.get_feature_flags("S003")
    assert flags3["features"]["chef_at_home"] is True
    assert flags3["features"]["vip_room_management"] is False
    assert flags3["features"]["delivery_module"] is True


def test_evolution_set_feature_flag(evo: Evolution2030Service) -> None:
    """单独设置功能标志"""
    evo.init_store_by_type("S001", "小店Lite")
    # 升级: 打开智能厨房调度
    result = evo.set_feature_flag("S001", "smart_kitchen_dispatch", True)
    assert result["ok"] is True
    assert result["previous"] is False
    assert result["enabled"] is True

    flags = evo.get_feature_flags("S001")
    assert flags["features"]["smart_kitchen_dispatch"] is True


# ═══════════════════════════════════════════════════════════════════
# 2030 Evolution: Multi-region
# ═══════════════════════════════════════════════════════════════════

def test_evolution_multi_region(evo: Evolution2030Service) -> None:
    """区域联邦配置"""
    config = evo.get_region_config("华中")
    assert config["region_id"] == "华中"
    assert config["currency"] == "CNY"
    assert config["timezone"] == "Asia/Shanghai"

    # 设置区域策略
    result = evo.set_region_policy("华东", {
        "timezone": "Asia/Shanghai",
        "data_residency": "cn-shanghai",
        "sync_interval_seconds": 180,
    })
    assert result["ok"] is True
    assert "data_residency" in result["updated_fields"]

    config2 = evo.get_region_config("华东")
    assert config2["data_residency"] == "cn-shanghai"
    assert config2["sync_interval_seconds"] == 180


# ═══════════════════════════════════════════════════════════════════
# 2030 Evolution: Currency Conversion
# ═══════════════════════════════════════════════════════════════════

def test_evolution_currency_conversion(evo: Evolution2030Service) -> None:
    """货币转换"""
    # CNY → HKD
    result = evo.convert_currency(100_00, "CNY", "HKD")
    assert result["ok"] is True
    assert result["converted_amount"] > 100  # HKD > CNY
    assert result["rate"] > 1

    # CNY → USD
    result2 = evo.convert_currency(100_00, "CNY", "USD")
    assert result2["ok"] is True
    assert result2["converted_amount"] < 100  # USD < CNY

    # 不支持的币种
    result3 = evo.convert_currency(100_00, "CNY", "BTC")
    assert result3.get("ok") is False

    # 获取汇率表
    rates = evo.get_exchange_rates()
    assert rates["base"] == "CNY"
    assert "USD" in rates["rates"]
    assert "HKD" in rates["rates"]
    assert len(rates["rates"]) >= 7


# ═══════════════════════════════════════════════════════════════════
# 2030 Evolution: Agent Level Registry
# ═══════════════════════════════════════════════════════════════════

def test_evolution_agent_levels(evo: Evolution2030Service) -> None:
    """Agent放权追踪"""
    # 初始等级
    info = evo.get_agent_level("discount_guard")
    assert info["level"] == 0
    assert info["level_name"] == "通知"

    # 升级到 Level 1
    result = evo.set_agent_level("discount_guard", 1, "试运行一个月表现良好")
    assert result["ok"] is True
    assert result["previous_level"] == 0
    assert result["new_level"] == 1

    # 升级到 Level 2
    evo.set_agent_level("discount_guard", 2, "数据显示准确率99%")

    # 检查历史
    history = evo.get_agent_level_history("discount_guard")
    assert len(history) == 2
    assert history[0]["previous_level"] == 0
    assert history[0]["new_level"] == 1
    assert history[1]["new_level"] == 2

    # 无效等级
    result2 = evo.set_agent_level("discount_guard", 5, "invalid")
    assert result2["ok"] is False


# ═══════════════════════════════════════════════════════════════════
# 2030 Evolution: System Maturity Score
# ═══════════════════════════════════════════════════════════════════

def test_evolution_system_maturity_score(evo: Evolution2030Service) -> None:
    """系统成熟度评分"""
    # 初始状态（无Agent、无门店、无区域）
    score = evo.get_system_maturity_score()
    assert score["max_score"] == 100.0
    assert score["score"] >= 0
    assert score["level"] in ("起步阶段", "初级", "中等成熟度", "高成熟度")

    # 添加一些Agent和门店
    evo.set_agent_level("discount_guard", 2, "")
    evo.set_agent_level("smart_menu", 1, "")
    evo.set_agent_level("kitchen_dispatch", 2, "")
    evo.init_store_by_type("S001", "大店Pro")
    evo.init_store_by_type("S002", "小店Lite")
    evo.get_region_config("华中")
    evo.get_region_config("华东")

    score2 = evo.get_system_maturity_score()
    assert score2["score"] > score["score"]
    assert score2["breakdown"]["agent_autonomy"]["agent_count"] == 3
    assert score2["breakdown"]["agent_autonomy"]["avg_level"] > 0
    assert score2["breakdown"]["feature_coverage"]["coverage_ratio"] > 0
    assert score2["breakdown"]["regional_expansion"]["region_count"] == 2


# ═══════════════════════════════════════════════════════════════════
# Voice: Response Generation
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_voice_response_ssml(orchestrator: VoiceOrchestrator) -> None:
    """SSML格式回复"""
    action_result = {
        "ok": True,
        "intent": "order_add",
        "data": {
            "dish_name": "剁椒鱼头",
            "quantity": 1,
            "table_no": 8,
            "total_amount_fen": 16800,
        },
    }
    response = await orchestrator.generate_response(action_result, format="ssml")
    assert response["format"] == "ssml"
    assert "<speak>" in response["ssml"]
    assert "剁椒鱼头" in response["response_text"]


@pytest.mark.asyncio
async def test_voice_response_error(orchestrator: VoiceOrchestrator) -> None:
    """错误回复"""
    action_result = {"ok": False, "error": "菜品已售罄", "intent": "order_add"}
    response = await orchestrator.generate_response(action_result)
    assert "抱歉" in response["response_text"]
    assert "售罄" in response["response_text"]


# ═══════════════════════════════════════════════════════════════════
# CFO Dashboard: Cost Structure
# ═══════════════════════════════════════════════════════════════════

def test_cfo_cost_structure(cfo: CFODashboardService) -> None:
    """成本结构分析"""
    data = {
        "revenue": 500_0000_00,
        "fixed_costs": {
            "rent": 30_0000_00,
            "depreciation": 10_0000_00,
            "admin_salary": 20_0000_00,
            "insurance": 2_0000_00,
        },
        "variable_costs": {
            "food_cost": 120_0000_00,
            "beverage_cost": 15_0000_00,
            "hourly_labor": 50_0000_00,
            "utilities": 8_0000_00,
            "packaging": 5_0000_00,
            "platform_commission": 10_0000_00,
        },
        "covers": 15000,
        "store_count": 5,
    }

    result = cfo.get_cost_structure("B001", "2026-03", data)

    # 固定成本 = 30 + 10 + 20 + 2 = 62万
    assert result["fixed_costs"]["total"] == 62_0000_00
    # 变动成本 = 120 + 15 + 50 + 8 + 5 + 10 = 208万
    assert result["variable_costs"]["total"] == 208_0000_00
    # 总成本 = 270万
    assert result["total_cost"] == 270_0000_00
    # 盈亏平衡点存在
    assert result["breakeven"]["breakeven_revenue"] > 0
    assert result["breakeven"]["safety_margin"] > 0
    # 单位成本
    assert result["unit_costs"]["cost_per_cover"] > 0
    assert result["unit_costs"]["cost_per_store"] > 0
