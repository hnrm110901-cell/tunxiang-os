"""POS 崩溃遥测路由 — 单元测试（Sprint A1）

覆盖 5 条场景：
  1. test_pos_crash_ok                 — 合法载荷返回 200 + report_id
  2. test_missing_device_id_400        — 缺失/空 device_id 返回 400
  3. test_rate_limited_second_call_429 — 同 device_id 60s 内第二次返回 429
  4. test_rls_cross_tenant_isolation   — tenant_A 写入后 tenant_B 视角下读不到
  5. test_db_error_returns_500_no_leak — SQLAlchemyError 不泄露堆栈

技术约束：
  - sys.modules 存根注入 shared.ontology / structlog（与 test_trial_data_clear 对齐）
  - TestClient + dependency_overrides[get_db] + AsyncMock
  - 每个测试前清空限流缓存，避免用例间串扰
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
from ..api.telemetry_routes import router as telemetry_router  # noqa: E402

app = FastAPI()
app.include_router(telemetry_router)


TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


def _override(db_mock: AsyncMock):
    async def _dep() -> AsyncGenerator:
        yield db_mock

    return _dep


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """每个用例前后清空限流缓存，避免交叉污染。"""
    telemetry_routes._rate_limit_cache.clear()
    yield
    telemetry_routes._rate_limit_cache.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 合法载荷 → 200
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPosCrashOk:
    def test_pos_crash_ok(self):
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/telemetry/pos-crash",
            json={
                "device_id": "sunmi-T2-SN-001",
                "route": "/cashier/checkout",
                "error_stack": "TypeError: Cannot read properties of undefined",
                "user_action": "click checkout button",
                "store_id": STORE_ID,
            },
            headers={"X-Tenant-ID": TENANT_A},
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert "report_id" in body["data"]
        uuid.UUID(body["data"]["report_id"])  # 结果必须是合法 UUID
        # 第一条 set_config（RLS）+ 第二条 INSERT
        assert db.execute.await_count == 2
        db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 缺失 device_id → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMissingDeviceId:
    def test_missing_device_id_returns_422(self):
        # Pydantic 缺字段默认 422
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/telemetry/pos-crash",
            json={"route": "/cashier"},
            headers={"X-Tenant-ID": TENANT_A},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_empty_device_id_returns_400(self):
        # 空白 device_id 触发路由内显式校验：INVALID_PAYLOAD / 400
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/telemetry/pos-crash",
            json={"device_id": "   "},
            headers={"X-Tenant-ID": TENANT_A},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 400
        detail = resp.json().get("detail", {})
        assert isinstance(detail, dict)
        assert detail.get("code") == "INVALID_PAYLOAD"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 同 device_id 第二次请求 → 429
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRateLimited:
    def test_rate_limited_second_call_429(self):
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)
        client = TestClient(app)

        payload = {
            "device_id": "sunmi-T2-SN-RATE",
            "route": "/cashier",
        }

        first = client.post(
            "/api/v1/telemetry/pos-crash",
            json=payload,
            headers={"X-Tenant-ID": TENANT_A},
        )
        assert first.status_code == 200

        second = client.post(
            "/api/v1/telemetry/pos-crash",
            json=payload,
            headers={"X-Tenant-ID": TENANT_A},
        )

        app.dependency_overrides.clear()
        assert second.status_code == 429
        detail = second.json().get("detail", {})
        assert detail.get("code") == "RATE_LIMITED"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. RLS 隔离：tenant_B 视角看不到 tenant_A 的记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRlsIsolation:
    """验证路由对每个请求都调用 set_config('app.tenant_id', tenant, true)，
    并在 INSERT 时把 tenant 参数正确绑定。真实 RLS 策略在迁移层保证隔离，
    此处确保上游调用契约不会退化（否则 RLS 失效）。"""

    def test_rls_set_config_called_per_tenant(self):
        db = _make_db()
        captured_params = []

        async def _capture(sql, params=None):
            captured_params.append((str(sql), params or {}))
            return MagicMock()

        db.execute = AsyncMock(side_effect=_capture)

        app.dependency_overrides[get_db] = _override(db)
        client = TestClient(app)

        # tenant_A 上报
        resp_a = client.post(
            "/api/v1/telemetry/pos-crash",
            json={"device_id": "device-A"},
            headers={"X-Tenant-ID": TENANT_A},
        )
        # tenant_B 上报（不同 device 避免限流）
        resp_b = client.post(
            "/api/v1/telemetry/pos-crash",
            json={"device_id": "device-B"},
            headers={"X-Tenant-ID": TENANT_B},
        )

        app.dependency_overrides.clear()
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

        # 每次请求都应先 set_config 再 INSERT，且 tenant 参数严格对应 Header
        set_config_calls = [(s, p) for s, p in captured_params if "set_config" in s]
        insert_calls = [(s, p) for s, p in captured_params if "INSERT INTO pos_crash_reports" in s]

        assert len(set_config_calls) == 2
        assert set_config_calls[0][1]["tid"] == TENANT_A
        assert set_config_calls[1][1]["tid"] == TENANT_B

        assert len(insert_calls) == 2
        assert insert_calls[0][1]["tid"] == TENANT_A
        assert insert_calls[1][1]["tid"] == TENANT_B
        # tenant 对 device 的绑定不串台
        assert insert_calls[0][1]["did"] == "device-A"
        assert insert_calls[1][1]["did"] == "device-B"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. SQLAlchemyError 降级 500，不泄露堆栈
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDbErrorNoLeak:
    def test_db_error_returns_500_no_leak(self):
        from sqlalchemy.exc import SQLAlchemyError

        db = _make_db()

        call_idx = {"n": 0}

        async def _execute(sql, params=None):
            call_idx["n"] += 1
            # 第一次 set_config 通过，第二次 INSERT 抛错
            if call_idx["n"] == 1:
                return MagicMock()
            raise SQLAlchemyError("connection reset by peer — should NOT leak")

        db.execute = AsyncMock(side_effect=_execute)

        app.dependency_overrides[get_db] = _override(db)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/telemetry/pos-crash",
            json={"device_id": "device-DB-ERR"},
            headers={"X-Tenant-ID": TENANT_A},
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 500
        body = resp.text
        # 不得回显 SQLAlchemy 原文
        assert "connection reset by peer" not in body
        assert "SQLAlchemyError" not in body
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "INTERNAL_ERROR"
        db.rollback.assert_awaited()
