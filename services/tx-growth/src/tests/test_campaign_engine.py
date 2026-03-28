"""营销活动引擎测试 — 覆盖核心生命周期 + 模板执行

测试:
1.  活动创建 (全22种类型)
2.  活动状态机 (draft -> active -> paused -> ended)
3.  非法状态转换拒绝
4.  活动资格检查 (正常/预算耗尽/参与上限)
5.  触发奖励发放
6.  消费触发引擎
7.  注册触发引擎
8.  生日触发引擎
9.  定时触发引擎 (精准营销)
10. 奖励引擎 (5种奖励类型)
11. 抽奖概率校验 (总和=100%)
12. 储值套餐多档位匹配
13. 报名抽奖 (报名+开奖)
14. 活动效果分析
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.campaign_engine import (
    CampaignEngine,
    TriggerEngine,
    RewardEngine,
    clear_all_campaigns,
    _campaigns,
)
from campaigns.lottery import validate_prizes, draw_prize
from campaigns.stored_value_gift import execute as sv_execute
from campaigns.referral import execute as referral_execute
from campaigns.report_draw import execute as report_execute, clear_report_entries
from campaigns.sign_in import execute as sign_in_execute
from campaigns.spend_reward import execute as spend_execute
from campaigns.points_exchange import execute as points_execute

TENANT = "tenant-xuji"


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def clean():
    clear_all_campaigns()
    clear_report_entries()
    yield


@pytest.fixture
def engine():
    return CampaignEngine()


@pytest.fixture
def trigger():
    return TriggerEngine()


@pytest.fixture
def reward():
    return RewardEngine()


# ===========================================================================
# 1. 活动创建 — 全22种类型
# ===========================================================================

@pytest.mark.asyncio
async def test_create_all_campaign_types(engine):
    """22种活动类型均可成功创建"""
    for ctype in CampaignEngine.CAMPAIGN_TYPES:
        result = await engine.create_campaign(
            ctype, {"name": f"测试{ctype}"}, TENANT
        )
        assert "campaign_id" in result, f"创建 {ctype} 失败"
        assert result["status"] == "draft"
        assert result["tenant_id"] == TENANT

    # 不支持的类型
    bad = await engine.create_campaign("unknown_type", {}, TENANT)
    assert "error" in bad


# ===========================================================================
# 2. 状态机 — draft -> active -> paused -> ended
# ===========================================================================

@pytest.mark.asyncio
async def test_campaign_lifecycle(engine):
    """活动完整生命周期: 创建->启动->暂停->恢复->结束"""
    c = await engine.create_campaign(
        "spend_reward", {"name": "满减活动"}, TENANT
    )
    cid = c["campaign_id"]
    assert c["status"] == "draft"

    # draft -> active
    r = await engine.start_campaign(cid, TENANT)
    assert r["status"] == "active"

    # active -> paused
    r = await engine.pause_campaign(cid, TENANT)
    assert r["status"] == "paused"

    # paused -> active (恢复)
    r = await engine.start_campaign(cid, TENANT)
    assert r["status"] == "active"

    # active -> ended
    r = await engine.end_campaign(cid, TENANT)
    assert r["status"] == "ended"


# ===========================================================================
# 3. 非法状态转换
# ===========================================================================

@pytest.mark.asyncio
async def test_invalid_state_transitions(engine):
    """非法状态转换应被拒绝"""
    c = await engine.create_campaign("birthday", {"name": "生日"}, TENANT)
    cid = c["campaign_id"]

    # draft 不能直接暂停
    r = await engine.pause_campaign(cid, TENANT)
    assert "error" in r

    # draft 不能直接结束
    r = await engine.end_campaign(cid, TENANT)
    assert "error" in r

    # ended 不能再启动
    await engine.start_campaign(cid, TENANT)
    await engine.end_campaign(cid, TENANT)
    r = await engine.start_campaign(cid, TENANT)
    assert "error" in r


# ===========================================================================
# 4. 资格检查
# ===========================================================================

@pytest.mark.asyncio
async def test_eligibility_check(engine):
    """资格检查: 正常/未启动/预算耗尽/参与上限"""
    c = await engine.create_campaign(
        "scan_coupon",
        {"name": "扫码领券", "budget_fen": 10000, "max_per_customer": 2,
         "reward": {"type": "coupon", "amount_fen": 500}},
        TENANT,
    )
    cid = c["campaign_id"]

    # 未启动不可参与
    r = await engine.check_eligibility("cust-001", cid, TENANT)
    assert r["eligible"] is False

    await engine.start_campaign(cid, TENANT)

    # 正常可参与
    r = await engine.check_eligibility("cust-001", cid, TENANT)
    assert r["eligible"] is True

    # 预算耗尽
    _campaigns[cid]["spent_fen"] = 10000
    r = await engine.check_eligibility("cust-001", cid, TENANT)
    assert r["eligible"] is False
    assert "预算" in r["reason"]

    # 恢复预算, 测试参与上限
    _campaigns[cid]["spent_fen"] = 0
    await engine.trigger_reward("cust-001", cid, {"type": "scan"}, TENANT)
    await engine.trigger_reward("cust-001", cid, {"type": "scan"}, TENANT)
    r = await engine.check_eligibility("cust-001", cid, TENANT)
    assert r["eligible"] is False
    assert "上限" in r["reason"]


# ===========================================================================
# 5. 触发奖励发放
# ===========================================================================

@pytest.mark.asyncio
async def test_trigger_reward(engine):
    """触发奖励发放并更新统计"""
    c = await engine.create_campaign(
        "register_welcome",
        {"name": "开卡有礼", "reward": {"type": "coupon", "amount_fen": 1000}},
        TENANT,
    )
    cid = c["campaign_id"]
    await engine.start_campaign(cid, TENANT)

    r = await engine.trigger_reward(
        "cust-001", cid, {"type": "register"}, TENANT
    )
    assert r["rewarded"] is True
    assert r["reward"]["reward_type"] == "coupon"
    assert r["reward"]["amount_fen"] == 1000

    # 统计更新
    assert _campaigns[cid]["stats"]["participant_count"] == 1
    assert _campaigns[cid]["stats"]["reward_count"] == 1


# ===========================================================================
# 6. 消费触发引擎
# ===========================================================================

@pytest.mark.asyncio
async def test_consume_trigger(engine, trigger):
    """消费满额自动触发奖励"""
    c = await engine.create_campaign(
        "spend_reward",
        {"name": "满200送券", "threshold_fen": 20000,
         "reward": {"type": "coupon", "amount_fen": 3000}},
        TENANT,
    )
    await engine.start_campaign(c["campaign_id"], TENANT)

    order = {"customer_id": "cust-001", "total_fen": 25000}
    results = await trigger.on_consume(order, TENANT)
    assert len(results) >= 1
    assert results[0]["rewarded"] is True


# ===========================================================================
# 7. 注册触发引擎
# ===========================================================================

@pytest.mark.asyncio
async def test_register_trigger(engine, trigger):
    """新会员注册自动触发开卡有礼"""
    c = await engine.create_campaign(
        "register_welcome",
        {"name": "新客礼", "reward": {"type": "points", "points": 200}},
        TENANT,
    )
    await engine.start_campaign(c["campaign_id"], TENANT)

    customer = {"customer_id": "cust-new-001", "name": "张三"}
    results = await trigger.on_register(customer, TENANT)
    assert len(results) == 1
    assert results[0]["rewarded"] is True


# ===========================================================================
# 8. 生日触发引擎
# ===========================================================================

@pytest.mark.asyncio
async def test_birthday_trigger(engine, trigger):
    """生日触发"""
    c = await engine.create_campaign(
        "birthday",
        {"name": "生日礼", "reward": {"type": "coupon", "amount_fen": 5000}},
        TENANT,
    )
    await engine.start_campaign(c["campaign_id"], TENANT)

    customer = {"customer_id": "cust-bday", "birthday": "1990-03-27"}
    results = await trigger.on_birthday(customer, TENANT)
    assert len(results) == 1
    assert results[0]["rewarded"] is True


# ===========================================================================
# 9. 定时触发 — 精准营销
# ===========================================================================

@pytest.mark.asyncio
async def test_schedule_trigger(engine, trigger):
    """精准营销定时触发 (每周/每月)"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    weekday = now.isoweekday()

    c = await engine.create_campaign(
        "precision_marketing",
        {
            "name": "每周召回",
            "schedule": {"type": "weekly", "weekdays": [weekday]},
            "target_segments": ["dormant"],
        },
        TENANT,
    )
    await engine.start_campaign(c["campaign_id"], TENANT)

    results = await trigger.on_schedule(TENANT)
    assert len(results) == 1
    assert results[0]["action"] == "send_to_segments"
    assert "dormant" in results[0]["target_segments"]


# ===========================================================================
# 10. 奖励引擎 — 5种奖励类型
# ===========================================================================

@pytest.mark.asyncio
async def test_reward_engine_all_types(reward):
    """5种奖励类型均可发放"""
    configs = [
        {"type": "coupon", "amount_fen": 2000, "validity_days": 14},
        {"type": "points", "points": 500},
        {"type": "stored_value", "amount_fen": 5000},
        {"type": "physical", "gift_name": "长寿面", "cost_fen": 800},
        {"type": "privilege", "privilege_id": "gold_card", "days": 365, "cost_fen": 0},
    ]
    for cfg in configs:
        r = await reward.grant_reward("cust-001", cfg, TENANT)
        assert r["reward_type"] == cfg["type"]
        assert r["status"] == "granted"
        assert r["tenant_id"] == TENANT


# ===========================================================================
# 11. 抽奖概率校验
# ===========================================================================

def test_lottery_probability_validation():
    """抽奖概率总和必须=100%"""
    valid_prizes = [
        {"prize_id": "1", "name": "一等奖", "probability": 5},
        {"prize_id": "2", "name": "二等奖", "probability": 15},
        {"prize_id": "3", "name": "三等奖", "probability": 30},
        {"prize_id": "4", "name": "谢谢参与", "probability": 50, "is_thank_you": True},
    ]
    ok, msg = validate_prizes(valid_prizes)
    assert ok is True

    invalid_prizes = [
        {"prize_id": "1", "name": "一等奖", "probability": 5},
        {"prize_id": "2", "name": "二等奖", "probability": 15},
    ]
    ok, msg = validate_prizes(invalid_prizes)
    assert ok is False
    assert "100%" in msg


def test_lottery_draw():
    """抽奖抽取功能"""
    prizes = [
        {"prize_id": "a", "name": "奖品A", "probability": 50, "stock": -1},
        {"prize_id": "b", "name": "奖品B", "probability": 50, "stock": -1},
    ]
    result = draw_prize(prizes)
    assert result["prize_id"] in ("a", "b")

    # 库存为0的奖品不可抽中
    prizes_no_stock = [
        {"prize_id": "x", "name": "X", "probability": 100, "stock": 0},
    ]
    result = draw_prize(prizes_no_stock)
    assert "error" in result


# ===========================================================================
# 12. 储值套餐多档位匹配
# ===========================================================================

@pytest.mark.asyncio
async def test_stored_value_tiers():
    """储值套餐: 充500送80, 充1000送200"""
    config = {
        "name": "储值套餐",
        "tiers": [
            {"charge_fen": 50000, "bonus_fen": 8000},
            {"charge_fen": 100000, "bonus_fen": 20000},
        ],
    }

    # 充值600元, 匹配500档
    r = await sv_execute("cust-001", config, {"charge_fen": 60000}, TENANT)
    assert r["success"] is True
    assert r["bonus_fen"] == 8000

    # 充值1200元, 匹配1000档
    r = await sv_execute("cust-001", config, {"charge_fen": 120000}, TENANT)
    assert r["success"] is True
    assert r["bonus_fen"] == 20000

    # 充值300元, 不够最低档
    r = await sv_execute("cust-001", config, {"charge_fen": 30000}, TENANT)
    assert r["success"] is False


# ===========================================================================
# 13. 报名抽奖 (报名+开奖)
# ===========================================================================

@pytest.mark.asyncio
async def test_report_draw():
    """报名抽奖: 报名 -> 开奖"""
    config = {
        "name": "报名抽免单",
        "draw_time": "2026-04-01T12:00:00Z",
        "max_participants": 100,
        "prizes": [
            {"prize_id": "p1", "name": "免单", "winner_count": 1, "reward": {"type": "coupon", "amount_fen": 10000}},
            {"prize_id": "p2", "name": "50元券", "winner_count": 2, "reward": {"type": "coupon", "amount_fen": 5000}},
        ],
    }

    # 报名
    for i in range(5):
        r = await report_execute(
            f"cust-{i}", config,
            {"campaign_id": "camp-rpt-1", "action": "report"}, TENANT,
        )
        assert r["success"] is True

    # 重复报名
    r = await report_execute(
        "cust-0", config,
        {"campaign_id": "camp-rpt-1", "action": "report"}, TENANT,
    )
    assert r["success"] is False

    # 开奖
    r = await report_execute(
        "", config,
        {"campaign_id": "camp-rpt-1", "action": "draw"}, TENANT,
    )
    assert r["success"] is True
    assert r["total_participants"] == 5
    assert len(r["winners"]) == 3  # 1 + 2


# ===========================================================================
# 14. 活动效果分析
# ===========================================================================

@pytest.mark.asyncio
async def test_campaign_analytics(engine):
    """活动效果分析"""
    c = await engine.create_campaign(
        "scan_coupon",
        {"name": "扫码领券", "budget_fen": 100000,
         "reward": {"type": "coupon", "amount_fen": 500}},
        TENANT,
    )
    cid = c["campaign_id"]
    await engine.start_campaign(cid, TENANT)

    # 触发3次
    for i in range(3):
        await engine.trigger_reward(f"cust-{i}", cid, {"type": "scan"}, TENANT)

    analytics = await engine.get_campaign_analytics(cid, TENANT)
    assert analytics["participant_count"] == 3
    assert analytics["reward_count"] == 3
    assert analytics["total_cost_fen"] == 1500  # 500 * 3
    assert analytics["budget_usage"] == 0.015  # 1500/100000


# ===========================================================================
# 额外: 签到连续奖励
# ===========================================================================

@pytest.mark.asyncio
async def test_sign_in_streak():
    """签到: 每日积分 + 连续7天奖励"""
    config = {
        "name": "签到有礼",
        "daily_reward": {"type": "points", "points": 10},
        "streak_rewards": [
            {"streak_days": 7, "reward": {"type": "coupon", "amount_fen": 2000}},
        ],
    }

    # 普通签到(第3天)
    r = await sign_in_execute("cust-001", config, {"streak_days": 3}, TENANT)
    assert r["success"] is True
    assert r["has_streak_bonus"] is False
    assert len(r["rewards"]) == 1

    # 第7天签到, 触发连续奖励
    r = await sign_in_execute("cust-001", config, {"streak_days": 7}, TENANT)
    assert r["success"] is True
    assert r["has_streak_bonus"] is True
    assert len(r["rewards"]) == 2


# ===========================================================================
# 额外: 积分兑换
# ===========================================================================

@pytest.mark.asyncio
async def test_points_exchange():
    """积分兑换: 积分足够/不足/商品不存在"""
    config = {
        "name": "积分商城",
        "exchange_items": [
            {"item_id": "d1", "item_name": "甜品", "points_cost": 500, "stock": 10},
        ],
    }

    # 积分不足
    r = await points_execute(
        "cust-001", config,
        {"item_id": "d1", "customer_points": 300}, TENANT,
    )
    assert r["success"] is False

    # 积分足够
    r = await points_execute(
        "cust-001", config,
        {"item_id": "d1", "customer_points": 600}, TENANT,
    )
    assert r["success"] is True
    assert r["remaining_points"] == 100

    # 商品不存在
    r = await points_execute(
        "cust-001", config,
        {"item_id": "d999", "customer_points": 600}, TENANT,
    )
    assert r["success"] is False
