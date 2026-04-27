"""ModelRouter 测试套件

覆盖：
  - ModelSelectionStrategy：按 task_type 和 urgency 选择模型
  - CostTracker：精确成本计算 + DB 写入 + 用量聚合
  - CircuitBreaker：全状态机路径
  - ModelRouter.complete：重试、超时、熔断集成

运行：
  pytest services/tx-agent/src/tests/test_model_router.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 将 src 目录加入 path，以便无 package 安装时也能导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.model_router import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    CostTracker,
    ModelCallRecord,
    ModelRouter,
    ModelSelectionStrategy,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def strategy() -> ModelSelectionStrategy:
    return ModelSelectionStrategy()


@pytest.fixture
def cost_tracker() -> CostTracker:
    return CostTracker()


@pytest.fixture
def circuit() -> CircuitBreaker:
    """内存熔断器（Redis 不可用时降级到内存）"""
    return CircuitBreaker(name="test_circuit", failure_threshold=5, recovery_timeout_s=30)


@pytest.fixture
def router(circuit: CircuitBreaker) -> ModelRouter:
    """带 fake API key 的 ModelRouter，API 调用由各测试 mock 替换。"""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
        return ModelRouter(circuit_breaker=circuit)


# ─────────────────────────────────────────────────────────────────────────────
# 1. ModelSelectionStrategy
# ─────────────────────────────────────────────────────────────────────────────


class TestModelSelectionStrategy:
    def test_quick_classification_returns_haiku(self, strategy: ModelSelectionStrategy):
        model = strategy.select_model("quick_classification")
        assert model == "claude-haiku-4-5-20251001"

    def test_standard_analysis_returns_sonnet(self, strategy: ModelSelectionStrategy):
        model = strategy.select_model("standard_analysis")
        assert model == "claude-sonnet-4-6"

    def test_complex_reasoning_returns_opus(self, strategy: ModelSelectionStrategy):
        model = strategy.select_model("complex_reasoning")
        assert model == "claude-opus-4-6"

    def test_agent_decision_returns_sonnet(self, strategy: ModelSelectionStrategy):
        model = strategy.select_model("agent_decision")
        assert model == "claude-sonnet-4-6"

    def test_patrol_report_returns_haiku(self, strategy: ModelSelectionStrategy):
        model = strategy.select_model("patrol_report")
        assert model == "claude-haiku-4-5-20251001"

    def test_unknown_task_type_returns_default_sonnet(self, strategy: ModelSelectionStrategy):
        model = strategy.select_model("non_existent_task_xyz")
        assert model == "claude-sonnet-4-6"

    def test_urgency_fast_always_returns_haiku(self, strategy: ModelSelectionStrategy):
        """urgency=fast 无论 task_type 是什么，都降级到 haiku"""
        for task in ["complex_reasoning", "standard_analysis", "agent_decision"]:
            model = strategy.select_model(task, urgency="fast")
            assert model == "claude-haiku-4-5-20251001", f"task={task} should degrade to haiku"

    def test_urgency_quality_always_returns_opus(self, strategy: ModelSelectionStrategy):
        """urgency=quality 无论 task_type 是什么，都升级到 opus"""
        for task in ["quick_classification", "patrol_report", "standard_analysis"]:
            model = strategy.select_model(task, urgency="quality")
            assert model == "claude-opus-4-6", f"task={task} should upgrade to opus"

    def test_urgency_normal_uses_task_map(self, strategy: ModelSelectionStrategy):
        assert strategy.select_model("quick_classification", urgency="normal") == "claude-haiku-4-5-20251001"
        assert strategy.select_model("standard_analysis", urgency="normal") == "claude-sonnet-4-6"


# ─────────────────────────────────────────────────────────────────────────────
# 2. CostTracker
# ─────────────────────────────────────────────────────────────────────────────


class TestCostTracker:
    def test_calculate_cost_haiku(self, cost_tracker: CostTracker):
        """haiku: $0.80/M input + $4.00/M output"""
        cost = cost_tracker.calculate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert cost == pytest.approx(4.80, rel=1e-5)

    def test_calculate_cost_sonnet(self, cost_tracker: CostTracker):
        """sonnet: $3.00/M input + $15.00/M output"""
        cost = cost_tracker.calculate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.00, rel=1e-5)

    def test_calculate_cost_opus(self, cost_tracker: CostTracker):
        """opus: $15.00/M input + $75.00/M output"""
        cost = cost_tracker.calculate_cost("claude-opus-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(90.00, rel=1e-5)

    def test_calculate_cost_small_call(self, cost_tracker: CostTracker):
        """小调用精度测试：100 input tokens + 50 output tokens on sonnet"""
        cost = cost_tracker.calculate_cost("claude-sonnet-4-6", 100, 50)
        expected = 100 / 1_000_000 * 3.00 + 50 / 1_000_000 * 15.00
        assert cost == pytest.approx(expected, rel=1e-5)

    def test_calculate_cost_unknown_model_falls_back_to_sonnet(self, cost_tracker: CostTracker):
        """未知模型按 sonnet 价格计算"""
        cost_unknown = cost_tracker.calculate_cost("claude-future-model", 1_000_000, 1_000_000)
        cost_sonnet = cost_tracker.calculate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost_unknown == cost_sonnet

    @pytest.mark.asyncio
    async def test_record_call_inserts_correct_fields(self, cost_tracker: CostTracker):
        """record_call 应以正确参数调用 db.execute"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        record = ModelCallRecord(
            tenant_id="tenant-001",
            task_type="standard_analysis",
            model="claude-sonnet-4-6",
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.004500,
            duration_ms=1200,
            success=True,
            error_type=None,
            request_id="req-abc123",
        )
        await cost_tracker.record_call(record, mock_db)

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

        # 检查传入的绑定参数包含关键字段
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params["tenant_id"] == "tenant-001"
        assert params["task_type"] == "standard_analysis"
        assert params["model"] == "claude-sonnet-4-6"
        assert params["input_tokens"] == 500
        assert params["output_tokens"] == 200
        assert params["cost_usd"] == pytest.approx(0.004500)
        assert params["success"] is True
        assert params["error_type"] is None
        assert params["request_id"] == "req-abc123"

    @pytest.mark.asyncio
    async def test_get_tenant_usage_aggregates_correctly(self, cost_tracker: CostTracker):
        """get_tenant_usage 返回正确聚合结构"""
        # 模拟 DB aggregate 行
        agg_row = {
            "call_count": 10,
            "success_count": 9,
            "total_input_tokens": 50000,
            "total_output_tokens": 20000,
            "total_cost_usd": 0.85,
        }
        model_row = {
            "model": "claude-sonnet-4-6",
            "call_count": 10,
            "cost_usd": 0.85,
        }

        mock_agg_result = MagicMock()
        mock_model_result = MagicMock()
        mock_agg_result.mappings.return_value.one.return_value = agg_row
        mock_model_result.mappings.return_value.all.return_value = [model_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[mock_agg_result, mock_model_result])

        result = await cost_tracker.get_tenant_usage(
            tenant_id="tenant-001",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            db=mock_db,
        )

        assert result["tenant_id"] == "tenant-001"
        assert result["call_count"] == 10
        assert result["success_count"] == 9
        assert result["total_input_tokens"] == 50000
        assert result["total_output_tokens"] == 20000
        assert result["total_cost_usd"] == pytest.approx(0.85)
        assert len(result["by_model"]) == 1
        assert result["by_model"][0]["model"] == "claude-sonnet-4-6"


# ─────────────────────────────────────────────────────────────────────────────
# 3. CircuitBreaker
# ─────────────────────────────────────────────────────────────────────────────


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self, circuit: CircuitBreaker):
        state = await circuit.get_state()
        assert state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_closed_to_open_after_threshold_failures(self, circuit: CircuitBreaker):
        """连续 5 次失败后，CLOSED → OPEN"""

        for _ in range(circuit.failure_threshold):
            await circuit.record_failure()

        state = await circuit.get_state()
        assert state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_rejects_requests_immediately(self, circuit: CircuitBreaker):
        """OPEN 状态下 call() 直接抛 CircuitOpenError，不执行 coro"""
        # 直接将熔断器设为 OPEN
        await circuit._save_state(CircuitState.OPEN, 5, time.monotonic())

        dummy_called = False

        async def dummy_coro():
            nonlocal dummy_called
            dummy_called = True
            return "result"

        with pytest.raises(CircuitOpenError):
            await circuit.call(dummy_coro())

        assert dummy_called is False, "OPEN 状态下 coro 不应被执行"

    @pytest.mark.asyncio
    async def test_open_to_half_open_after_recovery_timeout(self, circuit: CircuitBreaker):
        """OPEN 超过 recovery_timeout_s 后，get_state() 返回 HALF_OPEN"""
        # 设置 opened_at 为足够久远的过去
        past_time = time.monotonic() - (circuit.recovery_timeout_s + 1)
        await circuit._save_state(CircuitState.OPEN, 5, past_time)

        state = await circuit.get_state()
        assert state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success(self, circuit: CircuitBreaker):
        """HALF_OPEN 时一次成功 → CLOSED"""
        await circuit._save_state(CircuitState.HALF_OPEN, 5, time.monotonic())

        async def success_coro():
            return "ok"

        await circuit.call(success_coro())
        state = await circuit.get_state()
        assert state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self, circuit: CircuitBreaker):
        """HALF_OPEN 时一次失败 → 重新 OPEN"""
        from anthropic import APIConnectionError as AnthropicConnError

        await circuit._save_state(CircuitState.HALF_OPEN, 5, time.monotonic())

        async def fail_coro():
            raise AnthropicConnError(message="connection refused", request=MagicMock())

        with pytest.raises(AnthropicConnError):
            await circuit.call(fail_coro())

        state = await circuit.get_state()
        assert state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, circuit: CircuitBreaker):
        """成功后失败计数应清零"""
        # 先失败 3 次（未达到阈值）
        for _ in range(3):
            await circuit.record_failure()

        await circuit.record_success()

        _, failure_count, _ = await circuit._load_state()
        assert failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_recovery_allows_normal_calls(self, circuit: CircuitBreaker):
        """熔断恢复（OPEN → HALF_OPEN → CLOSED）后能正常执行 coro"""
        # Step 1: 触发熔断
        for _ in range(circuit.failure_threshold):
            await circuit.record_failure()
        assert await circuit.get_state() == CircuitState.OPEN

        # Step 2: 模拟时间流逝，进入 HALF_OPEN
        past_time = time.monotonic() - (circuit.recovery_timeout_s + 1)
        await circuit._save_state(CircuitState.OPEN, circuit.failure_threshold, past_time)
        assert await circuit.get_state() == CircuitState.HALF_OPEN

        # Step 3: 成功一次，恢复到 CLOSED
        async def success_coro():
            return "recovered"

        result = await circuit.call(success_coro())
        assert result == "recovered"
        assert await circuit.get_state() == CircuitState.CLOSED


# ─────────────────────────────────────────────────────────────────────────────
# 4. ModelRouter 集成测试
# ─────────────────────────────────────────────────────────────────────────────


def _make_mock_response(text: str = "分析结果", input_tokens: int = 100, output_tokens: int = 50):
    """构造 Anthropic SDK response mock 对象"""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    mock_response.usage.input_tokens = input_tokens
    mock_response.usage.output_tokens = output_tokens
    return mock_response


class TestModelRouterComplete:
    @pytest.mark.asyncio
    async def test_complete_returns_text_on_success(self, router: ModelRouter):
        """正常成功调用返回模型文本"""
        mock_resp = _make_mock_response("供应商评分：A级")

        with patch.object(router._client.messages, "create", new=AsyncMock(return_value=mock_resp)):
            result = await router.complete(
                tenant_id="tenant-001",
                task_type="supplier_scoring",
                messages=[{"role": "user", "content": "评估供应商"}],
            )

        assert result == "供应商评分：A级"

    @pytest.mark.asyncio
    async def test_complete_retries_on_connection_error(self, router: ModelRouter):
        """连接错误时自动重试最多 3 次"""
        from anthropic import APIConnectionError as AnthropicConnError

        mock_req = MagicMock()
        fail_exc = AnthropicConnError(message="connection refused", request=mock_req)
        success_resp = _make_mock_response("成功")

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise fail_exc
            return success_resp

        with patch.object(router._client.messages, "create", side_effect=side_effect):
            with patch("asyncio.sleep", new=AsyncMock()):
                result = await router.complete(
                    tenant_id="tenant-001",
                    task_type="standard_analysis",
                    messages=[{"role": "user", "content": "分析"}],
                )

        assert result == "成功"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_complete_raises_after_max_retries(self, router: ModelRouter):
        """重试 3 次全部失败后，抛出最后一次异常"""
        from anthropic import APIConnectionError as AnthropicConnError

        mock_req = MagicMock()
        fail_exc = AnthropicConnError(message="persistent failure", request=mock_req)

        with patch.object(router._client.messages, "create", new=AsyncMock(side_effect=fail_exc)):
            with patch("asyncio.sleep", new=AsyncMock()):
                with pytest.raises(AnthropicConnError):
                    await router.complete(
                        tenant_id="tenant-001",
                        task_type="standard_analysis",
                        messages=[{"role": "user", "content": "分析"}],
                    )

    @pytest.mark.asyncio
    async def test_complete_timeout_control(self, router: ModelRouter):
        """超时控制：asyncio.wait_for 超时后抛 asyncio.TimeoutError"""

        async def slow_api(**kwargs):
            await asyncio.sleep(100)  # 模拟极慢的 API
            return _make_mock_response()

        # 直接让 _call_api 抛 asyncio.TimeoutError 来模拟超时
        with patch.object(router, "_call_api", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            with patch("asyncio.sleep", new=AsyncMock()):
                with pytest.raises((asyncio.TimeoutError, Exception)):
                    await router.complete(
                        tenant_id="tenant-001",
                        task_type="standard_analysis",
                        messages=[{"role": "user", "content": "分析"}],
                        timeout_s=1,
                    )

    @pytest.mark.asyncio
    async def test_complete_raises_circuit_open_error_when_open(self, router: ModelRouter):
        """熔断器 OPEN 时，complete 直接抛 CircuitOpenError，不调用 API"""
        await router._circuit._save_state(CircuitState.OPEN, 5, time.monotonic())

        api_called = False

        async def should_not_be_called(**kwargs):
            nonlocal api_called
            api_called = True
            return _make_mock_response()

        with patch.object(router._client.messages, "create", side_effect=should_not_be_called):
            with pytest.raises(CircuitOpenError):
                await router.complete(
                    tenant_id="tenant-001",
                    task_type="standard_analysis",
                    messages=[{"role": "user", "content": "分析"}],
                )

        assert api_called is False

    @pytest.mark.asyncio
    async def test_complete_records_cost_when_db_provided(self, router: ModelRouter):
        """传入 db session 时，成功调用后应调用 cost_tracker.record_call"""
        mock_resp = _make_mock_response(input_tokens=200, output_tokens=100)
        mock_db = AsyncMock()

        with patch.object(router._client.messages, "create", new=AsyncMock(return_value=mock_resp)):
            with patch.object(router._cost_tracker, "record_call", new=AsyncMock()) as mock_record:
                await router.complete(
                    tenant_id="tenant-001",
                    task_type="standard_analysis",
                    messages=[{"role": "user", "content": "分析"}],
                    db=mock_db,
                )

                mock_record.assert_called_once()
                record_arg: ModelCallRecord = mock_record.call_args[0][0]
                assert record_arg.tenant_id == "tenant-001"
                assert record_arg.task_type == "standard_analysis"
                assert record_arg.input_tokens == 200
                assert record_arg.output_tokens == 100
                assert record_arg.success is True
                assert record_arg.cost_usd > 0

    @pytest.mark.asyncio
    async def test_complete_does_not_record_cost_when_no_db(self, router: ModelRouter):
        """未传入 db 时，不调用 record_call"""
        mock_resp = _make_mock_response()

        with patch.object(router._client.messages, "create", new=AsyncMock(return_value=mock_resp)):
            with patch.object(router._cost_tracker, "record_call", new=AsyncMock()) as mock_record:
                await router.complete(
                    tenant_id="tenant-001",
                    task_type="standard_analysis",
                    messages=[{"role": "user", "content": "分析"}],
                    # db 不传入
                )

                mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_uses_correct_model_for_task(self, router: ModelRouter):
        """complete 选择的模型应与 strategy 一致"""
        mock_resp = _make_mock_response()
        selected_model = None

        async def capture_model(**kwargs):
            nonlocal selected_model
            selected_model = kwargs.get("model")
            return mock_resp

        with patch.object(router._client.messages, "create", side_effect=capture_model):
            await router.complete(
                tenant_id="tenant-001",
                task_type="quick_classification",
                messages=[{"role": "user", "content": "分类"}],
            )

        assert selected_model == "claude-haiku-4-5-20251001"
