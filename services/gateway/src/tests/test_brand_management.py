"""多品牌经营中台测试 (U2.3)

测试场景：徐记海鲜集团
- 品牌A: 徐记海鲜（高端正餐）
- 品牌B: 徐记·南洋（东南亚菜）
- 品牌C: 徐记·海鲜工坊（快餐/外卖）
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brand_management import BrandManagementService

GROUP_ID = "grp_xuji"


def _make_service_with_brands():
    """创建带三个品牌的服务实例"""
    svc = BrandManagementService()
    b1 = svc.create_brand(GROUP_ID, "徐记海鲜", "fine_dining", description="高端海鲜正餐")
    b2 = svc.create_brand(GROUP_ID, "徐记·南洋", "casual", description="东南亚风味")
    b3 = svc.create_brand(GROUP_ID, "徐记·海鲜工坊", "fast_food", description="海鲜快餐外卖")
    return svc, b1, b2, b3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. Brand Registry
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestBrandRegistry:
    def test_create_brand(self):
        svc = BrandManagementService()
        brand = svc.create_brand(
            GROUP_ID, "徐记海鲜", "fine_dining",
            description="高端海鲜正餐",
            logo_url="https://cdn.xuji.com/logo.png",
            theme_colors={"primary": "#1E3A5F", "secondary": "#C0963C"},
        )
        assert brand["brand_name"] == "徐记海鲜"
        assert brand["business_type"] == "fine_dining"
        assert brand["status"] == "launching"
        assert brand["brand_id"].startswith("brand_")
        assert brand["theme_colors"]["primary"] == "#1E3A5F"

    def test_create_brand_invalid_type(self):
        svc = BrandManagementService()
        try:
            svc.create_brand(GROUP_ID, "测试", "invalid_type")
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "无效业态" in str(e)

    def test_list_brands(self):
        svc, b1, b2, b3 = _make_service_with_brands()
        brands = svc.list_brands(GROUP_ID)
        assert len(brands) == 3
        names = {b["brand_name"] for b in brands}
        assert "徐记海鲜" in names
        assert "徐记·南洋" in names
        assert "徐记·海鲜工坊" in names

    def test_list_brands_filter_by_group(self):
        svc, _, _, _ = _make_service_with_brands()
        svc.create_brand("grp_other", "其他品牌", "casual")
        assert len(svc.list_brands(GROUP_ID)) == 3
        assert len(svc.list_brands("grp_other")) == 1

    def test_get_brand_detail(self):
        svc, b1, _, _ = _make_service_with_brands()
        detail = svc.get_brand_detail(b1["brand_id"])
        assert detail["brand_name"] == "徐记海鲜"
        assert detail["description"] == "高端海鲜正餐"

    def test_get_brand_not_found(self):
        svc = BrandManagementService()
        try:
            svc.get_brand_detail("nonexistent")
            assert False, "Should raise ValueError"
        except ValueError:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. Menu Template Inheritance
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMenuInheritance:
    """
    测试菜单继承链:
    集团菜单: 红烧肉¥68, 剁椒鱼头¥168, 蒜蓉虾¥128
    品牌A(徐记海鲜): 红烧肉→¥78, +龙虾刺身¥388
    品牌A·芙蓉路店: 剁椒鱼头→¥188, -蒜蓉虾(供应不稳定)
    """

    def _setup(self):
        svc, b1, b2, b3 = _make_service_with_brands()

        # 集团主菜单
        master = svc.create_master_menu(GROUP_ID, "徐记集团标准菜单", [
            {"dish_id": "d001", "name": "红烧肉", "price_fen": 6800, "category": "热菜"},
            {"dish_id": "d002", "name": "剁椒鱼头", "price_fen": 16800, "category": "招牌"},
            {"dish_id": "d003", "name": "蒜蓉虾", "price_fen": 12800, "category": "海鲜"},
        ])

        # 品牌A覆盖
        brand_menu = svc.create_brand_menu(b1["brand_id"], master["menu_id"], [
            {"dish_id": "d001", "action": "override", "price_fen": 7800},
            {"dish_id": "d_lobster", "action": "add", "name": "龙虾刺身", "price_fen": 38800, "category": "刺身"},
        ])

        # 门店覆盖
        store_menu = svc.create_store_menu("store_furong", brand_menu["menu_id"], [
            {"dish_id": "d002", "action": "override", "price_fen": 18800},
            {"dish_id": "d003", "action": "remove"},
        ])

        return svc, master, brand_menu, store_menu

    def test_create_master_menu(self):
        svc = BrandManagementService()
        master = svc.create_master_menu(GROUP_ID, "测试菜单", [
            {"dish_id": "d1", "name": "测试菜", "price_fen": 1000},
        ])
        assert master["menu_id"].startswith("mm_")
        assert master["item_count"] == 1
        assert master["menu_level"] == "master"

    def test_create_brand_menu(self):
        svc, b1, _, _ = _make_service_with_brands()
        master = svc.create_master_menu(GROUP_ID, "菜单", [])
        bm = svc.create_brand_menu(b1["brand_id"], master["menu_id"], [])
        assert bm["menu_level"] == "brand"
        assert bm["parent_menu_id"] == master["menu_id"]

    def test_create_brand_menu_invalid_parent(self):
        svc, b1, _, _ = _make_service_with_brands()
        try:
            svc.create_brand_menu(b1["brand_id"], "nonexistent", [])
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_resolve_effective_menu_full_chain(self):
        svc, master, brand_menu, store_menu = self._setup()
        effective = svc.resolve_effective_menu("store_furong")

        # 应有3个菜品（红烧肉、剁椒鱼头、龙虾刺身；蒜蓉虾已移除）
        names = {item["name"] for item in effective}
        assert "红烧肉" in names
        assert "剁椒鱼头" in names
        assert "龙虾刺身" in names
        assert "蒜蓉虾" not in names
        assert len(effective) == 3

    def test_price_override_chain(self):
        svc, master, brand_menu, store_menu = self._setup()
        effective = svc.resolve_effective_menu("store_furong")
        menu_map = {item["name"]: item for item in effective}

        # 红烧肉：集团68→品牌78（品牌覆盖，门店未覆盖）
        assert menu_map["红烧肉"]["price_fen"] == 7800

        # 剁椒鱼头：集团168→品牌继承168→门店覆盖188
        assert menu_map["剁椒鱼头"]["price_fen"] == 18800

        # 龙虾刺身：品牌新增388→门店继承
        assert menu_map["龙虾刺身"]["price_fen"] == 38800

    def test_source_tracking(self):
        svc, master, brand_menu, store_menu = self._setup()
        effective = svc.resolve_effective_menu("store_furong")
        menu_map = {item["name"]: item for item in effective}

        # 红烧肉由品牌覆盖
        assert menu_map["红烧肉"]["source"] == "brand"
        # 剁椒鱼头由门店覆盖
        assert menu_map["剁椒鱼头"]["source"] == "store"
        # 龙虾刺身由品牌新增
        assert menu_map["龙虾刺身"]["source"] == "brand"

    def test_store_menu_not_found(self):
        svc = BrandManagementService()
        try:
            svc.resolve_effective_menu("nonexistent_store")
            assert False, "Should raise ValueError"
        except ValueError:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. Cross-brand Member
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCrossBrandMember:
    def _setup(self):
        svc, b1, b2, b3 = _make_service_with_brands()
        member = svc.link_member_across_brands("m001", [b1["brand_id"], b2["brand_id"], b3["brand_id"]])
        # 注入积分
        svc._set_member_points("m001", b1["brand_id"], 5000)
        svc._set_member_points("m001", b2["brand_id"], 2000)
        svc._set_member_points("m001", b3["brand_id"], 1000)
        return svc, b1, b2, b3

    def test_link_member(self):
        svc, b1, b2, b3 = _make_service_with_brands()
        member = svc.link_member_across_brands("m001", [b1["brand_id"], b2["brand_id"]])
        assert len(member["linked_brands"]) == 2
        assert member["member_id"] == "m001"

    def test_link_member_min_brands(self):
        svc, b1, _, _ = _make_service_with_brands()
        try:
            svc.link_member_across_brands("m001", [b1["brand_id"]])
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "至少" in str(e)

    def test_link_member_invalid_brand(self):
        svc, b1, _, _ = _make_service_with_brands()
        try:
            svc.link_member_across_brands("m001", [b1["brand_id"], "fake_brand"])
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_transfer_points(self):
        svc, b1, b2, b3 = self._setup()

        # 从徐记海鲜转1000积分到徐记·南洋
        record = svc.transfer_points("m001", b1["brand_id"], b2["brand_id"], 1000, exchange_rate=1.0)
        assert record["points_out"] == 1000
        assert record["points_in"] == 1000

        profile = svc.get_member_cross_brand_profile("m001")
        assert profile["points_by_brand"][b1["brand_id"]] == 4000
        assert profile["points_by_brand"][b2["brand_id"]] == 3000
        assert profile["total_points"] == 8000  # 4000+3000+1000

    def test_transfer_points_with_exchange_rate(self):
        svc, b1, b2, b3 = self._setup()

        # 高端品牌到快餐品牌，1:1.5兑换
        record = svc.transfer_points("m001", b1["brand_id"], b3["brand_id"], 1000, exchange_rate=1.5)
        assert record["points_out"] == 1000
        assert record["points_in"] == 1500

        profile = svc.get_member_cross_brand_profile("m001")
        assert profile["points_by_brand"][b1["brand_id"]] == 4000
        assert profile["points_by_brand"][b3["brand_id"]] == 2500

    def test_transfer_insufficient_points(self):
        svc, b1, b2, _ = self._setup()
        try:
            svc.transfer_points("m001", b1["brand_id"], b2["brand_id"], 99999)
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "积分不足" in str(e)

    def test_transfer_same_brand(self):
        svc, b1, _, _ = self._setup()
        try:
            svc.transfer_points("m001", b1["brand_id"], b1["brand_id"], 100)
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "不能相同" in str(e)

    def test_get_cross_brand_profile(self):
        svc, b1, b2, b3 = self._setup()
        profile = svc.get_member_cross_brand_profile("m001")
        assert profile["total_points"] == 8000
        assert len(profile["linked_brands"]) == 3
        assert profile["points_by_brand"][b1["brand_id"]] == 5000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. Unified Procurement
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestUnifiedProcurement:
    def _make_plan(self):
        svc = BrandManagementService()
        plan = svc.create_group_procurement_plan(GROUP_ID, [
            {
                "ingredient_id": "ing_bass",
                "name": "鲈鱼",
                "unit": "kg",
                "demands": [
                    {"brand_id": "b1", "store_id": "s_furong", "quantity": 50},
                    {"brand_id": "b1", "store_id": "s_wuyi", "quantity": 30},
                    {"brand_id": "b2", "store_id": "s_nanyang", "quantity": 20},
                ],
                "estimated_unit_price_fen": 3500,
            },
            {
                "ingredient_id": "ing_shrimp",
                "name": "基围虾",
                "unit": "kg",
                "demands": [
                    {"brand_id": "b1", "store_id": "s_furong", "quantity": 40},
                    {"brand_id": "b2", "store_id": "s_nanyang", "quantity": 25},
                ],
                "estimated_unit_price_fen": 5600,
            },
        ])
        return svc, plan

    def test_create_procurement_plan(self):
        svc, plan = self._make_plan()
        assert plan["plan_id"].startswith("gpp_")
        assert plan["item_count"] == 2
        assert plan["status"] == "draft"

        # 鲈鱼: (50+30+20) * 3500 = 350000
        # 基围虾: (40+25) * 5600 = 364000
        assert plan["total_estimated_fen"] == 350000 + 364000

    def test_split_delivery(self):
        svc, plan = self._make_plan()
        deliveries = svc.split_delivery(plan["plan_id"])

        # 3个门店
        store_ids = {d["store_id"] for d in deliveries}
        assert store_ids == {"s_furong", "s_wuyi", "s_nanyang"}

        # 芙蓉路店：鲈鱼50kg + 基围虾40kg
        furong = next(d for d in deliveries if d["store_id"] == "s_furong")
        assert len(furong["items"]) == 2
        assert furong["total_fen"] == 50 * 3500 + 40 * 5600

        # 五一店：仅鲈鱼30kg
        wuyi = next(d for d in deliveries if d["store_id"] == "s_wuyi")
        assert len(wuyi["items"]) == 1
        assert wuyi["total_fen"] == 30 * 3500

    def test_split_delivery_invalid_plan(self):
        svc = BrandManagementService()
        try:
            svc.split_delivery("nonexistent")
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_allocate_cost(self):
        svc, plan = self._make_plan()
        allocation = svc.allocate_cost(plan["plan_id"])

        assert allocation["total_cost_fen"] == plan["total_estimated_fen"]

        # 品牌级分摊
        b1_cost = allocation["brand_allocation"]["b1"]["cost_fen"]
        b2_cost = allocation["brand_allocation"]["b2"]["cost_fen"]
        assert b1_cost + b2_cost == plan["total_estimated_fen"]

        # b1: 鲈鱼(50+30)*3500 + 基围虾40*5600 = 280000 + 224000 = 504000
        assert b1_cost == 504000
        # b2: 鲈鱼20*3500 + 基围虾25*5600 = 70000 + 140000 = 210000
        assert b2_cost == 210000

        # 比率验证
        total = plan["total_estimated_fen"]
        assert abs(allocation["brand_allocation"]["b1"]["ratio"] - 504000 / total) < 0.001


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. Brand Comparison Analytics
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestBrandComparison:
    def _setup(self):
        svc, b1, b2, b3 = _make_service_with_brands()

        # 注入经营数据
        svc._set_brand_metrics(b1["brand_id"], {
            "revenue": 5000000,
            "profit_margin": 28.5,
            "table_turnover": 3.2,
            "customer_satisfaction": 92,
            "labor_efficiency": 85,
            "waste_rate": 3.1,
            "revenue_fen": 500000000,
            "employee_count": 320,
            "member_count": 50000,
        })
        svc._set_brand_metrics(b2["brand_id"], {
            "revenue": 2000000,
            "profit_margin": 22.0,
            "table_turnover": 4.1,
            "customer_satisfaction": 88,
            "labor_efficiency": 78,
            "waste_rate": 4.5,
            "revenue_fen": 200000000,
            "employee_count": 120,
            "member_count": 18000,
        })
        svc._set_brand_metrics(b3["brand_id"], {
            "revenue": 800000,
            "profit_margin": 18.0,
            "table_turnover": 6.5,
            "customer_satisfaction": 82,
            "labor_efficiency": 90,
            "waste_rate": 2.0,
            "revenue_fen": 80000000,
            "employee_count": 45,
            "member_count": 8000,
        })

        b1["store_count"] = 15
        b2["store_count"] = 8
        b3["store_count"] = 5

        return svc, b1, b2, b3

    def test_compare_brands(self):
        svc, b1, b2, b3 = self._setup()
        result = svc.compare_brands(
            GROUP_ID,
            ["revenue", "profit_margin", "table_turnover"],
            {"start": "2026-01-01", "end": "2026-03-31"},
        )
        assert len(result["brands"]) == 3
        assert "group_average" in result

        # 集团平均毛利率
        avg_margin = result["group_average"]["profit_margin"]
        assert abs(avg_margin - (28.5 + 22.0 + 18.0) / 3) < 0.1

    def test_get_brand_ranking(self):
        svc, b1, b2, b3 = self._setup()
        ranking = svc.get_brand_ranking(GROUP_ID, "revenue")
        assert ranking[0]["rank"] == 1
        assert ranking[0]["brand_id"] == b1["brand_id"]  # 徐记海鲜营收最高
        assert ranking[-1]["rank"] == 3

    def test_detect_brand_anomaly(self):
        svc, b1, b2, b3 = self._setup()

        # 海鲜工坊的 revenue=800000 vs 平均 (5000000+2000000+800000)/3=2600000
        # 800000 < 2600000 * 0.7 = 1820000 => 异常
        anomalies = svc.detect_brand_anomaly(GROUP_ID)
        revenue_anomalies = [a for a in anomalies if a["metric"] == "revenue"]
        assert len(revenue_anomalies) >= 1
        assert any(a["brand_name"] == "徐记·海鲜工坊" for a in revenue_anomalies)

    def test_no_anomaly_with_similar_brands(self):
        svc = BrandManagementService()
        b1 = svc.create_brand(GROUP_ID, "品牌A", "casual")
        b2 = svc.create_brand(GROUP_ID, "品牌B", "casual")
        svc._set_brand_metrics(b1["brand_id"], {"revenue": 1000, "profit_margin": 25, "customer_satisfaction": 90, "table_turnover": 3})
        svc._set_brand_metrics(b2["brand_id"], {"revenue": 1100, "profit_margin": 26, "customer_satisfaction": 91, "table_turnover": 3})
        anomalies = svc.detect_brand_anomaly(GROUP_ID)
        assert len(anomalies) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. Group Dashboard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGroupDashboard:
    def test_get_group_overview(self):
        svc, b1, b2, b3 = _make_service_with_brands()

        svc._set_brand_metrics(b1["brand_id"], {
            "revenue_fen": 500000000,
            "employee_count": 320,
            "member_count": 50000,
            "profit_margin": 28.5,
        })
        svc._set_brand_metrics(b2["brand_id"], {
            "revenue_fen": 200000000,
            "employee_count": 120,
            "member_count": 18000,
            "profit_margin": 22.0,
        })
        svc._set_brand_metrics(b3["brand_id"], {
            "revenue_fen": 80000000,
            "employee_count": 45,
            "member_count": 8000,
            "profit_margin": 12.0,  # 低于15%警戒线
        })

        overview = svc.get_group_overview(GROUP_ID)

        assert overview["total_revenue_fen"] == 780000000
        assert overview["total_employees"] == 485
        assert overview["total_members"] == 76000
        assert overview["brand_count"] == 3

        # 品牌按营收排序
        assert overview["brand_breakdown"][0]["brand_name"] == "徐记海鲜"

        # 风险提示：海鲜工坊毛利率12%低于15%
        assert len(overview["risk_alerts"]) >= 1
        assert any("海鲜工坊" in a["message"] for a in overview["risk_alerts"])

    def test_empty_group(self):
        svc = BrandManagementService()
        overview = svc.get_group_overview("empty_group")
        assert overview["total_revenue_fen"] == 0
        assert overview["brand_count"] == 0
        assert overview["brand_breakdown"] == []
