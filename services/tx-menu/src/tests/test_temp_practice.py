"""临时做法（有价做法）模块测试 — v345

覆盖：
  1. build_customizations 做法加价计算（含多份加料）
  2. calc_practice_extra_fen 从 customizations 提取总加价
  3. 默认模板完整性检查
  4. ORM 模型字段验证
  5. 临时做法创建逻辑
  6. practice_routes 请求模型验证
"""


import pytest
from services.tx_trade.src.services.dish_practice_service import (
    DEFAULT_PRACTICE_TEMPLATES,
    build_customizations,
    calc_practice_extra_fen,
)

# ─── build_customizations 测试 ───


class TestBuildCustomizations:
    """测试 build_customizations — 做法 → OrderItem.customizations JSON"""

    def test_empty_practices(self):
        """无做法选择，加价为0"""
        result = build_customizations([])
        assert result["total_extra_price_fen"] == 0
        assert result["practices"] == []

    def test_single_free_practice(self):
        """单个免费做法（微辣），加价为0"""
        result = build_customizations([
            {
                "practice_id": "p-001",
                "name": "微辣",
                "additional_price_fen": 0,
            }
        ])
        assert result["total_extra_price_fen"] == 0
        assert len(result["practices"]) == 1
        assert result["practices"][0]["name"] == "微辣"
        assert result["practices"][0]["quantity"] == 1
        assert result["practices"][0]["line_price_fen"] == 0

    def test_single_paid_practice(self):
        """单个有价做法（特辣+2元），加价200分"""
        result = build_customizations([
            {
                "practice_id": "p-002",
                "name": "特辣",
                "additional_price_fen": 200,
            }
        ])
        assert result["total_extra_price_fen"] == 200
        assert result["practices"][0]["line_price_fen"] == 200

    def test_multiple_practices_mixed(self):
        """混合做法：微辣(免费) + 加蛋(200分) + 加芝士(300分)"""
        result = build_customizations([
            {"practice_id": "p-001", "name": "微辣", "additional_price_fen": 0},
            {"practice_id": "p-002", "name": "加蛋", "additional_price_fen": 200},
            {"practice_id": "p-003", "name": "加芝士", "additional_price_fen": 300},
        ])
        assert result["total_extra_price_fen"] == 500
        assert len(result["practices"]) == 3

    def test_addon_multi_quantity(self):
        """加料多份场景：加蛋x3（每份200分 = 600分）"""
        result = build_customizations([
            {
                "practice_id": "p-egg",
                "name": "加蛋",
                "additional_price_fen": 200,
                "quantity": 3,
                "practice_type": "addon",
            }
        ])
        assert result["total_extra_price_fen"] == 600
        assert result["practices"][0]["quantity"] == 3
        assert result["practices"][0]["line_price_fen"] == 600

    def test_addon_multi_quantity_with_free(self):
        """加蛋x2(400分) + 不要香菜(免费) = 总加价400分"""
        result = build_customizations([
            {"practice_id": "p-egg", "name": "加蛋", "additional_price_fen": 200, "quantity": 2},
            {"practice_id": "p-no-cilantro", "name": "不要香菜", "additional_price_fen": 0},
        ])
        assert result["total_extra_price_fen"] == 400
        assert len(result["practices"]) == 2

    def test_practice_name_fallback(self):
        """使用 practice_name 字段而非 name"""
        result = build_customizations([
            {"id": "p-001", "practice_name": "半糖", "additional_price_fen": 0}
        ])
        assert result["practices"][0]["name"] == "半糖"
        assert result["practices"][0]["practice_id"] == "p-001"

    def test_temporary_practice_flag(self):
        """临时做法标记正确传递"""
        result = build_customizations([
            {
                "practice_id": "p-tmp",
                "name": "加辣椒酱",
                "additional_price_fen": 300,
                "practice_type": "temporary",
                "is_temporary": True,
            }
        ])
        assert result["practices"][0]["is_temporary"] is True
        assert result["practices"][0]["practice_type"] == "temporary"
        assert result["total_extra_price_fen"] == 300


# ─── calc_practice_extra_fen 测试 ───


class TestCalcPracticeExtraFen:
    """测试 calc_practice_extra_fen — 从 customizations 提取加价"""

    def test_empty_customizations(self):
        """空 customizations，返回0"""
        assert calc_practice_extra_fen({}) == 0

    def test_no_practices_key(self):
        """customizations 不含 total_extra_price_fen，返回0"""
        assert calc_practice_extra_fen({"some_key": "value"}) == 0

    def test_with_extra_price(self):
        """正常提取加价"""
        cust = build_customizations([
            {"practice_id": "p1", "name": "加蛋", "additional_price_fen": 200, "quantity": 2}
        ])
        assert calc_practice_extra_fen(cust) == 400

    def test_zero_extra_price(self):
        """纯免费做法，加价为0"""
        cust = build_customizations([
            {"practice_id": "p1", "name": "微辣", "additional_price_fen": 0}
        ])
        assert calc_practice_extra_fen(cust) == 0


# ─── 默认模板测试 ───


class TestDefaultTemplates:
    """验证默认做法模板的完整性和一致性"""

    def test_template_count(self):
        """默认模板包含13个做法"""
        assert len(DEFAULT_PRACTICE_TEMPLATES) == 13

    def test_template_groups(self):
        """模板覆盖4个分组：辣度/甜度/忌口/加料"""
        groups = {t["practice_group"] for t in DEFAULT_PRACTICE_TEMPLATES}
        assert groups == {"辣度", "甜度", "忌口", "加料"}

    def test_spicy_group_count(self):
        """辣度组4个选项"""
        spicy = [t for t in DEFAULT_PRACTICE_TEMPLATES if t["practice_group"] == "辣度"]
        assert len(spicy) == 4

    def test_addon_has_price(self):
        """加料类做法必须有加价"""
        addons = [t for t in DEFAULT_PRACTICE_TEMPLATES if t["practice_group"] == "加料"]
        assert all(t["additional_price_fen"] > 0 for t in addons)

    def test_addon_max_quantity_gt_1(self):
        """加料类做法 max_quantity > 1"""
        addons = [t for t in DEFAULT_PRACTICE_TEMPLATES if t["practice_group"] == "加料"]
        assert all(t["max_quantity"] > 1 for t in addons)

    def test_avoid_group_all_free(self):
        """忌口类做法全部免费"""
        avoids = [t for t in DEFAULT_PRACTICE_TEMPLATES if t["practice_group"] == "忌口"]
        assert all(t["additional_price_fen"] == 0 for t in avoids)

    def test_required_fields(self):
        """每个模板必须包含必要字段"""
        required = {"practice_name", "practice_group", "additional_price_fen", "practice_type", "max_quantity"}
        for tpl in DEFAULT_PRACTICE_TEMPLATES:
            assert required.issubset(tpl.keys()), f"模板 {tpl['practice_name']} 缺少字段"

    def test_practice_type_values(self):
        """practice_type 只能是 standard/temporary/addon"""
        valid_types = {"standard", "temporary", "addon"}
        for tpl in DEFAULT_PRACTICE_TEMPLATES:
            assert tpl["practice_type"] in valid_types, f"{tpl['practice_name']} type={tpl['practice_type']}"


# ─── ORM 模型字段测试 ───


class TestDishPracticeModel:
    """验证 DishPractice ORM 模型的 v345 新字段"""

    def test_model_has_new_fields(self):
        """DishPractice 模型包含 v345 新增的三个字段"""
        from services.tx_menu.src.models.dish_practice import DishPractice

        # 检查类属性存在（mapped_column 注册后的 InstrumentedAttribute）
        assert hasattr(DishPractice, "is_temporary")
        assert hasattr(DishPractice, "practice_type")
        assert hasattr(DishPractice, "max_quantity")

    def test_model_tablename(self):
        """确认表名为 dish_practices"""
        from services.tx_menu.src.models.dish_practice import DishPractice

        assert DishPractice.__tablename__ == "dish_practices"


# ─── 请求模型验证测试 ───


class TestPracticeRequestModels:
    """验证 practice_routes 的 Pydantic 请求模型"""

    def test_practice_item_defaults(self):
        """PracticeItem 默认值正确"""
        from services.tx_menu.src.api.practice_routes import PracticeItem

        item = PracticeItem(practice_name="微辣")
        assert item.practice_group == "default"
        assert item.additional_price_fen == 0
        assert item.is_default is False
        assert item.sort_order == 0
        assert item.practice_type == "standard"
        assert item.max_quantity == 1

    def test_practice_item_addon(self):
        """加料类 PracticeItem"""
        from services.tx_menu.src.api.practice_routes import PracticeItem

        item = PracticeItem(
            practice_name="加蛋",
            practice_group="加料",
            additional_price_fen=200,
            practice_type="addon",
            max_quantity=3,
        )
        assert item.additional_price_fen == 200
        assert item.max_quantity == 3

    def test_practice_item_negative_price_rejected(self):
        """加价不能为负数"""
        from services.tx_menu.src.api.practice_routes import PracticeItem

        with pytest.raises(ValueError):
            PracticeItem(practice_name="测试", additional_price_fen=-100)

    def test_temp_practice_req(self):
        """TempPracticeReq 模型验证"""
        from services.tx_menu.src.api.practice_routes import TempPracticeReq

        req = TempPracticeReq(
            practice_name="加辣椒酱",
            additional_price_fen=300,
        )
        assert req.practice_group == "临时做法"
        assert req.max_quantity == 1

    def test_temp_practice_req_negative_price_rejected(self):
        """临时做法加价不能为负数"""
        from services.tx_menu.src.api.practice_routes import TempPracticeReq

        with pytest.raises(ValueError):
            TempPracticeReq(practice_name="测试", additional_price_fen=-50)


# ─── 下单加价集成逻辑测试 ───


class TestOrderPracticeSurcharge:
    """测试做法加价在下单流程中的计算逻辑"""

    def test_subtotal_includes_practice_surcharge(self):
        """模拟：菜品单价2800分 x 1份 + 做法加价(加蛋200x2 + 特辣200) = 3400分"""
        unit_price_fen = 2800
        qty = 1
        customizations = build_customizations([
            {"practice_id": "p1", "name": "加蛋", "additional_price_fen": 200, "quantity": 2},
            {"practice_id": "p2", "name": "特辣", "additional_price_fen": 200},
        ])

        # 模拟 order_service.add_item 的计算逻辑
        practice_extra_fen = calc_practice_extra_fen(customizations)
        subtotal_fen = unit_price_fen * qty + practice_extra_fen

        assert practice_extra_fen == 600
        assert subtotal_fen == 3400

    def test_no_customizations_no_surcharge(self):
        """无做法选择时，小计 = 单价 x 数量"""
        unit_price_fen = 1800
        qty = 2
        practice_extra_fen = calc_practice_extra_fen({})
        subtotal_fen = unit_price_fen * qty + practice_extra_fen

        assert practice_extra_fen == 0
        assert subtotal_fen == 3600

    def test_weighted_pricing_with_practice(self):
        """称重菜品 + 做法加价"""
        unit_price_fen = 5000  # 50元/斤
        weight = 1.5
        customizations = build_customizations([
            {"practice_id": "p1", "name": "加芝士", "additional_price_fen": 300},
        ])

        weighted_subtotal = round(unit_price_fen * weight)
        practice_extra = calc_practice_extra_fen(customizations)
        total = weighted_subtotal + practice_extra

        assert weighted_subtotal == 7500
        assert practice_extra == 300
        assert total == 7800


# ─── KDS 做法显示测试 ───


class TestKDSPracticeDisplay:
    """测试 KDS 分单时做法信息的格式化"""

    def test_kds_practice_display_format(self):
        """验证 KDS 做法显示格式"""
        customizations = build_customizations([
            {"practice_id": "p1", "name": "微辣", "additional_price_fen": 0},
            {"practice_id": "p2", "name": "加蛋", "additional_price_fen": 200, "quantity": 2},
            {"practice_id": "p3", "name": "不要香菜", "additional_price_fen": 0},
        ])

        # 模拟 kds_dispatch.py 中的显示逻辑
        practices_display = []
        for prac in customizations["practices"]:
            label = prac.get("name", "")
            qty = prac.get("quantity", 1)
            price = prac.get("additional_price_fen", 0)
            if qty > 1:
                label = f"{label}x{qty}"
            if price > 0:
                label = f"{label}(+{price / 100:.0f}元)"
            practices_display.append(label)

        assert practices_display == ["微辣", "加蛋x2(+2元)", "不要香菜"]
