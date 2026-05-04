"""健康检查路由测试（2 个用例）。

/health 和 /readiness 属于公共路径（不验证 X-Tenant-ID），
不走 TenantMiddleware 的 tenant 检查，也不经 auto_override fixture 处理。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


class TestHealth:
    """GET /health — liveness 探针。"""

    async def test_health_endpoint(self, client) -> None:
        """进程存活应返回 200 及服务标识。"""
        response = await client.get("/health")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["service"] == "tx-devforge"
        assert data["data"]["version"] == "0.1.0"
        assert data["error"] == {}


class TestReadiness:
    """GET /readiness — readiness 探针。"""

    async def test_readiness_db_ok(self, client) -> None:
        """DB 可连通时 /readiness 返回 200。"""
        with patch(
            "src.api.health_routes.check_db_connectivity",
            new=AsyncMock(return_value=True),
        ):
            response = await client.get("/readiness")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["db"] == "ok"

    async def test_readiness_db_unreachable(self, client) -> None:
        """DB 不可达时 /readiness 返回 503。"""
        with patch(
            "src.api.health_routes.check_db_connectivity",
            new=AsyncMock(return_value=False),
        ):
            response = await client.get("/readiness")

        assert response.status_code == 503, response.text
        data = response.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "db_unreachable"
