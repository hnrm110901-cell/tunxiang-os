"""D7 自动派单引擎 + 通知引擎 — 测试套件

覆盖:
  1. 折扣异常 → 派给店长
  2. 出餐超时 → 派给厨师长
  3. 缺货 → 派给采购
  4. 食安 → 派给食安专员+区域经理
  5. 收银异常 → 派给财务
  6. 毛利下降 → 派给店长+区域
  7. SLA 超时自动升级
  8. 派单看板统计
  9. 通知发送(mock)
  10. 通知历史查询
  11. 自定义派单规则
  12. 未知预警类型报错
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ..services.auto_dispatch import (
    SLA_MINUTES,
    _reset_store as reset_dispatch,
    check_sla,
    get_dispatch_dashboard,
    get_dispatch_rules,
    process_agent_alert,
    register_alert_handler,
    set_dispatch_rule,
)
from ..services.notification_engine import (
    _reset_store as reset_notification,
    get_notification_history,
    send_alert_notification,
    send_notification,
)

TENANT = "tenant_test_001"
STORE = "store_001"


@pytest.fixture(autouse=True)
def _clean_stores():
    """每个测试前后清空内存存储。"""
    reset_dispatch()
    reset_notification()
    yield
    reset_dispatch()
    reset_notification()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 折扣异常 → 派给店长
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_discount_anomaly_dispatch():
    """折扣异常应派给 store_manager, severity=severe。"""
    alert = {
        "alert_type": "discount_anomaly",
        "store_id": STORE,
        "source_agent": "discount_guard",
        "summary": "员工张三连续3单折扣>50%",
    }
    result = await process_agent_alert(alert, TENANT, db=None)

    assert result["alert_type"] == "discount_anomaly"
    assert result["assignee_roles"] == ["store_manager"]
    assert result["severity"] == "severe"
    assert result["status"] == "pending"
    assert result["sla_deadline"] is not None
    assert result["task_id"].startswith("task_store_001_")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 出餐超时 → 派给厨师长
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_cooking_timeout_dispatch():
    """出餐超时应派给 head_chef。"""
    alert = {
        "alert_type": "cooking_timeout",
        "store_id": STORE,
        "source_agent": "serve_dispatch",
        "summary": "桌号A3等待超过25分钟",
    }
    result = await process_agent_alert(alert, TENANT, db=None)

    assert result["assignee_roles"] == ["head_chef"]
    assert result["severity"] == "severe"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 缺货 → 派给采购
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_stockout_dispatch():
    """缺货应派给 purchaser, severity=normal。"""
    alert = {
        "alert_type": "stockout",
        "store_id": STORE,
        "source_agent": "inventory_alert",
        "summary": "青椒库存低于安全线",
    }
    result = await process_agent_alert(alert, TENANT, db=None)

    assert result["assignee_roles"] == ["purchaser"]
    assert result["severity"] == "normal"
    assert result["sla_minutes"] == SLA_MINUTES["normal"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 食安 → 派给食安专员+区域经理, severity=urgent
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_food_safety_dispatch():
    """食品安全应派给 food_safety_officer + regional_manager, urgent。"""
    alert = {
        "alert_type": "food_safety",
        "store_id": STORE,
        "source_agent": "store_inspect",
        "summary": "发现过期食材",
    }
    result = await process_agent_alert(alert, TENANT, db=None)

    assert "food_safety_officer" in result["assignee_roles"]
    assert "regional_manager" in result["assignee_roles"]
    assert result["severity"] == "urgent"
    assert result["sla_minutes"] == SLA_MINUTES["urgent"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 收银异常 → 派给财务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_cashier_anomaly_dispatch():
    """收银异常应派给 finance。"""
    alert = {
        "alert_type": "cashier_anomaly",
        "store_id": STORE,
        "source_agent": "cashier_audit",
        "summary": "今日收银差异>100元",
    }
    result = await process_agent_alert(alert, TENANT, db=None)

    assert result["assignee_roles"] == ["finance"]
    assert result["severity"] == "severe"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 毛利下降 → 派给店长+区域
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_margin_drop_dispatch():
    """毛利下降应派给 store_manager + regional_manager。"""
    alert = {
        "alert_type": "margin_drop",
        "store_id": STORE,
        "source_agent": "finance_audit",
        "summary": "毛利率降至45%, 低于阈值50%",
    }
    result = await process_agent_alert(alert, TENANT, db=None)

    assert "store_manager" in result["assignee_roles"]
    assert "regional_manager" in result["assignee_roles"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. SLA 超时自动升级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_sla_timeout_escalation():
    """超时任务应自动升级到上一级角色。"""
    now = datetime.utcnow()

    # 创建一个已超时的任务
    tasks = [
        {
            "task_id": "task_001",
            "tenant_id": TENANT,
            "store_id": STORE,
            "alert_type": "stockout",
            "assignee_roles": ["purchaser"],
            "severity": "normal",
            "sla_deadline": (now - timedelta(minutes=5)).isoformat(),
            "status": "pending",
            "escalated": False,
            "escalation_history": [],
        },
        {
            "task_id": "task_002",
            "tenant_id": TENANT,
            "store_id": STORE,
            "alert_type": "discount_anomaly",
            "assignee_roles": ["store_manager"],
            "severity": "severe",
            "sla_deadline": (now + timedelta(minutes=10)).isoformat(),
            "status": "pending",
            "escalated": False,
            "escalation_history": [],
        },
    ]

    result = await check_sla(TENANT, db=None, now=now, tasks=tasks)

    assert result["checked"] == 2
    assert "task_001" in result["escalated"]
    assert "task_002" in result["ok"]

    # 验证 task_001 已升级
    assert tasks[0]["status"] == "escalated"
    assert tasks[0]["escalated"] is True
    # purchaser 升级到 store_manager
    assert "store_manager" in tasks[0]["assignee_roles"]
    assert len(tasks[0]["escalation_history"]) == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 派单看板统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_dispatch_dashboard():
    """看板应正确归类: pending/in_progress/overdue/resolved。"""
    now = datetime.utcnow()

    tasks = [
        {
            "task_id": "t1",
            "tenant_id": TENANT,
            "store_id": STORE,
            "status": "pending",
            "sla_deadline": (now + timedelta(minutes=10)).isoformat(),
        },
        {
            "task_id": "t2",
            "tenant_id": TENANT,
            "store_id": STORE,
            "status": "in_progress",
            "sla_deadline": (now + timedelta(minutes=20)).isoformat(),
        },
        {
            "task_id": "t3",
            "tenant_id": TENANT,
            "store_id": STORE,
            "status": "pending",
            "sla_deadline": (now - timedelta(minutes=5)).isoformat(),
        },
        {
            "task_id": "t4",
            "tenant_id": TENANT,
            "store_id": STORE,
            "status": "resolved",
            "sla_deadline": (now - timedelta(hours=1)).isoformat(),
        },
    ]

    result = await get_dispatch_dashboard(
        STORE, TENANT, db=None, now=now, tasks=tasks,
    )

    assert result["summary"]["pending"] == 1
    assert result["summary"]["in_progress"] == 1
    assert result["summary"]["overdue"] == 1
    assert result["summary"]["resolved"] == 1
    assert result["summary"]["total"] == 4


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. 通知发送(mock)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_send_notification():
    """mock 通知应返回 sent 状态。"""
    result = await send_notification(
        recipient_id="user_001",
        channel="wecom",
        title="测试通知",
        content="这是一条测试消息",
        tenant_id=TENANT,
        db=None,
    )

    assert result["status"] == "sent"
    assert result["channel"] == "wecom"
    assert result["recipient_id"] == "user_001"
    assert result["notification_id"].startswith("notif_")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  10. 批量通知 + 历史查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_alert_notification_and_history():
    """批量通知应发送给所有指派人, 历史可查询。"""
    alert = {
        "alert_type": "food_safety",
        "store_id": STORE,
        "summary": "发现过期食材",
        "severity": "urgent",
        "task_id": "task_fs_001",
    }
    assignees = [
        {"id": "officer_001", "name": "食安专员", "role": "food_safety_officer"},
        {"id": "rm_001", "name": "区域经理", "role": "regional_manager"},
    ]

    result = await send_alert_notification(
        alert=alert,
        assignees=assignees,
        tenant_id=TENANT,
        db=None,
        channels=["in_app"],
    )

    # 2 个指派人 x 1 个渠道 = 2 条通知
    assert result["total_notifications"] == 2
    assert result["alert_type"] == "food_safety"

    # 查询历史
    history = await get_notification_history(
        recipient_id="officer_001",
        tenant_id=TENANT,
        db=None,
    )
    assert history["total"] == 1
    assert history["items"][0]["recipient_id"] == "officer_001"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  11. 自定义派单规则
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_custom_dispatch_rule():
    """设置自定义规则后, 该规则应覆盖默认规则。"""
    await set_dispatch_rule(
        alert_type="stockout",
        assignee_role="store_manager",
        escalation_minutes=10,
        tenant_id=TENANT,
        db=None,
    )

    rules = await get_dispatch_rules(TENANT, db=None)
    assert "stockout" in rules["rules"]
    assert rules["rules"]["stockout"]["assignee_roles"] == ["store_manager"]

    # 使用自定义规则处理预警
    alert = {
        "alert_type": "stockout",
        "store_id": STORE,
        "source_agent": "inventory_alert",
        "summary": "青椒库存低于安全线",
    }
    result = await process_agent_alert(alert, TENANT, db=None)

    # 应使用自定义规则: store_manager 而非默认的 purchaser
    assert result["assignee_roles"] == ["store_manager"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  12. 未知预警类型报错
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_unknown_alert_type_raises():
    """未知的预警类型应抛出 ValueError。"""
    alert = {
        "alert_type": "unknown_type_xyz",
        "store_id": STORE,
        "source_agent": "test",
        "summary": "测试",
    }
    with pytest.raises(ValueError, match="Unknown alert_type"):
        await process_agent_alert(alert, TENANT, db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  13. 无效通知渠道报错
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_invalid_notification_channel():
    """无效的通知渠道应抛出 ValueError。"""
    with pytest.raises(ValueError, match="Invalid channel"):
        await send_notification(
            recipient_id="user_001",
            channel="telegram",
            title="测试",
            content="测试",
            tenant_id=TENANT,
            db=None,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  14. 注册自定义 alert handler
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_register_custom_alert_handler():
    """注册自定义预警处理器后应可正常派单。"""
    register_alert_handler("equipment_failure", {
        "assignee_roles": ["maintenance"],
        "severity": "severe",
        "issue_type": "equipment",
        "description_template": "设备故障: {summary}",
    })

    alert = {
        "alert_type": "equipment_failure",
        "store_id": STORE,
        "source_agent": "iot_monitor",
        "summary": "冰柜温度异常升至10度",
    }
    result = await process_agent_alert(alert, TENANT, db=None)

    assert result["assignee_roles"] == ["maintenance"]
    assert result["severity"] == "severe"
    assert "设备故障" in result["description"]
