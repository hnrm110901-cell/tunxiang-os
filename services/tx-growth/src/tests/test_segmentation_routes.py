"""分群引擎 API 路由测试 — api/segmentation_routes.py

覆盖场景：
1.  GET  /api/v1/growth/segments                          — 正常返回分群列表
2.  GET  /api/v1/growth/segments                          — 非法 X-Tenant-ID → 400
3.  GET  /api/v1/growth/segments/refresh                  — GET 方法提示用 POST → 400
4.  POST /api/v1/growth/segments/refresh                  — 正常刷新缓存
5.  POST /api/v1/growth/segments/refresh                  — httpx 异常 → 502
6.  GET  /api/v1/growth/segments/{segment_id}             — 内置分群详情
7.  GET  /api/v1/growth/segments/{segment_id}             — 自定义分群详情
8.  GET  /api/v1/growth/segments/{segment_id}             — 不存在 → 404
9.  GET  /api/v1/growth/segments/{segment_id}/members     — 正常返回成员
10. GET  /api/v1/growth/segments/{segment_id}/members     — ValueError → 404
11. GET  /api/v1/growth/segments/{segment_id}/members     — httpx 错误 → 502
12. POST /api/v1/growth/segments/{segment_id}/count       — 正常返回人数
13. POST /api/v1/growth/segments/{segment_id}/count       — ValueError → 404
14. POST /api/v1/growth/segments                          — 正常创建自定义分群
15. POST /api/v1/growth/segments                          — 缺少 name → 422
16. POST /api/v1/growth/segments                          — ValueError → 422
17. DELETE /api/v1/growth/segments/{segment_id}           — 正常删除
18. DELETE /api/v1/growth/segments/{segment_id}           — 内置分群不可删 → 403
19. DELETE /api/v1/growth/segments/{segment_id}           — 不存在 → 404
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing route module
# ---------------------------------------------------------------------------
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Stub structlog
_structlog_mod = types.ModuleType("structlog")
_structlog_mod.get_logger = MagicMock(return_value=MagicMock())
sys.modules.setdefault("structlog", _structlog_mod)

# Stub services.audience_segmentation
_seg_svc_mod = types.ModuleType("services.audience_segmentation")
_BUILTIN_SEGS = {
    "vip": {"name": "VIP客户", "description": "高频高消费"},
    "new_customer": {"name": "新客", "description": "首次到访"},
}
_seg_svc_mod.BUILTIN_SEGMENTS = _BUILTIN_SEGS

_fake_svc = MagicMock()
_seg_svc_mod.AudienceSegmentationService = MagicMock(return_value=_fake_svc)
_svc_parent = types.ModuleType("services")
sys.modules.setdefault("services", _svc_parent)
sys.modules["services.audience_segmentation"] = _seg_svc_mod

from api.segmentation_routes import router  # noqa: E402

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID}
_BAD_HEADERS = {"X-Tenant-ID": "not-a-uuid"}
_SEG_ID = str(uuid.uuid4())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /segments — 正常返回分群列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_segments_ok():
    """正常返回分群列表，包含 items 和 total"""
    _fake_svc.list_segments = AsyncMock(
        return_value=[
            {"segment_id": "vip", "name": "VIP客户", "total": 120},
            {"segment_id": _SEG_ID, "name": "自定义分群", "total": None},
        ]
    )
    resp = client.get("/api/v1/growth/segments", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert body["data"]["total"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /segments — 非法 X-Tenant-ID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_segments_bad_tenant():
    """非法 UUID 格式 X-Tenant-ID → 400"""
    resp = client.get("/api/v1/growth/segments", headers=_BAD_HEADERS)
    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /segments/refresh — 提示用 POST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_refresh_hint_get():
    """GET /refresh 返回提示错误，状态码 200（ok=False）"""
    resp = client.get("/api/v1/growth/segments/refresh", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /segments/refresh — 正常刷新缓存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_refresh_segment_cache_ok():
    """正常刷新缓存，返回刷新结果"""
    _fake_svc.refresh_segment_cache = AsyncMock(return_value={"refreshed": 5})
    resp = client.post("/api/v1/growth/segments/refresh", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["refreshed"] == 5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /segments/refresh — httpx 异常 → 502
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_refresh_segment_cache_http_error():
    """tx-member 调用失败 → 502"""
    _fake_svc.refresh_segment_cache = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    resp = client.post("/api/v1/growth/segments/refresh", headers=_HEADERS)
    assert resp.status_code == 502


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /segments/{segment_id} — 内置分群详情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_builtin_segment_detail():
    """内置分群 ID 直接返回定义，无需 DB 查询"""
    resp = client.get("/api/v1/growth/segments/vip", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["segment_id"] == "vip"
    assert body["data"]["segment_type"] == "builtin"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /segments/{segment_id} — 自定义分群详情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_custom_segment_detail():
    """自定义分群 ID 从 list_segments 过滤返回"""
    _fake_svc.list_segments = AsyncMock(
        return_value=[
            {"segment_id": _SEG_ID, "name": "自定义分群", "total": 50},
        ]
    )
    resp = client.get(f"/api/v1/growth/segments/{_SEG_ID}", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["segment_id"] == _SEG_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /segments/{segment_id} — 不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_segment_not_found():
    """既非内置又非自定义分群 → 404"""
    _fake_svc.list_segments = AsyncMock(return_value=[])
    resp = client.get("/api/v1/growth/segments/nonexistent_seg", headers=_HEADERS)
    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /segments/{segment_id}/members — 正常返回成员
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_segment_members_ok():
    """正常分页返回分群成员列表"""
    _fake_svc.get_segment_members = AsyncMock(
        return_value={
            "items": [str(uuid.uuid4()), str(uuid.uuid4())],
            "total": 2,
            "page": 1,
            "size": 100,
        }
    )
    resp = client.get(
        f"/api/v1/growth/segments/{_SEG_ID}/members",
        headers=_HEADERS,
        params={"page": 1, "size": 50},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: GET /members — ValueError → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_segment_members_not_found():
    """分群不存在 ValueError → 404"""
    _fake_svc.get_segment_members = AsyncMock(side_effect=ValueError("分群不存在: nonexistent"))
    resp = client.get(
        "/api/v1/growth/segments/nonexistent/members",
        headers=_HEADERS,
    )
    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: GET /members — httpx 错误 → 502
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_segment_members_http_error():
    """调用 tx-member 失败 → 502"""
    _fake_svc.get_segment_members = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    resp = client.get(
        f"/api/v1/growth/segments/{_SEG_ID}/members",
        headers=_HEADERS,
    )
    assert resp.status_code == 502


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: POST /segments/{segment_id}/count — 正常返回人数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_count_segment_ok():
    """正常返回分群人数"""
    _fake_svc.count_segment = AsyncMock(return_value=256)
    resp = client.post(
        f"/api/v1/growth/segments/{_SEG_ID}/count",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["count"] == 256
    assert body["data"]["segment_id"] == _SEG_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 13: POST /count — ValueError → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_count_segment_not_found():
    """分群不存在 ValueError → 404"""
    _fake_svc.count_segment = AsyncMock(side_effect=ValueError("分群不存在: nonexistent"))
    resp = client.post(
        "/api/v1/growth/segments/nonexistent/count",
        headers=_HEADERS,
    )
    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 14: POST /segments — 正常创建自定义分群
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_custom_segment_ok():
    """正常创建自定义分群，返回新分群数据"""
    new_seg = {
        "segment_id": _SEG_ID,
        "name": "高价值沉睡客",
        "rules": [{"field": "r_score", "op": "lte", "value": 2}],
    }
    _fake_svc.create_custom_segment = AsyncMock(return_value=new_seg)
    resp = client.post(
        "/api/v1/growth/segments",
        headers=_HEADERS,
        json={
            "name": "高价值沉睡客",
            "rules": [{"field": "r_score", "op": "lte", "value": 2}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["segment_id"] == _SEG_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 15: POST /segments — 缺少 name → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_custom_segment_missing_name():
    """缺少必填字段 name → 422"""
    resp = client.post(
        "/api/v1/growth/segments",
        headers=_HEADERS,
        json={"rules": [{"field": "r_score", "op": "lte", "value": 2}]},
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 16: POST /segments — rules 为空 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_custom_segment_empty_rules():
    """rules 为空列表 → 422（min_length=1）"""
    resp = client.post(
        "/api/v1/growth/segments",
        headers=_HEADERS,
        json={"name": "空规则分群", "rules": []},
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 17: DELETE /segments/{segment_id} — 正常删除
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_delete_custom_segment_ok():
    """正常删除自定义分群，返回 deleted=True"""
    _fake_svc.delete_custom_segment = AsyncMock(return_value=True)
    resp = client.delete(
        f"/api/v1/growth/segments/{_SEG_ID}",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["deleted"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 18: DELETE /segments/vip — 内置分群不可删 → 403
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_delete_builtin_segment_forbidden():
    """尝试删除内置分群 → 403"""
    resp = client.delete("/api/v1/growth/segments/vip", headers=_HEADERS)
    assert resp.status_code == 403


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 19: DELETE /segments/{segment_id} — 不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_delete_segment_not_found():
    """分群不存在（服务返回 False）→ 404"""
    _fake_svc.delete_custom_segment = AsyncMock(return_value=False)
    resp = client.delete(
        f"/api/v1/growth/segments/{_SEG_ID}",
        headers=_HEADERS,
    )
    assert resp.status_code == 404
