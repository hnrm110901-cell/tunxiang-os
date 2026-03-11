"""
会员进度推送引擎 member_progress_engine 单元测试 — A4·方向八
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from member_progress_engine import (
    LEVEL_MIN_VISITS,
    LEVEL_PRIVILEGE,
    MILESTONE_PUSH_RULES,
    MemberLevel,
    MilestoneType,
    _get_level,
    _next_level,
    _visits_to_next_level,
    build_push_message,
    check_milestones,
)


# ── 等级工具函数 ──────────────────────────────────────────────────────────────


class TestGetLevel:
    def test_1_visit_new_friend(self):
        assert _get_level(1) == MemberLevel.NEW_FRIEND

    def test_3_visits_still_new_friend(self):
        assert _get_level(3) == MemberLevel.NEW_FRIEND

    def test_4_visits_regular(self):
        assert _get_level(4) == MemberLevel.REGULAR

    def test_7_visits_still_regular(self):
        assert _get_level(7) == MemberLevel.REGULAR

    def test_8_visits_old_friend(self):
        assert _get_level(8) == MemberLevel.OLD_FRIEND

    def test_15_visits_still_old_friend(self):
        assert _get_level(15) == MemberLevel.OLD_FRIEND

    def test_16_visits_honored_guest(self):
        assert _get_level(16) == MemberLevel.HONORED_GUEST

    def test_100_visits_honored_guest(self):
        assert _get_level(100) == MemberLevel.HONORED_GUEST


class TestNextLevel:
    def test_new_friend_next_is_regular(self):
        assert _next_level(MemberLevel.NEW_FRIEND) == MemberLevel.REGULAR

    def test_regular_next_is_old_friend(self):
        assert _next_level(MemberLevel.REGULAR) == MemberLevel.OLD_FRIEND

    def test_old_friend_next_is_honored_guest(self):
        assert _next_level(MemberLevel.OLD_FRIEND) == MemberLevel.HONORED_GUEST

    def test_honored_guest_has_no_next(self):
        assert _next_level(MemberLevel.HONORED_GUEST) is None


class TestVisitsToNextLevel:
    def test_3_visits_need_1_more(self):
        assert _visits_to_next_level(3) == 1

    def test_7_visits_need_1_more(self):
        assert _visits_to_next_level(7) == 1

    def test_15_visits_need_1_more(self):
        assert _visits_to_next_level(15) == 1

    def test_2_visits_need_2_more(self):
        assert _visits_to_next_level(2) == 2

    def test_16_visits_no_next(self):
        assert _visits_to_next_level(16) is None

    def test_50_visits_no_next(self):
        assert _visits_to_next_level(50) is None


# ── build_push_message 测试 ───────────────────────────────────────────────────


class TestBuildPushMessage:
    def _m(self, **kwargs):
        base = {
            "store_name":         "徐记海鲜",
            "total_visits":       1,
            "total_spend":        150.0,
            "points":             200,
            "points_expire_days": 5,
            "favorite_dish":      "清蒸鲈鱼",
            "consecutive_months": 4,
            "first_visit_date":   "2025-03-11",
        }
        base.update(kwargs)
        return base

    def test_first_spend_100_contains_store_name(self):
        msg = build_push_message(MilestoneType.FIRST_SPEND_100, self._m())
        assert "徐记海鲜" in msg

    def test_first_spend_100_contains_new_friend_label(self):
        msg = build_push_message(MilestoneType.FIRST_SPEND_100, self._m())
        assert "新朋友" in msg

    def test_first_spend_100_contains_remaining_visits(self):
        # total_visits=1, 距熟客(4次)还差3次
        msg = build_push_message(MilestoneType.FIRST_SPEND_100, self._m(total_visits=1))
        assert "3" in msg

    def test_one_away_contains_next_level_name(self):
        # total_visits=3 → 下一级熟客
        msg = build_push_message(MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL, self._m(total_visits=3))
        assert "熟客" in msg

    def test_one_away_old_friend_transition(self):
        # total_visits=7 → 下一级老朋友
        msg = build_push_message(MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL, self._m(total_visits=7))
        assert "老朋友" in msg

    def test_one_away_honored_guest_is_top(self):
        msg = build_push_message(MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL, self._m(total_visits=16))
        assert "最高等级" in msg

    def test_consecutive_months_contains_count(self):
        msg = build_push_message(MilestoneType.CONSECUTIVE_MONTHS_3, self._m(consecutive_months=5))
        assert "5" in msg

    def test_consecutive_months_contains_favorite_dish(self):
        msg = build_push_message(MilestoneType.CONSECUTIVE_MONTHS_3, self._m(favorite_dish="口水鸡"))
        assert "口水鸡" in msg

    def test_consecutive_months_no_discount_word(self):
        """《关系飞轮》：不在关系里程碑插入折扣，否则降维成交易。"""
        msg = build_push_message(MilestoneType.CONSECUTIVE_MONTHS_3, self._m())
        assert "折" not in msg
        assert "优惠" not in msg

    def test_points_expiring_contains_points_count(self):
        msg = build_push_message(MilestoneType.POINTS_EXPIRING_7D, self._m(points=500, points_expire_days=3))
        assert "500" in msg
        assert "3" in msg

    def test_points_expiring_contains_redeem_options(self):
        msg = build_push_message(MilestoneType.POINTS_EXPIRING_7D, self._m())
        assert "兑换" in msg

    def test_annual_anniversary_contains_store_name(self):
        msg = build_push_message(MilestoneType.ANNUAL_ANNIVERSARY, self._m())
        assert "徐记海鲜" in msg

    def test_annual_anniversary_contains_visit_count(self):
        msg = build_push_message(MilestoneType.ANNUAL_ANNIVERSARY, self._m(total_visits=12))
        assert "12" in msg


# ── check_milestones 集成测试 ─────────────────────────────────────────────────


class TestCheckMilestones:
    def _base(self, **kwargs):
        base = {
            "store_name":         "徐记海鲜",
            "total_visits":       1,
            "total_spend":        50.0,
            "is_first_spend":     False,
            "points":             0,
            "points_expire_days": None,
            "consecutive_months": 0,
            "favorite_dish":      "招牌蟹",
            "first_visit_date":   None,
            "today":              "2026-03-11",
        }
        base.update(kwargs)
        return base

    def test_no_milestone_for_baseline(self):
        assert check_milestones(self._base()) == []

    def test_first_spend_100_triggers(self):
        result = check_milestones(self._base(is_first_spend=True, total_spend=120.0, total_visits=1))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.FIRST_SPEND_100 in types

    def test_first_spend_below_100_no_trigger(self):
        result = check_milestones(self._base(is_first_spend=True, total_spend=80.0))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.FIRST_SPEND_100 not in types

    def test_not_first_spend_no_trigger(self):
        result = check_milestones(self._base(is_first_spend=False, total_spend=200.0))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.FIRST_SPEND_100 not in types

    def test_one_away_from_regular_triggers(self):
        result = check_milestones(self._base(total_visits=3))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL in types

    def test_one_away_from_old_friend_triggers(self):
        result = check_milestones(self._base(total_visits=7))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL in types

    def test_one_away_from_honored_guest_triggers(self):
        result = check_milestones(self._base(total_visits=15))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL in types

    def test_not_one_away_no_trigger(self):
        result = check_milestones(self._base(total_visits=2))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL not in types

    def test_top_level_no_one_away_trigger(self):
        result = check_milestones(self._base(total_visits=16))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL not in types

    def test_consecutive_3_months_triggers(self):
        result = check_milestones(self._base(consecutive_months=3))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.CONSECUTIVE_MONTHS_3 in types

    def test_consecutive_5_months_also_triggers(self):
        result = check_milestones(self._base(consecutive_months=5))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.CONSECUTIVE_MONTHS_3 in types

    def test_consecutive_2_months_no_trigger(self):
        result = check_milestones(self._base(consecutive_months=2))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.CONSECUTIVE_MONTHS_3 not in types

    def test_points_expiring_within_7_days_triggers(self):
        result = check_milestones(self._base(points=200, points_expire_days=5))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.POINTS_EXPIRING_7D in types

    def test_points_expiring_exactly_7_days_triggers(self):
        result = check_milestones(self._base(points=100, points_expire_days=7))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.POINTS_EXPIRING_7D in types

    def test_points_expiring_8_days_no_trigger(self):
        result = check_milestones(self._base(points=200, points_expire_days=8))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.POINTS_EXPIRING_7D not in types

    def test_zero_points_no_expiry_trigger(self):
        result = check_milestones(self._base(points=0, points_expire_days=3))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.POINTS_EXPIRING_7D not in types

    def test_points_expire_days_none_no_trigger(self):
        result = check_milestones(self._base(points=500, points_expire_days=None))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.POINTS_EXPIRING_7D not in types

    def test_annual_anniversary_triggers_on_same_date(self):
        result = check_milestones(self._base(
            first_visit_date="2025-03-11",
            today="2026-03-11",
            total_visits=10,
        ))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.ANNUAL_ANNIVERSARY in types

    def test_annual_anniversary_no_trigger_wrong_date(self):
        result = check_milestones(self._base(
            first_visit_date="2025-03-10",
            today="2026-03-11",
        ))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.ANNUAL_ANNIVERSARY not in types

    def test_annual_anniversary_no_first_visit_no_trigger(self):
        result = check_milestones(self._base(first_visit_date=None, today="2026-03-11"))
        types = [r["milestone_type"] for r in result]
        assert MilestoneType.ANNUAL_ANNIVERSARY not in types

    def test_multiple_milestones_trigger_simultaneously(self):
        result = check_milestones(self._base(
            total_visits=3,
            consecutive_months=3,
            points=100,
            points_expire_days=5,
        ))
        assert len(result) >= 3

    def test_result_item_has_message_and_psychology(self):
        result = check_milestones(self._base(consecutive_months=3))
        assert len(result) == 1
        item = result[0]
        assert "message" in item
        assert "psychology" in item
        assert len(item["message"]) > 0

    def test_result_item_has_milestone_type(self):
        result = check_milestones(self._base(consecutive_months=3))
        assert result[0]["milestone_type"] == MilestoneType.CONSECUTIVE_MONTHS_3


# ── MILESTONE_PUSH_RULES 结构验证 ────────────────────────────────────────────


class TestMilestonePushRules:
    def test_has_five_rules(self):
        assert len(MILESTONE_PUSH_RULES) == 5

    def test_all_milestone_types_covered(self):
        covered = {r["milestone"] for r in MILESTONE_PUSH_RULES}
        assert covered == set(MilestoneType)

    def test_each_rule_has_push_timing(self):
        for rule in MILESTONE_PUSH_RULES:
            assert "push_timing" in rule, f"{rule['milestone']} 缺少 push_timing"

    def test_each_rule_has_psychology(self):
        for rule in MILESTONE_PUSH_RULES:
            assert "psychology" in rule, f"{rule['milestone']} 缺少 psychology"

    def test_consecutive_months_rule_has_forbidden(self):
        rule = next(r for r in MILESTONE_PUSH_RULES if r["milestone"] == MilestoneType.CONSECUTIVE_MONTHS_3)
        assert "forbidden" in rule

    def test_one_away_rule_has_note(self):
        rule = next(r for r in MILESTONE_PUSH_RULES if r["milestone"] == MilestoneType.ONE_AWAY_FROM_NEXT_LEVEL)
        assert "note" in rule
