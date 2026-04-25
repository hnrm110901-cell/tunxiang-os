"""D3c — Dish Dynamic Pricing 测试

覆盖：
  - test_edge_client_calls_coreml_bridge_with_timeout
  - test_edge_unavailable_falls_back_to_cloud
  - test_gross_margin_floor_clamps_aggressive_discount
  - test_dish_pricing_writes_agent_decision_log
  - test_route_rejects_unauthenticated
  - test_route_rejects_tenant_mismatch
  - test_aggressive_negative_input_still_clamped (additional safety)

技术约束：
  - 不连真实 coreml-bridge / 真实 LLM
  - httpx.AsyncClient + ASGITransport + 注入 mock service
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from ..agents.dish_pricing.cloud_fallback import DishPricingCloudFallback
from ..agents.dish_pricing.edge_client import (
    DishPricingEdgeClient,
    EdgeUnavailableError,
)
from ..agents.dish_pricing.schemas import DishPricingRequest
from ..agents.dish_pricing.service import GROSS_MARGIN_FLOOR, DishPricingService

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"


def _make_request(
    *,
    base_price_fen: int = 5800,
    cost_fen: int = 1900,
    time_of_day: str = "lunch_peak",
    traffic_forecast: str = "high",
    inventory_status: str = "near_expiry",
) -> DishPricingRequest:
    return DishPricingRequest(
        dish_id="dish_001",
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        base_price_fen=base_price_fen,
        cost_fen=cost_fen,
        time_of_day=time_of_day,  # type: ignore[arg-type]
        traffic_forecast=traffic_forecast,  # type: ignore[arg-type]
        inventory_status=inventory_status,  # type: ignore[arg-type]
    )


# ═══════════════════════════════════════════════════════════════════
# 1. Edge client — 调用 coreml-bridge 时使用短超时
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_edge_client_calls_coreml_bridge_with_timeout(monkeypatch):
    """edge_client 应该用 200ms 超时打 :8100/predict/dish-price"""
    from ..agents.dish_pricing import edge_client as edge_client_module

    captured: dict = {}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["payload"] = json
            return httpx.Response(
                200,
                json={
                    "recommended_price_fen": 5500,
                    "confidence": 0.78,
                    "reasoning_signals": {"traffic": "+0.05"},
                    "model_version": "stub-v0",
                    "computed_at_ms": 1714000000000,
                    "floor_protected": False,
                },
            )

    # 直接 patch 已导入模块的 httpx 引用 — 与字符串路径无关
    monkeypatch.setattr(edge_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    client = DishPricingEdgeClient(base_url="http://localhost:8100")
    result = await client.predict(_make_request())

    assert captured["url"] == "http://localhost:8100/predict/dish-price"
    assert captured["timeout"] == 0.2  # 200ms
    assert captured["payload"]["dish_id"] == "dish_001"
    assert captured["payload"]["base_price_fen"] == 5800
    assert result["recommended_price_fen"] == 5500


@pytest.mark.asyncio
async def test_edge_client_timeout_raises_edge_unavailable(monkeypatch):
    from ..agents.dish_pricing import edge_client as edge_client_module

    class _TimeoutClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr(edge_client_module.httpx, "AsyncClient", _TimeoutClient)

    client = DishPricingEdgeClient(base_url="http://localhost:8100")
    with pytest.raises(EdgeUnavailableError):
        await client.predict(_make_request())


# ═══════════════════════════════════════════════════════════════════
# 2. Edge unavailable → cloud fallback
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_edge_unavailable_falls_back_to_cloud():
    """Edge raise EdgeUnavailableError 时，service 应调 cloud_fallback。"""

    edge = MagicMock(spec=DishPricingEdgeClient)
    edge.predict = AsyncMock(side_effect=EdgeUnavailableError("simulated unavailable"))

    cloud = MagicMock(spec=DishPricingCloudFallback)
    cloud.recommend = AsyncMock(
        return_value={
            "recommended_price_fen": 5500,
            "confidence": 0.65,
            "reasoning_signals": [{"name": "cloud", "delta": "+0.00"}],
            "model_version": "cloud-fallback-v0",
            "computed_at_ms": int(time.time() * 1000),
            "floor_protected": False,
        }
    )

    service = DishPricingService(edge_client=edge, cloud_fallback=cloud)

    response = await service.recommend(_make_request())

    assert edge.predict.await_count == 1
    assert cloud.recommend.await_count == 1
    assert response.source == "cloud"
    assert response.recommended_price_fen == 5500
    assert response.model_version == "cloud-fallback-v0"


# ═══════════════════════════════════════════════════════════════════
# 3. 毛利底线 — 即使 -50% 的 aggressive 输入也被夹回
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_gross_margin_floor_clamps_aggressive_discount():
    """边缘返回离谱低价（cost 之下）→ service 层兜底夹回 cost/0.85。"""

    cost_fen = 5000
    base_price_fen = 10000
    # 边缘返回突破毛利底线的报价（甚至低于 cost）—— 模拟模型/规则失控
    rogue_price_fen = 2500  # 远低于 cost

    edge = MagicMock(spec=DishPricingEdgeClient)
    edge.predict = AsyncMock(
        return_value={
            "recommended_price_fen": rogue_price_fen,
            "confidence": 0.99,  # 即使模型说很自信
            "reasoning_signals": {"rogue": "-0.75"},
            "model_version": "rogue-test",
            "computed_at_ms": int(time.time() * 1000),
            "floor_protected": False,  # 故意不标记，强制 service 兜底
        }
    )

    service = DishPricingService(edge_client=edge)
    response = await service.recommend(
        _make_request(base_price_fen=base_price_fen, cost_fen=cost_fen)
    )

    expected_floor_fen = int(-(-int((cost_fen / (1 - GROSS_MARGIN_FLOOR)) * 100) // 100))
    # 直观：cost=5000, floor 价 >= 5000/0.85 = 5882.35 → 5883
    assert response.recommended_price_fen >= 5883, (
        f"floor must be enforced; got {response.recommended_price_fen}"
    )
    assert response.recommended_price_fen >= expected_floor_fen
    assert response.floor_protected is True
    # 必须夹回到至少能保 15% 毛利
    margin = (response.recommended_price_fen - cost_fen) / response.recommended_price_fen
    assert margin >= GROSS_MARGIN_FLOOR - 1e-6, f"margin breach: {margin}"

    # signals 中应记录 floor_clamp
    assert any("margin_floor_clamp" in s.name for s in response.reasoning_signals)


@pytest.mark.asyncio
async def test_gross_margin_floor_with_normal_pricing_does_not_clamp():
    """正常情况下不应触发 floor protection。"""

    edge = MagicMock(spec=DishPricingEdgeClient)
    edge.predict = AsyncMock(
        return_value={
            "recommended_price_fen": 5800,  # 与 base 持平
            "confidence": 0.85,
            "reasoning_signals": {"traffic": "+0.00"},
            "model_version": "stub-v0",
            "computed_at_ms": int(time.time() * 1000),
            "floor_protected": False,
        }
    )

    service = DishPricingService(edge_client=edge)
    # cost=1900 / 5800 = 67% margin — 远高于 15% floor
    response = await service.recommend(_make_request(base_price_fen=5800, cost_fen=1900))

    assert response.floor_protected is False
    assert response.recommended_price_fen == 5800


# ═══════════════════════════════════════════════════════════════════
# 4. 决策留痕
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dish_pricing_writes_agent_decision_log():
    """recommend 应调用 decision_log_writer.write 记录决策。"""

    edge = MagicMock(spec=DishPricingEdgeClient)
    edge.predict = AsyncMock(
        return_value={
            "recommended_price_fen": 5500,
            "confidence": 0.78,
            "reasoning_signals": {"traffic": "+0.05"},
            "model_version": "stub-v0",
            "computed_at_ms": int(time.time() * 1000),
            "floor_protected": False,
        }
    )

    decision_writer = MagicMock()
    decision_writer.write = AsyncMock()

    service = DishPricingService(edge_client=edge, decision_log_writer=decision_writer)
    response = await service.recommend(_make_request())

    decision_writer.write.assert_awaited_once()
    record = decision_writer.write.await_args.args[0]
    # 验证用了现有 AgentDecisionLog 字段（agent_id / decision_type / input_context /
    # output_action / constraints_check / confidence / inference_layer / model_id）
    assert record["agent_id"] == "dish_pricing_v0"
    assert record["decision_type"] == "dynamic_price_recommendation"
    assert record["tenant_id"] == TENANT_ID
    assert record["store_id"] == STORE_ID
    assert record["input_context"]["dish_id"] == "dish_001"
    assert record["output_action"]["recommended_price_fen"] == response.recommended_price_fen
    assert record["constraints_check"]["margin_ok"] is True
    assert record["constraints_check"]["floor_threshold_pct"] == 15
    assert record["confidence"] == response.confidence
    assert record["inference_layer"] in ("edge", "cloud")
    assert record["model_id"] == response.model_version


@pytest.mark.asyncio
async def test_dish_pricing_decision_log_failure_does_not_crash():
    """留痕失败不阻断主业务（best-effort）。"""

    edge = MagicMock(spec=DishPricingEdgeClient)
    edge.predict = AsyncMock(
        return_value={
            "recommended_price_fen": 5500,
            "confidence": 0.78,
            "reasoning_signals": {},
            "model_version": "stub-v0",
            "computed_at_ms": int(time.time() * 1000),
            "floor_protected": False,
        }
    )

    decision_writer = MagicMock()
    decision_writer.write = AsyncMock(side_effect=ValueError("simulated DB failure"))

    service = DishPricingService(edge_client=edge, decision_log_writer=decision_writer)
    # 不应抛异常
    response = await service.recommend(_make_request())
    assert response.recommended_price_fen == 5500


# ═══════════════════════════════════════════════════════════════════
# 5. HTTP 路由 — 拒绝未认证
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
async def http_client():
    from ..main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def valid_payload() -> dict:
    return {
        "dish_id": "dish_001",
        "store_id": STORE_ID,
        "tenant_id": TENANT_ID,
        "base_price_fen": 5800,
        "cost_fen": 1900,
        "time_of_day": "lunch_peak",
        "traffic_forecast": "high",
        "inventory_status": "near_expiry",
    }


@pytest.mark.asyncio
async def test_route_rejects_unauthenticated(http_client, valid_payload):
    """缺 X-Tenant-ID / Authorization 时，应拒绝（4xx）"""
    # 缺 X-Tenant-ID
    resp = await http_client.post(
        "/api/v1/agents/dish-pricing/recommend",
        headers={"Authorization": "Bearer test-token"},
        json=valid_payload,
    )
    assert resp.status_code in (400, 422)

    # 缺 Authorization
    resp2 = await http_client.post(
        "/api/v1/agents/dish-pricing/recommend",
        headers={"X-Tenant-ID": TENANT_ID},
        json=valid_payload,
    )
    assert resp2.status_code in (401, 422)

    # Authorization 不是 Bearer
    resp3 = await http_client.post(
        "/api/v1/agents/dish-pricing/recommend",
        headers={"X-Tenant-ID": TENANT_ID, "Authorization": "Basic xxx"},
        json=valid_payload,
    )
    assert resp3.status_code == 401


@pytest.mark.asyncio
async def test_route_rejects_tenant_mismatch(http_client, valid_payload):
    """body.tenant_id != X-Tenant-ID → 403"""
    other_tenant = "99999999-9999-9999-9999-999999999999"
    resp = await http_client.post(
        "/api/v1/agents/dish-pricing/recommend",
        headers={"X-Tenant-ID": other_tenant, "Authorization": "Bearer test-token"},
        json=valid_payload,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_route_invalid_input_returns_400(http_client):
    """cost >= base 应被路由拒绝（input-level sanity）"""
    bad_payload = {
        "dish_id": "dish_001",
        "store_id": STORE_ID,
        "tenant_id": TENANT_ID,
        "base_price_fen": 1000,
        "cost_fen": 1500,  # > base
        "time_of_day": "lunch_peak",
        "traffic_forecast": "high",
        "inventory_status": "normal",
    }
    resp = await http_client.post(
        "/api/v1/agents/dish-pricing/recommend",
        headers={"X-Tenant-ID": TENANT_ID, "Authorization": "Bearer t"},
        json=bad_payload,
    )
    # Pydantic gt/ge 通过；service 层 ValueError → 400
    assert resp.status_code == 400
