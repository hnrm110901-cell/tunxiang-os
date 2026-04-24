"""
品智同步模块测试
覆盖 5 个同步模块的映射函数 + 签名认证
"""

import os
import sys

# 将 pinzhi/src 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dish_sync import PinzhiDishSync
from inventory_sync import PinzhiInventorySync
from member_sync import PinzhiMemberSync
from order_sync import PinzhiOrderSync
from signature import build_auth_headers, generate_sign, pinzhi_sign

# ─── B1: 签名认证 ───


class TestSignature:
    def test_generate_sign_basic(self):
        """基本签名生成：参数排序 + MD5"""
        params = {"ognid": "12345", "beginDate": "2024-01-01"}
        sign = generate_sign("test_token", params)
        assert isinstance(sign, str)
        assert len(sign) == 32  # MD5 hex digest

    def test_generate_sign_excludes_page_params(self):
        """签名排除 pageIndex/pageSize"""
        params_with_page = {"ognid": "123", "pageIndex": 1, "pageSize": 20}
        params_without_page = {"ognid": "123"}
        assert generate_sign("tk", params_with_page) == generate_sign("tk", params_without_page)

    def test_pinzhi_sign_md5_mode(self):
        """pinzhi_sign 短密钥走 MD5 模式，与 generate_sign 一致"""
        params = {"ognid": "store1"}
        short_secret = "abc123"
        assert pinzhi_sign(params, short_secret) == generate_sign(short_secret, params)

    def test_build_auth_headers(self):
        """build_auth_headers 返回完整认证头"""
        headers = build_auth_headers("my_key", "my_secret", timestamp=1700000000)
        assert headers["X-Api-Key"] == "my_key"
        assert headers["X-Timestamp"] == "1700000000"
        assert "X-Sign" in headers
        assert len(headers["X-Sign"]) == 32


# ─── B2: 订单同步映射 ───


class TestOrderSync:
    def test_map_to_tunxiang_order_basic(self):
        """基本订单映射：字段正确转换，金额单位为分"""
        raw = {
            "billId": "ORD001",
            "billNo": "B20240101001",
            "orderSource": 1,
            "billStatus": 1,
            "tableNo": "A3",
            "dishPriceTotal": 8800,
            "specialOfferPrice": 500,
            "teaPrice": 200,
            "realPrice": 8500,
            "openTime": "2024-01-01 12:00:00",
            "payTime": "2024-01-01 12:30:00",
            "openOrderUser": "waiter01",
            "cashiers": "cashier01",
            "dishList": [
                {"dishId": "D1", "dishName": "宫保鸡丁", "dishPrice": 3800, "dishNum": 2},
                {"dishId": "D2", "dishName": "米饭", "dishPrice": 200, "dishNum": 1},
            ],
            "paymentList": [
                {"payType": "1", "payName": "微信", "payMoney": 8500},
            ],
        }
        result = PinzhiOrderSync.map_to_tunxiang_order(raw)

        assert result["order_id"] == "ORD001"
        assert result["order_number"] == "B20240101001"
        assert result["order_type"] == "dine_in"
        assert result["order_status"] == "completed"
        assert result["table_number"] == "A3"
        assert result["subtotal_fen"] == 8800
        assert result["discount_fen"] == 500
        assert result["total_fen"] == 8500
        assert result["source_system"] == "pinzhi"
        assert len(result["items"]) == 2
        assert result["items"][0]["unit_price_fen"] == 3800
        assert result["items"][0]["subtotal_fen"] == 7600  # 3800 * 2
        assert len(result["payments"]) == 1

    def test_map_order_cancelled_status(self):
        """退单状态映射"""
        raw = {"billId": "ORD002", "billStatus": 2, "dishPriceTotal": 0, "realPrice": 0}
        result = PinzhiOrderSync.map_to_tunxiang_order(raw)
        assert result["order_status"] == "cancelled"


# ─── B3: 菜品同步映射 ───


class TestDishSync:
    def test_map_to_tunxiang_dish_basic(self):
        """基本菜品映射：字段正确转换"""
        raw = {
            "dishId": "DISH001",
            "dishName": "剁椒鱼头",
            "dishCode": "DCY001",
            "categoryId": "CAT01",
            "categoryName": "湘菜",
            "dishPrice": 12800,
            "costPrice": 4500,
            "memberPrice": 11500,
            "unit": "份",
            "status": 1,
            "isWeighing": 0,
            "specList": [
                {"specId": "S1", "specName": "大份", "specPrice": 15800},
                {"specId": "S2", "specName": "小份", "specPrice": 8800},
            ],
        }
        result = PinzhiDishSync.map_to_tunxiang_dish(raw)

        assert result["dish_id"] == "DISH001"
        assert result["dish_name"] == "剁椒鱼头"
        assert result["price_fen"] == 12800
        assert result["cost_fen"] == 4500
        assert result["member_price_fen"] == 11500
        assert result["status"] == "active"
        assert len(result["specs"]) == 2
        assert result["specs"][0]["price_fen"] == 15800
        assert result["source_system"] == "pinzhi"

    def test_map_dish_inactive(self):
        """停用菜品状态映射"""
        raw = {"dishId": "D99", "dishName": "已下架", "status": 0}
        result = PinzhiDishSync.map_to_tunxiang_dish(raw)
        assert result["status"] == "inactive"


# ─── B4: 会员同步映射 ───


class TestMemberSync:
    def test_map_to_golden_id_basic(self):
        """基本会员映射：多身份标识收集"""
        raw = {
            "customerId": "MEM001",
            "name": "张三",
            "phone": "13800138000",
            "cardNo": "VIP20240001",
            "wechatOpenId": "ox_abc123",
            "vipLevel": 2,
            "balance": 50000,
            "points": 1200,
            "totalConsume": 380000,
            "visitCount": 15,
            "lastConsumeDate": "2024-06-15",
        }
        result = PinzhiMemberSync.map_to_golden_id(raw)

        assert result["name"] == "张三"
        assert result["level"] == "gold"
        assert result["balance_fen"] == 50000
        assert result["points"] == 1200
        assert result["total_consumption_fen"] == 380000
        assert result["visit_count"] == 15
        assert result["source_system"] == "pinzhi"

        # 三种身份标识
        id_types = {ident["type"] for ident in result["identities"]}
        assert id_types == {"phone", "pinzhi_card", "wechat_openid"}

    def test_merge_identity_dedup(self):
        """身份合并：去重 + 数值取大"""
        existing = {
            "name": "张三",
            "identities": [
                {"type": "phone", "value": "13800138000"},
            ],
            "balance_fen": 50000,
            "points": 1000,
            "total_consumption_fen": 200000,
            "visit_count": 10,
            "last_visit_date": "2024-05-01",
        }
        incoming = {
            "name": "张三丰",
            "identities": [
                {"type": "phone", "value": "13800138000"},  # 重复
                {"type": "wechat_openid", "value": "wx_new"},  # 新增
            ],
            "balance_fen": 30000,
            "points": 1500,
            "total_consumption_fen": 380000,
            "visit_count": 15,
            "last_visit_date": "2024-06-15",
        }
        merged = PinzhiMemberSync.merge_identity(existing, incoming)

        # 身份去重
        assert len(merged["identities"]) == 2
        # 名称以 incoming 为准
        assert merged["name"] == "张三丰"
        # 数值取大
        assert merged["balance_fen"] == 50000
        assert merged["points"] == 1500
        assert merged["total_consumption_fen"] == 380000
        assert merged["visit_count"] == 15
        # 日期取近
        assert merged["last_visit_date"] == "2024-06-15"


# ─── B5: 库存同步映射 ───


class TestInventorySync:
    def test_map_to_tunxiang_ingredient_basic(self):
        """基本食材映射：字段正确转换"""
        raw = {
            "ingredientId": "ING001",
            "ingredientName": "三文鱼",
            "ingredientCode": "SWY001",
            "category": "海鲜",
            "unit": "g",
            "unitPrice": 8000,
            "stockQty": 5000.0,
            "alertQty": 1000.0,
            "status": 1,
            "supplierId": "SUP01",
            "supplierName": "海鲜供应商",
            "shelfLifeDays": 3,
            "storageCondition": "refrigerated",
            "batchNo": "BATCH20240101",
        }
        result = PinzhiInventorySync.map_to_tunxiang_ingredient(raw)

        assert result["ingredient_id"] == "ING001"
        assert result["ingredient_name"] == "三文鱼"
        assert result["unit_price_fen"] == 8000
        assert result["stock_qty"] == 5000.0
        assert result["alert_qty"] == 1000.0
        assert result["status"] == "active"
        assert result["shelf_life_days"] == 3
        assert result["source_system"] == "pinzhi"

    def test_map_ingredient_from_practice(self):
        """从做法/配料数据映射食材（降级场景）"""
        raw = {
            "practiceId": "P001",
            "practiceName": "花椒",
            "unit": "g",
            "costPrice": 500,
            "quantity": 2000,
        }
        result = PinzhiInventorySync.map_to_tunxiang_ingredient(raw)

        assert result["ingredient_id"] == "P001"
        assert result["ingredient_name"] == "花椒"
        assert result["unit_price_fen"] == 500
        assert result["stock_qty"] == 2000.0
