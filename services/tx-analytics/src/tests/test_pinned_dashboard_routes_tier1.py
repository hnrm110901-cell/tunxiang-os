"""Tier 1 — S4-04 PR2.C 驾驶舱 Pin BFF 路由测试

覆盖端点：
  POST   /api/v1/dashboard/pins          — 201 + StandardResponse
  POST   /api/v1/dashboard/pins          — service ValueError → 400
  POST   /api/v1/dashboard/pins          — payload schema 错 → 422 (Pydantic)
  GET    /api/v1/dashboard/pins          — 200 + items + total
  DELETE /api/v1/dashboard/pins/{pin_id} — 200 + deleted=True
  DELETE /api/v1/dashboard/pins/{pin_id} — RLS 阻挡 / 重复软删 → 200 + deleted=False
  全端点                                  — 缺 X-Tenant-ID → 422

测试策略（mock-based unit + asyncio）：
  - dep override _get_db_with_tenant → 假 session（不连真 DB）
  - monkeypatch service 层函数（add_pin / list_pins / remove_pin） → 返回 PinnedItem
  - 验证响应 envelope + status code + service 层调用参数

不在本文件（PR2.B-2 真 PG fixture）：
  - 真实 RLS 跨 tenant 反测（INSERT WITH CHECK 拒）
  - FIFO 行为（21 条挤掉第 1 条）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api import pinned_dashboard_routes as routes
from ..services.pinned_dashboard import PinnedItem


TENANT_A = "11111111-1111-1111-1111-111111111111"
USER_A1 = "22222222-2222-2222-2222-222222222222"

_HEADERS = {"X-Tenant-ID": TENANT_A}

_SAMPLE_SURFACE = {
    "version": "0.8",
    "surface": {
        "id": "card-1",
        "type": "card",
        "props": {"title": "本周营收", "severity": "info"},
    },
}


def _make_pin_item(pin_id: str | None = None) -> PinnedItem:
    return PinnedItem(
        pin_id=pin_id or str(uuid.uuid4()),
        tenant_id=TENANT_A,
        pinner_user_id=USER_A1,
        pinned_at=datetime(2026, 5, 9, 1, 0, tzinfo=timezone.utc),
        surface_snapshot=_SAMPLE_SURFACE,
        source_query_id=None,
        source_natural_query=None,
    )


@pytest.fixture
def client() -> TestClient:
    """构建仅含 pinned_dashboard_router 的最小 FastAPI app + dep override。"""
    app = FastAPI()
    app.include_router(routes.router)

    async def _fake_db_dep(x_tenant_id: str = ""):  # type: ignore[no-untyped-def]
        yield AsyncMock()  # session 不真用，service 层全 mock

    app.dependency_overrides[routes._get_db_with_tenant] = _fake_db_dep
    return TestClient(app)


# ─────────────── POST /pins ───────────────


class TestCreatePinTier1:
    def test_create_pin_returns_201_with_pinned_item(self, client, monkeypatch):
        """店长 Pin 一条洞察 → 201 + StandardResponse(ok=True, data=PinnedItem.dict)。"""
        item = _make_pin_item(pin_id="pin-001")
        mock_add = AsyncMock(return_value=item)
        monkeypatch.setattr(routes, "add_pin", mock_add)

        resp = client.post(
            "/api/v1/dashboard/pins",
            headers=_HEADERS,
            json={
                "pinner_user_id": USER_A1,
                "surface_snapshot": _SAMPLE_SURFACE,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["pin_id"] == "pin-001"
        assert body["data"]["tenant_id"] == TENANT_A
        assert body["data"]["surface_snapshot"] == _SAMPLE_SURFACE

        # 验证 service 层接收正确参数（tenant 走 header，pinner 走 body）
        mock_add.assert_awaited_once()
        call_kwargs = mock_add.await_args.kwargs
        assert call_kwargs["tenant_id"] == TENANT_A
        assert call_kwargs["pinner_user_id"] == USER_A1
        assert call_kwargs["surface_snapshot"] == _SAMPLE_SURFACE

    def test_create_pin_value_error_maps_to_400(self, client, monkeypatch):
        """service 层抛 ValueError（如 tenant_id 空）→ 400 而非 500。"""
        async def _raise(*args, **kwargs):
            raise ValueError("tenant_id 必填非空（防 RLS 绕过）")

        monkeypatch.setattr(routes, "add_pin", _raise)
        resp = client.post(
            "/api/v1/dashboard/pins",
            headers=_HEADERS,
            json={
                "pinner_user_id": USER_A1,
                "surface_snapshot": _SAMPLE_SURFACE,
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["code"] == "INVALID_PAYLOAD"
        assert "tenant_id" in body["detail"]["message"]

    def test_create_pin_missing_pinner_returns_422(self, client):
        """payload 缺 pinner_user_id → Pydantic 422（service 层不被调用）。"""
        resp = client.post(
            "/api/v1/dashboard/pins",
            headers=_HEADERS,
            json={"surface_snapshot": _SAMPLE_SURFACE},
        )
        assert resp.status_code == 422

    def test_create_pin_missing_tenant_header_returns_422(self, client):
        """缺 X-Tenant-ID → FastAPI 422（防 RLS NULL 绕过的第一道）。"""
        resp = client.post(
            "/api/v1/dashboard/pins",
            json={
                "pinner_user_id": USER_A1,
                "surface_snapshot": _SAMPLE_SURFACE,
            },
        )
        assert resp.status_code == 422


# ─────────────── GET /pins ───────────────


class TestListPinsTier1:
    def test_list_pins_returns_items_and_total(self, client, monkeypatch):
        items = [_make_pin_item(pin_id=f"pin-{i:03}") for i in range(3)]
        mock_list = AsyncMock(return_value=items)
        monkeypatch.setattr(routes, "list_pins", mock_list)

        resp = client.get("/api/v1/dashboard/pins", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 3
        assert [p["pin_id"] for p in body["data"]["items"]] == [
            "pin-000",
            "pin-001",
            "pin-002",
        ]
        mock_list.assert_awaited_once()
        # tenant 由 header 传到 service 层（service 层做 NULL 校验 + RLS USING 实际过滤）
        assert mock_list.await_args.args[1] == TENANT_A

    def test_list_pins_empty_tenant_returns_empty_list(self, client, monkeypatch):
        """新 tenant 还没 Pin 任何 → items=[], total=0。"""
        mock_list = AsyncMock(return_value=[])
        monkeypatch.setattr(routes, "list_pins", mock_list)
        resp = client.get("/api/v1/dashboard/pins", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == {"items": [], "total": 0}


# ─────────────── DELETE /pins/{pin_id} ───────────────


class TestDeletePinTier1:
    def test_delete_pin_existing_returns_deleted_true(self, client, monkeypatch):
        """删自家 tenant 的 Pin 成功 → ok:true + data.deleted=true。"""
        mock_remove = AsyncMock(return_value=True)
        monkeypatch.setattr(routes, "remove_pin", mock_remove)

        pin_id = str(uuid.uuid4())
        resp = client.delete(
            f"/api/v1/dashboard/pins/{pin_id}", headers=_HEADERS
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"] == {"deleted": True}

        kwargs = mock_remove.await_args.kwargs
        assert kwargs["tenant_id"] == TENANT_A
        assert kwargs["pin_id"] == pin_id

    def test_delete_pin_cross_tenant_or_already_deleted_returns_deleted_false(
        self, client, monkeypatch
    ):
        """跨 tenant 删（RLS 阻挡）/ 重复软删 → ok:true + data.deleted=false（幂等）。"""
        mock_remove = AsyncMock(return_value=False)
        monkeypatch.setattr(routes, "remove_pin", mock_remove)

        resp = client.delete(
            f"/api/v1/dashboard/pins/{uuid.uuid4()}", headers=_HEADERS
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == {"deleted": False}
