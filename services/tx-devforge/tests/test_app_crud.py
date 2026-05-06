"""Application CRUD 路由测试（6 个用例）。

各测试通过 patch.object 模拟 ApplicationRepository 方法，
避免依赖真实 PostgreSQL 连接。emit_event 已在 auto_override fixture 中静默。

测试场景基于内部研发平台（DevForge）的实际使用流程。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.repositories.application import ApplicationRepository

from .conftest import TENANT_HEADERS, make_app


class TestCreateApplication:
    """POST /api/v1/devforge/applications — 创建应用目录条目。"""

    @patch.object(ApplicationRepository, "create")
    async def test_create_application(self, mock_create, client) -> None:
        """创建 backend_service 类型应用应返回 201 及正确字段。"""
        mock_app = make_app(code="my-service", name="My Service", owner="team-a")
        mock_create.return_value = mock_app

        response = await client.post(
            "/api/v1/devforge/applications",
            json={
                "code": "my-service",
                "name": "My Service",
                "resource_type": "backend_service",
                "owner": "team-a",
            },
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 201, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["code"] == "my-service"
        assert data["data"]["name"] == "My Service"
        assert data["data"]["owner"] == "team-a"
        assert data["data"]["resource_type"] == "backend_service"
        assert data["data"]["id"] == str(mock_app.id)
        assert data["data"]["is_deleted"] is False

    @patch.object(ApplicationRepository, "create")
    async def test_create_duplicate_code(self, mock_create, client) -> None:
        """同租户重复 code 应返回 409 Conflict。"""
        from src.repositories.application import ApplicationAlreadyExists

        mock_create.side_effect = ApplicationAlreadyExists(
            "application with code='my-service' already exists"
        )

        response = await client.post(
            "/api/v1/devforge/applications",
            json={
                "code": "my-service",
                "name": "Duplicate",
                "resource_type": "backend_service",
            },
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 409, response.text
        data = response.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "duplicate_code"


class TestListApplications:
    """GET /api/v1/devforge/applications — 分页列表。"""

    @patch.object(ApplicationRepository, "list")
    async def test_list_applications(self, mock_list, client) -> None:
        """返回分页的应用列表。"""
        apps = [make_app(code="app-1"), make_app(code="app-2")]
        mock_list.return_value = (apps, 2)

        response = await client.get(
            "/api/v1/devforge/applications",
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        items = data["data"]["items"]
        assert len(items) == 2
        assert items[0]["code"] == "app-1"
        assert items[1]["code"] == "app-2"
        assert data["data"]["total"] == 2
        assert data["data"]["page"] == 1
        assert data["data"]["size"] == 20

    @patch.object(ApplicationRepository, "list")
    async def test_list_applications_with_filters(self, mock_list, client) -> None:
        """resource_type 过滤参数应透传给 repository。"""
        apps = [make_app(code="fe-app", resource_type="frontend_app")]
        mock_list.return_value = (apps, 1)

        response = await client.get(
            "/api/v1/devforge/applications?resource_type=frontend_app&page=1&size=10",
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert len(data["data"]["items"]) == 1
        assert data["data"]["items"][0]["resource_type"] == "frontend_app"
        assert data["data"]["page"] == 1
        assert data["data"]["size"] == 10


class TestGetApplication:
    """GET /api/v1/devforge/applications/{id} — 单个应用详情。"""

    @patch.object(ApplicationRepository, "get_by_id")
    async def test_get_application(self, mock_get, client) -> None:
        """按 ID 查询应返回完整应用信息。"""
        app_id = uuid4()
        mock_app = make_app(id=app_id, code="my-service")
        mock_get.return_value = mock_app

        response = await client.get(
            f"/api/v1/devforge/applications/{app_id}",
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["id"] == str(app_id)
        assert data["data"]["code"] == "my-service"
        assert data["data"]["resource_type"] == "backend_service"

    @patch.object(ApplicationRepository, "get_by_id")
    async def test_get_nonexistent_application(self, mock_get, client) -> None:
        """不存在的 ID 应返回 404。"""
        mock_get.return_value = None

        response = await client.get(
            f"/api/v1/devforge/applications/{uuid4()}",
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 404, response.text
        data = response.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "not_found"


class TestUpdateApplication:
    """PATCH /api/v1/devforge/applications/{id} — 更新应用字段。"""

    @patch.object(ApplicationRepository, "update")
    async def test_update_application_name(self, mock_update, client) -> None:
        """更新 name 字段应返回更新后的数据。"""
        app_id = uuid4()
        mock_app = make_app(id=app_id, code="my-service", name="Updated Name")
        mock_update.return_value = mock_app

        response = await client.patch(
            f"/api/v1/devforge/applications/{app_id}",
            json={"name": "Updated Name"},
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["name"] == "Updated Name"
        assert data["data"]["id"] == str(app_id)

    @patch.object(ApplicationRepository, "update")
    async def test_update_nonexistent(self, mock_update, client) -> None:
        """更新不存在的 ID 应返回 404。"""
        mock_update.return_value = None

        response = await client.patch(
            f"/api/v1/devforge/applications/{uuid4()}",
            json={"name": "Nope"},
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 404, response.text
        data = response.json()
        assert data["ok"] is False


class TestDeleteApplication:
    """DELETE /api/v1/devforge/applications/{id} — 软删除。"""

    @patch.object(ApplicationRepository, "soft_delete")
    async def test_soft_delete_application(self, mock_delete, client) -> None:
        """软删除应返回 is_deleted=True。"""
        app_id = uuid4()
        mock_delete.return_value = True

        response = await client.delete(
            f"/api/v1/devforge/applications/{app_id}",
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["is_deleted"] is True
        assert data["data"]["id"] == str(app_id)

    @patch.object(ApplicationRepository, "soft_delete")
    async def test_delete_nonexistent(self, mock_delete, client) -> None:
        """删除不存在的 ID 应返回 404。"""
        mock_delete.return_value = False

        response = await client.delete(
            f"/api/v1/devforge/applications/{uuid4()}",
            headers=TENANT_HEADERS,
        )

        assert response.status_code == 404, response.text


class TestValidation:
    """请求体验证测试。"""

    async def test_missing_tenant_header(self, client) -> None:
        """缺少 X-Tenant-ID header 应返回 401。"""
        response = await client.post(
            "/api/v1/devforge/applications",
            json={"code": "x", "name": "X", "resource_type": "backend_service"},
        )
        assert response.status_code == 401, response.text
        data = response.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "tenant_required"

    async def test_invalid_resource_type(self, client) -> None:
        """非法的 resource_type 应返回 422。"""
        response = await client.post(
            "/api/v1/devforge/applications",
            json={
                "code": "bad-type",
                "name": "Bad Type",
                "resource_type": "invalid_type",
            },
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 422, response.text
