"""AI 客诉识别 Agent 单元测试"""

import pytest

from agents.complaint_detection_agent import (
    ComplaintCategory,
    ComplaintDetectionAgent,
    ComplaintSeverity,
    get_complaint_detection_agent,
)


def _agent() -> ComplaintDetectionAgent:
    return get_complaint_detection_agent()


class TestComplaintDetection:
    """客诉识别测试"""

    def test_food_safety_p0(self):
        result = _agent().analyze("顾客说吃完上吐下泻，怀疑食物中毒")
        assert result.is_complaint is True
        assert result.severity == ComplaintSeverity.P0_CRITICAL
        assert result.category == ComplaintCategory.FOOD_SAFETY

    def test_food_quality_p1(self):
        result = _agent().analyze("这个鸡腿根本没熟，里面还有血")
        assert result.is_complaint is True
        assert result.severity == ComplaintSeverity.P1_HIGH

    def test_service_complaint_p1(self):
        result = _agent().analyze("那个服务员态度特别差，还吼人")
        assert result.is_complaint is True
        assert result.severity == ComplaintSeverity.P1_HIGH
        assert result.category == ComplaintCategory.SERVICE

    def test_waiting_too_long_p2(self):
        result = _agent().analyze("上菜太慢了，等了40分钟")
        assert result.is_complaint is True
        assert result.severity == ComplaintSeverity.P2_MEDIUM

    def test_suggestion_p3(self):
        result = _agent().analyze("建议菜品可以再辣一点")
        assert result.is_complaint is True
        assert result.severity == ComplaintSeverity.P3_LOW

    def test_normal_message_no_complaint(self):
        result = _agent().analyze("今天天气不错，这家店环境挺好")
        assert result.is_complaint is False

    def test_ordering_no_complaint(self):
        result = _agent().analyze("我要一份宫保鸡丁，谢谢")
        assert result.is_complaint is False

    def test_empty_text_no_complaint(self):
        result = _agent().analyze("")
        assert result.is_complaint is False
        result = _agent().analyze("   ")
        assert result.is_complaint is False

    def test_batch_analysis(self):
        messages = [
            {"msgid": "1", "content": "这个菜太好吃了", "sender": "user1"},
            {"msgid": "2", "content": "上菜太慢了，等了一个小时", "sender": "user2"},
            {"msgid": "3", "content": "食物中毒了", "sender": "user3"},
        ]
        results = _agent().analyze_batch(messages)
        assert len(results) == 3
        assert results[0]["complaint"]["is_complaint"] is False
        assert results[1]["complaint"]["is_complaint"] is True
        assert results[2]["complaint"]["is_complaint"] is True
        assert results[2]["complaint"]["severity"] == "P0"

    def test_singleton(self):
        a1 = get_complaint_detection_agent()
        a2 = get_complaint_detection_agent()
        assert a1 is a2
