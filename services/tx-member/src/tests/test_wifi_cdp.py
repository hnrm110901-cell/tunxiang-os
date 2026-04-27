"""WiFi探针 + CDP多源融合测试 — S2W5

覆盖场景：
1. TestWiFiProbeService: MAC哈希、OUI厂商检测、访问会话合并
2. TestIdentityResolver: phone_hash精确匹配、时间关联匹配
3. TestExternalImport: external_order_id去重
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.external_import_routes import (
    _hash_phone,
    _imports_store,
)
from api.external_import_routes import (
    router as external_router,
)
from api.wifi_probe_routes import router as wifi_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.wifi_probe_service import (
    OUI_VENDORS,
    _detect_vendor,
    _hash_mac,
)

# ── 测试应用 ──────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(wifi_router)
app.include_router(external_router)
client = TestClient(app)

TENANT_HEADER = {"X-Tenant-ID": "t0000000-0000-0000-0000-000000000001"}
STORE_A = "s0000000-0000-0000-0000-000000000001"


# ── 1. WiFi探针服务测试 ───────────────────────────────────────────────────────


class TestWiFiProbeService:
    """MAC哈希、OUI厂商检测、探针API"""

    def test_mac_hashing_sha256(self):
        """MAC地址应被SHA-256哈希，不可逆"""
        mac = "3C:06:30:AA:BB:CC"
        h = _hash_mac(mac)
        assert len(h) == 64  # SHA-256 hex digest
        assert h == hashlib.sha256(mac.upper().encode()).hexdigest()

    def test_mac_hashing_case_insensitive(self):
        """大小写不同的MAC应产生相同哈希"""
        assert _hash_mac("3c:06:30:aa:bb:cc") == _hash_mac("3C:06:30:AA:BB:CC")

    def test_mac_hashing_strip_whitespace(self):
        """首尾空白应被去除"""
        assert _hash_mac("  3C:06:30:AA:BB:CC  ") == _hash_mac("3C:06:30:AA:BB:CC")

    def test_vendor_detection_apple(self):
        """Apple OUI前缀应识别为Apple"""
        vendor = _detect_vendor("3C:06:30:11:22:33")
        assert vendor == "Apple"

    def test_vendor_detection_huawei(self):
        """Huawei OUI前缀应识别为Huawei"""
        vendor = _detect_vendor("AC:CF:85:11:22:33")
        assert vendor == "Huawei"

    def test_vendor_detection_unknown(self):
        """未知OUI前缀应返回None"""
        vendor = _detect_vendor("FF:FF:FF:11:22:33")
        assert vendor is None

    def test_vendor_detection_all_known(self):
        """所有预定义OUI应能正确识别"""
        for prefix, expected in OUI_VENDORS.items():
            mac = f"{prefix}:11:22:33"
            assert _detect_vendor(mac) == expected

    def test_probe_ingest_api(self):
        """POST /probe 应返回成功并包含ingested数量"""
        r = client.post(
            "/api/v1/member/wifi/probe",
            json={
                "store_id": STORE_A,
                "probes": [
                    {"mac_address": "3C:06:30:AA:BB:CC", "signal_strength": -65},
                    {"mac_address": "AC:CF:85:11:22:33", "signal_strength": -70},
                ],
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["ingested"] == 2
        assert len(data["data"]["items"]) == 2

    def test_probe_marks_new_visitor(self):
        """首次出现的MAC应标记为新访客"""
        unique_mac = "00:26:AB:99:88:77"
        r = client.post(
            "/api/v1/member/wifi/probe",
            json={
                "store_id": STORE_A,
                "probes": [{"mac_address": unique_mac}],
            },
            headers=TENANT_HEADER,
        )
        data = r.json()
        # 首次应为新访客
        assert data["data"]["items"][0]["is_new"] is True

    def test_visit_heatmap_api(self):
        """GET /visits/{store_id} 应返回24小时热力图"""
        r = client.get(
            f"/api/v1/member/wifi/visits/{STORE_A}",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["data"]["heatmap"]) == 24

    def test_coverage_api(self):
        """GET /coverage 应返回匹配率统计"""
        r = client.get(
            "/api/v1/member/wifi/coverage",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "match_rate" in data["data"]


# ── 2. 身份解析测试 ──────────────────────────────────────────────────────────


class TestIdentityResolver:
    """phone_hash精确匹配、时间关联匹配的单元测试"""

    def test_phone_hash_deterministic(self):
        """相同手机号应产生相同哈希"""
        phone = "13800138000"
        h1 = _hash_phone(phone)
        h2 = _hash_phone(phone)
        assert h1 == h2
        assert len(h1) == 64

    def test_phone_hash_different_numbers(self):
        """不同手机号应产生不同哈希"""
        h1 = _hash_phone("13800138000")
        h2 = _hash_phone("13900139000")
        assert h1 != h2

    def test_match_trigger_api(self):
        """POST /match 应返回解析统计"""
        r = client.post(
            "/api/v1/member/wifi/match",
            json={},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["source"] == "wifi"
        assert "total" in data["data"]

    def test_resolve_trigger_api(self):
        """POST /resolve 应返回批量解析统计"""
        r = client.post(
            "/api/v1/member/external/resolve",
            json={},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "resolved" in data["data"]


# ── 3. 外部订单导入测试 ──────────────────────────────────────────────────────


class TestExternalImport:
    """external_order_id去重、导入API"""

    def setup_method(self):
        """每个测试前清空内存存储"""
        _imports_store.clear()

    def test_import_meituan_orders(self):
        """POST /import/meituan 应成功导入美团订单"""
        r = client.post(
            "/api/v1/member/external/import/meituan",
            json=[
                {
                    "external_order_id": "MT20260425001",
                    "store_id": STORE_A,
                    "customer_phone": "13800138000",
                    "order_total_fen": 8800,
                    "items": [{"name": "红烧肉", "quantity": 1, "price_fen": 5800}],
                    "ordered_at": "2026-04-25T12:30:00",
                },
            ],
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["imported"] == 1
        assert data["data"]["source"] == "meituan"

    def test_import_eleme_orders(self):
        """POST /import/eleme 应成功导入饿了么订单"""
        r = client.post(
            "/api/v1/member/external/import/eleme",
            json=[
                {
                    "external_order_id": "EL20260425001",
                    "store_id": STORE_A,
                    "order_total_fen": 6600,
                    "items": [],
                    "ordered_at": "2026-04-25T18:00:00",
                },
            ],
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["imported"] == 1

    def test_dedup_by_external_order_id(self):
        """相同source+external_order_id应幂等去重"""
        order = {
            "external_order_id": "MT_DEDUP_001",
            "store_id": STORE_A,
            "order_total_fen": 3300,
            "items": [],
            "ordered_at": "2026-04-25T12:00:00",
        }
        # 第一次导入
        r1 = client.post(
            "/api/v1/member/external/import/meituan",
            json=[order],
            headers=TENANT_HEADER,
        )
        assert r1.json()["data"]["imported"] == 1
        assert r1.json()["data"]["skipped_duplicates"] == 0

        # 第二次重复导入
        r2 = client.post(
            "/api/v1/member/external/import/meituan",
            json=[order],
            headers=TENANT_HEADER,
        )
        assert r2.json()["data"]["imported"] == 0
        assert r2.json()["data"]["skipped_duplicates"] == 1

    def test_dedup_different_source_allowed(self):
        """不同source的相同order_id应允许导入"""
        order_mt = {
            "external_order_id": "CROSS_SRC_001",
            "store_id": STORE_A,
            "order_total_fen": 4400,
            "items": [],
            "ordered_at": "2026-04-25T12:00:00",
        }
        order_el = {
            "external_order_id": "CROSS_SRC_001",
            "store_id": STORE_A,
            "order_total_fen": 4400,
            "items": [],
            "ordered_at": "2026-04-25T12:00:00",
        }
        r1 = client.post(
            "/api/v1/member/external/import/meituan",
            json=[order_mt],
            headers=TENANT_HEADER,
        )
        r2 = client.post(
            "/api/v1/member/external/import/eleme",
            json=[order_el],
            headers=TENANT_HEADER,
        )
        assert r1.json()["data"]["imported"] == 1
        assert r2.json()["data"]["imported"] == 1

    def test_list_imports_paginated(self):
        """GET /imports 应返回分页结果"""
        # 先导入一些数据
        client.post(
            "/api/v1/member/external/import/meituan",
            json=[
                {
                    "external_order_id": f"MT_LIST_{i}",
                    "store_id": STORE_A,
                    "order_total_fen": 1000 * i,
                    "items": [],
                    "ordered_at": "2026-04-25T12:00:00",
                }
                for i in range(5)
            ],
            headers=TENANT_HEADER,
        )
        r = client.get(
            "/api/v1/member/external/imports?page=1&size=3",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["total"] == 5
        assert len(data["data"]["items"]) == 3

    def test_list_imports_filter_by_source(self):
        """GET /imports?source=meituan 应只返回美团订单"""
        client.post(
            "/api/v1/member/external/import/meituan",
            json=[
                {
                    "external_order_id": "MT_FILTER_1",
                    "store_id": STORE_A,
                    "order_total_fen": 1000,
                    "items": [],
                    "ordered_at": "2026-04-25T12:00:00",
                }
            ],
            headers=TENANT_HEADER,
        )
        client.post(
            "/api/v1/member/external/import/eleme",
            json=[
                {
                    "external_order_id": "EL_FILTER_1",
                    "store_id": STORE_A,
                    "order_total_fen": 2000,
                    "items": [],
                    "ordered_at": "2026-04-25T12:00:00",
                }
            ],
            headers=TENANT_HEADER,
        )
        r = client.get(
            "/api/v1/member/external/imports?source=meituan",
            headers=TENANT_HEADER,
        )
        data = r.json()
        assert data["data"]["total"] == 1

    def test_coverage_api(self):
        """GET /coverage 应返回各来源匹配率"""
        client.post(
            "/api/v1/member/external/import/meituan",
            json=[
                {
                    "external_order_id": "MT_COV_1",
                    "store_id": STORE_A,
                    "order_total_fen": 5000,
                    "items": [],
                    "ordered_at": "2026-04-25T12:00:00",
                }
            ],
            headers=TENANT_HEADER,
        )
        r = client.get(
            "/api/v1/member/external/coverage",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "meituan" in data["data"]
        assert data["data"]["meituan"]["match_rate"] == 0.0

    def test_phone_hash_not_exposed_in_list(self):
        """列表API不应暴露完整phone_hash"""
        client.post(
            "/api/v1/member/external/import/meituan",
            json=[
                {
                    "external_order_id": "MT_SAFE_1",
                    "store_id": STORE_A,
                    "customer_phone": "13800138000",
                    "order_total_fen": 5000,
                    "items": [],
                    "ordered_at": "2026-04-25T12:00:00",
                }
            ],
            headers=TENANT_HEADER,
        )
        r = client.get(
            "/api/v1/member/external/imports",
            headers=TENANT_HEADER,
        )
        items = r.json()["data"]["items"]
        for item in items:
            assert "customer_phone_hash" not in item
            assert "has_phone" in item
