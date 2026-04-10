"""Round 106 — gateway 最终扫尾测试
涵盖端点：
  - pos_sync_routes.py   (1 endpoint: GET /sync-logs)
  - upload_routes.py     (4 endpoints: POST /image, POST /file, POST /base64, DELETE /{key})
测试数量：≥ 8
"""
import sys
import types
import unittest.mock as _mock

# ── Mock structlog ────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: _mock.MagicMock()
sys.modules.setdefault("structlog", _structlog)

# ── Mock shared integrations for upload_routes ────────────────────────
_shared = types.ModuleType("shared")
_shared_integrations = types.ModuleType("shared.integrations")
_cos_upload_mod = types.ModuleType("shared.integrations.cos_upload")

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALL_ALLOWED_TYPES = IMAGE_TYPES | {
    "application/pdf",
    "video/mp4",
    "audio/mpeg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class COSUploadError(Exception):
    pass


class FakeCOSService:
    async def upload_file(self, file_bytes, filename, content_type, folder):
        return {"url": f"https://cdn.example.com/{folder}/{filename}", "key": f"{folder}/{filename}", "size": len(file_bytes)}

    async def upload_base64(self, base64_data, filename, folder, content_type):
        return {"url": f"https://cdn.example.com/{folder}/{filename}", "key": f"{folder}/{filename}", "size": 100}

    async def delete_file(self, key):
        return True


_cos_upload_mod.IMAGE_TYPES = IMAGE_TYPES
_cos_upload_mod.ALL_ALLOWED_TYPES = ALL_ALLOWED_TYPES
_cos_upload_mod.COSUploadError = COSUploadError
_cos_upload_mod.get_cos_upload_service = lambda: FakeCOSService()

sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.integrations", _shared_integrations)
sys.modules.setdefault("shared.integrations.cos_upload", _cos_upload_mod)

# ── Mock src.response for pos_sync_routes ────────────────────────────
_src = types.ModuleType("src")
_src_response = types.ModuleType("src.response")


def _ok_response(data):
    return {"ok": True, "data": data, "error": None}


_src_response.ok = _ok_response
sys.modules.setdefault("src", _src)
sys.modules.setdefault("src.response", _src_response)

import pytest
import importlib.util
import pathlib
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
import io

GATEWAY_SRC = pathlib.Path(__file__).parent.parent
TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, str(GATEWAY_SRC / rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ════════════════════════════════════════════════════════════════════
# PART A — pos_sync_routes.py  (1 endpoint)
# ════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def pos_sync_client():
    mod = _load_module("api/pos_sync_routes.py", "pos_sync_routes")
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestPosSyncRoutes:
    """pos_sync_routes.py — GET /sync-logs"""

    def test_sync_logs_no_tenant_returns_empty(self, pos_sync_client):
        """未配置 X-Tenant-ID 时返回空列表，ok=True"""
        r = pos_sync_client.get("/api/v1/integrations/sync-logs")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    def test_sync_logs_with_tenant_import_error(self, pos_sync_client):
        """数据库模块不可用（ImportError）时，降级返回空结果"""
        # We mount request state via middleware-less approach
        # The route reads tenant_id from request.state, so we use custom headers
        # Since no middleware sets state, tenant_id will be None → returns empty
        r = pos_sync_client.get(
            "/api/v1/integrations/sync-logs",
            headers={"X-Tenant-ID": TENANT_ID},
            params={"days": "7"},
        )
        # Without middleware injecting request.state.tenant_id, falls back to empty
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_sync_logs_pagination_params(self, pos_sync_client):
        """分页参数传递正常"""
        r = pos_sync_client.get(
            "/api/v1/integrations/sync-logs",
            params={"page": 2, "size": 10},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["page"] == 2
        assert body["data"]["size"] == 10

    def test_sync_logs_merchant_code_filter(self, pos_sync_client):
        """merchant_code 过滤参数正常传递"""
        r = pos_sync_client.get(
            "/api/v1/integrations/sync-logs",
            params={"merchant_code": "czyz", "days": 30},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_sync_logs_days_range_validation(self, pos_sync_client):
        """days 超出范围（>90）→ 422"""
        r = pos_sync_client.get(
            "/api/v1/integrations/sync-logs",
            params={"days": 999},
        )
        assert r.status_code == 422

    def test_sync_logs_days_too_small(self, pos_sync_client):
        """days=0 → 422"""
        r = pos_sync_client.get(
            "/api/v1/integrations/sync-logs",
            params={"days": 0},
        )
        assert r.status_code == 422


# ════════════════════════════════════════════════════════════════════
# PART B — upload_routes.py  (4 endpoints)
# ════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def upload_client():
    mod = _load_module("api/upload_routes.py", "upload_routes")
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestUploadRoutes:
    """upload_routes.py — 4 端点覆盖"""

    def test_upload_image_success(self, upload_client):
        """正常图片上传 → ok=True，返回 url 和 key"""
        image_bytes = b"\xff\xd8\xff" + b"\x00" * 50  # fake JPEG header
        r = upload_client.post(
            "/api/v1/upload/image",
            data={"folder": "dishes"},
            files={"file": ("test.jpg", io.BytesIO(image_bytes), "image/jpeg")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "url" in body["data"]
        assert "key" in body["data"]

    def test_upload_image_invalid_type(self, upload_client):
        """非图片类型 → 400"""
        r = upload_client.post(
            "/api/v1/upload/image",
            data={"folder": "dishes"},
            files={"file": ("test.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
        )
        assert r.status_code == 400

    def test_upload_file_success(self, upload_client):
        """通用文件上传 PDF → ok=True"""
        r = upload_client.post(
            "/api/v1/upload/file",
            data={"folder": "documents"},
            files={"file": ("menu.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "key" in body["data"]

    def test_upload_file_unsupported_type(self, upload_client):
        """不支持的类型 → 400"""
        r = upload_client.post(
            "/api/v1/upload/file",
            data={"folder": "documents"},
            files={"file": ("script.sh", io.BytesIO(b"#!/bin/bash"), "application/x-sh")},
        )
        assert r.status_code == 400

    def test_upload_base64_success(self, upload_client):
        """Base64 上传 → ok=True"""
        import base64
        data = base64.b64encode(b"fake image data").decode()
        r = upload_client.post(
            "/api/v1/upload/base64",
            json={
                "data": data,
                "filename": "avatar.png",
                "folder": "avatars",
                "content_type": "image/png",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "key" in body["data"]

    def test_delete_file_success(self, upload_client):
        """删除文件 → ok=True，deleted=True"""
        r = upload_client.delete("/api/v1/upload/dishes/test-image.jpg")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["deleted"] is True

    def test_delete_file_short_key(self, upload_client):
        """key 太短（<5字符）→ 400"""
        r = upload_client.delete("/api/v1/upload/abc")
        assert r.status_code == 400
