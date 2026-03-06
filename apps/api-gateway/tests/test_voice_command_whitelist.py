"""
tests/test_voice_command_whitelist.py

测试语音指令白名单：纯函数 + 类接口
无 DB / 无网络依赖
"""
import os
import sys

# pydantic_settings 校验前先设置最小环境变量（L002 规则）
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from src.core.voice_command_whitelist import (
    RiskLevel,
    VoiceCommandWhitelist,
    VoiceValidationResult,
    classify_risk_level,
    get_confirmation_type,
    is_high_risk_operation,
)


# ── classify_risk_level 纯函数测试 ────────────────────────────────────────────

class TestClassifyRiskLevel:
    def test_query_commands_are_safe(self):
        for cmd in ["查询库存", "查看订单", "今天营收多少", "昨天库存状态"]:
            level, _ = classify_risk_level(cmd)
            assert level == RiskLevel.SAFE, f"期望 SAFE: {cmd!r}"

    def test_notify_commands_are_safe(self):
        for cmd in ["催菜", "呼叫服务员", "通知后厨", "提醒备料"]:
            level, category = classify_risk_level(cmd)
            assert level == RiskLevel.SAFE
            assert category == "notify"

    def test_simple_confirm_commands_are_safe(self):
        level, category = classify_risk_level("确认收货")
        assert level == RiskLevel.SAFE
        assert category == "simple_confirm"

    def test_financial_commands_are_high_risk(self):
        for cmd in ["退款给客户", "打款给供应商", "转账500元", "提现申请"]:
            level, category = classify_risk_level(cmd)
            assert level == RiskLevel.HIGH_RISK, f"期望 HIGH_RISK: {cmd!r}"
            assert category == "financial"

    def test_bulk_inventory_is_high_risk(self):
        level, category = classify_risk_level("批量删除库存")
        assert level == RiskLevel.HIGH_RISK
        assert category == "bulk_inventory"

    def test_system_commands_are_high_risk(self):
        for cmd in ["修改权限", "删除数据", "重置系统"]:
            level, _ = classify_risk_level(cmd)
            assert level == RiskLevel.HIGH_RISK, f"期望 HIGH_RISK: {cmd!r}"

    def test_purchase_commands_require_confirm(self):
        for cmd in ["采购食材", "下单进货", "补货申请"]:
            level, category = classify_risk_level(cmd)
            assert level == RiskLevel.CONFIRM, f"期望 CONFIRM: {cmd!r}"
            assert category == "purchase"

    def test_adjust_commands_require_confirm(self):
        level, category = classify_risk_level("调整排班")
        assert level == RiskLevel.CONFIRM
        assert category in ("adjust", "schedule")

    def test_unknown_command_falls_back_to_confirm(self):
        level, category = classify_risk_level("啊啊啊随机命令")
        assert level == RiskLevel.CONFIRM
        assert category == "unknown"

    def test_high_risk_wins_over_safe_in_mixed_command(self):
        """同时含"查询"和"退款"关键词，高危优先。"""
        level, _ = classify_risk_level("查询退款记录")
        assert level == RiskLevel.HIGH_RISK

    def test_category_returned_matches_matched_group(self):
        _, category = classify_risk_level("退款操作")
        assert category == "financial"


# ── is_high_risk_operation 纯函数 ─────────────────────────────────────────────

class TestIsHighRiskOperation:
    def test_returns_true_for_financial(self):
        assert is_high_risk_operation("转账给供应商") is True

    def test_returns_false_for_query(self):
        assert is_high_risk_operation("查询库存") is False

    def test_returns_false_for_confirm_level(self):
        assert is_high_risk_operation("采购食材") is False


# ── get_confirmation_type 纯函数 ──────────────────────────────────────────────

class TestGetConfirmationType:
    def test_safe_commands_need_none(self):
        assert get_confirmation_type("查看今日营收") == "none"

    def test_confirm_commands_need_voice(self):
        assert get_confirmation_type("采购50斤牛肉") == "voice"

    def test_high_risk_commands_need_mobile(self):
        assert get_confirmation_type("退款200元") == "mobile"


# ── VoiceCommandWhitelist 类接口测试 ─────────────────────────────────────────

class TestVoiceCommandWhitelist:
    def setup_method(self):
        self.whitelist = VoiceCommandWhitelist()

    def test_returns_validation_result_type(self):
        result = self.whitelist.validate("查询库存")
        assert isinstance(result, VoiceValidationResult)

    def test_empty_command_not_allowed(self):
        result = self.whitelist.validate("")
        assert result.allowed is False
        assert result.category == "empty"

    def test_whitespace_only_command_not_allowed(self):
        result = self.whitelist.validate("   ")
        assert result.allowed is False

    def test_safe_query_allowed_no_mobile_confirm(self):
        result = self.whitelist.validate("查看今天的营业额")
        assert result.allowed is True
        assert result.risk_level == RiskLevel.SAFE
        assert result.require_mobile_confirm is False

    def test_high_risk_allowed_but_requires_mobile(self):
        result = self.whitelist.validate("退款给顾客")
        assert result.allowed is True  # 允许发起，但需确认
        assert result.risk_level == RiskLevel.HIGH_RISK
        assert result.require_mobile_confirm is True

    def test_confirm_level_allowed_no_mobile_confirm(self):
        result = self.whitelist.validate("采购食材")
        assert result.allowed is True
        assert result.risk_level == RiskLevel.CONFIRM
        assert result.require_mobile_confirm is False

    def test_reason_field_is_non_empty(self):
        for cmd in ["查询库存", "退款", "采购"]:
            result = self.whitelist.validate(cmd)
            assert result.reason, f"reason 不应为空: {cmd!r}"

    def test_instance_is_stateless_multiple_calls(self):
        """同一实例多次调用结果一致（无状态验证）。"""
        r1 = self.whitelist.validate("退款")
        r2 = self.whitelist.validate("退款")
        assert r1 == r2
