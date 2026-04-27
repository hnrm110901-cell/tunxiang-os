"""Sprint G — 实验框架（A/B test infrastructure）

四件套：
  G1 assignment.py    纯函数分桶（hash → variant）
  G2 orchestrator.py  ExperimentOrchestrator 判桶 + idempotent expose + 熔断守卫
  G3 metrics.py       Welch's t-test
  G3 dashboard.py     ExperimentDashboard 多指标显著性汇总
  G4 circuit_breaker.py  CircuitBreakerEvaluator（默认跌幅 -20% 触发）

设计原则（CLAUDE.md §17 Tier3）：
  - assignment 无副作用、无 I/O，方便单测
  - orchestrator 唯一持久化点，DB 唯一约束保证幂等
  - 熔断阈值由 experiment_definitions.circuit_breaker_threshold_pct 逐实验覆盖
"""

from .assignment import (
    CONTROL_BUCKET,
    AssignmentResult,
    Variant,
    assign_bucket,
)

__all__ = [
    "Variant",
    "AssignmentResult",
    "assign_bucket",
    "CONTROL_BUCKET",
]
