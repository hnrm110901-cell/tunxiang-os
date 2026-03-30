"""总部管理功能测试 — 门店克隆 / 法人公司 / 批量操作"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app
from services.legal_entity import reset_storage as reset_legal
from services.store_batch import reset_storage as reset_batch

client = TestClient(app)
TENANT = "test-tenant-001"
HEADERS = {"X-Tenant-ID": TENANT}


def setup_function():
    """每个测试前重置内存存储。"""
    reset_legal()
    reset_batch()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  门店克隆
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestStoreClone:
    def test_clone_preview(self):
        r = client.get("/api/v1/admin/stores/src-001/clone-preview", headers=HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"]
        assert "cloneable" in data["data"]
        assert "non_cloneable" in data["data"]
        # 应包含 6 个可克隆模块
        assert len(data["data"]["cloneable"]) == 6

    def test_clone_single_store(self):
        r = client.post(
            "/api/v1/admin/stores/clone",
            json={
                "source_store_id": "src-001",
                "new_store_name": "尝在一起(河西店)",
                "new_address": "长沙市岳麓区河西大道100号",
            },
            headers=HEADERS,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["name"] == "尝在一起(河西店)"
        assert data["cloned_from"] == "src-001"
        assert data["status"] == "inactive"
        # 深拷贝验证：新 ID 不等于源
        assert data["id"] != "src-001"
        assert "clone_summary" in data

    def test_clone_empty_name_rejected(self):
        r = client.post(
            "/api/v1/admin/stores/clone",
            json={"source_store_id": "src-001", "new_store_name": "", "new_address": "addr"},
            headers=HEADERS,
        )
        assert r.status_code == 400

    def test_batch_clone(self):
        r = client.post(
            "/api/v1/admin/stores/batch-clone",
            json={
                "source_store_id": "src-001",
                "new_stores": [
                    {"name": "分店A", "address": "地址A"},
                    {"name": "分店B", "address": "地址B"},
                    {"name": "分店C", "address": "地址C"},
                ],
            },
            headers=HEADERS,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["success_count"] == 3
        assert data["failed_count"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  法人 / 公司管理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLegalEntity:
    def test_create_legal_entity_and_company(self):
        # 创建法人
        r = client.post(
            "/api/v1/admin/legal-entities",
            json={"name": "屯象科技有限公司", "tax_id": "91430100MA4L1234X", "type": "corporation"},
            headers=HEADERS,
        )
        assert r.status_code == 200
        entity = r.json()["data"]
        assert entity["type"] == "corporation"
        entity_id = entity["id"]

        # 创建公司
        r = client.post(
            "/api/v1/admin/companies",
            json={"name": "长沙运营公司", "legal_entity_id": entity_id},
            headers=HEADERS,
        )
        assert r.status_code == 200
        company = r.json()["data"]
        assert company["legal_entity_id"] == entity_id

    def test_invalid_entity_type_rejected(self):
        r = client.post(
            "/api/v1/admin/legal-entities",
            json={"name": "测试公司", "tax_id": "TAX001", "type": "invalid_type"},
            headers=HEADERS,
        )
        assert r.status_code == 400

    def test_entity_structure(self):
        # 先创建数据
        r = client.post(
            "/api/v1/admin/legal-entities",
            json={"name": "集团A", "tax_id": "TAX-STRUCT-001", "type": "corporation"},
            headers=HEADERS,
        )
        entity_id = r.json()["data"]["id"]

        r = client.post(
            "/api/v1/admin/companies",
            json={"name": "子公司1", "legal_entity_id": entity_id},
            headers=HEADERS,
        )
        company_id = r.json()["data"]["id"]

        # 门店归属
        r = client.post(
            "/api/v1/admin/stores/assign-company",
            json={"store_id": "store-001", "company_id": company_id},
            headers=HEADERS,
        )
        assert r.status_code == 200

        # 查架构树
        r = client.get("/api/v1/admin/entity-structure", headers=HEADERS)
        assert r.status_code == 200
        tree = r.json()["data"]
        assert tree["total_entities"] >= 1
        assert len(tree["entities"][0]["companies"]) >= 1

    def test_company_stores(self):
        # 创建法人 + 公司
        r = client.post(
            "/api/v1/admin/legal-entities",
            json={"name": "集团B", "tax_id": "TAX-CS-001", "type": "non_corporation"},
            headers=HEADERS,
        )
        entity_id = r.json()["data"]["id"]

        r = client.post(
            "/api/v1/admin/companies",
            json={"name": "运营公司B", "legal_entity_id": entity_id},
            headers=HEADERS,
        )
        company_id = r.json()["data"]["id"]

        # 归属两家门店
        for sid in ["s-b1", "s-b2"]:
            client.post(
                "/api/v1/admin/stores/assign-company",
                json={"store_id": sid, "company_id": company_id},
                headers=HEADERS,
            )

        r = client.get(f"/api/v1/admin/companies/{company_id}/stores", headers=HEADERS)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["store_count"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  批量操作
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestStoreBatch:
    def test_batch_create_and_activate(self):
        # 批量创建
        r = client.post(
            "/api/v1/admin/stores/batch-create",
            json={
                "stores": [
                    {"name": "新店1", "address": "地址1"},
                    {"name": "新店2", "address": "地址2"},
                ]
            },
            headers=HEADERS,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["success_count"] == 2
        store_ids = [s["store_id"] for s in data["created"]]

        # 批量激活
        r = client.post(
            "/api/v1/admin/stores/batch-activate",
            json={"store_ids": store_ids},
            headers=HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["data"]["activated_count"] == 2

    def test_batch_deactivate(self):
        # 先创建并激活
        r = client.post(
            "/api/v1/admin/stores/batch-create",
            json={"stores": [{"name": "待停用店", "address": "地址X"}]},
            headers=HEADERS,
        )
        store_id = r.json()["data"]["created"][0]["store_id"]
        client.post(
            "/api/v1/admin/stores/batch-activate",
            json={"store_ids": [store_id]},
            headers=HEADERS,
        )

        # 停用
        r = client.post(
            "/api/v1/admin/stores/batch-deactivate",
            json={"store_ids": [store_id], "reason": "租约到期"},
            headers=HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["data"]["deactivated_count"] == 1

    def test_import_stores_from_csv(self):
        csv_data = "name,address,brand_id\n导入店A,导入地址A,brand-1\n导入店B,导入地址B,brand-1"
        r = client.post(
            "/api/v1/admin/stores/import",
            json={"file_data": csv_data},
            headers=HEADERS,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["success_count"] == 2
        assert data["import_source"] == "excel"

    def test_batch_limit_exceeded(self):
        # 超过 100 家上限
        stores = [{"name": f"店{i}", "address": f"地址{i}"} for i in range(101)]
        r = client.post(
            "/api/v1/admin/stores/batch-create",
            json={"stores": stores},
            headers=HEADERS,
        )
        assert r.status_code == 400
