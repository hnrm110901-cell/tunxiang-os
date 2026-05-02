"""NLQ V2 — 自然语言查询引擎（BI-1.3 升级）

模块组成：
- intent_templates_v2: 200+ 意图模板（分域模块化）
- context_manager: 多轮对话上下文管理（Redis / 内存）
- olap_bridge: NLQ 意图结果 → OLAP 查询桥接
- chart_router: 图表类型智能路由

升级要点：
1. 从 50 模板扩展到 200+ 模板（10 大业务域）
2. 支持多轮对话上下文（代词消解、追问收敛）
3. 桥接 OLAP 引擎（dimensions × measures 多维查询）
4. 自动选择图表类型（基于数据特征）
"""

from __future__ import annotations

from .intent_templates_v2 import INTENT_TEMPLATES_V2, match_intent_v2, TEMPLATE_COUNT  # noqa: F401
from .context_manager import ContextManager, DialogueContext  # noqa: F401
from .olap_bridge import nlq_to_olap_query, suggest_drill  # noqa: F401
from .chart_router import select_chart_type  # noqa: F401

__all__ = [
    "INTENT_TEMPLATES_V2",
    "TEMPLATE_COUNT",
    "match_intent_v2",
    "ContextManager",
    "DialogueContext",
    "nlq_to_olap_query",
    "suggest_drill",
    "select_chart_type",
]
