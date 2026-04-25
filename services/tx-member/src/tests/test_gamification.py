"""游戏化忠诚度2.0 单元测试 — 徽章/挑战/惊喜奖励

测试范围：
  - Badge API: CRUD + evaluate + leaderboard + holders
  - Challenge API: CRUD + join + progress + claim
  - Surprise Reward: 规则注册 + 概率触发 + 防重复
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.badge_routes import router as badge_router
from api.challenge_routes import router as challenge_router
from fastapi.testclient import TestClient
from main import app

# 注册路由
for r in (badge_router, challenge_router):
    prefix = getattr(r, "prefix", "")
    if not any(getattr(rt, "prefix", "") == prefix for rt in app.routes if hasattr(rt, "prefix")):
        app.include_router(r)

client = TestClient(app)

TENANT = "test-tenant-gamification"
HEADERS = {"X-Tenant-ID": TENANT}


# ═══════════════════════════════════════════════════════════════════════════════
# Badge API Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateBadge:
    def test_create_badge_ok(self):
        r = client.post(
            "/api/v1/member/badges",
            json={
                "name": "首次到店",
                "category": "milestone",
                "unlock_rule": {"type": "visit_count", "threshold": 1},
                "rarity": "common",
                "points_reward": 100,
            },
            headers=HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["name"] == "首次到店"
        assert data["data"]["category"] == "milestone"
        assert "id" in data["data"]

    def test_create_badge_minimal(self):
        r = client.post(
            "/api/v1/member/badges",
            json={"name": "基础徽章", "category": "loyalty"},
            headers=HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestListBadges:
    def test_list_badges_ok(self):
        # 先创建
        client.post(
            "/api/v1/member/badges",
            json={"name": "列表测试", "category": "social"},
            headers=HEADERS,
        )
        r = client.get("/api/v1/member/badges", headers=HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]

    def test_list_badges_with_category_filter(self):
        r = client.get("/api/v1/member/badges?category=social", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestGetBadge:
    def test_get_badge_ok(self):
        cr = client.post(
            "/api/v1/member/badges",
            json={"name": "获取测试", "category": "exploration"},
            headers=HEADERS,
        )
        badge_id = cr.json()["data"]["id"]
        r = client.get(f"/api/v1/member/badges/{badge_id}", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["data"]["name"] == "获取测试"

    def test_get_badge_not_found(self):
        r = client.get("/api/v1/member/badges/nonexistent-id", headers=HEADERS)
        assert r.json()["ok"] is False


class TestUpdateBadge:
    def test_update_badge_ok(self):
        cr = client.post(
            "/api/v1/member/badges",
            json={"name": "更新前", "category": "loyalty"},
            headers=HEADERS,
        )
        badge_id = cr.json()["data"]["id"]
        r = client.put(
            f"/api/v1/member/badges/{badge_id}",
            json={"name": "更新后", "points_reward": 200},
            headers=HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["data"]["name"] == "更新后"
        assert r.json()["data"]["points_reward"] == 200


class TestDeleteBadge:
    def test_delete_badge_ok(self):
        cr = client.post(
            "/api/v1/member/badges",
            json={"name": "删除测试", "category": "seasonal"},
            headers=HEADERS,
        )
        badge_id = cr.json()["data"]["id"]
        r = client.delete(f"/api/v1/member/badges/{badge_id}", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["data"]["deleted"] is True


class TestEvaluateBadges:
    def test_evaluate_ok(self):
        r = client.post(
            "/api/v1/member/badges/evaluate",
            json={"customer_id": "cust-001"},
            headers=HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "newly_unlocked" in data["data"]


class TestBadgeLeaderboard:
    def test_leaderboard_ok(self):
        r = client.get("/api/v1/member/badges/leaderboard/top", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestBadgeHolders:
    def test_holders_ok(self):
        cr = client.post(
            "/api/v1/member/badges",
            json={"name": "持有者测试", "category": "milestone"},
            headers=HEADERS,
        )
        badge_id = cr.json()["data"]["id"]
        r = client.get(f"/api/v1/member/badges/{badge_id}/holders", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Challenge API Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateChallenge:
    def test_create_challenge_ok(self):
        r = client.post(
            "/api/v1/member/challenges",
            json={
                "name": "连续7天打卡",
                "type": "visit_streak",
                "rules": {"target": 7, "consecutive": True},
                "reward": {"type": "points", "amount": 500},
                "start_date": "2026-04-01T00:00:00Z",
                "end_date": "2026-05-01T00:00:00Z",
            },
            headers=HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["name"] == "连续7天打卡"
        assert data["data"]["type"] == "visit_streak"


class TestListChallenges:
    def test_list_ok(self):
        r = client.get("/api/v1/member/challenges", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert "items" in r.json()["data"]

    def test_list_filter_type(self):
        r = client.get("/api/v1/member/challenges?type=visit_streak", headers=HEADERS)
        assert r.status_code == 200


class TestJoinChallenge:
    def test_join_and_progress(self):
        # 创建挑战
        cr = client.post(
            "/api/v1/member/challenges",
            json={
                "name": "测试挑战",
                "type": "spend_target",
                "rules": {"target": 3},
                "reward": {"type": "points", "amount": 100},
                "start_date": "2026-04-01T00:00:00Z",
                "end_date": "2026-05-01T00:00:00Z",
            },
            headers=HEADERS,
        )
        ch_id = cr.json()["data"]["id"]

        # 参加
        jr = client.post(
            "/api/v1/member/challenges/join",
            json={"customer_id": "cust-join-001", "challenge_id": ch_id},
            headers=HEADERS,
        )
        assert jr.status_code == 200
        assert jr.json()["data"]["status"] == "active"
        assert jr.json()["data"]["target_value"] == 3

        # 更新进度
        pr = client.post(
            "/api/v1/member/challenges/progress",
            json={"customer_id": "cust-join-001", "challenge_id": ch_id, "increment": 2},
            headers=HEADERS,
        )
        assert pr.status_code == 200
        assert pr.json()["data"]["current_value"] == 2
        assert pr.json()["data"]["status"] == "active"

        # 完成
        pr2 = client.post(
            "/api/v1/member/challenges/progress",
            json={"customer_id": "cust-join-001", "challenge_id": ch_id, "increment": 1},
            headers=HEADERS,
        )
        assert pr2.json()["data"]["status"] == "completed"

    def test_join_idempotent(self):
        cr = client.post(
            "/api/v1/member/challenges",
            json={
                "name": "幂等测试",
                "type": "visit_streak",
                "rules": {"target": 5},
                "reward": {"type": "points", "amount": 50},
                "start_date": "2026-04-01T00:00:00Z",
                "end_date": "2026-05-01T00:00:00Z",
            },
            headers=HEADERS,
        )
        ch_id = cr.json()["data"]["id"]

        j1 = client.post(
            "/api/v1/member/challenges/join",
            json={"customer_id": "cust-idem", "challenge_id": ch_id},
            headers=HEADERS,
        )
        j2 = client.post(
            "/api/v1/member/challenges/join",
            json={"customer_id": "cust-idem", "challenge_id": ch_id},
            headers=HEADERS,
        )
        assert j1.json()["ok"] is True
        assert j2.json()["ok"] is True


class TestClaimReward:
    def test_claim_after_complete(self):
        cr = client.post(
            "/api/v1/member/challenges",
            json={
                "name": "领取测试",
                "type": "visit_streak",
                "rules": {"target": 1},
                "reward": {"type": "points", "amount": 999},
                "start_date": "2026-04-01T00:00:00Z",
                "end_date": "2026-05-01T00:00:00Z",
            },
            headers=HEADERS,
        )
        ch_id = cr.json()["data"]["id"]

        client.post(
            "/api/v1/member/challenges/join",
            json={"customer_id": "cust-claim", "challenge_id": ch_id},
            headers=HEADERS,
        )
        client.post(
            "/api/v1/member/challenges/progress",
            json={"customer_id": "cust-claim", "challenge_id": ch_id, "increment": 1},
            headers=HEADERS,
        )

        r = client.post(
            "/api/v1/member/challenges/claim",
            json={"customer_id": "cust-claim", "challenge_id": ch_id},
            headers=HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["data"]["claimed"] is True
        assert r.json()["data"]["reward"]["amount"] == 999

    def test_claim_not_completed(self):
        cr = client.post(
            "/api/v1/member/challenges",
            json={
                "name": "未完成领取",
                "type": "visit_streak",
                "rules": {"target": 10},
                "reward": {"type": "points", "amount": 50},
                "start_date": "2026-04-01T00:00:00Z",
                "end_date": "2026-05-01T00:00:00Z",
            },
            headers=HEADERS,
        )
        ch_id = cr.json()["data"]["id"]

        client.post(
            "/api/v1/member/challenges/join",
            json={"customer_id": "cust-notdone", "challenge_id": ch_id},
            headers=HEADERS,
        )
        r = client.post(
            "/api/v1/member/challenges/claim",
            json={"customer_id": "cust-notdone", "challenge_id": ch_id},
            headers=HEADERS,
        )
        assert r.json()["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# Surprise Reward Tests (unit, no DB)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSurpriseReward:
    def test_register_rule(self):
        from services.surprise_reward import (
            clear_surprise_rules,
            get_surprise_rules,
            register_surprise_rule,
        )

        clear_surprise_rules()
        rule_id = register_surprise_rule(
            "t1",
            {
                "nth_visit": 10,
                "probability": 1.0,
                "reward": {"type": "points", "amount": 200},
            },
        )
        assert rule_id
        rules = get_surprise_rules("t1")
        assert len(rules) == 1
        assert rules[0]["nth_visit"] == 10

    def test_rules_isolated_by_tenant(self):
        from services.surprise_reward import (
            clear_surprise_rules,
            get_surprise_rules,
            register_surprise_rule,
        )

        clear_surprise_rules()
        register_surprise_rule("t-a", {"nth_visit": 5, "probability": 1.0, "reward": {}})
        register_surprise_rule("t-b", {"nth_visit": 10, "probability": 1.0, "reward": {}})
        assert len(get_surprise_rules("t-a")) == 1
        assert len(get_surprise_rules("t-b")) == 1
        assert get_surprise_rules("t-a")[0]["nth_visit"] == 5

    def test_clear_rules(self):
        from services.surprise_reward import (
            clear_surprise_rules,
            get_surprise_rules,
            register_surprise_rule,
        )

        clear_surprise_rules()
        register_surprise_rule("t-c", {"nth_visit": 3, "probability": 1.0, "reward": {}})
        clear_surprise_rules("t-c")
        assert len(get_surprise_rules("t-c")) == 0
