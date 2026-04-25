"""telemetry_routes — Tier1 跨租户拦截测试套件（A1 安全修复）

场景：徐记海鲜 17 号桌。背景：
  - 旧版 telemetry_routes 仅从 X-Tenant-ID Header 读取租户身份（line 116），
    完全未与 JWT user.tenant_id 比对
  - 前端 reportCrashToTelemetry 从 localStorage 取 tenant_id，任何 XSS / 恶意员工
    修改 localStorage 即可伪造跨租户 crash 写入，用作探测竞争对手 saga_id/order_no
  - _rate_limit_cache 仅以 device_id 为键，调试机切多个 tenant 登录会误伤限流

修复后必须满足的 4 条契约：
  1. test_xujihaixian_x_tenant_id_mismatch_jwt_returns_403_tenant_mismatch
  2. test_xujihaixian_body_tenant_id_mismatch_jwt_returns_403
  3. test_xujihaixian_rate_limit_cache_keyed_by_tenant_device_no_cross_pollution
  4. test_xujihaixian_localStorage_tampered_no_cross_tenant_write
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  sys.modules 存根（必须在导入路由前）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")

if not hasattr(_db_mod, "get_db"):

    async def _placeholder_get_db():  # pragma: no cover
        yield None

    _db_mod.get_db = _placeholder_get_db

if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl


from shared.ontology.src.database import get_db  # noqa: E402

from ..api import telemetry_routes  # noqa: E402
from ..api.telemetry_routes import get_current_user  # noqa: E402
from ..api.telemetry_routes import router as telemetry_router

app = FastAPI()
app.include_router(telemetry_router)


# 徐记海鲜：tenant_A 是当前合法登录身份，tenant_B 是攻击者尝试探测的目标租户
TENANT_XUJI = "11111111-1111-1111-1111-111111111111"
TENANT_COMPETITOR = "22222222-2222-2222-2222-222222222222"
STORE_ID = str(uuid.uuid4())


def _override(db_mock: AsyncMock):
    async def _dep() -> AsyncGenerator:
        yield db_mock

    return _dep


def _override_user(tenant_id: str, user_id: str = "xuji-cashier-007"):
    async def _dep():
        return {"user_id": user_id, "tenant_id": tenant_id, "role": "cashier"}

    return _dep


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    telemetry_routes._rate_limit_cache.clear()
    yield
    telemetry_routes._rate_limit_cache.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. X-Tenant-ID Header 与 JWT 不一致 → 403 TENANT_MISMATCH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTenantHeaderMismatch:
    """攻击场景：徐记 17 号桌收银员 JWT 认证身份是 TENANT_XUJI，
    但前端被 XSS 改写后请求 Header 携带 TENANT_COMPETITOR
    （企图把 crash 写入对手租户的 pos_crash_reports 表，探测对方 saga_id）。
    路由必须 403 拦截 + 写审计 deny 事件，且不调用 db.execute。"""

    def test_xujihaixian_x_tenant_id_mismatch_jwt_returns_403_tenant_mismatch(self):
        db = _make_db()
        audit_calls: list = []

        async def _fake_audit(**kwargs):
            audit_calls.append(kwargs)

        original_hook = getattr(telemetry_routes, "_audit_hook", None)
        telemetry_routes._audit_hook = _fake_audit  # type: ignore[attr-defined]

        try:
            app.dependency_overrides[get_db] = _override(db)
            app.dependency_overrides[get_current_user] = _override_user(TENANT_XUJI)
            client = TestClient(app)

            resp = client.post(
                "/api/v1/telemetry/pos-crash",
                json={
                    "device_id": "sunmi-T2-XJ17-SN-001",
                    "saga_id": str(uuid.uuid4()),  # 探测载荷
                    "order_no": "XJ20260424-00047",
                },
                headers={"X-Tenant-ID": TENANT_COMPETITOR},
            )
        finally:
            app.dependency_overrides.clear()
            # 还原 hook：原值若为 None 也要写回 None，不能 delattr
            # （生产代码 hook = _audit_hook 是模块级读取，删掉会触发 NameError）
            telemetry_routes._audit_hook = original_hook  # type: ignore[attr-defined]

        assert resp.status_code == 403, resp.text
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "TENANT_MISMATCH"
        # 关键：拦截发生在 _set_rls / INSERT 之前，db.execute 不应被调用
        assert db.execute.await_count == 0
        db.commit.assert_not_awaited()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. body 中 tenant_id 与 JWT 不一致 → 403
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTenantBodyMismatch:
    """攻击场景：Header 与 JWT 一致（绕过表层校验），但攻击者在 body 中
    塞 tenant_id 字段企图影响下游处理。路由必须同时校验 body.tenant_id。"""

    def test_xujihaixian_body_tenant_id_mismatch_jwt_returns_403(self):
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)
        app.dependency_overrides[get_current_user] = _override_user(TENANT_XUJI)
        client = TestClient(app)

        try:
            resp = client.post(
                "/api/v1/telemetry/pos-crash",
                json={
                    "device_id": "sunmi-T2-XJ17-SN-002",
                    "tenant_id": TENANT_COMPETITOR,  # 攻击者塞的对手租户
                },
                headers={"X-Tenant-ID": TENANT_XUJI},  # Header 与 JWT 一致
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 403, resp.text
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "TENANT_MISMATCH"
        assert db.execute.await_count == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. rate_limit_cache 加 (tenant_id, device_id) 维度 — 不再跨租户污染
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRateLimitTenantScoped:
    """场景：徐记调试机一台物理设备（device-id = sunmi-DEBUG-007），
    上午用 tenant_A 登录上报一次 crash，下午用 tenant_B 登录想再上报一次。
    旧版限流键仅 device_id → tenant_B 被错误限流到 60s 后才能上报。
    修复后：限流键 = "tenant_id:device_id"，不同 tenant 相互独立计窗。"""

    def test_xujihaixian_rate_limit_cache_keyed_by_tenant_device_no_cross_pollution(self):
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)
        client = TestClient(app)

        same_device = "sunmi-DEBUG-007"

        try:
            # 上午：TENANT_XUJI 登录，第一次上报应通过（200）
            app.dependency_overrides[get_current_user] = _override_user(TENANT_XUJI)
            resp_xuji_first = client.post(
                "/api/v1/telemetry/pos-crash",
                json={"device_id": same_device, "route": "/cashier"},
                headers={"X-Tenant-ID": TENANT_XUJI},
            )
            assert resp_xuji_first.status_code == 200, resp_xuji_first.text

            # 同租户同设备 60s 内第二次 → 限流（验证限流仍然生效）
            resp_xuji_second = client.post(
                "/api/v1/telemetry/pos-crash",
                json={"device_id": same_device, "route": "/cashier"},
                headers={"X-Tenant-ID": TENANT_XUJI},
            )
            assert resp_xuji_second.status_code == 429
            assert resp_xuji_second.json()["detail"]["code"] == "RATE_LIMITED"

            # 下午：TENANT_COMPETITOR 登录同一物理设备 → 不应被 TENANT_XUJI 的窗口阻塞
            # （这正是修复要实现的：限流键含 tenant_id 后，不同 tenant 各自独立计窗）
            app.dependency_overrides[get_current_user] = _override_user(
                TENANT_COMPETITOR, user_id="competitor-tester-001"
            )
            resp_competitor = client.post(
                "/api/v1/telemetry/pos-crash",
                json={"device_id": same_device, "route": "/cashier"},
                headers={"X-Tenant-ID": TENANT_COMPETITOR},
            )
        finally:
            app.dependency_overrides.clear()

        # 关键断言：tenant_B 的请求 不应 因为 tenant_A 的窗口被限流
        assert resp_competitor.status_code == 200, (
            f"跨租户限流污染！tenant_B 在 tenant_A 同 device 的窗口内被误伤："
            f"{resp_competitor.text}"
        )

        # 限流缓存中应有 2 个 key（tenant_xuji:device, tenant_competitor:device）
        cache = telemetry_routes._rate_limit_cache
        assert len(cache) == 2
        assert f"{TENANT_XUJI}:{same_device}" in cache
        assert f"{TENANT_COMPETITOR}:{same_device}" in cache


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 模拟 localStorage 篡改 — 后端拦截不让跨租户 INSERT 执行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLocalStorageTamperingBlocked:
    """端到端场景：徐记收银员被植入 XSS payload，
    localStorage.setItem('tenant_id', TENANT_COMPETITOR) 后触发崩溃。
    旧版前端读 localStorage tenant_id 作为 X-Tenant-ID 上报；
    后端旧版仅看 Header → 跨租户写入成功，攻击者能从 pos_crash_reports
    探测 TENANT_COMPETITOR 的 saga_id / order_no。

    修复后：
      - 前端：reportCrashToTelemetry 改从 JWT 解 tenant_id，但即使前端被绕过……
      - 后端：路由层 X-Tenant-ID vs JWT 强一致性校验拦截，不让 INSERT 执行。

    本用例模拟"前端被绕过"的最坏情况：客户端直接构造篡改后的 X-Tenant-ID。
    """

    def test_xujihaixian_localStorage_tampered_no_cross_tenant_write(self):
        db = _make_db()
        captured: list = []

        async def _capture(sql, params=None):
            captured.append((str(sql), params or {}))
            return MagicMock()

        db.execute = AsyncMock(side_effect=_capture)

        app.dependency_overrides[get_db] = _override(db)
        # JWT 身份 = 徐记（合法登录），但攻击者篡改 localStorage 让前端把
        # X-Tenant-ID 改写成 TENANT_COMPETITOR。后端必须拦截。
        app.dependency_overrides[get_current_user] = _override_user(TENANT_XUJI)
        client = TestClient(app)

        try:
            resp = client.post(
                "/api/v1/telemetry/pos-crash",
                json={
                    "device_id": "sunmi-T2-XJ17-VICTIM",
                    "saga_id": str(uuid.uuid4()),
                    "order_no": "XJ20260424-VICTIM",
                    "store_id": STORE_ID,
                },
                headers={"X-Tenant-ID": TENANT_COMPETITOR},  # 被篡改的 tenant_id
            )
        finally:
            app.dependency_overrides.clear()

        # 关键：后端必须 403 拦截
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "TENANT_MISMATCH"

        # 关键：绝对不允许 INSERT 执行（即使有 set_config 也不应到 INSERT）
        insert_calls = [(s, p) for s, p in captured if "INSERT INTO pos_crash_reports" in s]
        assert len(insert_calls) == 0, (
            f"严重：跨租户 INSERT 被执行了！攻击成功污染 pos_crash_reports："
            f"{insert_calls}"
        )
        # set_config 也不应执行（拦截发生在 RLS 之前，防御深度第一道关）
        set_config_calls = [(s, p) for s, p in captured if "set_config" in s]
        assert len(set_config_calls) == 0
        db.commit.assert_not_awaited()
