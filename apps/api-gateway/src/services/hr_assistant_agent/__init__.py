"""
HR Assistant Agent (Hermes Agent-N) — 数字人 AI 助手
对标 i人事「数字人」+ 乐才云 AI 助手，员工可用自然语言查询 HR 数据。

对外暴露：
    - HRAssistantAgent: 主 Agent 类
    - TOOL_REGISTRY: 工具注册表
    - INTENT_RULES: 意图规则
"""

from .agent import HRAssistantAgent
from .tools import TOOL_REGISTRY, tool_schemas_for_llm
from .intent_classifier import INTENT_RULES, classify_intent

__all__ = [
    "HRAssistantAgent",
    "TOOL_REGISTRY",
    "tool_schemas_for_llm",
    "INTENT_RULES",
    "classify_intent",
]
