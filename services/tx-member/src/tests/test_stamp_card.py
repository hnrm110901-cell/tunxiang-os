"""集点卡功能测试 — 覆盖核心链路

测试:
1. CONFIG_SCHEMA 结构校验
2. 集点卡模板执行（盖章中/集满完成）
3. 奖励类型校验
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from campaigns.stamp_card import CONFIG_SCHEMA
from campaigns.stamp_card import execute as stamp_card_execute

TENANT = "tenant-test-001"


# ===========================================================================
# 1. CONFIG_SCHEMA 结构校验
# ===========================================================================

def test_config_schema_has_required_fields():
    """集点卡配置 Schema 包含必填字段"""
    required = CONFIG_SCHEMA["required"]
    assert "name" in required
    assert "target_stamps" in required
    assert "reward_config" in required


def test_config_schema_target_stamps_range():
    """target_stamps 范围 [2, 50]"""
    props = CONFIG_SCHEMA["properties"]["target_stamps"]
    assert props["minimum"] == 2
    assert props["maximum"] == 50


def test_config_schema_reward_types():
    """支持4种奖励类型"""
    types = CONFIG_SCHEMA["properties"]["reward_config"]["properties"]["type"]["enum"]
    assert "coupon" in types
    assert "free_item" in types
    assert "points" in types
    assert "stored_value" in types


# ===========================================================================
# 2. 集点卡模板执行 — 盖章中
# ===========================================================================

@pytest.mark.asyncio
async def test_stamp_card_in_progress():
    """盖章中（未集满）"""
    config = {
        "name": "集5杯送1杯",
        "target_stamps": 5,
        "reward_config": {"type": "free_item", "free_item_id": "latte"},
    }
    trigger_event = {
        "instance_id": "inst-001",
        "stamp_count": 3,
        "completed": False,
    }

    result = await stamp_card_execute("cust-001", config, trigger_event, TENANT)
    assert result["success"] is True
    assert result["completed"] is False
    assert result["stamp_count"] == 3
    assert result["target_stamps"] == 5
    assert "reward" not in result


# ===========================================================================
# 3. 集点卡模板执行 — 集满完成
# ===========================================================================

@pytest.mark.asyncio
async def test_stamp_card_completed():
    """集满后触发奖励"""
    config = {
        "name": "集5杯送1杯",
        "target_stamps": 5,
        "reward_config": {
            "type": "coupon",
            "coupon_amount_fen": 3000,
        },
    }
    trigger_event = {
        "instance_id": "inst-002",
        "stamp_count": 5,
        "completed": True,
    }

    result = await stamp_card_execute("cust-001", config, trigger_event, TENANT)
    assert result["success"] is True
    assert result["completed"] is True
    assert result["stamp_count"] == 5
    assert result["reward"]["type"] == "coupon"
    assert result["reward"]["coupon_amount_fen"] == 3000


@pytest.mark.asyncio
async def test_stamp_card_completed_free_item():
    """集满后赠送免费商品"""
    config = {
        "name": "集10次送甜品",
        "target_stamps": 10,
        "reward_config": {
            "type": "free_item",
            "free_item_id": "dessert-001",
        },
    }
    trigger_event = {
        "instance_id": "inst-003",
        "stamp_count": 10,
        "completed": True,
    }

    result = await stamp_card_execute("cust-001", config, trigger_event, TENANT)
    assert result["success"] is True
    assert result["completed"] is True
    assert result["reward"]["type"] == "free_item"
    assert result["reward"]["free_item_id"] == "dessert-001"


# ===========================================================================
# 4. 默认值校验
# ===========================================================================

def test_config_defaults():
    """默认值正确"""
    props = CONFIG_SCHEMA["properties"]
    assert props["validity_days"]["default"] == 90
    assert props["min_order_fen"]["default"] == 0
    assert props["auto_stamp"]["default"] is True
