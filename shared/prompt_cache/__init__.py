"""屯象OS 统一 Prompt Cache 工具层

在 Sprint D4a/D4b/D4c 中发现：三份 CachedPromptBuilder 的 cache_control 逻辑完全
一致，只有 STABLE_SYSTEM 的 JSON schema 和 DOMAIN_BENCHMARKS 的内容不同。本模块
把共用骨架抽出来，三个 service 层只需继承 BaseCachedPromptBuilder 并覆盖两个
classmethod 即可。

典型用法：

    from shared.prompt_cache import BaseCachedPromptBuilder

    class CostRootCauseBuilder(BaseCachedPromptBuilder):
        MODEL_ID = "claude-sonnet-4-7"
        MAX_TOKENS = 2048

        @classmethod
        def stable_system(cls) -> str:
            return "你是屯象OS 成本根因 Agent..."

        @classmethod
        def domain_benchmarks(cls) -> str:
            return "【餐饮成本基准】..."

        @classmethod
        def serialize_user_context(cls, bundle: CostSignalBundle) -> str:
            return f"请分析以下成本波动：\n{bundle.to_dict()}"

    messages = CostRootCauseBuilder.build_messages(bundle)
    # 交给 AnthropicCacheInvoker 或自定义 invoker

附带工具：
  · parse_json_response — 容错解析 Sonnet 输出（剥离 code fence）
  · AnthropicCacheInvoker — 封装真实 Anthropic SDK 调用 + usage 回传
  · compute_cache_hit_rate / aggregate_usage — 命中率统计助手
"""

from .base_builder import BaseCachedPromptBuilder
from .invoker import AnthropicCacheInvoker, CacheInvoker, UsageStats
from .metrics import aggregate_usage, compute_cache_hit_rate
from .response_parser import parse_json_response

__all__ = [
    "AnthropicCacheInvoker",
    "BaseCachedPromptBuilder",
    "CacheInvoker",
    "UsageStats",
    "aggregate_usage",
    "compute_cache_hit_rate",
    "parse_json_response",
]
