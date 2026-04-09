"""AI日报 + 情感分析 + 企微机器人对话入口 集成测试

测试场景:
  1. 门店日报生成 — 推荐行动生成逻辑
  2. 评价情感分析 — 关键词匹配正负面识别
  3. 情感分析 — 批量评价汇总统计
  4. 企微机器人 — 消息格式化与签名验证
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import (
    DEFAULT_HEADERS,
    MOCK_STORE_ID,
    MOCK_TENANT_ID,
    assert_ok,
)


# ─── 直接从文件路径加载模块（避免 api 包名冲突） ─────────────────────

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _load_module(name: str, file_path: str):
    """从绝对路径加载 Python 模块"""
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# 加载情感分析模块（纯函数，不需要 DB 依赖）
_sentiment_mod = _load_module(
    "sentiment_routes",
    os.path.join(_PROJECT_ROOT, "services", "tx-intel", "src", "api", "sentiment_routes.py"),
)
_analyze_single_review = _sentiment_mod._analyze_single_review

# 加载日报模块（只需要纯函数部分）
_daily_brief_mod = _load_module(
    "daily_brief_routes",
    os.path.join(_PROJECT_ROOT, "services", "tx-analytics", "src", "api", "daily_brief_routes.py"),
)
_generate_recommendations = _daily_brief_mod._generate_recommendations

# 加载企微机器人模块
_gateway_src = os.path.join(_PROJECT_ROOT, "services", "gateway", "src")
if _gateway_src not in sys.path:
    sys.path.insert(0, _gateway_src)
from wecom_bot_routes import _format_nlq_response, _verify_signature


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试1: 评价情感分析 — 关键词匹配正负面识别
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSentimentAnalysis:
    """评价情感分析核心算法测试（纯函数，不需要 HTTP/DB）。"""

    def test_positive_review(self) -> None:
        """正面评价 → sentiment_score > 0, label=positive"""
        result = _analyze_single_review("这家店真的好吃，服务好，环境好，下次还来！", rating=5)
        assert result["sentiment_score"] > 0.3, f"Expected positive score, got {result['sentiment_score']}"
        assert result["sentiment_label"] == "positive"
        assert len(result["positive_keywords"]) >= 2
        assert "好吃" in result["positive_keywords"]
        assert len(result["issues"]) == 0

    def test_negative_review(self) -> None:
        """负面评价 → sentiment_score < 0, label=negative, 有问题分类"""
        result = _analyze_single_review("上菜太慢了，等了半小时，而且菜都不新鲜，太咸了", rating=1)
        assert result["sentiment_score"] < -0.3, f"Expected negative score, got {result['sentiment_score']}"
        assert result["sentiment_label"] == "negative"
        assert len(result["negative_keywords"]) >= 2
        assert len(result["issues"]) > 0
        assert any(issue in result["issues"] for issue in ["等待时间", "出品质量"])

    def test_neutral_review(self) -> None:
        """中性评价 → sentiment_label=neutral"""
        result = _analyze_single_review("一般般吧，没什么特别的", rating=3)
        assert result["sentiment_label"] == "neutral"
        assert -0.3 <= result["sentiment_score"] <= 0.3

    def test_rating_influence(self) -> None:
        """星级评分影响最终得分"""
        result_5star = _analyze_single_review("还行", rating=5)
        result_1star = _analyze_single_review("还行", rating=1)
        assert result_5star["sentiment_score"] > result_1star["sentiment_score"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试2: 日报推荐行动生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDailyBriefRecommendations:
    """日报推荐明日行动逻辑测试（纯函数）。"""

    def test_revenue_drop_recommendation(self) -> None:
        """营收下降时应推荐引流建议"""
        metrics = {
            "today": {"revenue": 10000, "order_count": 80, "avg_ticket": 125, "margin_rate": 0.35},
            "vs_yesterday": {"revenue": -0.15, "order_count": -0.1, "avg_ticket": -0.05, "margin_rate": 0.0},
        }
        recs = _generate_recommendations(metrics, [], {"top5_hot": [], "top5_slow": []})
        assert any("下降" in r for r in recs), f"Expected revenue drop recommendation, got {recs}"

    def test_low_margin_recommendation(self) -> None:
        """低毛利率时应推荐成本优化"""
        metrics = {
            "today": {"revenue": 10000, "order_count": 80, "avg_ticket": 125, "margin_rate": 0.20},
            "vs_yesterday": {"revenue": 0.05, "order_count": 0.03, "avg_ticket": 0.02, "margin_rate": 0.01},
        }
        recs = _generate_recommendations(metrics, [], {"top5_hot": [], "top5_slow": []})
        assert any("毛利率" in r for r in recs), f"Expected margin recommendation, got {recs}"

    def test_stable_performance_recommendation(self) -> None:
        """经营稳定时应给出保持策略建议"""
        metrics = {
            "today": {"revenue": 10000, "order_count": 80, "avg_ticket": 125, "margin_rate": 0.45},
            "vs_yesterday": {"revenue": 0.02, "order_count": 0.01, "avg_ticket": 0.01, "margin_rate": 0.01},
        }
        recs = _generate_recommendations(metrics, [], {"top5_hot": [], "top5_slow": []})
        assert len(recs) > 0, "Should have at least one recommendation"

    def test_refund_anomaly_recommendation(self) -> None:
        """存在退单异常时应推荐复盘"""
        metrics = {
            "today": {"revenue": 10000, "order_count": 80, "avg_ticket": 125, "margin_rate": 0.40},
            "vs_yesterday": {"revenue": 0.02, "order_count": 0.01, "avg_ticket": 0.01, "margin_rate": 0.01},
        }
        anomalies = [{"type": "refund", "description": "今日退单5笔", "count": 5}]
        recs = _generate_recommendations(metrics, anomalies, {"top5_hot": [], "top5_slow": []})
        assert any("退单" in r for r in recs), f"Expected refund recommendation, got {recs}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试3: 企微机器人消息格式化与签名验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestWecomBotFormatting:
    """企微机器人回复格式化测试。"""

    def test_format_success_response(self) -> None:
        """NLQ 成功返回时应格式化为可读文本"""
        nlq_result = {
            "ok": True,
            "data": {
                "answer": "今日营收18600元，环比增长5%",
                "actions": [
                    {"label": "查看详细报表"},
                    {"label": "对比上周数据"},
                ],
                "chart_type": "柱状",
            },
        }
        reply = _format_nlq_response(nlq_result)
        assert "18600" in reply
        assert "查看详细报表" in reply
        assert "柱状" in reply

    def test_format_error_response(self) -> None:
        """NLQ 失败时应返回友好错误提示"""
        nlq_result = {"ok": False, "error": "NLQ 服务响应超时"}
        reply = _format_nlq_response(nlq_result)
        assert "超时" in reply

    def test_verify_signature_correct(self) -> None:
        """正确签名应通过验证"""
        token = "test_token_123"
        timestamp = "1680000000"
        nonce = "abc123"
        parts = sorted([token, timestamp, nonce])
        expected = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()
        assert _verify_signature(token, timestamp, nonce, expected) is True

    def test_verify_signature_wrong(self) -> None:
        """错误签名应拒绝验证"""
        assert _verify_signature("token", "ts", "nonce", "wrong_sig") is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试4: 情感分析批量汇总统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSentimentBatchAnalysis:
    """批量情感分析汇总统计测试。"""

    def test_batch_analysis_aggregation(self) -> None:
        """多条评价的汇总统计应正确计算"""
        reviews = [
            ("好吃，服务好，推荐！", 5),
            ("一般般", 3),
            ("太难吃了，上菜慢，不新鲜", 1),
            ("味道好，分量足，实惠", 4),
        ]

        results = [_analyze_single_review(content, rating) for content, rating in reviews]

        positive_count = sum(1 for r in results if r["sentiment_label"] == "positive")
        negative_count = sum(1 for r in results if r["sentiment_label"] == "negative")
        neutral_count = sum(1 for r in results if r["sentiment_label"] == "neutral")

        assert positive_count >= 2, f"Expected >= 2 positive, got {positive_count}"
        assert negative_count >= 1, f"Expected >= 1 negative, got {negative_count}"
        assert positive_count + negative_count + neutral_count == 4

        # 平均得分应为正（3条正面/中性 vs 1条负面）
        avg_score = sum(r["sentiment_score"] for r in results) / len(results)
        assert avg_score > 0, f"Expected positive avg score, got {avg_score}"

    def test_food_safety_issue_detection(self) -> None:
        """食安关键词应识别为卫生安全问题"""
        result = _analyze_single_review("在菜里发现了头发，太脏了，不卫生", rating=1)
        assert "卫生安全" in result["issues"]
        assert result["sentiment_label"] == "negative"
