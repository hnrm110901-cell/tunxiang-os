"""会员卡引擎测试 — API 冒烟 + 服务逻辑单元测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.card_routes import router as card_router
from fastapi.testclient import TestClient
from main import app

if not any(r.prefix == "/api/v1/member/card" for r in app.routes if hasattr(r, "prefix")):
    app.include_router(card_router)

client = TestClient(app)


# ── API 冒烟测试 ──────────────────────────────────────────────


class TestCreateCardTypeAPI:
    def test_create_card_type_ok(self):
        r = client.post(
            "/api/v1/member/card/types",
            json={"name": "金卡", "rules": {"stored_value_enabled": True}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["name"] == "金卡"
        assert "card_type_id" in data["data"]

    def test_create_card_type_minimal(self):
        r = client.post(
            "/api/v1/member/card/types",
            json={"name": "普通卡"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestListCardTypesAPI:
    def test_list_card_types_ok(self):
        r = client.get("/api/v1/member/card/types")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]


class TestSetCardLevelsAPI:
    def test_set_levels_ok(self):
        levels = [
            {"name": "银卡", "rank": 1, "benefits": [], "upgrade_rules": {}},
            {"name": "金卡", "rank": 2, "benefits": [], "upgrade_rules": {}},
        ]
        r = client.put(
            "/api/v1/member/card/types/ct1/levels",
            json={"levels": levels},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["levels_count"] == 2


class TestAnonymousCardsAPI:
    def test_create_anonymous_cards_ok(self):
        r = client.post(
            "/api/v1/member/card/types/ct1/anonymous-cards",
            json={"batch_no": "BATCH-001", "count": 10},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["batch_no"] == "BATCH-001"
        assert data["data"]["count"] == 10

    def test_create_anonymous_cards_invalid_count(self):
        r = client.post(
            "/api/v1/member/card/types/ct1/anonymous-cards",
            json={"batch_no": "BATCH-002", "count": 0},
        )
        assert r.status_code == 422  # validation error


class TestIssueCardAPI:
    def test_issue_card_ok(self):
        r = client.post(
            "/api/v1/member/card/issue",
            json={"customer_id": "cust-001", "card_type_id": "ct1"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["customer_id"] == "cust-001"
        assert data["data"]["status"] == "active"


class TestUpgradeDowngradeAPI:
    def test_upgrade_ok(self):
        r = client.post("/api/v1/member/card/cards/card-001/upgrade")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "upgraded" in data["data"]

    def test_downgrade_ok(self):
        r = client.post("/api/v1/member/card/cards/card-001/downgrade")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "downgraded" in data["data"]


class TestMemberDayAPI:
    def test_set_member_day_ok(self):
        r = client.put(
            "/api/v1/member/card/types/ct1/member-day",
            json={"config": {"type": "weekly", "day_of_week": 2}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["card_type_id"] == "ct1"


class TestCardBenefitsAPI:
    def test_get_benefits_ok(self):
        r = client.get(
            "/api/v1/member/card/cards/card-001/benefits",
            params={"store_id": "store-001"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "benefits" in data["data"]

    def test_get_benefits_requires_store_id(self):
        r = client.get("/api/v1/member/card/cards/card-001/benefits")
        assert r.status_code == 422


class TestBatchOperationsAPI:
    def test_batch_ops_ok(self):
        ops = [
            {"type": "recharge", "card_id": "c1", "amount_fen": 10000},
        ]
        r = client.post(
            "/api/v1/member/card/batch-operations",
            json={"operations": ops},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "total_ops" in data["data"]


# ── 服务层纯函数单元测试 ─────────────────────────────────────

from services.card_engine import (
    BATCH_OP_TYPES,
    MEMBER_DAY_TYPES,
    UPGRADE_CRITERIA,
    check_downgrade_eligible,
    check_upgrade_eligible,
    resolve_store_benefits,
    validate_batch_operations,
    validate_level_rules,
    validate_member_day_config,
)


class TestValidateLevelRules:
    def test_valid_levels(self):
        levels = [
            {"name": "银卡", "rank": 1},
            {"name": "金卡", "rank": 2},
        ]
        assert validate_level_rules(levels) is True

    def test_empty_levels(self):
        assert validate_level_rules([]) is False

    def test_duplicate_ranks(self):
        levels = [
            {"name": "银卡", "rank": 1},
            {"name": "金卡", "rank": 1},
        ]
        assert validate_level_rules(levels) is False

    def test_missing_name(self):
        assert validate_level_rules([{"rank": 1}]) is False

    def test_negative_rank(self):
        assert validate_level_rules([{"name": "银卡", "rank": -1}]) is False


class TestUpgradeEligibility:
    def test_upgrade_by_growth_value(self):
        levels = [
            {"name": "普通", "rank": 0, "upgrade_rules": {}},
            {"name": "银卡", "rank": 1, "upgrade_rules": {"growth_value": 100}},
            {"name": "金卡", "rank": 2, "upgrade_rules": {"growth_value": 500}},
        ]
        stats = {"spend_amount_fen": 0, "order_count": 0, "growth_value": 150}
        result = check_upgrade_eligible(0, levels, stats)
        assert result is not None
        assert result["rank"] == 1

    def test_upgrade_to_highest_eligible(self):
        levels = [
            {"name": "普通", "rank": 0, "upgrade_rules": {}},
            {"name": "银卡", "rank": 1, "upgrade_rules": {"growth_value": 100}},
            {"name": "金卡", "rank": 2, "upgrade_rules": {"growth_value": 500}},
        ]
        stats = {"spend_amount_fen": 0, "order_count": 0, "growth_value": 600}
        result = check_upgrade_eligible(0, levels, stats)
        assert result is not None
        assert result["rank"] == 2

    def test_no_upgrade_when_not_eligible(self):
        levels = [
            {"name": "普通", "rank": 0, "upgrade_rules": {}},
            {"name": "银卡", "rank": 1, "upgrade_rules": {"growth_value": 100}},
        ]
        stats = {"spend_amount_fen": 0, "order_count": 0, "growth_value": 50}
        result = check_upgrade_eligible(0, levels, stats)
        assert result is None

    def test_already_at_max_rank(self):
        levels = [
            {"name": "普通", "rank": 0, "upgrade_rules": {}},
            {"name": "金卡", "rank": 2, "upgrade_rules": {"growth_value": 500}},
        ]
        stats = {"growth_value": 9999}
        result = check_upgrade_eligible(2, levels, stats)
        assert result is None


class TestDowngradeEligibility:
    def test_downgrade_when_below_threshold(self):
        levels = [
            {"name": "普通", "rank": 0, "upgrade_rules": {}, "downgrade_rules": {}},
            {"name": "银卡", "rank": 1, "upgrade_rules": {}, "downgrade_rules": {"growth_value": 100}},
        ]
        stats = {"spend_amount_fen": 0, "order_count": 0, "growth_value": 50}
        result = check_downgrade_eligible(1, levels, stats)
        assert result is not None
        assert result["rank"] == 0

    def test_no_downgrade_when_above_threshold(self):
        levels = [
            {"name": "普通", "rank": 0, "upgrade_rules": {}, "downgrade_rules": {}},
            {"name": "银卡", "rank": 1, "upgrade_rules": {}, "downgrade_rules": {"growth_value": 100}},
        ]
        stats = {"spend_amount_fen": 0, "order_count": 0, "growth_value": 150}
        result = check_downgrade_eligible(1, levels, stats)
        assert result is None

    def test_no_downgrade_without_rules(self):
        levels = [
            {"name": "普通", "rank": 0, "upgrade_rules": {}},
            {"name": "银卡", "rank": 1, "upgrade_rules": {}},
        ]
        stats = {"growth_value": 0}
        result = check_downgrade_eligible(1, levels, stats)
        assert result is None


class TestMemberDayConfig:
    def test_weekly_valid(self):
        assert validate_member_day_config({"type": "weekly", "day_of_week": 2}) is True

    def test_monthly_valid(self):
        assert validate_member_day_config({"type": "monthly", "day_of_month": 15}) is True

    def test_invalid_type(self):
        assert validate_member_day_config({"type": "daily"}) is False

    def test_weekly_invalid_day(self):
        assert validate_member_day_config({"type": "weekly", "day_of_week": 7}) is False

    def test_monthly_invalid_day(self):
        assert validate_member_day_config({"type": "monthly", "day_of_month": 29}) is False
        assert validate_member_day_config({"type": "monthly", "day_of_month": 0}) is False


class TestResolveStoreBenefits:
    def test_no_overrides(self):
        benefits = [{"key": "discount", "value": 0.9}]
        result = resolve_store_benefits(benefits, {}, "store-1")
        assert result == benefits

    def test_with_overrides(self):
        benefits = [{"key": "discount", "value": 0.9}]
        overrides = {"store-1": {"discount": {"value": 0.85}}}
        result = resolve_store_benefits(benefits, overrides, "store-1")
        assert result[0]["value"] == 0.85

    def test_other_store_no_effect(self):
        benefits = [{"key": "discount", "value": 0.9}]
        overrides = {"store-1": {"discount": {"value": 0.85}}}
        result = resolve_store_benefits(benefits, overrides, "store-2")
        assert result[0]["value"] == 0.9


class TestBatchOperationsValidation:
    def test_valid_ops(self):
        ops = [{"type": "recharge", "card_id": "c1", "amount_fen": 10000}]
        valid, msg = validate_batch_operations(ops)
        assert valid is True

    def test_empty_ops(self):
        valid, msg = validate_batch_operations([])
        assert valid is False

    def test_invalid_type(self):
        ops = [{"type": "unknown", "card_id": "c1", "amount_fen": 100}]
        valid, msg = validate_batch_operations(ops)
        assert valid is False

    def test_invalid_amount(self):
        ops = [{"type": "recharge", "card_id": "c1", "amount_fen": -100}]
        valid, msg = validate_batch_operations(ops)
        assert valid is False

    def test_missing_card_id(self):
        ops = [{"type": "recharge", "amount_fen": 100}]
        valid, msg = validate_batch_operations(ops)
        assert valid is False


class TestConstants:
    def test_upgrade_criteria(self):
        assert "spend_amount_fen" in UPGRADE_CRITERIA
        assert "order_count" in UPGRADE_CRITERIA
        assert "growth_value" in UPGRADE_CRITERIA

    def test_member_day_types(self):
        assert "weekly" in MEMBER_DAY_TYPES
        assert "monthly" in MEMBER_DAY_TYPES

    def test_batch_op_types(self):
        assert "recharge" in BATCH_OP_TYPES
        assert "deduct" in BATCH_OP_TYPES
        assert "transfer" in BATCH_OP_TYPES
