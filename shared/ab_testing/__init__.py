"""shared/ab_testing — A/B 实验平台工具层

Sprint G 交付：实验分配 + 统计显著性 + 熔断器 pure-Python 工具。
与 tx-brain/tx-agent/tx-member 解耦，可被任何 service 直接 import。

典型用法：

    from shared.ab_testing import (
        ArmDefinition,
        ArmStats,
        assign_entity,
        frequentist_significance,
        evaluate_circuit_breaker,
    )

    arms = [
        ArmDefinition(arm_key="control", traffic_weight=50, is_control=True),
        ArmDefinition(arm_key="treatment", traffic_weight=50),
    ]

    # 分配
    arm_key = assign_entity(
        entity_id="customer_uuid",
        experiment_key="menu_v2_vs_v1",
        arms=arms,
        traffic_percentage=100.0,
    )

    # 显著性
    control_stats = ArmStats(exposure=1000, conversion=120, is_control=True)
    treatment_stats = ArmStats(exposure=1000, conversion=150)
    result = frequentist_significance(control_stats, treatment_stats, alpha=0.05)
    # result.significant == True / False

    # 熔断
    decision = evaluate_circuit_breaker(
        control_stats, treatment_stats,
        threshold_pct=0.20, min_samples=200,
    )
    # decision.should_trip == True if treatment_degrades >20%

不依赖 DB 或 ORM。service 层负责把 DB 数据 map 成 ArmStats。
"""

from .assignment import (
    ArmDefinition,
    AssignmentDecision,
    NotEnrolled,
    assign_entity,
    compute_assignment_hash,
)
from .circuit_breaker import (
    CircuitBreakerDecision,
    evaluate_circuit_breaker,
)
from .statistics import (
    ArmStats,
    BayesianResult,
    SignificanceResult,
    bayesian_posterior,
    frequentist_significance,
    required_sample_size,
)

__all__ = [
    "ArmDefinition",
    "ArmStats",
    "AssignmentDecision",
    "BayesianResult",
    "CircuitBreakerDecision",
    "NotEnrolled",
    "SignificanceResult",
    "assign_entity",
    "bayesian_posterior",
    "compute_assignment_hash",
    "evaluate_circuit_breaker",
    "frequentist_significance",
    "required_sample_size",
]
