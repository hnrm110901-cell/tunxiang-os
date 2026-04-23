"""Prompt Cache 命中率统计助手

D4 系列三张表都有 4 个 token 字段（cache_read / cache_creation / input / output）。
本模块提供聚合工具：

  · compute_cache_hit_rate — 单次统计
  · aggregate_usage — 多次 usage 求和
  · CacheHitTargets — 命中率门槛常量（供 API summary 接口使用）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# ─────────────────────────────────────────────────────────────
# 命中率门槛常量
# ─────────────────────────────────────────────────────────────


class CacheHitTargets:
    """D4 系列 Prompt Cache 命中率门槛。

    设计原则：
      · 新上线首月：≥ 40%（首次分析创建 cache，后续读取）
      · 3 个月稳态：≥ 75%
      · 跨季度：≥ 85%（多租户共享 DOMAIN_BENCHMARKS cache）

    API /summary 端点应返回 meets_target 字段，供 Grafana 看板告警。
    """

    LAUNCH = 0.40  # 上线首月
    STEADY = 0.75  # 稳态门槛（CLAUDE.md 硬约束）
    EXCELLENT = 0.85  # 优秀水平


# ─────────────────────────────────────────────────────────────
# 聚合工具
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AggregatedUsage:
    """一组 usage 的累加结果"""

    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0

    @property
    def total_input(self) -> int:
        return self.cache_read_tokens + self.cache_creation_tokens + self.input_tokens

    @property
    def cache_hit_rate(self) -> float:
        return compute_cache_hit_rate(
            cache_read_tokens=self.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens,
            input_tokens=self.input_tokens,
        )

    @property
    def meets_steady_target(self) -> bool:
        return self.cache_hit_rate >= CacheHitTargets.STEADY

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "call_count": self.call_count,
            "total_input_tokens": self.total_input,
            "cache_hit_rate": self.cache_hit_rate,
            "meets_steady_target": self.meets_steady_target,
            "steady_target": CacheHitTargets.STEADY,
        }


def compute_cache_hit_rate(
    *,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    input_tokens: int,
) -> float:
    """计算单次（或聚合后）的 cache 命中率。

    公式：cache_read / (cache_read + cache_creation + input_tokens)

    注：分母不含 output_tokens（那是响应 token，与 cache 无关）。
    """
    total_input = cache_read_tokens + cache_creation_tokens + input_tokens
    if total_input <= 0:
        return 0.0
    return round(cache_read_tokens / total_input, 4)


def aggregate_usage(items: Iterable[Mapping[str, Any]]) -> AggregatedUsage:
    """累加一组 usage 字典。

    每个 item 需包含下列 key（可缺省，缺省按 0 处理）：
      · cache_read_tokens
      · cache_creation_tokens
      · input_tokens
      · output_tokens

    典型用法：
        rows = await db.fetch_all("SELECT cache_read_tokens, ... FROM d4_table")
        agg = aggregate_usage([dict(r) for r in rows])
        return {"cache_hit_rate": agg.cache_hit_rate}
    """
    cache_read = 0
    cache_create = 0
    input_ = 0
    output = 0
    count = 0
    for item in items:
        cache_read += int(item.get("cache_read_tokens", 0) or 0)
        cache_create += int(item.get("cache_creation_tokens", 0) or 0)
        input_ += int(item.get("input_tokens", 0) or 0)
        output += int(item.get("output_tokens", 0) or 0)
        count += 1
    return AggregatedUsage(
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_create,
        input_tokens=input_,
        output_tokens=output,
        call_count=count,
    )
