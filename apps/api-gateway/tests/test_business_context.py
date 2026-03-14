"""
BusinessContext 单元测试

覆盖：
  - 序列化/反序列化无损往返
  - 面包屑累积
  - 从 AgentMessage 提取上下文
  - Redis mock 存取
  - lifecycle_bridge 无 ctx 时向后兼容
"""
import os

for _k, _v in {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.business_context import (
    BusinessContext,
    BusinessContextStore,
)


class TestBusinessContextSerialization:
    """to_dict/from_dict 无损往返。"""

    def test_roundtrip_basic(self):
        ctx = BusinessContext(
            store_id="S001",
            actor_id="user_123",
            actor_role="store_manager",
            customer_id="C456",
            trigger="reservation.arrived",
            source_event_id="EVT_001",
        )
        ctx.add_breadcrumb("reservation:R001")
        ctx.accumulate("party_size", 8)

        d = ctx.to_dict()
        ctx2 = BusinessContext.from_dict(d)

        assert ctx2.store_id == "S001"
        assert ctx2.actor_id == "user_123"
        assert ctx2.actor_role == "store_manager"
        assert ctx2.customer_id == "C456"
        assert ctx2.trigger == "reservation.arrived"
        assert ctx2.source_event_id == "EVT_001"
        assert ctx2.trace_id == ctx.trace_id
        assert ctx2.created_at == ctx.created_at
        assert ctx2.breadcrumbs == ["reservation:R001"]
        assert ctx2.accumulated_data == {"party_size": 8}

    def test_roundtrip_empty(self):
        ctx = BusinessContext()
        d = ctx.to_dict()
        ctx2 = BusinessContext.from_dict(d)
        assert ctx2.store_id == ""
        assert ctx2.breadcrumbs == []
        assert ctx2.accumulated_data == {}

    def test_roundtrip_preserves_trace_id(self):
        ctx = BusinessContext(store_id="S001")
        d = ctx.to_dict()
        ctx2 = BusinessContext.from_dict(d)
        assert ctx2.trace_id == ctx.trace_id


class TestBreadcrumbAccumulation:
    """链式 add_breadcrumb。"""

    def test_chain(self):
        ctx = BusinessContext(store_id="S001")
        ctx.add_breadcrumb("reservation:R001")
        ctx.add_breadcrumb("order:O001")
        ctx.add_breadcrumb("cdp:C001")

        assert len(ctx.breadcrumbs) == 3
        assert ctx.breadcrumbs[0] == "reservation:R001"
        assert ctx.breadcrumbs[2] == "cdp:C001"

    def test_fluent_api(self):
        ctx = (
            BusinessContext(store_id="S001")
            .add_breadcrumb("a")
            .add_breadcrumb("b")
            .accumulate("key", "value")
        )
        assert len(ctx.breadcrumbs) == 2
        assert ctx.accumulated_data["key"] == "value"

    def test_child_inherits_breadcrumbs(self):
        parent = BusinessContext(store_id="S001", trigger="reservation.arrived")
        parent.add_breadcrumb("reservation:R001")

        child = parent.child("order.created")
        assert child.trigger == "order.created"
        assert child.breadcrumbs == ["reservation:R001"]
        assert child.trace_id == parent.trace_id
        assert child.parent_context_id == parent.trace_id

        # 修改子级不影响父级
        child.add_breadcrumb("order:O001")
        assert len(parent.breadcrumbs) == 1
        assert len(child.breadcrumbs) == 2


class TestFromAgentMessage:
    """从 AgentMessage 提取 context。"""

    def test_from_message_with_context(self):
        msg = MagicMock()
        msg.context = {
            "store_id": "S001",
            "actor_id": "agent:ops",
            "trigger": "revenue_anomaly",
            "trace_id": "trace-abc",
            "breadcrumbs": ["step1"],
        }
        msg.trace_id = "trace-abc"

        ctx = BusinessContext.from_agent_message(msg)
        assert ctx.store_id == "S001"
        assert ctx.actor_id == "agent:ops"
        assert ctx.trace_id == "trace-abc"
        assert ctx.breadcrumbs == ["step1"]

    def test_from_message_without_context(self):
        msg = MagicMock()
        msg.context = None
        msg.store_id = "S002"
        msg.from_agent = "schedule"
        msg.action = "query_staff_availability"
        msg.trace_id = "trace-xyz"

        ctx = BusinessContext.from_agent_message(msg)
        assert ctx.store_id == "S002"
        assert ctx.actor_role == "agent:schedule"
        assert ctx.trigger == "query_staff_availability"
        assert ctx.trace_id == "trace-xyz"


class TestBusinessContextStore:
    """Redis mock 存取。"""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.get = AsyncMock()

        store = BusinessContextStore(mock_redis)
        ctx = BusinessContext(store_id="S001", trigger="test")
        ctx.add_breadcrumb("test:1")

        # save
        await store.save(ctx)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert f"biz_ctx:{ctx.trace_id}" == call_args[0][0]

        # load — 模拟返回保存的数据
        import json
        mock_redis.get = AsyncMock(return_value=json.dumps(ctx.to_dict()))
        loaded = await store.load(ctx.trace_id)

        assert loaded is not None
        assert loaded.store_id == "S001"
        assert loaded.breadcrumbs == ["test:1"]

    @pytest.mark.asyncio
    async def test_load_nonexistent(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        store = BusinessContextStore(mock_redis)

        result = await store.load("nonexistent-trace-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_graceful_degradation(self):
        store = BusinessContextStore(None)
        ctx = BusinessContext(store_id="S001")

        # 不抛异常
        await store.save(ctx)
        result = await store.load("any-id")
        assert result is None


class TestBackwardCompatibleBridge:
    """lifecycle_bridge 无 ctx 时正常工作。"""

    def test_bridge_function_accepts_no_ctx(self):
        """验证桥接函数签名接受无 ctx 参数。"""
        import inspect
        from src.services.lifecycle_bridge import (
            prepare_order_from_reservation,
            sync_order_completion_to_reservation,
            trigger_procurement_from_beo,
            on_order_completed,
            check_active_journeys_on_reservation,
        )

        for fn in [
            prepare_order_from_reservation,
            sync_order_completion_to_reservation,
            trigger_procurement_from_beo,
            on_order_completed,
            check_active_journeys_on_reservation,
        ]:
            sig = inspect.signature(fn)
            assert "ctx" in sig.parameters, f"{fn.__name__} missing ctx param"
            param = sig.parameters["ctx"]
            assert param.default is None, f"{fn.__name__} ctx should default to None"
