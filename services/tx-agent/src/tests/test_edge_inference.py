"""test_edge_inference.py — EdgeInferenceClient 单元测试

测试场景：
  1. bridge 在线时调用成功，返回预测结果
  2. bridge 离线时自动 fallback（不抛异常）
  3. 请求超时（1秒超时）时也 fallback
  4. 预测结果格式验证（必要字段存在）
  5. Mock bridge 的 HTTP 交互（不依赖真实 Mac mini）

运行：
    pytest services/tx-agent/src/tests/test_edge_inference.py -v
"""

from __future__ import annotations

import os
import sys

# 将 src 目录加入 sys.path，使 "from services.xxx import ..." 可用
_here = os.path.dirname(__file__)
_src = os.path.abspath(os.path.join(_here, ".."))
if _src not in sys.path:
    sys.path.insert(0, _src)

import httpx
import pytest
import respx
from services.edge_inference import EdgeInferenceClient

# ─── Fixtures ────────────────────────────────────────────────────────────────

BRIDGE_URL = "http://localhost:8100"


@pytest.fixture
def client() -> EdgeInferenceClient:
    return EdgeInferenceClient(bridge_url=BRIDGE_URL)


# ─── 1. Bridge 在线 — 调用成功 ───────────────────────────────────────────────


class TestBridgeOnline:
    @pytest.mark.asyncio
    @respx.mock
    async def test_predict_dish_time_success(self, client: EdgeInferenceClient) -> None:
        """bridge 在线时 predict_dish_time 返回预测结果"""
        mock_response = {
            "predicted_seconds": 480,
            "confidence": 0.85,
            "model": "dish_time_v1",
        }
        respx.post(f"{BRIDGE_URL}/predict/dish-time").mock(return_value=httpx.Response(200, json=mock_response))

        result = await client.predict_dish_time(
            dish_id="dish_001",
            hour=12,
            day_type="weekday",
            queue_length=3,
        )

        assert result["predicted_seconds"] == 480
        assert result["confidence"] == 0.85
        assert result["model"] == "dish_time_v1"
        assert result["source"] == "edge"

    @pytest.mark.asyncio
    @respx.mock
    async def test_predict_discount_risk_success(self, client: EdgeInferenceClient) -> None:
        """bridge 在线时 predict_discount_risk 返回风险评分"""
        mock_response = {
            "risk_score": 0.72,
            "risk_level": "high",
            "reason": "discount_rate_too_high",
        }
        respx.post(f"{BRIDGE_URL}/predict/discount-risk").mock(return_value=httpx.Response(200, json=mock_response))

        result = await client.predict_discount_risk(
            discount_rate=0.35,
            order_amount=256.0,
            member_level="gold",
        )

        assert result["risk_score"] == 0.72
        assert result["risk_level"] == "high"
        assert result["reason"] == "discount_rate_too_high"
        assert result["source"] == "edge"

    @pytest.mark.asyncio
    @respx.mock
    async def test_predict_traffic_success(self, client: EdgeInferenceClient) -> None:
        """bridge 在线时 predict_traffic 返回客流预测"""
        mock_response = {
            "predicted_covers": 45,
            "confidence": 0.78,
        }
        respx.post(f"{BRIDGE_URL}/predict/traffic").mock(return_value=httpx.Response(200, json=mock_response))

        result = await client.predict_traffic(
            store_id="store_001",
            date="2026-04-01",
            hour=12,
        )

        assert result["predicted_covers"] == 45
        assert result["confidence"] == 0.78
        assert result["source"] == "edge"

    @pytest.mark.asyncio
    @respx.mock
    async def test_is_available_online(self, client: EdgeInferenceClient) -> None:
        """bridge 在线时 is_available 返回 True"""
        respx.get(f"{BRIDGE_URL}/health").mock(return_value=httpx.Response(200, json={"ok": True, "models_loaded": []}))

        result = await client.is_available()
        assert result is True


# ─── 2. Bridge 离线 — Graceful Fallback ──────────────────────────────────────


class TestBridgeOffline:
    @pytest.mark.asyncio
    @respx.mock
    async def test_dish_time_fallback_on_connect_error(self, client: EdgeInferenceClient) -> None:
        """bridge 离线时 predict_dish_time fallback，不抛异常"""
        respx.post(f"{BRIDGE_URL}/predict/dish-time").mock(side_effect=httpx.ConnectError("Connection refused"))

        result = await client.predict_dish_time(
            dish_id="dish_001",
            hour=12,
            day_type="weekday",
            queue_length=3,
        )

        # 不抛异常，返回 fallback 结果
        assert result["source"] == "fallback"
        assert "predicted_seconds" in result
        assert result["predicted_seconds"] > 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_discount_risk_fallback_on_connect_error(self, client: EdgeInferenceClient) -> None:
        """bridge 离线时 predict_discount_risk fallback，不抛异常"""
        respx.post(f"{BRIDGE_URL}/predict/discount-risk").mock(side_effect=httpx.ConnectError("Connection refused"))

        result = await client.predict_discount_risk(
            discount_rate=0.35,
            order_amount=256.0,
            member_level="gold",
        )

        assert result["source"] == "fallback"
        assert "risk_score" in result
        assert "risk_level" in result
        assert "reason" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_traffic_fallback_on_connect_error(self, client: EdgeInferenceClient) -> None:
        """bridge 离线时 predict_traffic fallback，不抛异常"""
        respx.post(f"{BRIDGE_URL}/predict/traffic").mock(side_effect=httpx.ConnectError("Connection refused"))

        result = await client.predict_traffic(
            store_id="store_001",
            date="2026-04-01",
            hour=12,
        )

        assert result["source"] == "fallback"
        assert "predicted_covers" in result
        assert result["predicted_covers"] >= 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_is_available_offline(self, client: EdgeInferenceClient) -> None:
        """bridge 离线时 is_available 返回 False"""
        respx.get(f"{BRIDGE_URL}/health").mock(side_effect=httpx.ConnectError("Connection refused"))

        result = await client.is_available()
        assert result is False


# ─── 3. 超时 — Fallback ───────────────────────────────────────────────────────


class TestTimeout:
    @pytest.mark.asyncio
    @respx.mock
    async def test_dish_time_fallback_on_timeout(self, client: EdgeInferenceClient) -> None:
        """请求超时时 predict_dish_time fallback，不抛异常"""
        respx.post(f"{BRIDGE_URL}/predict/dish-time").mock(side_effect=httpx.TimeoutException("Request timed out"))

        result = await client.predict_dish_time(
            dish_id="dish_001",
            hour=18,
            day_type="weekend",
            queue_length=5,
        )

        assert result["source"] == "fallback"
        assert "predicted_seconds" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_discount_risk_fallback_on_timeout(self, client: EdgeInferenceClient) -> None:
        """请求超时时 predict_discount_risk fallback，不抛异常"""
        respx.post(f"{BRIDGE_URL}/predict/discount-risk").mock(side_effect=httpx.TimeoutException("Request timed out"))

        result = await client.predict_discount_risk(
            discount_rate=0.50,
            order_amount=600.0,
            member_level="regular",
        )

        assert result["source"] == "fallback"
        assert result["risk_level"] in ("low", "medium", "high")

    @pytest.mark.asyncio
    @respx.mock
    async def test_traffic_fallback_on_timeout(self, client: EdgeInferenceClient) -> None:
        """请求超时时 predict_traffic fallback，不抛异常"""
        respx.post(f"{BRIDGE_URL}/predict/traffic").mock(side_effect=httpx.TimeoutException("Request timed out"))

        result = await client.predict_traffic(
            store_id="store_001",
            date="2026-04-01",
            hour=19,
        )

        assert result["source"] == "fallback"
        assert "predicted_covers" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_is_available_timeout(self, client: EdgeInferenceClient) -> None:
        """健康检查超时时 is_available 返回 False"""
        respx.get(f"{BRIDGE_URL}/health").mock(side_effect=httpx.TimeoutException("Request timed out"))

        result = await client.is_available()
        assert result is False


# ─── 4. 预测结果格式验证 ──────────────────────────────────────────────────────


class TestResultFormat:
    @pytest.mark.asyncio
    @respx.mock
    async def test_dish_time_required_fields(self, client: EdgeInferenceClient) -> None:
        """dish_time 结果包含所有必要字段"""
        respx.post(f"{BRIDGE_URL}/predict/dish-time").mock(
            return_value=httpx.Response(
                200,
                json={
                    "predicted_seconds": 300,
                    "confidence": 0.80,
                    "model": "dish_time_v1",
                },
            )
        )

        result = await client.predict_dish_time("d1", 11, "weekday", 2)

        assert isinstance(result["predicted_seconds"], int)
        assert isinstance(result["confidence"], float)
        assert isinstance(result["model"], str)
        assert result["source"] in ("edge", "fallback")

    @pytest.mark.asyncio
    @respx.mock
    async def test_discount_risk_required_fields(self, client: EdgeInferenceClient) -> None:
        """discount_risk 结果包含所有必要字段"""
        respx.post(f"{BRIDGE_URL}/predict/discount-risk").mock(
            return_value=httpx.Response(
                200,
                json={
                    "risk_score": 0.30,
                    "risk_level": "medium",
                    "reason": "discount_rate_near_limit",
                },
            )
        )

        result = await client.predict_discount_risk(0.25, 150.0, "silver")

        assert isinstance(result["risk_score"], (int, float))
        assert result["risk_level"] in ("low", "medium", "high")
        assert isinstance(result["reason"], str)
        assert result["source"] in ("edge", "fallback")

    @pytest.mark.asyncio
    @respx.mock
    async def test_traffic_required_fields(self, client: EdgeInferenceClient) -> None:
        """traffic 结果包含所有必要字段"""
        respx.post(f"{BRIDGE_URL}/predict/traffic").mock(
            return_value=httpx.Response(
                200,
                json={
                    "predicted_covers": 32,
                    "confidence": 0.75,
                },
            )
        )

        result = await client.predict_traffic("store_002", "2026-04-05", 14)

        assert isinstance(result["predicted_covers"], int)
        assert isinstance(result["confidence"], float)
        assert result["source"] in ("edge", "fallback")

    def test_fallback_dish_time_format(self, client: EdgeInferenceClient) -> None:
        """fallback dish_time 结果格式正确"""
        result = client._fallback_dish_time(hour=12, day_type="weekday", queue_length=3)

        assert isinstance(result["predicted_seconds"], int)
        assert 0.0 <= result["confidence"] <= 1.0
        assert isinstance(result["model"], str)
        assert result["source"] == "fallback"

    def test_fallback_discount_risk_format(self, client: EdgeInferenceClient) -> None:
        """fallback discount_risk 结果格式正确"""
        result = client._fallback_discount_risk(
            discount_rate=0.35,
            order_amount=300.0,
            member_level="gold",
        )

        assert 0.0 <= result["risk_score"] <= 1.0
        assert result["risk_level"] in ("low", "medium", "high")
        assert isinstance(result["reason"], str)
        assert result["source"] == "fallback"

    def test_fallback_traffic_format(self, client: EdgeInferenceClient) -> None:
        """fallback traffic 结果格式正确"""
        result = client._fallback_traffic(hour=12)

        assert isinstance(result["predicted_covers"], int)
        assert result["predicted_covers"] >= 0
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["source"] == "fallback"


# ─── 5. Fallback 逻辑正确性验证 ──────────────────────────────────────────────


class TestFallbackLogic:
    def test_discount_risk_platinum_allows_higher_discount(self, client: EdgeInferenceClient) -> None:
        """铂金会员允许更高折扣，相同折扣率风险分更低"""
        gold_result = client._fallback_discount_risk(0.35, 200.0, "gold")
        platinum_result = client._fallback_discount_risk(0.35, 200.0, "platinum")

        assert platinum_result["risk_score"] <= gold_result["risk_score"]

    def test_discount_risk_high_amount_raises_score(self, client: EdgeInferenceClient) -> None:
        """高金额订单的风险分高于同折扣率的低金额订单"""
        low_amount = client._fallback_discount_risk(0.10, 100.0, "regular")
        high_amount = client._fallback_discount_risk(0.10, 600.0, "regular")

        assert high_amount["risk_score"] >= low_amount["risk_score"]

    def test_dish_time_peak_hour_longer(self, client: EdgeInferenceClient) -> None:
        """高峰时段（12点）出餐时间比非高峰（15点）长"""
        peak = client._fallback_dish_time(hour=12, day_type="weekday", queue_length=2)
        off_peak = client._fallback_dish_time(hour=15, day_type="weekday", queue_length=2)

        assert peak["predicted_seconds"] > off_peak["predicted_seconds"]

    def test_dish_time_weekend_longer_than_weekday(self, client: EdgeInferenceClient) -> None:
        """周末出餐时间比工作日长"""
        weekday = client._fallback_dish_time(hour=12, day_type="weekday", queue_length=3)
        weekend = client._fallback_dish_time(hour=12, day_type="weekend", queue_length=3)

        assert weekend["predicted_seconds"] > weekday["predicted_seconds"]

    def test_traffic_peak_hour_more_covers(self, client: EdgeInferenceClient) -> None:
        """高峰时段（12点）客流量多于非高峰（10点）"""
        peak = client._fallback_traffic(hour=12)
        off_peak = client._fallback_traffic(hour=10)

        assert peak["predicted_covers"] >= off_peak["predicted_covers"]

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """COREML_BRIDGE_URL 环境变量可以覆盖默认地址"""
        monkeypatch.setenv("COREML_BRIDGE_URL", "http://mac-mini.local:8100")
        c = EdgeInferenceClient()
        assert c._base_url == "http://mac-mini.local:8100"

    def test_default_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设置环境变量时使用默认地址"""
        monkeypatch.delenv("COREML_BRIDGE_URL", raising=False)
        c = EdgeInferenceClient()
        assert c._base_url == "http://localhost:8100"
