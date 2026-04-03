"""食安合规与追溯中心 -- 纯函数 + 温控 + 留样 + 合规检查表测试"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.food_safety import (
    SAMPLE_RETENTION_HOURS,
    EventSeverity,
    _check_temperature,
    get_compliance_checklist,
    record_sample,
    record_temperature,
)

# ─── 温控校验 ───


class TestCheckTemperature:
    def test_cold_storage_compliant(self):
        result = _check_temperature("cold_storage", 2.5)
        assert result["compliant"] is True
        assert "合规" in result["message"]

    def test_cold_storage_too_warm(self):
        result = _check_temperature("cold_storage", 8.0)
        assert result["compliant"] is False
        assert "异常" in result["message"]

    def test_cold_storage_boundary_low(self):
        result = _check_temperature("cold_storage", 0.0)
        assert result["compliant"] is True

    def test_cold_storage_boundary_high(self):
        result = _check_temperature("cold_storage", 4.0)
        assert result["compliant"] is True

    def test_freezer_compliant(self):
        result = _check_temperature("freezer", -22.0)
        assert result["compliant"] is True

    def test_freezer_too_warm(self):
        result = _check_temperature("freezer", -10.0)
        assert result["compliant"] is False

    def test_freezer_boundary(self):
        result = _check_temperature("freezer", -18.0)
        assert result["compliant"] is True

    def test_hot_chain_compliant(self):
        result = _check_temperature("hot_chain", 65.0)
        assert result["compliant"] is True

    def test_hot_chain_too_cold(self):
        result = _check_temperature("hot_chain", 50.0)
        assert result["compliant"] is False

    def test_hot_chain_boundary(self):
        result = _check_temperature("hot_chain", 60.0)
        assert result["compliant"] is True

    def test_unknown_location(self):
        result = _check_temperature("unknown_area", 25.0)
        assert result["compliant"] is True


# ─── 留样记录 ───


class TestRecordSample:
    def test_basic_record(self):
        sample_time = datetime.now()
        result = record_sample(
            store_id="store-001",
            dish_id="dish-001",
            sample_time=sample_time,
            photo_url="https://example.com/photo.jpg",
            operator_id="op-001",
            tenant_id="tenant-001",
        )
        assert result["store_id"] == "store-001"
        assert result["dish_id"] == "dish-001"
        assert result["photo_url"] == "https://example.com/photo.jpg"
        assert result["retention_hours"] == SAMPLE_RETENTION_HOURS
        assert result["is_within_retention"] is True

    def test_retention_48_hours(self):
        sample_time = datetime.now()
        result = record_sample(
            store_id="s1", dish_id="d1", sample_time=sample_time,
            photo_url="url", operator_id="op1", tenant_id="t1",
        )
        retention_until = datetime.fromisoformat(result["retention_until"])
        expected = sample_time + timedelta(hours=48)
        # 允许 1 秒误差
        assert abs((retention_until - expected).total_seconds()) < 1

    def test_old_sample_expired(self):
        sample_time = datetime.now() - timedelta(hours=50)
        result = record_sample(
            store_id="s1", dish_id="d1", sample_time=sample_time,
            photo_url="url", operator_id="op1", tenant_id="t1",
        )
        assert result["is_within_retention"] is False


# ─── 温控记录 ───


class TestRecordTemperature:
    def test_compliant_record(self):
        result = record_temperature(
            store_id="store-001",
            location="cold_storage",
            temperature=3.0,
            operator_id="op-001",
            tenant_id="tenant-001",
        )
        assert result["compliant"] is True
        assert result["location"] == "cold_storage"
        assert result["temperature"] == 3.0

    def test_non_compliant_record(self):
        result = record_temperature(
            store_id="store-001",
            location="freezer",
            temperature=-5.0,
            operator_id="op-001",
            tenant_id="tenant-001",
        )
        assert result["compliant"] is False


# ─── 合规检查表 ───


class TestGetComplianceChecklist:
    def test_checklist_items(self):
        result = get_compliance_checklist(
            store_id="store-001",
            check_date=date(2026, 3, 27),
            tenant_id="tenant-001",
        )
        assert result["store_id"] == "store-001"
        assert result["date"] == "2026-03-27"
        assert result["total"] >= 7
        assert result["required_count"] >= 6

    def test_checklist_has_key_items(self):
        result = get_compliance_checklist(
            store_id="s1", check_date=date.today(), tenant_id="t1",
        )
        item_names = [i["item"] for i in result["items"]]
        assert "晨检" in item_names
        assert "留样" in item_names
        assert "冷藏温控" in item_names
        assert "效期检查" in item_names

    def test_checklist_structure(self):
        result = get_compliance_checklist(
            store_id="s1", check_date=date.today(), tenant_id="t1",
        )
        for item in result["items"]:
            assert "item" in item
            assert "description" in item
            assert "required" in item
            assert "frequency" in item


# ─── EventSeverity 枚举 ───


class TestEventSeverity:
    def test_critical_value(self):
        assert EventSeverity.critical.value == "critical"

    def test_all_levels(self):
        levels = {e.value for e in EventSeverity}
        assert levels == {"low", "medium", "high", "critical"}
