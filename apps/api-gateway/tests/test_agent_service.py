"""
测试Agent服务
"""
import os
for _k, _v in {
    "DATABASE_URL":          "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL":             "redis://localhost:6379/0",
    "CELERY_BROKER_URL":     "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY":            "test-secret-key",
    "JWT_SECRET":            "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
from unittest.mock import AsyncMock, patch
from src.services.agent_service import AgentService


class TestAgentService:
    """测试AgentService类"""

    @pytest.fixture
    def agent_service(self):
        """创建AgentService实例"""
        return AgentService()

    @pytest.mark.unit
    async def test_execute_schedule_agent(self, agent_service, sample_schedule_data):
        """测试执行排班Agent"""
        input_data = {
            "action": "run",
            **sample_schedule_data,
        }

        result = await agent_service.execute_agent("schedule", input_data)

        assert result is not None
        assert "execution_time" in result
        assert isinstance(result["execution_time"], (int, float))

    @pytest.mark.unit
    async def test_execute_order_agent(self, agent_service, sample_order_data):
        """测试执行订单Agent"""
        input_data = {
            "action": "process",
            "order_id": "ORD_001",
            "order_data": sample_order_data,
        }

        result = await agent_service.execute_agent("order", input_data)

        assert result is not None
        assert "execution_time" in result

    @pytest.mark.unit
    async def test_execute_inventory_agent(self, agent_service, sample_inventory_data):
        """测试执行库存Agent"""
        input_data = {
            "action": "check",
            "store_id": "store_001",
            "items": ["大米", "食用油"],
        }

        result = await agent_service.execute_agent("inventory", input_data)

        assert result is not None
        assert "execution_time" in result

    @pytest.mark.unit
    async def test_execute_invalid_agent(self, agent_service):
        """测试执行不存在的Agent"""
        result = await agent_service.execute_agent("invalid_agent", {"action": "test"})

        assert result is not None
        assert result["success"] is False
        assert "未知的Agent类型" in result["error"]

    @pytest.mark.unit
    async def test_execute_agent_with_empty_data(self, agent_service):
        """测试使用空数据执行Agent"""
        result = await agent_service.execute_agent("schedule", {"action": "run"})

        assert result is not None
        # Agent应该能处理空数据或返回错误

    @pytest.mark.unit
    async def test_agent_execution_time(self, agent_service, sample_schedule_data):
        """测试Agent执行时间记录"""
        input_data = {
            "action": "run",
            **sample_schedule_data,
        }

        result = await agent_service.execute_agent("schedule", input_data)

        assert "execution_time" in result
        assert result["execution_time"] >= 0
        assert result["execution_time"] < 10  # 应该在10秒内完成

    @pytest.mark.unit
    async def test_multiple_agent_executions(self, agent_service, sample_schedule_data):
        """测试多次执行Agent"""
        input_data = {
            "action": "run",
            **sample_schedule_data,
        }

        # 执行多次
        results = []
        for _ in range(3):
            result = await agent_service.execute_agent("schedule", input_data)
            results.append(result)

        # 所有执行都应该成功
        assert len(results) == 3
        for result in results:
            assert result is not None
            assert "execution_time" in result

    @pytest.mark.unit
    async def test_service_agent(self, agent_service):
        """测试服务质量Agent"""
        input_data = {
            "action": "analyze",
            "store_id": "store_001",
            "feedback_data": {
                "rating": 4.5,
                "comments": ["服务很好", "菜品美味"],
            },
        }

        result = await agent_service.execute_agent("service", input_data)

        assert result is not None
        assert "execution_time" in result

    @pytest.mark.unit
    async def test_training_agent(self, agent_service):
        """测试培训Agent"""
        input_data = {
            "action": "assess",
            "store_id": "store_001",
            "employee_id": "emp_001",
        }

        result = await agent_service.execute_agent("training", input_data)

        assert result is not None
        assert "execution_time" in result

    @pytest.mark.unit
    async def test_decision_agent(self, agent_service):
        """测试决策Agent"""
        input_data = {
            "action": "analyze",
            "store_id": "store_001",
            "date_range": {
                "start": "2024-02-01",
                "end": "2024-02-28",
            },
        }

        result = await agent_service.execute_agent("decision", input_data)

        assert result is not None
        assert "execution_time" in result

    @pytest.mark.unit
    async def test_reservation_agent(self, agent_service):
        """测试预订Agent"""
        input_data = {
            "action": "create",
            "store_id": "store_001",
            "reservation_data": {
                "customer_name": "张三",
                "phone": "13800138000",
                "date": "2024-02-25",
                "time": "18:00",
                "party_size": 4,
            },
        }

        result = await agent_service.execute_agent("reservation", input_data)

        assert result is not None
        assert "execution_time" in result

    @pytest.mark.unit
    async def test_service_agent_uses_store_id_in_params(self):
        """service agent 应按 params.store_id 构造服务实例"""
        with patch.object(AgentService, "_initialize_agents", return_value=None):
            svc = AgentService()
            svc._agents = {"service": object()}

        mock_instance = AsyncMock()
        mock_instance.get_service_quality_metrics.return_value = {"quality_score": 92}

        with patch("src.services.service_service.ServiceQualityService", return_value=mock_instance) as mock_cls:
            result = await svc.execute_agent("service", {
                "action": "get_service_quality_metrics",
                "params": {"store_id": "S999", "start_date": "2026-03-01", "end_date": "2026-03-08"},
            })

        mock_cls.assert_called_once_with(store_id="S999")
        mock_instance.get_service_quality_metrics.assert_awaited_once()
        assert result["success"] is True
        assert result["data"]["quality_score"] == 92

    @pytest.mark.unit
    async def test_training_agent_uses_store_id_in_params(self):
        """training agent 应按 params.store_id 构造服务实例"""
        with patch.object(AgentService, "_initialize_agents", return_value=None):
            svc = AgentService()
            svc._agents = {"training": object()}

        mock_instance = AsyncMock()
        mock_instance.get_training_statistics.return_value = {"total_trainings": 12}

        with patch("src.services.training_service.TrainingService", return_value=mock_instance) as mock_cls:
            result = await svc.execute_agent("training", {
                "action": "get_training_statistics",
                "params": {"store_id": "S888", "start_date": "2026-03-01", "end_date": "2026-03-08"},
            })

        mock_cls.assert_called_once_with(store_id="S888")
        mock_instance.get_training_statistics.assert_awaited_once()
        assert result["success"] is True
        assert result["data"]["total_trainings"] == 12
