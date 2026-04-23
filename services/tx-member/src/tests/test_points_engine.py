"""积分引擎测试 — API 冒烟 + 服务逻辑单元测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.points_routes import router as points_router
from fastapi.testclient import TestClient
from main import app

if not any(r.prefix == "/api/v1/member/points" for r in app.routes if hasattr(r, "prefix")):
    app.include_router(points_router)

client = TestClient(app)


# ── API 冒烟测试 ──────────────────────────────────────────────


class TestEarnPointsAPI:
    def test_earn_ok(self):
        r = client.post(
            "/api/v1/member/points/earn",
            json={"card_id": "c1", "source": "consume", "amount": 100},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["card_id"] == "c1"
        assert data["data"]["earned"] == 100

    def test_earn_invalid_amount(self):
        r = client.post(
            "/api/v1/member/points/earn",
            json={"card_id": "c1", "source": "consume", "amount": 0},
        )
        assert r.status_code == 422


class TestSpendPointsAPI:
    def test_spend_ok(self):
        r = client.post(
            "/api/v1/member/points/spend",
            json={"card_id": "c1", "amount": 50, "purpose": "cash_offset"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["spent"] == 50

    def test_spend_invalid_amount(self):
        r = client.post(
            "/api/v1/member/points/spend",
            json={"card_id": "c1", "amount": -10, "purpose": "exchange"},
        )
        assert r.status_code == 422


class TestSetEarnRulesAPI:
    def test_set_earn_rules_ok(self):
        r = client.put(
            "/api/v1/member/points/types/ct1/earn-rules",
            json={"rules": {"earn_ratio": 1, "earn_unit_fen": 10000}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["card_type_id"] == "ct1"


class TestSetSpendRulesAPI:
    def test_set_spend_rules_ok(self):
        r = client.put(
            "/api/v1/member/points/types/ct1/spend-rules",
            json={"rules": {"spend_ratio": 100, "spend_value_fen": 100}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True


class TestSetMultiplierAPI:
    def test_set_multiplier_ok(self):
        r = client.put(
            "/api/v1/member/points/types/ct1/multiplier",
            json={"multiplier": 2.0, "conditions": {"trigger": "member_day"}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["multiplier"] == 2.0

    def test_set_multiplier_invalid(self):
        r = client.put(
            "/api/v1/member/points/types/ct1/multiplier",
            json={"multiplier": 0, "conditions": {"trigger": "member_day"}},
        )
        assert r.status_code == 422


class TestGrowthValueAPI:
    def test_manage_growth_value_ok(self):
        r = client.post(
            "/api/v1/member/points/cards/c1/growth-value",
            json={"action": "add", "amount": 50},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["card_id"] == "c1"
        assert data["data"]["added"] == 50


class TestPointsBalanceAPI:
    def test_balance_ok(self):
        r = client.get("/api/v1/member/points/cards/c1/balance")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "points" in data["data"]
        assert "growth_value" in data["data"]


class TestPointsHistoryAPI:
    def test_history_ok(self):
        r = client.get("/api/v1/member/points/cards/c1/history")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]
        assert data["data"]["page"] == 1
        assert data["data"]["size"] == 20

    def test_history_pagination(self):
        r = client.get(
            "/api/v1/member/points/cards/c1/history",
            params={"page": 2, "size": 10},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["page"] == 2
        assert data["size"] == 10


class TestCrossStoreSettlementAPI:
    def test_settlement_ok(self):
        r = client.get("/api/v1/member/points/settlement/2026-03")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["month"] == "2026-03"
        assert "store_settlements" in data["data"]
        assert "total_points_earned" in data["data"]
        assert "total_points_spent" in data["data"]


# ── 服务层纯函数单元测试 ─────────────────────────────────────

from services.points_engine import (
    DEFAULT_EARN_RATIO,
    DEFAULT_SPEND_RATIO,
    EARN_SOURCES,
    SPEND_PURPOSES,
    calculate_cash_offset_fen,
    calculate_earn_points,
    validate_earn_rules,
    validate_multiplier_conditions,
    validate_spend_rules,
)


class TestCalculateEarnPoints:
    def test_basic_earn(self):
        """每消费100元（10000分）获1积分"""
        result = calculate_earn_points(50000, 1, 10000)
        assert result == 5  # 500元 -> 5积分

    def test_earn_with_multiplier(self):
        """双倍积分"""
        result = calculate_earn_points(50000, 1, 10000, multiplier=2.0)
        assert result == 10

    def test_earn_floor_division(self):
        """不足整单位不算"""
        result = calculate_earn_points(15000, 1, 10000)
        assert result == 1  # 150元 -> 1积分（只算100元部分）

    def test_earn_zero_amount(self):
        result = calculate_earn_points(0, 1, 10000)
        assert result == 0

    def test_earn_invalid_ratio(self):
        result = calculate_earn_points(10000, 0, 10000)
        assert result == 0

    def test_earn_invalid_unit(self):
        result = calculate_earn_points(10000, 1, 0)
        assert result == 0

    def test_earn_result_is_integer(self):
        """积分必须是整数"""
        result = calculate_earn_points(33333, 1, 10000, multiplier=1.5)
        assert isinstance(result, int)


class TestCalculateCashOffset:
    def test_basic_offset(self):
        """100积分抵1元（100分）"""
        result = calculate_cash_offset_fen(500, 100, 100)
        assert result == 500  # 500积分 -> 5元 -> 500分

    def test_offset_floor(self):
        """不足兑换单位不算"""
        result = calculate_cash_offset_fen(150, 100, 100)
        assert result == 100  # 只能兑1次

    def test_offset_zero_ratio(self):
        result = calculate_cash_offset_fen(100, 0, 100)
        assert result == 0


class TestValidateEarnRules:
    def test_valid(self):
        rules = {"earn_ratio": 1, "earn_unit_fen": 10000}
        assert validate_earn_rules(rules) is True

    def test_missing_ratio(self):
        assert validate_earn_rules({"earn_unit_fen": 10000}) is False

    def test_zero_ratio(self):
        assert validate_earn_rules({"earn_ratio": 0, "earn_unit_fen": 10000}) is False

    def test_empty(self):
        assert validate_earn_rules({}) is False


class TestValidateSpendRules:
    def test_valid(self):
        rules = {"spend_ratio": 100, "spend_value_fen": 100}
        assert validate_spend_rules(rules) is True

    def test_missing_value(self):
        assert validate_spend_rules({"spend_ratio": 100}) is False

    def test_zero_ratio(self):
        assert validate_spend_rules({"spend_ratio": 0, "spend_value_fen": 100}) is False


class TestValidateMultiplierConditions:
    def test_member_day(self):
        assert validate_multiplier_conditions({"trigger": "member_day"}) is True

    def test_activity(self):
        assert validate_multiplier_conditions({"trigger": "activity"}) is True

    def test_invalid_trigger(self):
        assert validate_multiplier_conditions({"trigger": "unknown"}) is False

    def test_empty(self):
        assert validate_multiplier_conditions({}) is False


class TestConstants:
    def test_earn_sources(self):
        assert "consume" in EARN_SOURCES
        assert "recharge" in EARN_SOURCES
        assert "activity" in EARN_SOURCES
        assert "sign_in" in EARN_SOURCES

    def test_spend_purposes(self):
        assert "cash_offset" in SPEND_PURPOSES
        assert "exchange" in SPEND_PURPOSES

    def test_default_ratios(self):
        assert DEFAULT_EARN_RATIO == 1
        assert DEFAULT_SPEND_RATIO == 100
