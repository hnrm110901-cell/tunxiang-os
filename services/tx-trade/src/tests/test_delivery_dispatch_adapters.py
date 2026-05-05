"""配送商适配器单元测试 — DadaAdapter / SfExpressAdapter / OwnRiderAdapter

覆盖：
1. dispatch 返回 DispatchResult.success=True + provider_order_id（mock）
2. dispatch 在 config 缺失关键字段时 success=False（达达 / 顺丰）
3. cancel / query_location / notify_pickup_ready 的 mock 行为
4. get_adapter 工厂方法路由正确
5. provider 字符串与 adapter 不匹配抛 ValueError
"""

from __future__ import annotations

import os
import sys
import types

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))
for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg(
    "src.services.delivery_dispatch_adapters",
    os.path.join(_SRC_DIR, "services", "delivery_dispatch_adapters"),
)


import pytest

from src.services.delivery_dispatch_adapters import (  # noqa: E402
    DadaAdapter,
    DispatchOrderInput,
    OwnRiderAdapter,
    ProviderConfigSnapshot,
    SfExpressAdapter,
    get_adapter,
)


def _make_input(dispatch_id: str = "DSP-TEST0001") -> DispatchOrderInput:
    return DispatchOrderInput(
        dispatch_id=dispatch_id,
        order_id="ORD-001",
        store_id="store-001",
        delivery_address="长沙市岳麓区测试路 1 号",
        delivery_lat=28.2282,
        delivery_lng=112.9388,
        distance_meters=2500,
        delivery_fee_fen=600,
        tip_fen=200,
        estimated_minutes=25,
        customer_phone="138****0000",
    )


def _full_config(provider: str) -> ProviderConfigSnapshot:
    return ProviderConfigSnapshot(
        provider=provider,
        tenant_id="00000000-0000-0000-0000-000000000001",
        store_id="store-001",
        app_key="ak-test",
        app_secret="sk-test-1234567890abcdef",
        merchant_id="m-001",
        shop_no="shop-001",
        callback_url="https://example.com/cb",
        extra_config={"city_code": "0731"},
    )


# ─── 1. Dada ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dada_dispatch_success_with_full_config() -> None:
    adapter = DadaAdapter(_full_config("dada"))
    result = await adapter.dispatch(_make_input())
    assert result.success is True
    assert result.provider_order_id is not None
    assert result.provider_order_id.startswith("DADA-")
    assert result.estimated_minutes == 25


@pytest.mark.asyncio
async def test_dada_dispatch_fails_without_credentials() -> None:
    cfg = ProviderConfigSnapshot(
        provider="dada",
        tenant_id="00000000-0000-0000-0000-000000000001",
        store_id="store-001",
    )
    result = await DadaAdapter(cfg).dispatch(_make_input())
    assert result.success is False
    assert result.error_code == "CONFIG_INCOMPLETE"


@pytest.mark.asyncio
async def test_dada_cancel_query_notify_paths() -> None:
    adapter = DadaAdapter(_full_config("dada"))
    assert await adapter.cancel("DADA-XYZ", "顾客取消") is True
    loc = await adapter.query_location("DADA-XYZ")
    assert loc.rider_lat is not None and loc.rider_lng is not None
    # 达达 notify_pickup_ready 是 noop 但应返回 True
    assert await adapter.notify_pickup_ready("DADA-XYZ", "DSP-1") is True


def test_dada_sign_uses_md5_uppercase() -> None:
    adapter = DadaAdapter(_full_config("dada"))
    sig = adapter._sign({"a": "1", "b": "2"})
    assert len(sig) == 32
    assert sig == sig.upper()


# ─── 2. SF Express ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sf_express_dispatch_success() -> None:
    adapter = SfExpressAdapter(_full_config("shunfeng"))
    result = await adapter.dispatch(_make_input())
    assert result.success is True
    assert result.provider_order_id is not None
    assert result.provider_order_id.startswith("SHUNFENG-")


@pytest.mark.asyncio
async def test_sf_express_dispatch_fails_without_shop_no() -> None:
    cfg = ProviderConfigSnapshot(
        provider="shunfeng",
        tenant_id="00000000-0000-0000-0000-000000000001",
        store_id="store-001",
        app_key="ak",
        app_secret="sk",
        # missing shop_no
    )
    result = await SfExpressAdapter(cfg).dispatch(_make_input())
    assert result.success is False
    assert result.error_code == "CONFIG_INCOMPLETE"


@pytest.mark.asyncio
async def test_sf_express_pickup_ready_calls_meal_ready_api() -> None:
    adapter = SfExpressAdapter(_full_config("shunfeng"))
    ok = await adapter.notify_pickup_ready("SF-123", "DSP-1")
    assert ok is True


# ─── 3. Own Rider ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_own_rider_dispatch_publishes_event() -> None:
    cfg = ProviderConfigSnapshot(
        provider="self_rider",
        tenant_id="00000000-0000-0000-0000-000000000001",
        store_id="store-001",
    )
    result = await OwnRiderAdapter(cfg).dispatch(_make_input())
    assert result.success is True
    assert result.provider_order_id.startswith("SELF_RIDER-")


@pytest.mark.asyncio
async def test_own_rider_pickup_ready_pushes_event() -> None:
    cfg = ProviderConfigSnapshot(
        provider="self_rider",
        tenant_id="00000000-0000-0000-0000-000000000001",
        store_id="store-001",
    )
    ok = await OwnRiderAdapter(cfg).notify_pickup_ready("SR-1", "DSP-1")
    assert ok is True


@pytest.mark.asyncio
async def test_own_rider_query_location_returns_none_for_app_reported() -> None:
    cfg = ProviderConfigSnapshot(
        provider="self_rider",
        tenant_id="00000000-0000-0000-0000-000000000001",
        store_id="store-001",
    )
    loc = await OwnRiderAdapter(cfg).query_location("SR-1")
    assert loc.rider_lat is None and loc.rider_lng is None


# ─── 4. Factory ──────────────────────────────────────────────────────────────


def test_get_adapter_factory_routes_correctly() -> None:
    cfg_dada = ProviderConfigSnapshot(provider="dada", tenant_id="t", store_id="s")
    cfg_sf = ProviderConfigSnapshot(provider="shunfeng", tenant_id="t", store_id="s")
    cfg_own = ProviderConfigSnapshot(provider="self_rider", tenant_id="t", store_id="s")
    assert isinstance(get_adapter("dada", cfg_dada), DadaAdapter)
    assert isinstance(get_adapter("shunfeng", cfg_sf), SfExpressAdapter)
    assert isinstance(get_adapter("self_rider", cfg_own), OwnRiderAdapter)


def test_get_adapter_unknown_provider_raises() -> None:
    cfg = ProviderConfigSnapshot(provider="unknown", tenant_id="t", store_id="s")
    with pytest.raises(ValueError, match="unknown delivery provider"):
        get_adapter("unknown", cfg)


def test_adapter_provider_mismatch_raises() -> None:
    cfg = ProviderConfigSnapshot(provider="shunfeng", tenant_id="t", store_id="s")
    with pytest.raises(ValueError, match="expects provider"):
        DadaAdapter(cfg)
