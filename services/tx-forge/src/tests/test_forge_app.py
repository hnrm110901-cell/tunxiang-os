"""tx-forge 应用市场路由测试 — app_routes.py

覆盖场景（共 8 个）：
1.  POST /api/v1/forge/apps              — 正常创建应用
2.  GET  /api/v1/forge/apps              — 分页列表
3.  GET  /api/v1/forge/apps/{app_id}     — 单个查询
4.  PUT  /api/v1/forge/apps/{app_id}     — 更新元数据
5.  GET  /api/v1/forge/apps/{app_id}/revenue  — 收入查询
6.  GET  /api/v1/forge/apps/{app_id}/reviews  — 评价查询
7.  POST /api/v1/forge/apps              — 缺少必填字段 → 422
8.  GET  /api/v1/forge/apps/{not_found}  — 不存在 → 404
"""
import uuid
from unittest.mock import MagicMock
import pytest
from shared.ontology.src.database import get_db

TENANT_ID = "00000000-0000-0000-0000-000000000001"
APP_ID = str(uuid.uuid4())
DEV_ID = str(uuid.uuid4())


class TestForgeAppCreate:
    @pytest.mark.asyncio
    async def test_create_app(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        created = {"id": APP_ID, "tenant_id": TENANT_ID, "developer_id": DEV_ID,
                    "name": "订单管理", "category": "pos",
                    "description": "智能订单管理", "version": "1.0.0",
                    "status": "draft"}
        mock_db.execute.return_value = MagicMock(
            mappings=lambda: MagicMock(one=lambda: created))
        resp = await client.post("/api/v1/forge/apps", json={
            "developer_id": DEV_ID, "name": "订单管理", "category": "pos",
            "description": "智能订单管理", "version": "1.0.0"}, headers=tenant_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "订单管理"
        assert data["status"] == "draft"

    @pytest.mark.asyncio
    async def test_create_app_validation_error(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = await client.post("/api/v1/forge/apps", json={}, headers={})
        assert resp.status_code == 422


class TestForgeAppList:
    @pytest.mark.asyncio
    async def test_list_apps(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        items = [{"id": APP_ID, "name": "App A", "status": "active"},
                 {"id": str(uuid.uuid4()), "name": "App B", "status": "draft"}]
        mock_db.execute.return_value = MagicMock(
            mappings=lambda: MagicMock(all=lambda: items))
        resp = await client.get("/api/v1/forge/apps", headers=tenant_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2


class TestForgeAppGet:
    @pytest.mark.asyncio
    async def test_get_app(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        expected = {"id": APP_ID, "name": "订单管理", "status": "active"}
        mock_db.execute.return_value = MagicMock(
            mappings=lambda: MagicMock(first=lambda: expected))
        resp = await client.get(f"/api/v1/forge/apps/{APP_ID}", headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == APP_ID

    @pytest.mark.asyncio
    async def test_get_app_not_found(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        mock_db.execute.return_value = MagicMock(
            mappings=lambda: MagicMock(first=lambda: None))
        resp = await client.get(f"/api/v1/forge/apps/{uuid.uuid4()}", headers=tenant_headers)
        assert resp.status_code == 404


class TestForgeAppUpdate:
    @pytest.mark.asyncio
    async def test_update_app(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        updated = {"id": APP_ID, "name": "新名称", "status": "active"}
        mock_db.execute.return_value = MagicMock(
            mappings=lambda: MagicMock(first=lambda: updated))
        resp = await client.put(f"/api/v1/forge/apps/{APP_ID}",
                                 json={"name": "新名称"}, headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名称"


class TestForgeAppRevenue:
    @pytest.mark.asyncio
    async def test_get_app_revenue(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        rev = {"app_id": APP_ID, "total_revenue": 100000, "tx_count": 50}
        mock_db.execute.return_value = MagicMock(
            mappings=lambda: MagicMock(first=lambda: rev))
        resp = await client.get(f"/api/v1/forge/apps/{APP_ID}/revenue", headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.json()["total_revenue"] == 100000


class TestForgeAppReviews:
    @pytest.mark.asyncio
    async def test_get_app_reviews(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        reviews = [{"id": str(uuid.uuid4()), "app_id": APP_ID, "rating": 5},
                   {"id": str(uuid.uuid4()), "app_id": APP_ID, "rating": 4}]
        mock_db.execute.return_value = MagicMock(
            mappings=lambda: MagicMock(all=lambda: reviews))
        resp = await client.get(f"/api/v1/forge/apps/{APP_ID}/reviews", headers=tenant_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2
