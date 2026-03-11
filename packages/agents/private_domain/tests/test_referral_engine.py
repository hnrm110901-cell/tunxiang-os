"""
裂变场景自动识别引擎 referral_engine 单元测试 — B3·方向五
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from referral_engine import (
    REFERRAL_PLAYBOOKS,
    ReferralScenario,
    detect_and_get_playbook,
    detect_referral_potential,
    get_playbook,
)


# ── 剧本结构验证 ──────────────────────────────────────────────────────────────


class TestReferralPlaybooksStructure:
    def test_all_four_scenarios_have_playbooks(self):
        assert set(REFERRAL_PLAYBOOKS.keys()) == set(ReferralScenario)

    def test_each_playbook_has_required_fields(self):
        required = {"trigger_timing", "bait", "tool", "hook", "k_estimate", "psychology"}
        for scenario, pb in REFERRAL_PLAYBOOKS.items():
            missing = required - set(pb.keys())
            assert not missing, f"{scenario} 缺少字段: {missing}"

    def test_birthday_organizer_highest_k_value(self):
        """生日宴 K 值应最高（K=3.2）。"""
        birthday_k = REFERRAL_PLAYBOOKS[ReferralScenario.BIRTHDAY_ORGANIZER]["k_estimate"]
        for scenario, pb in REFERRAL_PLAYBOOKS.items():
            if scenario != ReferralScenario.BIRTHDAY_ORGANIZER:
                assert birthday_k >= pb["k_estimate"]

    def test_all_k_values_above_1(self):
        """所有高 K 值场景 K≥1.5（才有裂变意义）。"""
        for scenario, pb in REFERRAL_PLAYBOOKS.items():
            assert pb["k_estimate"] >= 1.5, f"{scenario} K值 {pb['k_estimate']} 过低"

    def test_no_discount_in_bait(self):
        """
        《怪诞行为学》锚定效应：诱饵不应是折扣优惠券（折扣会拉低价格锚点）。
        检查：bait 中不应出现「X折」或「优惠券」等折扣语言。
        """
        import re
        discount_pattern = re.compile(r"\d折|优惠券|打折")
        for scenario, pb in REFERRAL_PLAYBOOKS.items():
            bait = pb["bait"]
            assert not discount_pattern.search(bait), (
                f"{scenario} 裂变诱饵包含折扣，会破坏价值锚点: {bait}"
            )

    def test_super_fan_uses_identity_not_money(self):
        """超级用户裂变动机是身份认同，不是金钱激励。"""
        pb = REFERRAL_PLAYBOOKS[ReferralScenario.SUPER_FAN]
        assert "荣誉" in pb["bait"] or "身份" in pb["bait"]
        assert "影响力" in pb["psychology"] or "身份认同" in pb["psychology"]


# ── detect_referral_potential 检测逻辑 ───────────────────────────────────────


class TestDetectReferralPotential:
    def _customer(self, **kwargs):
        return {"customer_id": "C001", **kwargs}

    def _orders(self, **kwargs):
        """默认：1次订单，2人桌，5天前，工作日午餐。"""
        base = {"days_ago": 5, "party_size": 2, "tags": "", "weekday": True, "hour": 12}
        base.update(kwargs)
        return [base]

    # ── 生日宴 ──────────────────────────────────────────────────────────────

    def test_birthday_tag_detected(self):
        orders = self._orders(tags="生日套餐", days_ago=10)
        result = detect_referral_potential(self._customer(), orders)
        assert result == ReferralScenario.BIRTHDAY_ORGANIZER

    def test_birthday_tag_in_any_recent_order(self):
        orders = [
            {"days_ago": 5, "party_size": 2, "tags": ""},
            {"days_ago": 80, "party_size": 4, "tags": "生日蛋糕"},
        ]
        result = detect_referral_potential(self._customer(), orders)
        assert result == ReferralScenario.BIRTHDAY_ORGANIZER

    def test_birthday_order_over_90_days_not_detected(self):
        """超过90天的订单不参与近期分析。"""
        orders = self._orders(tags="生日", days_ago=91)
        result = detect_referral_potential(self._customer(), orders)
        assert result != ReferralScenario.BIRTHDAY_ORGANIZER

    def test_birthday_has_priority_over_large_party(self):
        """同时有生日标签和大桌，优先返回 BIRTHDAY_ORGANIZER。"""
        orders = [{"days_ago": 5, "party_size": 8, "tags": "生日", "weekday": True, "hour": 12}]
        result = detect_referral_potential(self._customer(), orders)
        assert result == ReferralScenario.BIRTHDAY_ORGANIZER

    # ── 家宴 ────────────────────────────────────────────────────────────────

    def test_avg_party_size_6_detects_family_banquet(self):
        orders = [
            {"days_ago": 5, "party_size": 6, "tags": "", "weekday": False, "hour": 18},
            {"days_ago": 20, "party_size": 8, "tags": "", "weekday": False, "hour": 18},
        ]
        result = detect_referral_potential(self._customer(), orders)
        assert result == ReferralScenario.FAMILY_BANQUET

    def test_small_party_not_family_banquet(self):
        orders = self._orders(party_size=3)
        result = detect_referral_potential(self._customer(), orders)
        assert result != ReferralScenario.FAMILY_BANQUET

    # ── 商务宴请 ─────────────────────────────────────────────────────────────

    def test_two_weekday_lunch_large_tables_detects_corporate(self):
        orders = [
            {"days_ago": 10, "party_size": 5, "tags": "", "weekday": True, "hour": 12},
            {"days_ago": 25, "party_size": 4, "tags": "", "weekday": True, "hour": 13},
        ]
        result = detect_referral_potential(self._customer(), orders)
        assert result == ReferralScenario.CORPORATE_HOST

    def test_one_business_order_not_enough(self):
        orders = [
            {"days_ago": 10, "party_size": 5, "tags": "", "weekday": True, "hour": 12},
        ]
        result = detect_referral_potential(self._customer(), orders)
        # 只有1次商务订单，不满足≥2次，结果不应是CORPORATE_HOST
        assert result != ReferralScenario.CORPORATE_HOST

    def test_weekend_lunch_not_corporate(self):
        orders = [
            {"days_ago": 10, "party_size": 6, "tags": "", "weekday": False, "hour": 12},
            {"days_ago": 20, "party_size": 5, "tags": "", "weekday": False, "hour": 12},
        ]
        result = detect_referral_potential(self._customer(), orders)
        assert result != ReferralScenario.CORPORATE_HOST

    # ── 超级用户 ─────────────────────────────────────────────────────────────

    def test_4_orders_in_30_days_detects_super_fan(self):
        orders = [
            {"days_ago": 5,  "party_size": 2, "tags": "", "weekday": True, "hour": 19},
            {"days_ago": 12, "party_size": 2, "tags": "", "weekday": True, "hour": 19},
            {"days_ago": 20, "party_size": 2, "tags": "", "weekday": True, "hour": 19},
            {"days_ago": 28, "party_size": 2, "tags": "", "weekday": True, "hour": 19},
        ]
        result = detect_referral_potential(self._customer(), orders)
        assert result == ReferralScenario.SUPER_FAN

    def test_3_orders_in_30_days_not_super_fan(self):
        orders = [
            {"days_ago": 5,  "party_size": 2, "tags": "", "weekday": True, "hour": 19},
            {"days_ago": 12, "party_size": 2, "tags": "", "weekday": True, "hour": 19},
            {"days_ago": 20, "party_size": 2, "tags": "", "weekday": True, "hour": 19},
        ]
        result = detect_referral_potential(self._customer(), orders)
        assert result != ReferralScenario.SUPER_FAN

    # ── 无匹配 ───────────────────────────────────────────────────────────────

    def test_no_signal_returns_none(self):
        orders = self._orders(party_size=2, tags="")
        result = detect_referral_potential(self._customer(), orders)
        assert result is None

    def test_empty_order_history_returns_none(self):
        result = detect_referral_potential(self._customer(), [])
        assert result is None


# ── get_playbook 和 detect_and_get_playbook ──────────────────────────────────


class TestGetPlaybook:
    def test_returns_correct_playbook(self):
        pb = get_playbook(ReferralScenario.BIRTHDAY_ORGANIZER)
        assert pb["k_estimate"] == 3.2

    def test_super_fan_playbook_identity_bait(self):
        pb = get_playbook(ReferralScenario.SUPER_FAN)
        assert "荣誉" in pb["bait"]


class TestDetectAndGetPlaybook:
    def test_returns_none_for_no_signal(self):
        result = detect_and_get_playbook({}, [])
        assert result is None

    def test_returns_scenario_and_playbook(self):
        orders = [{"days_ago": 5, "party_size": 2, "tags": "生日", "weekday": True, "hour": 12}]
        result = detect_and_get_playbook({}, orders)
        assert result is not None
        assert result["scenario"] == ReferralScenario.BIRTHDAY_ORGANIZER
        assert "bait" in result["playbook"]
        assert "hook" in result["playbook"]

    def test_playbook_k_estimate_is_float(self):
        orders = [{"days_ago": 5, "party_size": 2, "tags": "生日", "weekday": True, "hour": 12}]
        result = detect_and_get_playbook({}, orders)
        assert isinstance(result["playbook"]["k_estimate"], float)
