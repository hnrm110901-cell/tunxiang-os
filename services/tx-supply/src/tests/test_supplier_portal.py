"""供应链深度管理测试 (U2.4)

测试场景：徐记海鲜集团供应链
- 供应商: 湘江渔港(海鲜)、马王堆市场(蔬菜)、新农都冻品(冻品)
- 食材: 鲈鱼、基围虾、波士顿龙虾、空心菜、冻鱿鱼
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.supplier_portal_service import SupplierPortalService

STORE_ID = "store_furong"


def _make_service_with_suppliers():
    """创建带供应商的服务实例"""
    svc = SupplierPortalService()

    s1 = svc.register_supplier(
        "湘江渔港水产", "seafood",
        {"person": "张海生", "phone": "13812345678", "address": "长沙市望城区渔港路88号"},
        ["食品经营许可证", "水产品检验检疫证", "ISO22000", "HACCP"],
        "net30",
    )
    s2 = svc.register_supplier(
        "马王堆蔬菜批发", "vegetable",
        {"person": "李菜农", "phone": "13987654321", "address": "长沙市芙蓉区马王堆路"},
        ["食品经营许可证", "有机认证"],
        "cod",
    )
    s3 = svc.register_supplier(
        "新农都冻品中心", "frozen",
        {"person": "王冻品", "phone": "13611112222", "address": "长沙市开福区新农都"},
        ["食品经营许可证", "冷链运输资质", "ISO22000"],
        "net60",
    )

    return svc, s1, s2, s3


def _inject_delivery_records(svc, supplier_id, count=20, on_time_rate=0.9, quality_rate=0.95):
    """注入交付记录"""
    import random
    random.seed(42)

    for i in range(count):
        day = f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}"
        svc._add_delivery_record(supplier_id, {
            "date": day,
            "on_time": random.random() < on_time_rate,
            "quality": "pass" if random.random() < quality_rate else "fail",
            "ingredient": "鲈鱼" if i % 3 == 0 else "基围虾" if i % 3 == 1 else "空心菜",
            "total_fen": random.randint(50000, 200000),
            "price_competitiveness": random.randint(65, 95),
            "service_rating": random.randint(70, 95),
            "price_adherence": True,
        })


def _inject_price_history(svc, ingredient, base_price, count=30, volatility=0.05):
    """注入价格历史"""
    import random
    random.seed(123)

    entries = []
    price = base_price
    for i in range(count):
        day = f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}"
        fluctuation = random.uniform(-volatility, volatility)
        price = int(base_price * (1 + fluctuation))
        entries.append({
            "date": f"{day}T00:00:00+00:00",
            "supplier_id": "any",
            "price_fen": price,
        })

    svc._add_price_history(ingredient, entries)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. Supplier Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSupplierManagement:
    def test_register_supplier(self):
        svc = SupplierPortalService()
        s = svc.register_supplier(
            "湘江渔港水产", "seafood",
            {"person": "张海生", "phone": "138xxx"},
            ["食品经营许可证", "ISO22000"],
        )
        assert s["supplier_id"].startswith("sup_")
        assert s["name"] == "湘江渔港水产"
        assert s["category"] == "seafood"
        assert s["status"] == "active"
        assert len(s["certifications"]) == 2

    def test_register_invalid_category(self):
        svc = SupplierPortalService()
        try:
            svc.register_supplier("测试", "invalid_cat", {}, [])
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "无效供应商类别" in str(e)

    def test_list_suppliers(self):
        svc, s1, s2, s3 = _make_service_with_suppliers()
        all_suppliers = svc.list_suppliers()
        assert len(all_suppliers) == 3

    def test_list_suppliers_by_category(self):
        svc, s1, s2, s3 = _make_service_with_suppliers()
        seafood = svc.list_suppliers(category="seafood")
        assert len(seafood) == 1
        assert seafood[0]["name"] == "湘江渔港水产"

    def test_list_suppliers_by_rating(self):
        svc, s1, s2, s3 = _make_service_with_suppliers()
        # 注入评分
        svc._suppliers[s1["supplier_id"]]["overall_score"] = 90
        svc._suppliers[s2["supplier_id"]]["overall_score"] = 70
        svc._suppliers[s3["supplier_id"]]["overall_score"] = 50

        high_rated = svc.list_suppliers(rating_min=75)
        assert len(high_rated) == 1
        assert high_rated[0]["name"] == "湘江渔港水产"

    def test_get_supplier_profile(self):
        svc, s1, _, _ = _make_service_with_suppliers()
        _inject_delivery_records(svc, s1["supplier_id"], count=10)

        profile = svc.get_supplier_profile(s1["supplier_id"])
        assert profile["name"] == "湘江渔港水产"
        assert profile["total_deliveries"] == 10
        assert 0 <= profile["on_time_rate"] <= 1
        assert 0 <= profile["quality_pass_rate"] <= 1

    def test_get_supplier_not_found(self):
        svc = SupplierPortalService()
        try:
            svc.get_supplier_profile("nonexistent")
            assert False
        except ValueError:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. Auto Bidding
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAutoBidding:
    def _setup_rfq(self):
        svc, s1, s2, s3 = _make_service_with_suppliers()
        # 注入可靠性数据
        _inject_delivery_records(svc, s1["supplier_id"], count=20, on_time_rate=0.95, quality_rate=0.98)
        _inject_delivery_records(svc, s3["supplier_id"], count=15, on_time_rate=0.7, quality_rate=0.8)

        rfq = svc.request_quotes("波士顿龙虾", 100, "2026-04-01",
                                  [s1["supplier_id"], s3["supplier_id"]])

        svc._submit_quote(rfq["rfq_id"], s1["supplier_id"], 18000, 3, "空运新鲜直达")
        svc._submit_quote(rfq["rfq_id"], s3["supplier_id"], 15000, 5, "冻品发货")

        return svc, rfq, s1, s3

    def test_request_quotes(self):
        svc, s1, s2, s3 = _make_service_with_suppliers()
        rfq = svc.request_quotes("鲈鱼", 50, "2026-04-01")
        assert rfq["rfq_id"].startswith("rfq_")
        assert rfq["item_name"] == "鲈鱼"
        assert rfq["status"] == "open"
        assert len(rfq["supplier_ids"]) == 3  # 所有活跃供应商

    def test_request_quotes_specified_suppliers(self):
        svc, s1, s2, _ = _make_service_with_suppliers()
        rfq = svc.request_quotes("鲈鱼", 50, "2026-04-01", [s1["supplier_id"]])
        assert len(rfq["supplier_ids"]) == 1

    def test_compare_quotes(self):
        svc, rfq, s1, s3 = self._setup_rfq()
        comparison = svc.compare_quotes(rfq["rfq_id"])

        assert comparison["item_name"] == "波士顿龙虾"
        assert len(comparison["quotes"]) == 2
        assert comparison["recommended"] is not None
        assert comparison["recommended"]["supplier_id"] in [s1["supplier_id"], s3["supplier_id"]]

        # 每个报价应有评分
        for q in comparison["quotes"]:
            assert "price_score" in q
            assert "delivery_score" in q
            assert "reliability_score" in q
            assert "composite_score" in q

    def test_compare_quotes_no_quotes(self):
        svc, s1, _, _ = _make_service_with_suppliers()
        rfq = svc.request_quotes("空心菜", 100, "2026-04-01", [s1["supplier_id"]])
        # 不提交任何报价
        result = svc.compare_quotes(rfq["rfq_id"])
        assert result["recommended"] is None
        assert "无供应商报价" in result["reason"]

    def test_accept_quote(self):
        svc, rfq, s1, _ = self._setup_rfq()
        result = svc.accept_quote(rfq["rfq_id"], s1["supplier_id"])
        assert result["status"] == "accepted"
        assert result["supplier_id"] == s1["supplier_id"]
        assert result["unit_price_fen"] == 18000
        assert result["total_price_fen"] == 1800000  # 18000 * 100

    def test_accept_invalid_rfq(self):
        svc = SupplierPortalService()
        try:
            svc.accept_quote("nonexistent", "sup1")
            assert False
        except ValueError:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. Contract Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestContractManagement:
    def _setup(self):
        svc, s1, s2, s3 = _make_service_with_suppliers()

        contract = svc.create_contract(
            s1["supplier_id"],
            [
                {"ingredient_id": "ing_bass", "name": "鲈鱼", "agreed_price_fen": 3500, "min_quantity": 100, "unit": "kg"},
                {"ingredient_id": "ing_shrimp", "name": "基围虾", "agreed_price_fen": 5600, "min_quantity": 50, "unit": "kg"},
            ],
            "2026-01-01", "2026-06-30",
            pricing_terms="季度固定价，市场波动超10%可协商调整",
            payment_terms="net30",
            penalties={"late_delivery_pct": 5, "quality_failure_pct": 10, "max_penalty_pct": 30},
        )
        return svc, s1, contract

    def test_create_contract(self):
        svc, s1, contract = self._setup()
        assert contract["contract_id"].startswith("ct_")
        assert contract["supplier_name"] == "湘江渔港水产"
        assert contract["item_count"] == 2
        assert contract["status"] == "active"
        assert contract["duration_days"] in (180, 181)  # date math boundary

    def test_create_contract_invalid_dates(self):
        svc, s1, _, _ = _make_service_with_suppliers()
        try:
            svc.create_contract(s1["supplier_id"], [], "2026-06-30", "2026-01-01", "", "", {})
            assert False
        except ValueError as e:
            assert "晚于" in str(e)

    def test_create_contract_invalid_supplier(self):
        svc = SupplierPortalService()
        try:
            svc.create_contract("fake", [], "2026-01-01", "2026-12-31", "", "", {})
            assert False
        except ValueError:
            pass

    def test_check_contract_expiry(self):
        svc, s1, _, _ = _make_service_with_suppliers()
        from datetime import date, timedelta

        # 创建一个即将在15天后到期的合同
        today = date.today()
        soon = today + timedelta(days=15)
        svc.create_contract(
            s1["supplier_id"], [],
            str(today - timedelta(days=180)), str(soon),
            "", "net30", {},
        )

        expiring = svc.check_contract_expiry(days_ahead=30)
        assert len(expiring) == 1
        assert expiring[0]["days_remaining"] == 15

        # 7天内不应包含
        not_expiring = svc.check_contract_expiry(days_ahead=7)
        assert len(not_expiring) == 0

    def test_evaluate_contract_compliance(self):
        svc, s1, contract = self._setup()
        _inject_delivery_records(svc, s1["supplier_id"], count=20, on_time_rate=0.9, quality_rate=0.95)

        compliance = svc.evaluate_contract_compliance(contract["contract_id"])
        assert compliance["contract_id"] == contract["contract_id"]
        assert compliance["total_deliveries"] > 0
        assert 0 <= compliance["on_time_delivery_rate"] <= 1
        assert 0 <= compliance["quality_pass_rate"] <= 1
        assert compliance["status"] in ("good", "needs_attention", "poor")

    def test_evaluate_empty_contract(self):
        svc, s1, contract = self._setup()
        # 无交付记录
        compliance = svc.evaluate_contract_compliance(contract["contract_id"])
        assert compliance["status"] == "no_data"
        assert compliance["total_deliveries"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. Price Intelligence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPriceIntelligence:
    def test_get_price_trend(self):
        svc = SupplierPortalService()
        _inject_price_history(svc, "鲈鱼", 3500, count=30, volatility=0.05)

        trend = svc.get_price_trend("鲈鱼", days=180)
        assert trend["ingredient"] == "鲈鱼"
        assert trend["data_points"] == 30
        assert trend["avg_price_fen"] > 0
        assert trend["trend"] in ("rising", "falling", "stable", "insufficient_data")
        assert trend["volatility"] >= 0

    def test_get_price_trend_no_data(self):
        svc = SupplierPortalService()
        trend = svc.get_price_trend("不存在的食材")
        assert trend["data_points"] == 0
        assert trend["trend"] == "no_data"

    def test_detect_price_anomaly_normal(self):
        svc = SupplierPortalService()
        _inject_price_history(svc, "基围虾", 5600, count=30, volatility=0.03)

        # 正常价格
        result = svc.detect_price_anomaly("sup1", "基围虾", 5700)
        assert result["is_anomaly"] is False

    def test_detect_price_anomaly_high(self):
        svc = SupplierPortalService()
        _inject_price_history(svc, "基围虾", 5600, count=30, volatility=0.03)

        # 异常高价（远超均价）
        result = svc.detect_price_anomaly("sup1", "基围虾", 9000)
        assert result["is_anomaly"] is True
        assert result["deviation_pct"] > 30

    def test_detect_price_anomaly_no_history(self):
        svc = SupplierPortalService()
        result = svc.detect_price_anomaly("sup1", "新食材", 5000)
        assert result["is_anomaly"] is False
        assert result["confidence"] == 0.0

    def test_predict_price(self):
        svc = SupplierPortalService()
        _inject_price_history(svc, "鲈鱼", 3500, count=30, volatility=0.05)

        prediction = svc.predict_price("鲈鱼", days_ahead=30)
        assert prediction["ingredient"] == "鲈鱼"
        assert prediction["predicted_price_fen"] > 0
        assert prediction["method"] == "linear_regression_seasonal"
        assert prediction["data_points"] == 30
        assert prediction["confidence"] > 0

    def test_predict_price_insufficient_data(self):
        svc = SupplierPortalService()
        _inject_price_history(svc, "稀有食材", 10000, count=3)

        prediction = svc.predict_price("稀有食材")
        assert prediction["method"] == "insufficient_data"
        assert prediction["confidence"] == 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. Supplier Scoring
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSupplierScoring:
    def test_calculate_score_good_supplier(self):
        svc, s1, _, _ = _make_service_with_suppliers()
        _inject_delivery_records(svc, s1["supplier_id"], count=20, on_time_rate=0.95, quality_rate=0.98)

        score = svc.calculate_supplier_score(s1["supplier_id"])
        assert score["supplier_name"] == "湘江渔港水产"
        assert score["overall_score"] > 0
        assert score["quality_score"] > 0
        assert score["delivery_score"] > 0
        assert score["recommendation"] in ("preferred", "approved", "probation", "blacklist")
        assert score["record_count"] == 20

        # 好供应商应该是 preferred 或 approved
        assert score["recommendation"] in ("preferred", "approved")

    def test_calculate_score_poor_supplier(self):
        svc, _, _, s3 = _make_service_with_suppliers()
        _inject_delivery_records(svc, s3["supplier_id"], count=20, on_time_rate=0.4, quality_rate=0.5)

        score = svc.calculate_supplier_score(s3["supplier_id"])
        assert score["overall_score"] < 70  # poor supplier with 40% on-time, 50% quality
        assert score["recommendation"] in ("probation", "blacklist", "approved")

    def test_calculate_score_no_records(self):
        svc, s1, _, _ = _make_service_with_suppliers()
        score = svc.calculate_supplier_score(s1["supplier_id"])
        assert score["overall_score"] == 0
        assert score["trend"] == "no_data"

    def test_calculate_score_not_found(self):
        svc = SupplierPortalService()
        try:
            svc.calculate_supplier_score("nonexistent")
            assert False
        except ValueError:
            pass

    def test_supplier_ranking(self):
        svc, s1, _, s3 = _make_service_with_suppliers()
        # 注册另一个海鲜供应商
        s4 = svc.register_supplier("南海水产", "seafood", {"person": "陈渔夫"}, ["食品经营许可证"])

        _inject_delivery_records(svc, s1["supplier_id"], count=20, on_time_rate=0.95, quality_rate=0.98)
        _inject_delivery_records(svc, s4["supplier_id"], count=15, on_time_rate=0.7, quality_rate=0.8)

        ranking = svc.get_supplier_ranking("seafood")
        assert len(ranking) == 2
        assert ranking[0]["rank"] == 1
        assert ranking[1]["rank"] == 2
        # 湘江渔港应排名更高
        assert ranking[0]["name"] == "湘江渔港水产"

    def test_flag_underperforming(self):
        svc, s1, s2, s3 = _make_service_with_suppliers()
        _inject_delivery_records(svc, s1["supplier_id"], count=20, on_time_rate=0.95, quality_rate=0.98)
        _inject_delivery_records(svc, s2["supplier_id"], count=15, on_time_rate=0.5, quality_rate=0.6)
        _inject_delivery_records(svc, s3["supplier_id"], count=10, on_time_rate=0.4, quality_rate=0.5)

        flagged = svc.flag_underperforming_suppliers()
        assert len(flagged) >= 1
        flagged_names = {f["name"] for f in flagged}
        # 低绩效供应商应被标记
        assert "新农都冻品中心" in flagged_names


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. Supply Chain Risk
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSupplyChainRisk:
    def _setup_risky_store(self):
        svc, s1, s2, s3 = _make_service_with_suppliers()

        # 关联门店与供应商
        svc._link_store_supplier(STORE_ID, s1["supplier_id"])
        svc._link_store_supplier(STORE_ID, s3["supplier_id"])

        # 交付记录（鲈鱼只有s1供应 → 单一来源风险）
        _inject_delivery_records(svc, s1["supplier_id"], count=20, on_time_rate=0.95, quality_rate=0.98)
        _inject_delivery_records(svc, s3["supplier_id"], count=15, on_time_rate=0.6, quality_rate=0.7)

        # 价格波动数据
        _inject_price_history(svc, "波士顿龙虾", 18000, count=20, volatility=0.25)

        return svc, s1, s3

    def test_assess_risk(self):
        svc, s1, s3 = self._setup_risky_store()
        assessment = svc.assess_risk(STORE_ID)

        assert assessment["store_id"] == STORE_ID
        assert assessment["risk_level"] in ("low", "medium", "high")
        assert assessment["risk_count"] > 0
        assert len(assessment["risks"]) > 0

        risk_types = {r["type"] for r in assessment["risks"]}
        # 应检测到交付失败风险（s3准时率60%）
        assert "delivery_failure_rate" in risk_types

    def test_assess_risk_empty_store(self):
        svc = SupplierPortalService()
        assessment = svc.assess_risk("empty_store")
        assert assessment["risk_level"] == "low"
        assert assessment["risk_count"] == 0

    def test_suggest_mitigation_delivery(self):
        svc, s1, s3 = self._setup_risky_store()
        assessment = svc.assess_risk(STORE_ID)

        delivery_risk = next(
            (r for r in assessment["risks"] if r["type"] == "delivery_failure_rate"),
            None,
        )
        assert delivery_risk is not None

        suggestion = svc.suggest_mitigation(delivery_risk["risk_id"])
        assert suggestion["risk_type"] == "delivery_failure_rate"
        assert len(suggestion["mitigation"]["actions"]) > 0
        assert suggestion["mitigation"]["priority"] == "high"

    def test_suggest_mitigation_unknown_risk(self):
        svc = SupplierPortalService()
        suggestion = svc.suggest_mitigation("unknown_risk_id")
        assert suggestion["risk_type"] == "unknown"
        assert len(suggestion["mitigation"]["actions"]) > 0

    def test_concentration_risk(self):
        svc, s1, _, _ = _make_service_with_suppliers()
        svc._link_store_supplier(STORE_ID, s1["supplier_id"])

        # 只有一个供应商，且有大量采购
        for i in range(20):
            svc._add_delivery_record(s1["supplier_id"], {
                "date": f"2026-01-{1 + i:02d}",
                "on_time": True,
                "quality": "pass",
                "ingredient": "鲈鱼",
                "total_fen": 100000,
            })

        assessment = svc.assess_risk(STORE_ID)
        risk_types = {r["type"] for r in assessment["risks"]}
        # 100%集中在一个供应商
        assert "concentration_risk" in risk_types


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  集成测试：完整供应链工作流
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestEndToEndWorkflow:
    def test_full_procurement_cycle(self):
        """完整采购流程: 注册供应商 → 询价比价 → 签合同 → 评分"""
        svc = SupplierPortalService()

        # 1. 注册供应商
        s1 = svc.register_supplier(
            "湘江渔港", "seafood",
            {"person": "张三", "phone": "138xxx"},
            ["食品经营许可证", "ISO22000", "HACCP", "水产检疫"],
        )
        s2 = svc.register_supplier(
            "南海水产", "seafood",
            {"person": "李四", "phone": "139xxx"},
            ["食品经营许可证"],
        )

        # 2. 发起询价
        rfq = svc.request_quotes("鲈鱼", 200, "2026-04-15", [s1["supplier_id"], s2["supplier_id"]])
        assert rfq["status"] == "open"

        # 3. 供应商报价
        svc._submit_quote(rfq["rfq_id"], s1["supplier_id"], 3500, 2, "当日捕捞，次日送达")
        svc._submit_quote(rfq["rfq_id"], s2["supplier_id"], 3200, 4, "冰鲜运输")

        # 4. 比价
        comparison = svc.compare_quotes(rfq["rfq_id"])
        assert comparison["recommended"] is not None

        # 5. 接受报价
        winner_id = comparison["recommended"]["supplier_id"]
        acceptance = svc.accept_quote(rfq["rfq_id"], winner_id)
        assert acceptance["status"] == "accepted"

        # 6. 签订合同
        contract = svc.create_contract(
            winner_id,
            [{"ingredient_id": "ing_bass", "name": "鲈鱼", "agreed_price_fen": 3500, "min_quantity": 200, "unit": "kg"}],
            "2026-04-01", "2026-09-30",
            "半年固定价", "net30",
            {"late_delivery_pct": 5, "quality_failure_pct": 10, "max_penalty_pct": 30},
        )
        assert contract["status"] == "active"

        # 7. 模拟交付并评分
        _inject_delivery_records(svc, winner_id, count=10, on_time_rate=0.9, quality_rate=0.95)
        score = svc.calculate_supplier_score(winner_id)
        assert score["overall_score"] > 0
        assert score["recommendation"] in ("preferred", "approved")

    def test_price_monitoring_and_alert(self):
        """价格监控: 历史数据 → 异常检测 → 预测"""
        svc = SupplierPortalService()
        _inject_price_history(svc, "波士顿龙虾", 18000, count=30, volatility=0.05)

        # 1. 查看趋势
        trend = svc.get_price_trend("波士顿龙虾")
        assert trend["data_points"] == 30

        # 2. 检测正常报价
        normal = svc.detect_price_anomaly("sup1", "波士顿龙虾", 18500)
        assert normal["is_anomaly"] is False

        # 3. 检测异常报价
        anomaly = svc.detect_price_anomaly("sup1", "波士顿龙虾", 30000)
        assert anomaly["is_anomaly"] is True
        assert anomaly["deviation_pct"] > 50

        # 4. 预测未来价格
        prediction = svc.predict_price("波士顿龙虾", 30)
        assert prediction["predicted_price_fen"] > 0
