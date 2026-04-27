"""Follow-up PR B: GET /api/v1/flags 路由测试

覆盖范围:
  1. domain=trade 返回 ok + flags 字典包含 3 个 A1 flag
  2. 未带 X-Tenant-ID header 返回 401 AUTH_MISSING
  3. domain=unknown 返回 400 INVALID_DOMAIN
  4. domain=trade 不同 tenant 可能得到不同布尔值（灰度规则）
  5. 响应 request_id 存在且格式为 UUID v4
  6. 响应时间 < 100ms（60s 缓存生效后）

测试策略：独立构造一个 FastAPI 应用，只挂载 flags_routes.router，
避免 Gateway 全链路 middleware 干扰（JWT/API Key 等在此场景不需要）。
"""

from __future__ import annotations

import os
import re
import sys
import time
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ─── 路径修正：让 tests 能 import 到 src 和 shared ───
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from api.flags_routes import _CACHE  # noqa: E402
from api.flags_routes import router as flags_router  # noqa: E402

TENANT_A = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
TENANT_B = "b1b2c3d4-e5f6-7890-abcd-ef1234567890"

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _build_app() -> FastAPI:
    """构造只挂载 flags_routes 的最小 FastAPI 应用，隔离其他 middleware。"""
    app = FastAPI()
    app.include_router(flags_router)
    return app


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个测试清空进程内缓存，避免测试间互相影响。"""
    _CACHE.clear()
    yield
    _CACHE.clear()


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


# ─────────────────────────────────────────────────────────────────
# 1. domain=trade 返回 A1 三个 flag
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_domain_trade_returns_a1_flags(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/flags",
            params={"domain": "trade"},
            headers={"X-Tenant-ID": TENANT_A},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    flags = body["data"]["flags"]
    # A1 三件套必须存在
    assert "trade.pos.settle.hardening.enable" in flags
    assert "trade.pos.toast.enable" in flags
    assert "trade.pos.errorBoundary.enable" in flags
    # 所有值必须是布尔
    for name, value in flags.items():
        assert isinstance(value, bool), f"{name} 不是 bool: {type(value)}"


# ─────────────────────────────────────────────────────────────────
# 2. 未带 X-Tenant-ID 返回 401 AUTH_MISSING
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_tenant_returns_401(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/flags", params={"domain": "trade"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AUTH_MISSING"


# ─────────────────────────────────────────────────────────────────
# 3. domain=unknown 返回 400 INVALID_DOMAIN
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_domain_returns_400(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/flags",
            params={"domain": "unknown"},
            headers={"X-Tenant-ID": TENANT_A},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_DOMAIN"


# ─────────────────────────────────────────────────────────────────
# 4. 不同 tenant 可能得到不同布尔值（灰度规则）
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_different_tenants_cached_separately(app: FastAPI):
    """缓存按 tenant_id 分桶，不同 tenant 走独立计算路径。

    由于当前 A1 flag 的 targeting_rules 均为空列表且环境默认基值相同，
    两次请求返回的结构应该相同；但缓存 key 必须按 tenant 隔离（防止串数据）。
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp_a = await c.get(
            "/api/v1/flags",
            params={"domain": "trade"},
            headers={"X-Tenant-ID": TENANT_A},
        )
        resp_b = await c.get(
            "/api/v1/flags",
            params={"domain": "trade"},
            headers={"X-Tenant-ID": TENANT_B},
        )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    # 缓存 key 必须包含 tenant_id，两个不同 tenant 分别有各自的缓存条目
    cache_keys = list(_CACHE.keys())
    tenant_a_keys = [k for k in cache_keys if TENANT_A in k]
    tenant_b_keys = [k for k in cache_keys if TENANT_B in k]
    assert len(tenant_a_keys) >= 1, f"TENANT_A 缓存条目缺失: {cache_keys}"
    assert len(tenant_b_keys) >= 1, f"TENANT_B 缓存条目缺失: {cache_keys}"


# ─────────────────────────────────────────────────────────────────
# 5. request_id 存在且格式为 UUID v4
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_id_is_uuid_v4(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/flags",
            params={"domain": "trade"},
            headers={"X-Tenant-ID": TENANT_A},
        )
    assert resp.status_code == 200
    body = resp.json()
    request_id = body.get("request_id")
    assert request_id is not None, "response missing request_id"
    assert UUID_V4_RE.match(request_id), f"request_id 非 UUID v4: {request_id}"
    # 双重验证：用 uuid 库解析
    parsed = uuid.UUID(request_id)
    assert parsed.version == 4
    # 响应 header 也必须带
    assert resp.headers.get("X-Request-Id") == request_id


# ─────────────────────────────────────────────────────────────────
# 6. 响应时间 < 100ms P95（60s 缓存生效后）
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cached_response_under_100ms(app: FastAPI):
    """第一次请求预热缓存，后续 5 次请求必须全部 < 100ms。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 预热
        await c.get(
            "/api/v1/flags",
            params={"domain": "trade"},
            headers={"X-Tenant-ID": TENANT_A},
        )
        # 测 5 次取 max，模拟 P95
        elapsed_ms: list[float] = []
        for _ in range(5):
            t0 = time.perf_counter()
            resp = await c.get(
                "/api/v1/flags",
                params={"domain": "trade"},
                headers={"X-Tenant-ID": TENANT_A},
            )
            elapsed_ms.append((time.perf_counter() - t0) * 1000)
            assert resp.status_code == 200
    assert max(elapsed_ms) < 100, f"缓存命中后 P95 超过 100ms: {elapsed_ms}"


# ─────────────────────────────────────────────────────────────────
# 额外：domain=all 返回全部 domain 的聚合结果（前端启动时可一次拉取）
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_domain_all_returns_merged_flags(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/flags",
            params={"domain": "all"},
            headers={"X-Tenant-ID": TENANT_A},
        )
    assert resp.status_code == 200
    body = resp.json()
    flags = body["data"]["flags"]
    # 聚合视图必须跨多个 domain（至少 trade + agent）
    has_trade = any(name.startswith("trade.") for name in flags)
    has_agent = any(name.startswith("agent.") for name in flags)
    assert has_trade and has_agent, f"domain=all 聚合缺失 trade/agent: {list(flags)[:5]}"
