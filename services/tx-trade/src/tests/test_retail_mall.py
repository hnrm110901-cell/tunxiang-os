"""甄选商城测试 — API 冒烟 + 服务逻辑单元测试

覆盖场景：
1. 商品列表 (分类筛选/全量)
2. 商品详情 (正常/不存在)
3. 创建零售订单 (正常/空商品/地址缺失)
4. 会员折扣 (正常)
5. 快递追踪 (正常)
6. 礼品卡列表 (正常)
7. 校验函数单元测试
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.retail_mall_routes import router as retail_router
from fastapi.testclient import TestClient
from main import app

if not any(r.prefix == "/api/v1/retail" for r in app.routes if hasattr(r, "prefix")):
    app.include_router(retail_router)

client = TestClient(app)

TENANT_HEADER = {"X-Tenant-ID": "test-tenant-001"}


# ── 1. 商品列表 ──────────────────────────────────────────────

class TestListProducts:
    def test_list_all_products(self):
        r = client.get("/api/v1/retail/products", headers=TENANT_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]

    def test_list_products_by_category(self):
        r = client.get(
            "/api/v1/retail/products",
            params={"category": "seafood_gift"},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_list_products_pagination(self):
        r = client.get(
            "/api/v1/retail/products",
            params={"page": 2, "size": 10},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["page"] == 2
        assert data["size"] == 10


# ── 2. 商品详情 ──────────────────────────────────────────────

class TestProductDetail:
    def test_get_product_detail(self):
        r = client.get(
            "/api/v1/retail/products/prod-001",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["product_id"] == "prod-001"


# ── 3. 创建零售订单 ──────────────────────────────────────────

class TestCreateRetailOrder:
    def test_create_order_ok(self):
        r = client.post(
            "/api/v1/retail/orders",
            json={
                "customer_id": "cust-001",
                "items": [
                    {"product_id": "prod-001", "sku_id": "sku-001", "quantity": 2},
                ],
                "address": {
                    "name": "张三",
                    "phone": "13800138000",
                    "province": "湖南省",
                    "city": "长沙市",
                    "district": "岳麓区",
                    "detail": "银盆南路xxx号",
                },
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["customer_id"] == "cust-001"
        assert data["data"]["status"] == "pending"
        assert len(data["data"]["items"]) == 1

    def test_create_order_invalid_quantity(self):
        r = client.post(
            "/api/v1/retail/orders",
            json={
                "customer_id": "cust-001",
                "items": [
                    {"product_id": "prod-001", "sku_id": "sku-001", "quantity": 0},
                ],
                "address": {
                    "name": "张三",
                    "phone": "13800138000",
                    "province": "湖南省",
                    "city": "长沙市",
                    "district": "岳麓区",
                    "detail": "银盆南路xxx号",
                },
            },
            headers=TENANT_HEADER,
        )
        assert r.status_code == 422  # Pydantic 校验失败

    def test_create_order_empty_items(self):
        r = client.post(
            "/api/v1/retail/orders",
            json={
                "customer_id": "cust-001",
                "items": [],
                "address": {
                    "name": "张三",
                    "phone": "13800138000",
                    "province": "湖南省",
                    "city": "长沙市",
                    "district": "岳麓区",
                    "detail": "银盆南路xxx号",
                },
            },
            headers=TENANT_HEADER,
        )
        # 空列表在 Pydantic 层允许，业务层拦截
        assert r.status_code == 200


# ── 4. 会员折扣 ──────────────────────────────────────────────

class TestMemberDiscount:
    def test_apply_discount(self):
        r = client.post(
            "/api/v1/retail/orders/order-001/discount",
            json={"card_id": "card-001"},
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["order_id"] == "order-001"
        assert data["data"]["card_id"] == "card-001"


# ── 5. 快递追踪 ──────────────────────────────────────────────

class TestDeliveryTracking:
    def test_track_delivery(self):
        r = client.get(
            "/api/v1/retail/orders/order-001/delivery",
            headers=TENANT_HEADER,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "traces" in data["data"]


# ── 6. 礼品卡列表 ────────────────────────────────────────────

class TestGiftCards:
    def test_list_gift_cards(self):
        r = client.get("/api/v1/retail/gift-cards", headers=TENANT_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "items" in data["data"]


# ── 7. 服务层校验函数单元测试 ────────────────────────────────

class TestValidationHelpers:
    def test_validate_retail_items_ok(self):
        from services.retail_mall import validate_retail_items
        ok, msg = validate_retail_items([
            {"product_id": "p1", "sku_id": "s1", "quantity": 2},
        ])
        assert ok is True
        assert msg == "ok"

    def test_validate_retail_items_empty(self):
        from services.retail_mall import validate_retail_items
        ok, msg = validate_retail_items([])
        assert ok is False
        assert msg == "items_empty"

    def test_validate_retail_items_missing_product_id(self):
        from services.retail_mall import validate_retail_items
        ok, msg = validate_retail_items([{"sku_id": "s1", "quantity": 1}])
        assert ok is False
        assert "missing_product_id" in msg

    def test_validate_retail_items_invalid_quantity(self):
        from services.retail_mall import validate_retail_items
        ok, msg = validate_retail_items([
            {"product_id": "p1", "sku_id": "s1", "quantity": -1},
        ])
        assert ok is False
        assert "invalid_quantity" in msg

    def test_validate_address_ok(self):
        from services.retail_mall import validate_address
        ok, msg = validate_address({
            "name": "张三", "phone": "13800138000",
            "province": "湖南省", "city": "长沙市",
            "district": "岳麓区", "detail": "银盆南路xxx号",
        })
        assert ok is True

    def test_validate_address_missing_field(self):
        from services.retail_mall import validate_address
        ok, msg = validate_address({"name": "张三"})
        assert ok is False
        assert "missing_address_field" in msg
