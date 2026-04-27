"""会员 API 路由测试 — api/members.py

覆盖场景：
1.  GET  /api/v1/member/customers               — 正常路径返回空列表（占位实现）
2.  POST /api/v1/member/customers               — 正常创建，返回 ok=True
3.  POST /api/v1/member/customers               — 缺少 phone → 422
4.  GET  /api/v1/member/customers/{id}          — 正常路径返回 ok=True
5.  GET  /api/v1/member/customers/{id}/orders   — 正常路径返回空列表
6.  GET  /api/v1/member/rfm/segments            — 正常路径返回 segments 字段
7.  GET  /api/v1/member/rfm/at-risk             — 正常路径返回 customers 字段
8.  POST /api/v1/member/customers/merge         — 正常路径返回 merged_into
9.  GET  /api/v1/member/campaigns               — 正常路径返回 campaigns 字段
10. POST /api/v1/member/campaigns               — 正常路径返回 campaign_id
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID, "Authorization": "Bearer test"}

# ── 加载路由 ────────────────────────────────────────────────────────────────

from api.members import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /customers — 正常路径
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_customers_ok():
    """返回 ok=True 及 items/total 字段"""
    resp = client.get("/api/v1/member/customers?store_id=store-001", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert "total" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /customers — 正常创建
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_customer_ok():
    """传入 phone 字段，返回 ok=True 及 customer_id"""
    resp = client.post(
        "/api/v1/member/customers",
        json={"phone": "13800138000", "display_name": "测试用户"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "customer_id" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /customers — 缺少 phone → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_customer_missing_phone():
    """phone 为必填字段，缺少时应返回 422"""
    resp = client.post(
        "/api/v1/member/customers",
        json={"display_name": "no-phone"},
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /customers/{id} — 360 画像
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_customer_ok():
    """返回 ok=True，data 字段存在"""
    cid = str(uuid.uuid4())
    resp = client.get(f"/api/v1/member/customers/{cid}", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /customers/{id}/orders — 订单分页
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_customer_orders_ok():
    """返回 items/total 分页结构"""
    cid = str(uuid.uuid4())
    resp = client.get(f"/api/v1/member/customers/{cid}/orders", headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "items" in data
    assert "total" in data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /rfm/segments — RFM 分层
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_rfm_segments_ok():
    """返回 segments 字段"""
    resp = client.get("/api/v1/member/rfm/segments?store_id=store-001", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "segments" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /rfm/at-risk — 流失风险
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_at_risk_customers_ok():
    """返回 customers 字段"""
    resp = client.get("/api/v1/member/rfm/at-risk?store_id=store-001", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "customers" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /customers/merge — Golden ID 合并
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_merge_customers_ok():
    """返回 merged_into 为 primary_id"""
    primary = str(uuid.uuid4())
    secondary = str(uuid.uuid4())
    resp = client.post(
        f"/api/v1/member/customers/merge?primary_id={primary}&secondary_id={secondary}",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["merged_into"] == primary


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /campaigns — 活动列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_campaigns_ok():
    """返回 campaigns 字段"""
    resp = client.get("/api/v1/member/campaigns?store_id=store-001", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "campaigns" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /campaigns — 创建活动
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_campaign_ok():
    """返回 campaign_id"""
    resp = client.post(
        "/api/v1/member/campaigns",
        json={"name": "周末活动", "discount_rate": 0.9},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "campaign_id" in body["data"]
