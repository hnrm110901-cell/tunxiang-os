"""A/B 实验 deterministic hash-based 流量分配

原则：
  1. 同一 (entity_id, experiment_key) 必须分到同一个 arm（稳定性）
  2. 不同 entity 按 arm 权重均匀分布
  3. traffic_percentage < 100 时部分 entity 不进入实验（NotEnrolled）
  4. 分配决策不查 DB（pure function）；DB 只缓存首次决策用于审计

算法：
    h = int(sha256(entity_id + ":" + experiment_key).hexdigest()[:8], 16)
    bucket = h % 10000  # 0-9999

    if bucket >= traffic_percentage * 100:
        return NotEnrolled
    else:
        cumulative = 0
        for arm in sorted_arms:
            cumulative += arm.traffic_weight
            if bucket % (total_weight) < cumulative:
                return arm
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional


class NotEnrolled:
    """Sentinel: entity 未进入实验（因 traffic_percentage < 100 被随机排除）"""

    def __repr__(self) -> str:
        return "NotEnrolled"


NOT_ENROLLED = NotEnrolled()


# ─────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArmDefinition:
    """Arm 配置（对应 ab_experiment_arms 行）"""

    arm_key: str
    traffic_weight: int  # 0-100，相对比例
    is_control: bool = False
    parameters: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.arm_key:
            raise ValueError("arm_key 不能为空")
        if not (0 <= self.traffic_weight <= 100):
            raise ValueError(
                f"traffic_weight 必须 ∈ [0, 100]，收到 {self.traffic_weight}"
            )


@dataclass(frozen=True)
class AssignmentDecision:
    """assign_entity 返回的决策结果"""

    arm_key: str
    arm: ArmDefinition
    bucket: int  # 0-9999，用于审计
    hash_value: int  # 完整 hash，用于审计


# ─────────────────────────────────────────────────────────────
# 分配算法
# ─────────────────────────────────────────────────────────────


def compute_assignment_hash(entity_id: str, experiment_key: str) -> int:
    """计算 deterministic hash；返回 32-bit 无符号整数"""
    if not entity_id or not experiment_key:
        raise ValueError("entity_id 和 experiment_key 不能为空")
    payload = f"{entity_id}:{experiment_key}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:8]
    return int(digest, 16)


def assign_entity(
    *,
    entity_id: str,
    experiment_key: str,
    arms: list[ArmDefinition],
    traffic_percentage: float = 100.0,
) -> AssignmentDecision | NotEnrolled:
    """稳定分配 entity 到某 arm

    Args:
      entity_id: 实体 ID（customer_id / order_id / session_id / device_id）
      experiment_key: 实验业务键
      arms: arm 列表（必须非空，traffic_weight 总和 > 0）
      traffic_percentage: 进入实验的总流量占比（0-100）

    Returns:
      AssignmentDecision（若进入实验）
      NOT_ENROLLED 单例（若未进入实验）
    """
    if not arms:
        raise ValueError("arms 不能为空")
    if not (0 <= traffic_percentage <= 100):
        raise ValueError(
            f"traffic_percentage 必须 ∈ [0, 100]，收到 {traffic_percentage}"
        )

    total_weight = sum(a.traffic_weight for a in arms)
    if total_weight <= 0:
        raise ValueError("arms 的 traffic_weight 总和必须 > 0")

    hash_value = compute_assignment_hash(entity_id, experiment_key)
    # bucket ∈ [0, 9999]（用于 traffic_percentage 判定，精度 0.01%）
    bucket = hash_value % 10000

    # 先判 traffic_percentage
    enrolled_threshold = int(traffic_percentage * 100)  # 0-10000
    if bucket >= enrolled_threshold:
        return NOT_ENROLLED

    # 按权重分配：用 hash_value // 10000 的剩余位 mod total_weight，避免 bucket 和分配 re-use 同一 hash bits
    arm_bucket = (hash_value >> 16) % total_weight
    cumulative = 0
    # 按 arm_key 字典序排序保证稳定性（新增 arm 不影响老分配）
    sorted_arms = sorted(arms, key=lambda a: a.arm_key)
    for arm in sorted_arms:
        cumulative += arm.traffic_weight
        if arm_bucket < cumulative:
            return AssignmentDecision(
                arm_key=arm.arm_key,
                arm=arm,
                bucket=bucket,
                hash_value=hash_value,
            )

    # 理论不可达（cumulative 必达 total_weight）
    fallback = sorted_arms[-1]
    return AssignmentDecision(
        arm_key=fallback.arm_key,
        arm=fallback,
        bucket=bucket,
        hash_value=hash_value,
    )


def is_enrolled(
    result: AssignmentDecision | NotEnrolled,
) -> bool:
    """类型 narrowing helper"""
    return isinstance(result, AssignmentDecision)


def extract_arm_key(
    result: AssignmentDecision | NotEnrolled,
    default: Optional[str] = None,
) -> Optional[str]:
    """若未入组返回 default（或 None）"""
    if isinstance(result, AssignmentDecision):
        return result.arm_key
    return default
