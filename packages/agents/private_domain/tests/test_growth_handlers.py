"""
用户增长侧 growth_handlers 单元测试
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from growth_handlers import (
    GROWTH_ACTIONS,
    COGNITIVE_FRIENDLY_TEMPLATES,
    _render_template,
    run_growth_action,
)


@pytest.fixture
def store_id():
    return "S001"


@pytest.mark.asyncio
async def test_growth_actions_count():
    assert len(GROWTH_ACTIONS) == 18
    assert "nl_query" in GROWTH_ACTIONS
    assert "user_portrait" in GROWTH_ACTIONS


@pytest.mark.asyncio
async def test_unknown_action_returns_error():
    out = await run_growth_action("unknown_action", {}, "")
    assert "error" in out
    assert "supported" in out


@pytest.mark.asyncio
async def test_user_portrait_returns_summary_and_demographics(store_id):
    out = await run_growth_action("user_portrait", {"segment_id": "vip"}, store_id)
    assert "error" not in out
    assert "summary" in out
    assert "demographics" in out
    assert out.get("store_id") == store_id


@pytest.mark.asyncio
async def test_user_portrait_uses_context():
    ctx = {"member_summary": "自定义画像摘要", "demographics": {"custom": 1}}
    out = await run_growth_action("user_portrait", {"context": ctx}, "")
    assert out.get("summary") == "自定义画像摘要"
    assert out.get("demographics", {}).get("custom") == 1


@pytest.mark.asyncio
async def test_realtime_metrics_uses_context():
    ctx = {"metrics_summary": "今日增长10%", "metrics": {"dau_growth_pct": 10}}
    out = await run_growth_action("realtime_metrics", {"context": ctx}, "S002")
    assert out.get("summary") == "今日增长10%"
    assert out.get("metrics", {}).get("dau_growth_pct") == 10
    assert out.get("store_id") == "S002"


@pytest.mark.asyncio
async def test_personalized_recommend_limit_bounded():
    out = await run_growth_action("personalized_recommend", {"user_id": "U1", "limit": 3}, "")
    assert len(out.get("items", [])) <= 3
    assert out.get("limit") == 3


@pytest.mark.asyncio
async def test_personalized_recommend_uses_context():
    ctx = {"recommendations": [{"type": "menu", "name": "A", "reason": "因为A"}]}
    out = await run_growth_action("personalized_recommend", {"context": ctx, "limit": 5}, "")
    assert out["items"][0]["name"] == "A"
    assert out["items"][0]["reason"] == "因为A"


@pytest.mark.asyncio
async def test_nl_query_requires_query():
    out = await run_growth_action("nl_query", {}, "")
    # 参数校验失败时返回 error，未进入 handler 故无 answer
    assert "error" in out
    assert "query" in out.get("error", "").lower() or "query" in str(out)


@pytest.mark.asyncio
async def test_nl_query_intent_user_portrait():
    out = await run_growth_action("nl_query", {"query": "用户画像怎么样"}, "")
    assert out.get("resolved_actions") == ["user_portrait"]
    assert "data" in out
    assert "summary" in out.get("data", {})


@pytest.mark.asyncio
async def test_nl_query_intent_inventory():
    out = await run_growth_action("nl_query", {"query": "库存和采购计划"}, "")
    assert "inventory_plan" in out.get("resolved_actions", [])


@pytest.mark.asyncio
async def test_nl_query_intent_staff_schedule():
    out = await run_growth_action("nl_query", {"query": "下周排班人手不够"}, "")
    assert "staff_schedule_advice" in out.get("resolved_actions", [])


@pytest.mark.asyncio
async def test_nl_query_intent_store_location():
    out = await run_growth_action("nl_query", {"query": "想开新店选址"}, "")
    assert "store_location_advice" in out.get("resolved_actions", [])


@pytest.mark.asyncio
async def test_validation_personalized_recommend_limit_invalid():
    out = await run_growth_action("personalized_recommend", {"limit": 100}, "")
    assert "error" in out


@pytest.mark.asyncio
async def test_funnel_optimize_returns_suggestions():
    out = await run_growth_action("funnel_optimize", {"funnel_stage": "retention"}, "")
    assert "bottleneck" in out
    assert "suggestions" in out
    assert len(out["suggestions"]) >= 1


@pytest.mark.asyncio
async def test_demand_forecast_returns_horizon():
    out = await run_growth_action("demand_forecast", {"horizon": "14d"}, "")
    assert out.get("horizon") == "14d"
    assert "forecast_growth_pct" in out
    assert "inventory_suggestion_pct" in out


@pytest.mark.asyncio
async def test_food_safety_alert_returns_alerts():
    out = await run_growth_action("food_safety_alert", {"store_id": "S1"}, "")
    assert "alerts" in out
    assert len(out["alerts"]) >= 1
    assert out.get("store_id") == "S1"


# ── A1 认知友好模板系统测试 ────────────────────────────────────────────────────

class TestCognitiveFriendlyTemplates:
    """方向十二：认知友好模板系统——行为科学原则验证。"""

    def test_all_four_themes_defined(self):
        assert set(COGNITIVE_FRIENDLY_TEMPLATES.keys()) == {
            "新品上市", "节假日促销", "复购唤醒", "口碑引导"
        }

    def test_each_template_has_required_fields(self):
        for theme, tpl in COGNITIVE_FRIENDLY_TEMPLATES.items():
            assert "draft_template" in tpl, f"{theme} 缺少 draft_template"
            assert "draft_fallback" in tpl, f"{theme} 缺少 draft_fallback"
            assert "principle" in tpl, f"{theme} 缺少 principle"
            assert "publish_tip" in tpl, f"{theme} 缺少 publish_tip"
            assert "forbidden" in tpl, f"{theme} 缺少 forbidden"

    def test_render_template_with_full_vars(self):
        tpl = COGNITIVE_FRIENDLY_TEMPLATES["新品上市"]
        result = _render_template(tpl, {
            "taster_count": 5,
            "dish_name": "清蒸鲈鱼",
            "chef_name": "张师傅",
            "texture_word": "嫩",
        })
        assert "5" in result
        assert "清蒸鲈鱼" in result
        assert "张师傅" in result

    def test_render_template_falls_back_on_missing_vars(self):
        tpl = COGNITIVE_FRIENDLY_TEMPLATES["新品上市"]
        result = _render_template(tpl, {})  # 缺少所有变量
        assert result == tpl["draft_fallback"]
        assert len(result) > 0

    def test_render_holiday_template(self):
        tpl = COGNITIVE_FRIENDLY_TEMPLATES["节假日促销"]
        result = _render_template(tpl, {
            "holiday": "五一",
            "store_name": "徐记海鲜",
            "seat_count": 2,
        })
        assert "五一" in result
        assert "徐记海鲜" in result
        assert "2" in result

    def test_render_reactivation_template(self):
        tpl = COGNITIVE_FRIENDLY_TEMPLATES["复购唤醒"]
        result = _render_template(tpl, {
            "last_visit_season": "夏天",
            "current_ingredient": "秋蟹",
        })
        assert "夏天" in result
        assert "秋蟹" in result

    def test_render_reputation_template(self):
        tpl = COGNITIVE_FRIENDLY_TEMPLATES["口碑引导"]
        result = _render_template(tpl, {"visit_count": 8})
        assert "8" in result

    # ── action 接口测试 ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_social_content_draft_returns_principle_and_forbidden(self):
        """返回值必须包含行为科学原理字段。"""
        out = await run_growth_action(
            "social_content_draft",
            {"theme": "新品上市"},
            "S001",
        )
        assert "draft" in out
        assert "principle" in out
        assert "forbidden" in out
        assert "publish_tip" in out
        assert len(out["draft"]) > 0

    @pytest.mark.asyncio
    async def test_social_content_draft_new_product_with_vars(self):
        """变量填充后文案包含具体的人和菜品名。"""
        out = await run_growth_action(
            "social_content_draft",
            {
                "theme": "新品上市",
                "vars": {
                    "taster_count": 4,
                    "dish_name": "口水鸡",
                    "chef_name": "李大厨",
                    "texture_word": "香",
                },
            },
            "S001",
        )
        assert "口水鸡" in out["draft"]
        assert "李大厨" in out["draft"]
        # 验证不是广告感文案（不含「上市！」等）
        assert "上市！" not in out["draft"]

    @pytest.mark.asyncio
    async def test_social_content_draft_holiday_no_discount_word(self):
        """节假日模板不应包含折扣百分比。"""
        out = await run_growth_action(
            "social_content_draft",
            {
                "theme": "节假日促销",
                "vars": {
                    "holiday": "国庆",
                    "store_name": "徐记",
                    "seat_count": 4,
                },
            },
            "S001",
        )
        assert "折" not in out["draft"]
        assert "%" not in out["draft"]
        assert "forbidden" in out

    @pytest.mark.asyncio
    async def test_social_content_draft_reactivation_no_absence_pressure(self):
        """复购唤醒模板不应包含「没来」「想念」等施压词。"""
        out = await run_growth_action(
            "social_content_draft",
            {"theme": "复购唤醒"},
            "S001",
        )
        assert "没来" not in out["draft"]
        assert "想念" not in out["draft"]

    @pytest.mark.asyncio
    async def test_social_content_draft_reputation_uses_altruism_framing(self):
        """口碑引导文案要包含利他视角（帮助还没来过的人）。"""
        out = await run_growth_action(
            "social_content_draft",
            {"theme": "口碑引导"},
            "S001",
        )
        assert "还没来过" in out["draft"] or "还没" in out["draft"]

    @pytest.mark.asyncio
    async def test_social_content_draft_unknown_theme_falls_back(self):
        """未知主题降级到新品上市，不报错。"""
        out = await run_growth_action(
            "social_content_draft",
            {"theme": "随便一个不存在的主题"},
            "S001",
        )
        assert "draft" in out
        assert out.get("theme") == "新品上市"

    @pytest.mark.asyncio
    async def test_social_content_draft_store_id_propagated(self):
        """store_id 正确传播到返回值。"""
        out = await run_growth_action(
            "social_content_draft",
            {"theme": "口碑引导"},
            "S999",
        )
        assert out.get("store_id") == "S999"
