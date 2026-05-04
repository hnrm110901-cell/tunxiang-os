"""tx-forge 信任管理路由测试 — trust_routes.py

覆盖场景（共 4 个）：
1.  POST /api/v1/forge/trust/audit              — 提交信任审计
2.  GET  /api/v1/forge/trust/tiers              — 查询信任等级
3.  GET  /api/v1/forge/trust/{app_id}/status    — 查询应用信任状态
4.  POST /api/v1/forge/trust/{app_id}/upgrade   — 申请升级信任等级
"""
import uuid
from unittest.mock import MagicMock
import pytest
from shared.ontology.src.database import get_db

TENANT_ID = "00000000-0000-0000-0000-000000000001"
APP_ID = str(uuid.uuid4())
AUDIT_ID = str(uuid.uuid4())


class TestForgeTrust:
    @pytest.mark.asyncio
    async def test_submit_audit(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        audit = {"id": AUDIT_ID, "app_id": APP_ID, "requested_tier": "silver", "status": "pending"}
        mock_db.execute.return_value = MagicMock(mappings=lambda: MagicMock(one=lambda: audit))
        resp = await client.post("/api/v1/forge/trust/audit", json={
            "app_id": APP_ID, "requested_tier": "silver",
            "evidence": {"security_report": "pass"}}, headers=tenant_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["requested_tier"] == "silver"

    @pytest.mark.asyncio
    async def test_get_tiers(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        tiers = [{"level": 1, "name": "bronze"}, {"level": 2, "name": "silver"}, {"level": 3, "name": "gold"}]
        mock_db.execute.return_value = MagicMock(mappings=lambda: MagicMock(all=lambda: tiers))
        resp = await client.get("/api/v1/forge/trust/tiers", headers=tenant_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    @pytest.mark.asyncio
    async def test_get_app_trust_status(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        status = {"app_id": APP_ID, "current_tier": "silver", "status": "active"}
        mock_db.execute.return_value = MagicMock(mappings=lambda: MagicMock(first=lambda: status))
        resp = await client.get(f"/api/v1/forge/trust/{APP_ID}/status", headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.json()["current_tier"] == "silver"

    @pytest.mark.asyncio
    async def test_request_upgrade(self, app, client, mock_db, tenant_headers):
        app.dependency_overrides[get_db] = lambda: mock_db
        upgrade = {"app_id": APP_ID, "target_tier": "gold", "status": "pending"}
        mock_db.execute.return_value = MagicMock(mappings=lambda: MagicMock(one=lambda: upgrade))
        resp = await client.post(f"/api/v1/forge/trust/{APP_ID}/upgrade", json={
            "target_tier": "gold", "evidence": {"audit_score": 95}}, headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.json()["target_tier"] == "gold"
        assert resp.json()["status"] == "pending"
