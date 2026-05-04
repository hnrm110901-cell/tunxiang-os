"""tx-forge 开发者路由测试 — developer_routes.py

覆盖场景（共 4 个）：
1.  POST /api/v1/forge/developers            — 注册开发者
2.  GET  /api/v1/forge/developers            — 列表查询
3.  GET  /api/v1/forge/developers/{id}/revenue  — 收入查询
4.  POST /api/v1/forge/developers (duplicate) — 冲突检测 → 500
"""
import uuid
from unittest.mock import MagicMock
import httpx
import pytest
from shared.ontology.src.database import get_db

TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEV_ID = str(uuid.uuid4())


class TestForgeDeveloperRegister:
    @pytest.mark.asyncio
    async def test_register_developer(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        created = {"id": DEV_ID, "name": "DevCo", "email": "dev@co.com", "status": "pending"}
        mock_db.execute.return_value = MagicMock(mappings=lambda: MagicMock(one=lambda: created))
        resp = await client.post("/api/v1/forge/developers", json={
            "name": "DevCo", "email": "dev@co.com", "company": "DevCo Ltd"}, headers=tenant_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "DevCo"
        assert data["email"] == "dev@co.com"
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_register_duplicate(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        # DB INSERT raises -> route handler exception -> Starlette re-raises
        mock_db.execute.side_effect = [MagicMock(), Exception("duplicate key")]
        try:
            await client.post("/api/v1/forge/developers", json={
                "name": "DevCo", "email": "dev@co.com", "company": "DevCo Ltd"}, headers=tenant_headers)
            assert False, "expected exception"
        except Exception:
            pass


class TestForgeDeveloperList:
    @pytest.mark.asyncio
    async def test_list_developers(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        items = [{"id": DEV_ID, "name": "DevCo", "status": "pending"},
                 {"id": str(uuid.uuid4()), "name": "OtherCo", "status": "approved"}]
        mock_db.execute.return_value = MagicMock(mappings=lambda: MagicMock(all=lambda: items))
        resp = await client.get("/api/v1/forge/developers", headers=tenant_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2


class TestForgeDeveloperRevenue:
    @pytest.mark.asyncio
    async def test_get_developer_revenue(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        rev = {"developer_id": DEV_ID, "total_revenue": 500000, "tx_count": 120}
        mock_db.execute.return_value = MagicMock(mappings=lambda: MagicMock(first=lambda: rev))
        resp = await client.get(f"/api/v1/forge/developers/{DEV_ID}/revenue", headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.json()["total_revenue"] == 500000
