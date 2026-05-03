"""AI 客诉识别 Agent

分析企微会话存档中的聊天消息，识别客诉/负面情绪，并进行分级和分类。

工作流：
  1. 接收原始消息文本
  2. 通过关键词 + Claude API 双重判定是否存在客诉
  3. 对客诉进行严重级别分级（P0-P3）
  4. 分类客诉类型（菜品/服务/价格/环境/配送/其他）
  5. 输出结构化结果用于后续处理

当前 Phase 2 实现使用关键词规则引擎（轻量快速），
Claude API 深度分析在 Phase 3 接入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ComplaintSeverity(str, Enum):
    """客诉严重级别"""
    P0_CRITICAL = "P0"   # 食品安全/人身伤害，需立即响应
    P1_HIGH = "P1"       # 严重菜品问题/态度恶劣，需30分钟内响应
    P2_MEDIUM = "P2"     # 一般服务质量问题，需2小时内响应
    P3_LOW = "P3"        # 轻微不满/建议，需24小时内响应
    NONE = "NONE"        # 非客诉


class ComplaintCategory(str, Enum):
    """客诉分类"""
    FOOD_QUALITY = "food_quality"        # 菜品质量
    SERVICE = "service"                   # 服务态度
    PRICE = "price"                       # 价格异议
    ENVIRONMENT = "environment"           # 环境问题
    DELIVERY = "delivery"                 # 配送/外卖
    FOOD_SAFETY = "food_safety"           # 食品安全（P0 级别）
    OTHER = "other"                       # 其他


# ─── 客诉关键词规则库 ───

_COMPLAINT_RULES: list[dict[str, Any]] = [
    # 食品安全（P0）
    {"keywords": ["食物中毒", "拉肚子", "上吐下泻", "异物", "虫子", "头发",
                  "变质", "馊了", "酸了", "发霉", "不新鲜", "臭了"],
     "severity": ComplaintSeverity.P0_CRITICAL,
     "category": ComplaintCategory.FOOD_SAFETY},
    # 严重菜品问题（P1）
    {"keywords": ["没熟", "生的", "不熟", "有血", "咸死了", "没法吃",
                  "太难吃", "恶心", "想吐", "全是油"],
     "severity": ComplaintSeverity.P1_HIGH,
     "category": ComplaintCategory.FOOD_QUALITY},
    # 服务差（P1）
    {"keywords": ["态度差", "骂人", "吼", "服务员态度", "不理人",
                  "叫半天", "没人管", "凶", "甩脸色"],
     "severity": ComplaintSeverity.P1_HIGH,
     "category": ComplaintCategory.SERVICE},
    # 一般投诉（P2）
    {"keywords": ["上菜慢", "太慢", "等太久", "催单", "上错了", "漏单",
                  "分量少", "量太少", "价格贵", "太贵了", "不值",
                  "不好吃", "一般", "失望", "差评"],
     "severity": ComplaintSeverity.P2_MEDIUM,
     "category": ComplaintCategory.FOOD_QUALITY},
    # 轻微不满（P3）
    {"keywords": ["建议", "能不能", "希望", "改进", "不太满意",
                  "有点慢", "一般般", "随便吧"],
     "severity": ComplaintSeverity.P3_LOW,
     "category": ComplaintCategory.OTHER},
]


# ─── 数据模型 ───


@dataclass
class ComplaintResult:
    """客诉检测结果"""
    is_complaint: bool
    severity: ComplaintSeverity = ComplaintSeverity.NONE
    category: ComplaintCategory = ComplaintCategory.OTHER
    matched_keywords: list[str] = field(default_factory=list)
    confidence: float = 0.0
    summary: str = ""


# ─── Agent ───


class ComplaintDetectionAgent:
    """AI 客诉识别 Agent

    对聊天消息进行客诉检测，输出结构化结果。
    Phase 2 实现关键词规则引擎；Phase 3 接入 Claude API 深度分析。
    """

    def __init__(self) -> None:
        self._rules = _COMPLAINT_RULES

    def analyze(self, text: str) -> ComplaintResult:
        """分析单条消息是否包含客诉。

        Args:
            text: 聊天消息文本

        Returns:
            ComplaintResult: 客诉检测结果
        """
        if not text or not text.strip():
            return ComplaintResult(is_complaint=False)

        matched_keywords: list[str] = []
        highest_severity = ComplaintSeverity.NONE
        best_category = ComplaintCategory.OTHER

        for rule in self._rules:
            for kw in rule["keywords"]:
                if kw in text:
                    matched_keywords.append(kw)
                    rule_severity = rule["severity"]
                    # 取最高严重级别
                    if _severity_rank(rule_severity) < _severity_rank(highest_severity):
                        highest_severity = rule_severity
                        best_category = rule["category"]

        if not matched_keywords:
            return ComplaintResult(is_complaint=False)

        return ComplaintResult(
            is_complaint=True,
            severity=highest_severity,
            category=best_category,
            matched_keywords=list(set(matched_keywords)),
            confidence=min(0.5 + 0.1 * len(set(matched_keywords)), 0.95),
            summary=_generate_summary(highest_severity, best_category, matched_keywords),
        )

    def analyze_batch(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量分析消息列表，返回包含客诉标记的结果。

        Args:
            messages: 消息列表，每项需包含 "content" 和 "msgid" 字段

        Returns:
            附带客诉分析结果的消息列表
        """
        results: list[dict[str, Any]] = []
        for msg in messages:
            text = msg.get("content", "")
            analysis = self.analyze(text)
            results.append({
                "msgid": msg.get("msgid", ""),
                "sender": msg.get("sender", ""),
                "content": text,
                "timestamp": msg.get("timestamp", ""),
                "complaint": {
                    "is_complaint": analysis.is_complaint,
                    "severity": analysis.severity.value,
                    "category": analysis.category.value,
                    "matched_keywords": analysis.matched_keywords,
                    "confidence": analysis.confidence,
                    "summary": analysis.summary,
                },
            })
        return results


# ─── 辅助函数 ───


def _severity_rank(severity: ComplaintSeverity) -> int:
    """严重级别排序（数字越小越严重）。"""
    rank_map = {
        ComplaintSeverity.P0_CRITICAL: 0,
        ComplaintSeverity.P1_HIGH: 1,
        ComplaintSeverity.P2_MEDIUM: 2,
        ComplaintSeverity.P3_LOW: 3,
        ComplaintSeverity.NONE: 99,
    }
    return rank_map.get(severity, 99)


def _generate_summary(
    severity: ComplaintSeverity,
    category: ComplaintCategory,
    keywords: list[str],
) -> str:
    """根据检测结果生成摘要。"""
    severity_label = {
        ComplaintSeverity.P0_CRITICAL: "【紧急】",
        ComplaintSeverity.P1_HIGH: "【重要】",
        ComplaintSeverity.P2_MEDIUM: "【一般】",
        ComplaintSeverity.P3_LOW: "【轻微】",
    }.get(severity, "")

    category_label = {
        ComplaintCategory.FOOD_SAFETY: "食品安全",
        ComplaintCategory.FOOD_QUALITY: "菜品质量",
        ComplaintCategory.SERVICE: "服务",
        ComplaintCategory.PRICE: "价格",
        ComplaintCategory.ENVIRONMENT: "环境",
        ComplaintCategory.DELIVERY: "配送",
        ComplaintCategory.OTHER: "其他",
    }.get(category, "")

    kw_str = "、".join(keywords[:3])
    return f"{severity_label}{category_label}：检测到关键词「{kw_str}」"


# ─── 全局单例 ───

_instance: ComplaintDetectionAgent | None = None


def get_complaint_detection_agent() -> ComplaintDetectionAgent:
    global _instance
    if _instance is None:
        _instance = ComplaintDetectionAgent()
    return _instance
