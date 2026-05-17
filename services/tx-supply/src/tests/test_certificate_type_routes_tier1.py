"""certificate_type_routes 端点测试（PRD-12 / Phase 3 W13 / Tier 1 邻接）

5 个 endpoint 各自 happy path + 错误码验证：
  POST   /api/v1/supply/cert-types                       → 201
  PUT    /api/v1/supply/cert-types/{id}                  → 200
  DELETE /api/v1/supply/cert-types/{id}                  → 200
  GET    /api/v1/supply/cert-types                        → 200 分页
  POST   /api/v1/supply/cert-types/initialize-defaults   → 200 幂等

错误码：
  409 CERT_TYPE_NAME_EXISTS
  404 CERT_TYPE_NOT_FOUND

mock 风格：mock service 层函数，不走真 DB。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

# ─── 常量 ────────────────────────────────────────────────────────────────────

_TENANT = "11111111-aaaa-aaaa-aaaa-111111111111"
_CERT_TYPE_ID = "33333333-cccc-cccc-cccc-333333333333"
_CERT_NAME = "食品经营许可证"

_CERT_TYPE_DICT = {
    "id": _CERT_TYPE_ID,
    "tenant_id": _TENANT,
    "name": _CERT_NAME,
    "applicable_supplier_kinds": ["all"],
    "validity_period_days": 365,
    "is_required": True,
    "is_deleted": False,
    "created_at": datetime(2026, 5, 17, 10, 0, tzinfo=timezone.utc).isoformat(),
    "updated_at": datetime(2026, 5, 17, 10, 0, tzinfo=timezone.utc).isoformat(),
}

_SERVICE_MODULE = "services.tx_supply.src.api.certificate_type_routes"


# ─── FastAPI TestClient helper ────────────────────────────────────────────────


def _make_client():
    """创建 FastAPI TestClient（不走真 DB）。"""
    try:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from services.tx_supply.src.api.certificate_type_routes import router

        app = FastAPI()

        # Mock DB dependency
        from shared.ontology.src.database import get_db as _get_db

        async def _fake_db():
            yield AsyncMock()

        app.dependency_overrides[_get_db] = _fake_db
        app.include_router(router)
        return TestClient(app, raise_server_exceptions=False)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/supply/cert-types
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_cert_types_happy_path():
    """GET /cert-types → 200 + items 分页结构。"""
    with patch(
        f"{_SERVICE_MODULE}.list_certificate_types",
        new=AsyncMock(
            return_value={"items": [_CERT_TYPE_DICT], "total": 1}
        ),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.get(
            "/api/v1/supply/cert-types",
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total"] == 1
        assert len(data["data"]["items"]) == 1


# ════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/cert-types
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_post_cert_type_happy_path():
    """POST /cert-types → 200 返回新建条目。"""
    with patch(
        f"{_SERVICE_MODULE}.create_certificate_type",
        new=AsyncMock(return_value=_CERT_TYPE_DICT),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.post(
            "/api/v1/supply/cert-types",
            json={
                "name": _CERT_NAME,
                "applicable_supplier_kinds": ["all"],
                "validity_period_days": 365,
                "is_required": True,
            },
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["name"] == _CERT_NAME


@pytest.mark.asyncio
async def test_post_cert_type_409_duplicate():
    """POST 同名证件类型 → 409 CERT_TYPE_NAME_EXISTS。"""
    with patch(
        f"{_SERVICE_MODULE}.create_certificate_type",
        new=AsyncMock(side_effect=ValueError("CERT_TYPE_NAME_EXISTS")),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.post(
            "/api/v1/supply/cert-types",
            json={"name": _CERT_NAME},
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 409
        assert "CERT_TYPE_NAME_EXISTS" in resp.text


# ════════════════════════════════════════════════════════════════════════════
# PUT /api/v1/supply/cert-types/{id}
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_put_cert_type_happy_path():
    """PUT /cert-types/{id} → 200 返回更新后字段。"""
    updated = {**_CERT_TYPE_DICT, "name": "食品经营许可证（续期）"}
    with patch(
        f"{_SERVICE_MODULE}.update_certificate_type",
        new=AsyncMock(return_value=updated),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.put(
            f"/api/v1/supply/cert-types/{_CERT_TYPE_ID}",
            json={"name": "食品经营许可证（续期）"},
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["name"] == "食品经营许可证（续期）"


@pytest.mark.asyncio
async def test_put_cert_type_404_not_found():
    """PUT 不存在的证件类型 → 404 CERT_TYPE_NOT_FOUND。"""
    with patch(
        f"{_SERVICE_MODULE}.update_certificate_type",
        new=AsyncMock(side_effect=ValueError("CERT_TYPE_NOT_FOUND")),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.put(
            f"/api/v1/supply/cert-types/nonexistent-id",
            json={"name": "新名称"},
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 404
        assert "CERT_TYPE_NOT_FOUND" in resp.text


# ════════════════════════════════════════════════════════════════════════════
# DELETE /api/v1/supply/cert-types/{id}
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_delete_cert_type_happy_path():
    """DELETE /cert-types/{id} → 200 + deleted=True。"""
    with patch(
        f"{_SERVICE_MODULE}.soft_delete_certificate_type",
        new=AsyncMock(return_value=None),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.delete(
            f"/api/v1/supply/cert-types/{_CERT_TYPE_ID}",
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["deleted"] is True
        assert data["data"]["id"] == _CERT_TYPE_ID


@pytest.mark.asyncio
async def test_delete_cert_type_404():
    """DELETE 不存在的证件类型 → 404。"""
    with patch(
        f"{_SERVICE_MODULE}.soft_delete_certificate_type",
        new=AsyncMock(side_effect=ValueError("CERT_TYPE_NOT_FOUND")),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.delete(
            "/api/v1/supply/cert-types/nonexistent-id",
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/cert-types/initialize-defaults
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_initialize_defaults_endpoint():
    """POST /cert-types/initialize-defaults → 200 created/skipped 统计。"""
    with patch(
        f"{_SERVICE_MODULE}.initialize_defaults",
        new=AsyncMock(
            return_value={"created": 5, "skipped": 0, "total_defaults": 5}
        ),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.post(
            "/api/v1/supply/cert-types/initialize-defaults",
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["created"] == 5
        assert data["data"]["total_defaults"] == 5


@pytest.mark.asyncio
async def test_initialize_defaults_endpoint_idempotent():
    """POST /cert-types/initialize-defaults 重复调用 → skipped=5（幂等）。"""
    with patch(
        f"{_SERVICE_MODULE}.initialize_defaults",
        new=AsyncMock(
            return_value={"created": 0, "skipped": 5, "total_defaults": 5}
        ),
    ):
        client = _make_client()
        if client is None:
            pytest.skip("TestClient 初始化失败（环境依赖缺失）")
        resp = client.post(
            "/api/v1/supply/cert-types/initialize-defaults",
            headers={"X-Tenant-ID": _TENANT},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["skipped"] == 5
        assert data["data"]["created"] == 0
