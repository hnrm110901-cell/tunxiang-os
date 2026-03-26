"""活鲜管理服务测试 — 覆盖全链路

测试数据基于徐记海鲜典型海鲜池场景。
"""
import pytest
from ..services.live_seafood_service import (
    LiveSeafoodService,
    TankStatus,
    SPECIES_DATABASE,
    _batches,
    _tanks,
    _inspections,
    _market_prices,
    _price_history,
    _sales,
    _compliance_logs,
)


TENANT_ID = "t-xuji-seafood-001"
STORE_ID = "s-xuji-changsha-01"


@pytest.fixture(autouse=True)
def clean_storage():
    """每个测试前清空内存存储"""
    _batches.clear()
    _tanks.clear()
    _inspections.clear()
    _market_prices.clear()
    _price_history.clear()
    _sales.clear()
    _compliance_logs.clear()
    yield


@pytest.fixture
def svc():
    return LiveSeafoodService(tenant_id=TENANT_ID, store_id=STORE_ID)


def _intake_lobster(svc: LiveSeafoodService, batch_id: str = "BATCH-LOB-001") -> dict:
    """辅助函数：入池一批龙虾"""
    return svc.record_intake(
        batch_id=batch_id,
        species="lobster",
        supplier_id="SUP-HUANGSHA-01",
        quantity_kg=50.0,
        unit_price_fen=28000,  # 280元/kg
        quarantine_cert="QC-2026-03-001",
        tank_id="TANK-A1",
        intake_date="2026-03-25T08:00:00+08:00",
    )


def _intake_king_crab(svc: LiveSeafoodService, batch_id: str = "BATCH-KC-001") -> dict:
    """辅助函数：入池一批帝王蟹"""
    return svc.record_intake(
        batch_id=batch_id,
        species="king_crab",
        supplier_id="SUP-DALIAN-01",
        quantity_kg=30.0,
        unit_price_fen=68000,  # 680元/kg
        quarantine_cert="QC-2026-03-002",
        tank_id="TANK-B1",
        intake_date="2026-03-25T08:00:00+08:00",
    )


# ─── 1. 进货入池 ───

class TestIntake:
    def test_record_lobster_intake(self, svc: LiveSeafoodService):
        result = _intake_lobster(svc)

        assert result["batch_id"] == "BATCH-LOB-001"
        assert result["species"] == "lobster"
        assert result["species_name_cn"] == "龙虾"
        assert result["quantity_kg"] == 50.0
        assert result["remaining_kg"] == 50.0
        assert result["mortality_kg"] == 0.0
        assert result["unit_price_fen"] == 28000
        assert result["total_cost_fen"] == 1400000  # 50 * 28000
        assert result["quarantine_cert"] == "QC-2026-03-001"
        assert result["status"] == "active"
        assert result["tank_id"] == "TANK-A1"

    def test_record_king_crab_intake(self, svc: LiveSeafoodService):
        result = _intake_king_crab(svc)

        assert result["species"] == "king_crab"
        assert result["species_name_cn"] == "帝王蟹"
        assert result["total_cost_fen"] == 2040000  # 30 * 68000

    def test_intake_creates_tank(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        assert "TANK-A1" in _tanks
        tank = _tanks["TANK-A1"]
        assert tank["current_stock_kg"] == 50.0
        assert "lobster" in tank["species"]

    def test_intake_multiple_species_same_tank(self, svc: LiveSeafoodService):
        """同一池子可以存放多个物种（实际中需谨慎）"""
        svc.record_intake("B1", "grouper", "SUP-01", 20.0, 15000, "QC-001", "TANK-MIX")
        svc.record_intake("B2", "abalone", "SUP-01", 10.0, 35000, "QC-002", "TANK-MIX")

        tank = _tanks["TANK-MIX"]
        assert tank["current_stock_kg"] == 30.0
        assert "grouper" in tank["species"]
        assert "abalone" in tank["species"]

    def test_intake_unknown_species(self, svc: LiveSeafoodService):
        with pytest.raises(ValueError, match="Unknown species"):
            svc.record_intake("B1", "unicorn_fish", "SUP-01", 10.0, 10000, "QC-001", "TANK-X")

    def test_intake_invalid_quantity(self, svc: LiveSeafoodService):
        with pytest.raises(ValueError, match="quantity_kg must be positive"):
            svc.record_intake("B1", "lobster", "SUP-01", 0, 10000, "QC-001", "TANK-X")

    def test_intake_missing_quarantine_cert(self, svc: LiveSeafoodService):
        with pytest.raises(ValueError, match="quarantine_cert is required"):
            svc.record_intake("B1", "lobster", "SUP-01", 10.0, 10000, "", "TANK-X")

    def test_intake_expiry_date_calculated(self, svc: LiveSeafoodService):
        result = _intake_lobster(svc)
        # Lobster shelf_life_days = 7
        assert "expiry_date" in result
        # Expiry should be 7 days after intake


# ─── 2. 海鲜池管理 ───

class TestTankManagement:
    def test_update_tank_status(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        result = svc.update_tank_status(
            tank_id="TANK-A1",
            temperature=15.0,
            salinity=30.0,
            ph=8.1,
        )

        assert result["tank_id"] == "TANK-A1"
        assert result["temperature"] == 15.0
        assert result["salinity"] == 30.0
        assert result["ph"] == 8.1
        assert result["alert_level"] == "normal"
        assert len(result["alerts"]) == 0

    def test_tank_temperature_alert(self, svc: LiveSeafoodService):
        """龙虾适温12-18C，设30C应触发告警"""
        _intake_lobster(svc)
        result = svc.update_tank_status("TANK-A1", temperature=30.0, salinity=30.0, ph=8.1)

        assert result["alert_level"] == "critical"
        assert any(a["type"] == "temperature_high" for a in result["alerts"])

    def test_tank_salinity_alert(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        result = svc.update_tank_status("TANK-A1", temperature=15.0, salinity=20.0, ph=8.1)

        assert result["alert_level"] in ("warning", "critical")
        assert any(a["type"] == "salinity_low" for a in result["alerts"])

    def test_tank_ph_alert(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        result = svc.update_tank_status("TANK-A1", temperature=15.0, salinity=30.0, ph=6.0)

        assert any(a["type"] == "ph_out_of_range" for a in result["alerts"])

    def test_tank_not_found(self, svc: LiveSeafoodService):
        with pytest.raises(ValueError, match="Tank not found"):
            svc.update_tank_status("TANK-NOEXIST", 15.0, 30.0, 8.1)

    def test_get_tank_dashboard(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        _intake_king_crab(svc)

        dashboard = svc.get_tank_dashboard()
        assert len(dashboard) == 2
        tank_ids = [d["tank_id"] for d in dashboard]
        assert "TANK-A1" in tank_ids
        assert "TANK-B1" in tank_ids

        for tank in dashboard:
            assert "temperature" in tank
            assert "salinity" in tank
            assert "current_stock_kg" in tank
            assert "alert_level" in tank

    def test_check_tank_alerts_all_normal(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        # Tank is auto-created with optimal conditions
        alerts = svc.check_tank_alerts()
        # Default conditions should be within range
        assert all(a["severity"] != "critical" for a in alerts)

    def test_check_tank_alerts_critical(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.update_tank_status("TANK-A1", temperature=35.0, salinity=10.0, ph=6.0)

        alerts = svc.check_tank_alerts()
        assert len(alerts) > 0
        assert alerts[0]["severity"] == "critical"  # sorted critical first


# ─── 3. 日常巡检 ───

class TestInspection:
    def test_record_inspection(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        result = svc.record_inspection(
            tank_id="TANK-A1",
            inspector="海鲜池管理员-老张",
            mortality_count=2,
            mortality_kg=1.2,
            water_changed=True,
            notes="两只龙虾死亡，已捞出",
        )

        assert result["inspection_id"].startswith("INSP-")
        assert result["mortality_count"] == 2
        assert result["mortality_kg"] == 1.2
        assert result["stock_before_kg"] == 50.0
        assert result["stock_after_kg"] == 48.8  # 50 - 1.2
        assert result["water_changed"] is True
        assert result["mortality_rate"] == pytest.approx(0.024, abs=0.001)

    def test_inspection_updates_batch(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.record_inspection("TANK-A1", "老张", 2, 1.2, False)

        batch = _batches["BATCH-LOB-001"]
        assert batch["mortality_kg"] == 1.2
        assert batch["remaining_kg"] == pytest.approx(48.8, abs=0.01)

    def test_inspection_tank_not_found(self, svc: LiveSeafoodService):
        with pytest.raises(ValueError, match="Tank not found"):
            svc.record_inspection("TANK-NOEXIST", "老张", 0, 0, False)

    def test_get_mortality_trend(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.record_inspection("TANK-A1", "老张", 1, 0.5, False)
        svc.record_inspection("TANK-A1", "老张", 2, 1.0, True)

        trend = svc.get_mortality_trend("lobster", days=30)
        assert trend["species"] == "lobster"
        assert trend["species_name_cn"] == "龙虾"
        assert trend["avg_mortality_rate"] > 0
        assert trend["baseline_mortality_rate"] == 0.02

    def test_predict_mortality_normal_conditions(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        # Tank auto-created with optimal conditions
        prediction = svc.predict_mortality("TANK-A1", "lobster")

        assert prediction["species"] == "lobster"
        assert prediction["risk_level"] in ("low", "medium")
        assert prediction["predicted_mortality_rate"] <= 0.05  # should be reasonable

    def test_predict_mortality_bad_conditions(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        # Set terrible conditions
        svc.update_tank_status("TANK-A1", temperature=30.0, salinity=15.0, ph=6.0, water_quality="poor")

        prediction = svc.predict_mortality("TANK-A1", "lobster")
        assert prediction["risk_level"] in ("high", "critical")
        assert len(prediction["recommendations"]) > 0

    def test_predict_mortality_recommendations(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.update_tank_status("TANK-A1", temperature=8.0, salinity=25.0, ph=8.1)

        prediction = svc.predict_mortality("TANK-A1", "lobster")
        # Temperature too low for lobster (needs 12-18C)
        assert any("升温" in r for r in prediction["recommendations"])


# ─── 4. 时价管理 ───

class TestMarketPrice:
    def test_update_market_price(self, svc: LiveSeafoodService):
        result = svc.update_market_price(
            species="lobster",
            market_price_fen=35000,  # 350元/kg
            source="黄沙水产市场",
        )

        assert result["species"] == "lobster"
        assert result["market_price_fen"] == 35000
        assert result["source"] == "黄沙水产市场"

    def test_update_market_price_with_change(self, svc: LiveSeafoodService):
        svc.update_market_price("lobster", 35000, "黄沙水产市场")
        result = svc.update_market_price("lobster", 38000, "黄沙水产市场")

        assert result["change_pct"] == pytest.approx(8.57, abs=0.1)  # (38000-35000)/35000

    def test_calculate_selling_price(self, svc: LiveSeafoodService):
        result = svc.calculate_selling_price(
            species="lobster",
            cost_price_fen=28000,  # 280元/kg
            target_margin=0.45,
        )

        assert result["cost_price_fen"] == 28000
        assert result["yield_rate"] == 0.45  # lobster yield
        # Actual cost per edible kg: 28000/0.45 ~= 62222
        # Target selling price: 62222/(1-0.45) ~= 113131
        assert result["target_selling_price_fen"] > result["cost_price_fen"]
        assert result["recommended_price_fen"] > 0

    def test_calculate_selling_price_with_market_reference(self, svc: LiveSeafoodService):
        svc.update_market_price("lobster", 120000, "黄沙水产市场")  # 1200元/kg market

        result = svc.calculate_selling_price("lobster", 28000, 0.45)
        # Market price should influence recommendation
        assert result["market_price_fen"] == 120000

    def test_get_price_history(self, svc: LiveSeafoodService):
        svc.update_market_price("lobster", 33000, "A")
        svc.update_market_price("lobster", 35000, "B")
        svc.update_market_price("lobster", 34000, "C")

        history = svc.get_price_history("lobster", days=90)
        assert len(history) == 3

    def test_detect_price_anomaly_no_data(self, svc: LiveSeafoodService):
        result = svc.detect_price_anomaly("lobster", 35000)
        assert result["is_anomaly"] is False
        assert result["confidence"] < 0.5

    def test_detect_price_anomaly_normal(self, svc: LiveSeafoodService):
        # Build some history
        for price in [33000, 34000, 35000, 33500, 34500, 35500, 33000, 34000, 35000, 34000]:
            svc.update_market_price("lobster", price, "test")

        result = svc.detect_price_anomaly("lobster", 34500)
        assert result["is_anomaly"] is False

    def test_detect_price_anomaly_suspicious(self, svc: LiveSeafoodService):
        # Build consistent history around 34000
        for _ in range(10):
            svc.update_market_price("lobster", 34000, "test")

        # Propose price that's way off
        result = svc.detect_price_anomaly("lobster", 100000)
        assert result["is_anomaly"] is True
        assert result["z_score"] > 2.5


# ─── 5. 称重售卖 ───

class TestSale:
    def test_record_sale(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        sale = svc.record_sale(
            batch_id="BATCH-LOB-001",
            species="lobster",
            weight_kg=2.5,
            selling_price_fen=58000,  # 580元/kg
            order_id="ORD-20260325-001",
            cooking_method="蒜蓉蒸",
        )

        assert sale["sale_id"].startswith("SALE-")
        assert sale["weight_kg"] == 2.5
        assert sale["sale_amount_fen"] == 145000  # 2.5 * 58000
        assert sale["cost_amount_fen"] == 70000   # 2.5 * 28000
        assert sale["margin_fen"] == 75000
        assert sale["margin_rate"] == pytest.approx(0.5172, abs=0.01)
        assert sale["cooking_method"] == "蒜蓉蒸"

    def test_sale_updates_batch(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.record_sale("BATCH-LOB-001", "lobster", 2.5, 58000, "ORD-001", "蒜蓉蒸")

        batch = _batches["BATCH-LOB-001"]
        assert batch["sold_kg"] == 2.5
        assert batch["remaining_kg"] == pytest.approx(47.5, abs=0.01)

    def test_sale_updates_tank(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.record_sale("BATCH-LOB-001", "lobster", 2.5, 58000, "ORD-001", "蒜蓉蒸")

        tank = _tanks["TANK-A1"]
        assert tank["current_stock_kg"] == pytest.approx(47.5, abs=0.01)

    def test_sale_depletes_batch(self, svc: LiveSeafoodService):
        svc.record_intake("B-SMALL", "lobster", "SUP-01", 3.0, 28000, "QC-001", "TANK-S")
        svc.record_sale("B-SMALL", "lobster", 3.0, 58000, "ORD-001", "白灼")

        batch = _batches["B-SMALL"]
        assert batch["status"] == "depleted"
        assert batch["remaining_kg"] == 0

    def test_sale_insufficient_stock(self, svc: LiveSeafoodService):
        _intake_lobster(svc)  # 50kg
        with pytest.raises(ValueError, match="Insufficient stock"):
            svc.record_sale("BATCH-LOB-001", "lobster", 60.0, 58000, "ORD-001", "刺身")

    def test_sale_inactive_batch(self, svc: LiveSeafoodService):
        svc.record_intake("B-SMALL", "lobster", "SUP-01", 3.0, 28000, "QC-001", "TANK-S")
        svc.record_sale("B-SMALL", "lobster", 3.0, 58000, "ORD-001", "白灼")

        with pytest.raises(ValueError, match="cannot sell"):
            svc.record_sale("B-SMALL", "lobster", 1.0, 58000, "ORD-002", "蒜蓉蒸")

    def test_calculate_yield_rate(self, svc: LiveSeafoodService):
        result = svc.calculate_yield_rate("lobster", raw_weight_kg=2.5, cooked_weight_kg=1.1)

        assert result["actual_yield_rate"] == pytest.approx(0.44, abs=0.01)
        assert result["standard_yield_rate"] == 0.45
        assert result["waste_kg"] == pytest.approx(1.4, abs=0.01)
        assert result["status"] == "normal"  # close to standard

    def test_calculate_yield_rate_below_standard(self, svc: LiveSeafoodService):
        result = svc.calculate_yield_rate("king_crab", raw_weight_kg=3.0, cooked_weight_kg=0.6)

        assert result["actual_yield_rate"] == pytest.approx(0.2, abs=0.01)
        assert result["status"] == "below_standard"


# ─── 6. 全链路溯源 ───

class TestTraceability:
    def test_trace_item(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.record_inspection("TANK-A1", "老张", 0, 0, False, "一切正常")
        svc.record_sale("BATCH-LOB-001", "lobster", 2.5, 58000, "ORD-TABLE-08", "蒜蓉蒸")

        trace = svc.trace_item("ORD-TABLE-08")

        assert trace["found"] is True
        assert trace["trace_count"] == 1

        t = trace["traces"][0]
        assert t["sale"]["cooking_method"] == "蒜蓉蒸"
        assert t["batch"]["quarantine_cert"] == "QC-2026-03-001"
        assert t["batch"]["supplier_id"] == "SUP-HUANGSHA-01"
        assert t["tank"]["tank_id"] == "TANK-A1"
        assert len(t["inspections"]) >= 1

    def test_trace_item_not_found(self, svc: LiveSeafoodService):
        trace = svc.trace_item("ORD-NONEXISTENT")
        assert trace["found"] is False

    def test_get_batch_summary(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.record_inspection("TANK-A1", "老张", 1, 0.5, False)
        svc.record_sale("BATCH-LOB-001", "lobster", 2.5, 58000, "ORD-001", "蒜蓉蒸")
        svc.record_sale("BATCH-LOB-001", "lobster", 3.0, 56000, "ORD-002", "芝士焗")

        summary = svc.get_batch_summary("BATCH-LOB-001")

        assert summary["batch_id"] == "BATCH-LOB-001"
        assert summary["quantity"]["total_intake_kg"] == 50.0
        assert summary["quantity"]["mortality_kg"] == 0.5
        assert summary["quantity"]["sold_kg"] == pytest.approx(5.5, abs=0.01)
        assert summary["quantity"]["remaining_kg"] == pytest.approx(44.0, abs=0.1)
        assert summary["financials"]["total_revenue_fen"] == 145000 + 168000  # 2.5*58000 + 3.0*56000
        assert summary["financials"]["margin_rate"] > 0
        assert summary["metrics"]["sale_count"] == 2
        assert summary["metrics"]["loss_rate"] == pytest.approx(0.01, abs=0.001)

    def test_get_batch_summary_not_found(self, svc: LiveSeafoodService):
        with pytest.raises(ValueError, match="Batch not found"):
            svc.get_batch_summary("BATCH-NOEXIST")


# ─── 7. 食安合规 ───

class TestCompliance:
    def test_check_compliance_all_good(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.record_inspection("TANK-A1", "老张", 0, 0, False)

        result = svc.check_compliance()

        assert result["quarantine_cert_valid"] is True
        assert result["no_expired_batch"] is True
        assert result["traceability_complete"] is True
        assert result["compliance_score"] >= 70

    def test_check_compliance_temperature_issue(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        svc.update_tank_status("TANK-A1", temperature=30.0, salinity=30.0, ph=8.1)

        result = svc.check_compliance()
        assert result["temp_in_range"] is False
        assert any(i["type"] == "temperature_out_of_range" for i in result["issues"])

    def test_check_compliance_no_inspection(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        # No inspection recorded
        result = svc.check_compliance()
        assert any(i["type"] == "no_inspection_record" for i in result["issues"])

    def test_generate_safety_report(self, svc: LiveSeafoodService):
        _intake_lobster(svc)
        _intake_king_crab(svc)
        svc.record_inspection("TANK-A1", "老张", 1, 0.5, True)
        svc.record_sale("BATCH-LOB-001", "lobster", 5.0, 58000, "ORD-001", "蒜蓉蒸")

        report = svc.generate_safety_report()

        assert report["store_id"] == STORE_ID
        assert report["compliance"]["compliance_score"] > 0
        assert report["inventory_summary"]["active_batches"] == 2
        assert report["inventory_summary"]["active_tanks"] == 2
        assert report["sales_summary"]["total_sales"] == 1
        assert report["sales_summary"]["total_weight_kg"] == 5.0


# ─── 8. 物种数据库完整性 ───

class TestSpeciesDatabase:
    def test_all_required_species_present(self):
        required = [
            "lobster", "grouper", "abalone", "king_crab",
            "boston_lobster", "geoduck", "leopard_coral_grouper", "australian_lobster",
        ]
        for sp in required:
            assert sp in SPECIES_DATABASE, f"Missing species: {sp}"

    def test_species_have_required_fields(self):
        required_fields = [
            "name_cn", "name_en", "category", "temp_min", "temp_max",
            "salinity_min", "salinity_max", "ph_min", "ph_max",
            "max_density_kg_per_sqm", "typical_mortality_rate",
            "shelf_life_days", "default_margin", "yield_rate", "cooking_methods",
        ]
        for sp_key, sp in SPECIES_DATABASE.items():
            for field in required_fields:
                assert field in sp, f"Species {sp_key} missing field {field}"

    def test_species_ranges_valid(self):
        for sp_key, sp in SPECIES_DATABASE.items():
            assert sp["temp_min"] < sp["temp_max"], f"{sp_key} temp range invalid"
            assert sp["salinity_min"] < sp["salinity_max"], f"{sp_key} salinity range invalid"
            assert sp["ph_min"] < sp["ph_max"], f"{sp_key} pH range invalid"
            assert 0 < sp["yield_rate"] < 1, f"{sp_key} yield rate out of range"
            assert 0 < sp["typical_mortality_rate"] < 1, f"{sp_key} mortality rate out of range"
            assert sp["max_density_kg_per_sqm"] > 0, f"{sp_key} density must be positive"

    def test_king_crab_requires_cold_water(self):
        kc = SPECIES_DATABASE["king_crab"]
        assert kc["temp_max"] <= 8, "King crab needs very cold water"

    def test_leopard_coral_grouper_is_tropical(self):
        lcg = SPECIES_DATABASE["leopard_coral_grouper"]
        assert lcg["temp_min"] >= 18, "Leopard coral grouper needs warm water"


# ─── 9. 端到端流程 ───

class TestEndToEnd:
    def test_full_seafood_lifecycle(self, svc: LiveSeafoodService):
        """完整活鲜生命周期：进货 -> 入池 -> 巡检 -> 定价 -> 售卖 -> 溯源"""

        # Step 1: 进货入池
        intake = svc.record_intake(
            batch_id="BATCH-E2E-001",
            species="boston_lobster",
            supplier_id="SUP-BOSTON-01",
            quantity_kg=25.0,
            unit_price_fen=18000,  # 180元/kg
            quarantine_cert="QC-2026-E2E-001",
            tank_id="TANK-E2E",
            intake_date="2026-03-25T08:00:00+08:00",
        )
        assert intake["status"] == "active"

        # Step 2: 更新池子环境（波龙适温5-10C）
        tank_status = svc.update_tank_status("TANK-E2E", temperature=7.0, salinity=30.0, ph=8.1)
        assert tank_status["alert_level"] == "normal"

        # Step 3: 日常巡检
        inspection = svc.record_inspection("TANK-E2E", "老李", 1, 0.3, True, "一只死亡，已换水")
        assert inspection["mortality_rate"] < 0.02

        # Step 4: 设置市场时价
        svc.update_market_price("boston_lobster", 45000, "黄沙水产市场")

        # Step 5: 计算建议售价
        price = svc.calculate_selling_price("boston_lobster", 18000, target_margin=0.50)
        assert price["recommended_price_fen"] > 0

        # Step 6: 称重售卖
        sale = svc.record_sale(
            batch_id="BATCH-E2E-001",
            species="boston_lobster",
            weight_kg=1.5,
            selling_price_fen=price["recommended_price_fen"],
            order_id="ORD-E2E-TABLE-12",
            cooking_method="蒜蓉蒸",
        )
        assert sale["margin_rate"] >= 0.3  # margin should be decent

        # Step 7: 出成率计算
        yield_result = svc.calculate_yield_rate("boston_lobster", 1.5, 0.6)
        assert yield_result["actual_yield_rate"] == pytest.approx(0.4, abs=0.01)

        # Step 8: 全链路溯源
        trace = svc.trace_item("ORD-E2E-TABLE-12")
        assert trace["found"] is True
        assert trace["traces"][0]["batch"]["supplier_id"] == "SUP-BOSTON-01"
        assert trace["traces"][0]["batch"]["quarantine_cert"] == "QC-2026-E2E-001"

        # Step 9: 批次汇总
        summary = svc.get_batch_summary("BATCH-E2E-001")
        assert summary["quantity"]["total_intake_kg"] == 25.0
        assert summary["quantity"]["sold_kg"] == 1.5
        assert summary["quantity"]["mortality_kg"] == 0.3

        # Step 10: 食安检查
        compliance = svc.check_compliance()
        assert compliance["quarantine_cert_valid"] is True
        assert compliance["no_expired_batch"] is True

        # Step 11: 安全报告
        report = svc.generate_safety_report()
        assert report["inventory_summary"]["active_batches"] == 1
        assert report["sales_summary"]["total_sales"] == 1

    def test_multi_species_multi_tank(self, svc: LiveSeafoodService):
        """多物种多池子管理场景"""
        # 龙虾池
        svc.record_intake("B-LOB", "lobster", "SUP-01", 40.0, 28000, "QC-L", "TANK-LOB")
        # 帝王蟹池（冷水）
        svc.record_intake("B-KC", "king_crab", "SUP-02", 20.0, 68000, "QC-K", "TANK-KC")
        # 东星斑池（热带）
        svc.record_intake("B-LCG", "leopard_coral_grouper", "SUP-03", 30.0, 22000, "QC-G", "TANK-LCG")

        # 各池子设置不同温度
        svc.update_tank_status("TANK-LOB", 15.0, 30.0, 8.1)
        svc.update_tank_status("TANK-KC", 4.0, 32.0, 8.0)
        svc.update_tank_status("TANK-LCG", 24.0, 30.0, 8.2)

        dashboard = svc.get_tank_dashboard()
        assert len(dashboard) == 3

        # All should be normal at optimal conditions
        for tank in dashboard:
            assert tank["alert_level"] == "normal"

        # 各池子卖出
        svc.record_sale("B-LOB", "lobster", 3.0, 55000, "ORD-1", "白灼")
        svc.record_sale("B-KC", "king_crab", 2.0, 128000, "ORD-2", "清蒸")
        svc.record_sale("B-LCG", "leopard_coral_grouper", 1.5, 68000, "ORD-3", "清蒸")

        # 食安报告
        report = svc.generate_safety_report()
        assert report["inventory_summary"]["active_batches"] == 3
        assert report["sales_summary"]["total_sales"] == 3
