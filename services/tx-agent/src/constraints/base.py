"""约束协议 + 数据模型 — Sprint D1 框架基类

定义三个核心结构：
  - SkillContext     —— 每次决策注入的运行时上下文（门店阈值、tenant、db 等）
  - ConstraintCheck  —— 单条约束的校验结果
  - ConstraintResult —— 三条约束的聚合结果，passed=False 即整体阻断
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

ConstraintName = Literal["gross_margin", "food_safety", "customer_experience"]


@dataclass
class SkillContext:
    """Skill 决策的运行时上下文。

    阈值优先级：
        1. SkillContext 注入（门店配置）
        2. 模块默认值（gross_margin.MIN_MARGIN_RATE 等）

    Attributes:
        tenant_id:                  租户 UUID 字符串（决策留痕必填）
        store_id:                   门店 UUID 字符串，可为 None
        skill_name:                 Skill 标识（如 "discount_guard"）— 便于日志归档
        min_margin_rate:            毛利率底线（小数；缺省 0.15）
        expiry_buffer_hours:        食材距过期最小小时数（缺省 24）
        max_serve_minutes:          出餐时长上限（分钟；缺省 30）
        inventory_repository:       食安校验时按 ingredient_ids 反查批次效期的接口；
                                    可注入 mock，决策快照已含 ingredients 时可为 None
        db:                         AsyncSession，可选（用于决策留痕）
    """

    tenant_id: str
    store_id: Optional[str] = None
    skill_name: str = "unknown"
    min_margin_rate: float = 0.15
    expiry_buffer_hours: int = 24
    max_serve_minutes: int = 30
    inventory_repository: Optional[Any] = None
    db: Optional[Any] = None


@dataclass
class ConstraintCheck:
    """单条约束的校验结果"""

    name: ConstraintName
    passed: bool
    reason: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class ConstraintResult:
    """三条约束的聚合结果。

    Attributes:
        passed:               整体是否通过（任一 blocking failure 即 False）
        checks:               每条约束的 ConstraintCheck 明细
        blocking_failures:    失败原因短文案（用于业务可见拒绝原因）
        skipped:              因数据不足跳过校验的约束名（透明记录，不视为通过）
    """

    passed: bool = True
    checks: list[ConstraintCheck] = field(default_factory=list)
    blocking_failures: list[str] = field(default_factory=list)
    skipped: list[ConstraintName] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "blocking_failures": self.blocking_failures,
            "skipped": self.skipped,
        }
