"""ConstraintChecker 框架 — Sprint D1 51-Skill 覆盖

本包是对 `agents/constraints.py` 既有 ConstraintChecker 的二次封装，提供：

  1. 每条约束独立模块（gross_margin / food_safety / customer_experience），
     便于按 Skill 维度灵活组合调用、阈值注入、文档化
  2. `runner.run_checks()` 统一异步入口（接 Skill 决策快照 + SkillContext 阈值）
  3. `decorator.with_constraint_check()` 装饰器（在 commit 2 接入）：
     硬阻断决策 + 写入决策留痕 + 抛 ConstraintBlockedException

设计原则
-------
- **不重新实现校验逻辑**：复用 agents.constraints.ConstraintChecker，避免双源真相
- **不修改 AgentDecisionLog schema**（决策点 #1 等待创始人签字，本 Sprint 严格冻结）
- **向后兼容**：未装饰的 Skill 仍走 base.py::run() 软告警路径
"""

from .base import ConstraintCheck, ConstraintName, ConstraintResult, SkillContext
from .runner import run_checks

__all__ = [
    "ConstraintCheck",
    "ConstraintName",
    "ConstraintResult",
    "SkillContext",
    "run_checks",
]
