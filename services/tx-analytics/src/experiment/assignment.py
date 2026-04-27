"""G1 — 纯函数分桶（pure-function bucket assignment）

唯一职责：根据 (experiment_key, subject_id, seed, variants) 决定 subject 的桶。

绝对约束：
  - 纯函数：相同输入 100% 相同输出
  - 不调 DB / 不读时间 / 不读环境变量 / 不调 random
  - 哈希算法：SHA-256（稳定、跨平台、跨进程一致）

工作原理：
  1. 拼接 (experiment_key + "|" + subject_id + "|" + seed) 字节串
  2. SHA-256 → 取最后 8 字节 → big-endian uint64 → mod 10000 得到 [0, 9999] 桶位
  3. 按 variants 顺序累加 weight，第一个 >= bucket_position 的 variant 即返回

权重模型：
  - weight 为整数（百分比 × 100，即 0-10000），sum 应 == 10000
  - 若 variants 为空 → 返回 CONTROL_BUCKET（容错：后端无配置时不应崩溃）
  - 若 sum != 10000 → 按比例归一（不报错，只警告，避免线上挂掉）
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

CONTROL_BUCKET = "control"
"""未配置变体或熔断后强制使用的兜底桶名。"""

_BUCKET_RESOLUTION = 10000
"""分桶分辨率：weight 单位为万分之几（即 weight=5000 表示 50%）。"""


class Variant(BaseModel):
    """单个变体。

    weight 是 0-10000 的整数，表示该变体在 10000 桶上占的份额。
    name 是字符串桶名，例如 "control" / "variant_a" / "variant_b"。
    """

    name: str = Field(..., min_length=1, max_length=64)
    weight: int = Field(..., ge=0, le=10000)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("variant name 不可为空")
        return v


@dataclass(frozen=True)
class AssignmentResult:
    """分桶结果（不可变）。

    bucket: 选中的变体名
    bucket_position: 0-9999 的整数（仅供调试）
    fallback_reason: 若使用兜底（如 variants 为空、熔断），写明原因；否则 None
    """

    bucket: str
    bucket_position: int
    fallback_reason: str | None = None


def _hash_bucket_position(experiment_key: str, subject_id: str, seed: str) -> int:
    """SHA-256 → 取低 64 位 → mod 10000，纯函数。"""
    raw = f"{experiment_key}|{subject_id}|{seed}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    # 取最后 8 字节 big-endian
    low64 = int.from_bytes(digest[-8:], byteorder="big", signed=False)
    return low64 % _BUCKET_RESOLUTION


def assign_bucket(
    experiment_key: str,
    subject_id: str,
    variants: list[Variant],
    seed: str,
) -> AssignmentResult:
    """分桶主函数（纯函数）。

    Args:
        experiment_key: 实验键，例 "checkout.v2"
        subject_id: 对象 ID（user_id / device_serial / store_id / table_id）
        variants: 变体列表（顺序决定优先权）
        seed: 哈希种子（保证可重放：同 seed 同输入永远出同桶）

    Returns:
        AssignmentResult，含 bucket / bucket_position / fallback_reason

    设计：
      - 永不抛异常（线上路径不可崩）。所有异常路径都 fallback 到 control。
      - variants 为空 → control + reason="no_variants"
      - sum(weight) == 0 → control + reason="zero_weight"
      - sum(weight) != 10000 → 按比例归一，记 reason="weight_normalized"
    """
    if not isinstance(experiment_key, str) or not experiment_key:
        return AssignmentResult(
            bucket=CONTROL_BUCKET,
            bucket_position=0,
            fallback_reason="invalid_experiment_key",
        )
    if not isinstance(subject_id, str) or not subject_id:
        return AssignmentResult(
            bucket=CONTROL_BUCKET,
            bucket_position=0,
            fallback_reason="invalid_subject_id",
        )
    if seed is None:
        seed = ""

    bucket_position = _hash_bucket_position(experiment_key, subject_id, seed)

    if not variants:
        return AssignmentResult(
            bucket=CONTROL_BUCKET,
            bucket_position=bucket_position,
            fallback_reason="no_variants",
        )

    total_weight = sum(v.weight for v in variants)
    if total_weight == 0:
        return AssignmentResult(
            bucket=CONTROL_BUCKET,
            bucket_position=bucket_position,
            fallback_reason="zero_weight",
        )

    fallback_reason: str | None = None
    if total_weight != _BUCKET_RESOLUTION:
        fallback_reason = "weight_normalized"

    # 按归一化比例累加，找出 bucket_position 落在哪个区间
    cursor = 0
    last_variant_name = variants[-1].name
    for variant in variants:
        # 区间宽度按比例缩放到 _BUCKET_RESOLUTION
        scaled_width = (variant.weight * _BUCKET_RESOLUTION) // total_weight
        cursor += scaled_width
        if bucket_position < cursor:
            return AssignmentResult(
                bucket=variant.name,
                bucket_position=bucket_position,
                fallback_reason=fallback_reason,
            )

    # 浮点截断兜底：如果累加最后没命中（极端边界），归到最后一个变体
    return AssignmentResult(
        bucket=last_variant_name,
        bucket_position=bucket_position,
        fallback_reason=fallback_reason or "boundary_fallback",
    )
