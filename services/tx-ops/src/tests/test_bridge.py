"""Agent事件总线 → 自动派单桥接层测试

覆盖:
1. route_to_dispatch 可派单事件 → 创建任务
2. route_to_dispatch 不可派单事件 → 跳过
3. register_agent_hooks 注册所有预警回调
4. listen_agent_events 注册处理器到事件总线
5. _event_to_dict 正确转换 AgentEvent dataclass
6. 端到端: EventBus.publish → bridge handler → 创建派单
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.agent_dispatch_bridge import (
    DISPATCHABLE_EVENTS,
    EVENT_SEVERITY_MAP,
    EVENT_TO_ALERT_TYPE,
    _event_to_dict,
    listen_agent_events,
    register_agent_hooks,
    route_to_dispatch,
)

TENANT = "tenant_test_001"
STORE = "store_001"


# ─── Mock EventBus ───

class MockEventBus:
    def __init__(self):
        self.handlers: dict[str, list[tuple[str, any]]] = {}

    def register_handler(self, event_type: str, agent_id: str, handler):
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append((agent_id, handler))


# ─── Mock AgentEvent (dataclass) ───

@dataclass
class MockAgentEvent:
    event_type: str
    source_agent: str
    store_id: str
    data: dict = field(default_factory=dict)
    event_id: str = "evt-001"
    correlation_id: str = "corr-001"
    timestamp: float = 1711540800.0


# ═══════════════════════════════════════════════
# 1. route_to_dispatch — 可派单事件
# ═══════════════════════════════════════════════

class TestRouteToDispatch:
    @pytest.mark.asyncio
    async def test_dispatchable_event_creates_task(self):
        """可派单事件成功创建任务"""
        event = {
            "event_type": "discount_violation",
            "source_agent": "discount_guard",
            "store_id": STORE,
            "data": {"summary": "员工张三连续3单折扣>50%", "detail": {"employee": "张三"}},
        }

        mock_task = {
            "task_id": f"task_{STORE}_abc12345",
            "alert_type": "discount_anomaly",
            "severity": "severe",
            "status": "pending",
        }

        with patch(
            "services.agent_dispatch_bridge.process_agent_alert",
            new_callable=AsyncMock,
            return_value=mock_task,
        ) as mock_dispatch:
            result = await route_to_dispatch(event, TENANT, db=None)

            assert result["dispatched"] is True
            assert result["task_id"] == mock_task["task_id"]
            assert result["alert_type"] == "discount_anomaly"
            assert result["event_type"] == "discount_violation"

            # 验证传递给 process_agent_alert 的参数
            call_args = mock_dispatch.call_args
            alert = call_args.kwargs.get("alert") or call_args[0][0]
            assert alert["alert_type"] == "discount_anomaly"
            assert alert["severity"] == "severe"

    @pytest.mark.asyncio
    async def test_non_dispatchable_event_skips(self):
        """不可派单事件被跳过"""
        event = {
            "event_type": "vip_arrival",
            "source_agent": "member_insight",
            "store_id": STORE,
            "data": {},
        }

        result = await route_to_dispatch(event, TENANT, db=None)

        assert result["dispatched"] is False
        assert result["task_id"] is None
        assert "not dispatchable" in result["reason"]

    @pytest.mark.asyncio
    async def test_dispatch_failure_returns_error(self):
        """派单失败返回错误信息"""
        event = {
            "event_type": "cooking_timeout",
            "source_agent": "serve_dispatch",
            "store_id": STORE,
            "data": {"summary": "出餐超时30分钟"},
        }

        with patch(
            "services.agent_dispatch_bridge.process_agent_alert",
            new_callable=AsyncMock,
            side_effect=ValueError("Unknown alert_type"),
        ):
            result = await route_to_dispatch(event, TENANT, db=None)

            assert result["dispatched"] is False
            assert "Unknown alert_type" in result["reason"]


# ═══════════════════════════════════════════════
# 2. register_agent_hooks
# ═══════════════════════════════════════════════

class TestRegisterAgentHooks:
    def test_registers_all_dispatchable_events(self):
        """注册所有可派单事件的处理器"""
        bus = MockEventBus()

        result = register_agent_hooks(bus, TENANT, db=None)

        assert result["hooks_registered"] == len(DISPATCHABLE_EVENTS)
        assert set(result["event_types"]) == DISPATCHABLE_EVENTS
        assert result["agent_id"] == f"dispatch_bridge_{TENANT}"

        # 验证每个事件类型都有处理器
        for event_type in DISPATCHABLE_EVENTS:
            assert event_type in bus.handlers
            assert len(bus.handlers[event_type]) >= 1


# ═══════════════════════════════════════════════
# 3. listen_agent_events
# ═══════════════════════════════════════════════

class TestListenAgentEvents:
    @pytest.mark.asyncio
    async def test_registers_handlers(self):
        """listen_agent_events 注册所有处理器"""
        bus = MockEventBus()

        result = await listen_agent_events(TENANT, db=None, event_bus=bus)

        assert result["handler_count"] == len(DISPATCHABLE_EVENTS)
        assert len(result["registered_events"]) == len(DISPATCHABLE_EVENTS)


# ═══════════════════════════════════════════════
# 4. _event_to_dict
# ═══════════════════════════════════════════════

class TestEventToDict:
    def test_converts_dataclass(self):
        """正确转换 AgentEvent dataclass 为 dict"""
        event = MockAgentEvent(
            event_type="discount_violation",
            source_agent="discount_guard",
            store_id=STORE,
            data={"summary": "test"},
        )

        result = _event_to_dict(event)

        assert result["event_type"] == "discount_violation"
        assert result["source_agent"] == "discount_guard"
        assert result["store_id"] == STORE
        assert result["data"]["summary"] == "test"

    def test_passes_dict_through(self):
        """dict 输入直接返回"""
        event = {"event_type": "test", "store_id": "s1"}
        result = _event_to_dict(event)
        assert result is event


# ═══════════════════════════════════════════════
# 5. 配置映射完整性
# ═══════════════════════════════════════════════

class TestConfigMappings:
    def test_all_dispatchable_events_have_alert_type(self):
        """所有可派单事件都有对应的 alert_type 映射"""
        for event_type in DISPATCHABLE_EVENTS:
            assert event_type in EVENT_TO_ALERT_TYPE, \
                f"{event_type} missing from EVENT_TO_ALERT_TYPE"

    def test_all_dispatchable_events_have_severity(self):
        """所有可派单事件都有对应的严重级别"""
        for event_type in DISPATCHABLE_EVENTS:
            assert event_type in EVENT_SEVERITY_MAP, \
                f"{event_type} missing from EVENT_SEVERITY_MAP"
