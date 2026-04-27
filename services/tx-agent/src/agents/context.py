"""ConstraintContext —— Skill Agent 三条硬约束的结构化输入（Sprint D1 / PR G）

问题根因
-------
CLAUDE.md §九约定"每个 Agent 决策必须通过三条硬约束校验，无例外"，但旧实现的
`ConstraintChecker.check_all(result.data)` 在 `data` 缺字段时返回 None（见
`constraints.py::check_margin/check_food_safety/check_experience` 第一段 if），
被视作"无数据跳过"。51 个 Skill 里只有 9 个 P0 Skill 真实填入 price_fen/cost_fen/
ingredients/estimated_serve_minutes，其余 42 个约束形同虚设。

设计
----
引入 `ConstraintContext` 作为约束输入的显式类型，解决三个问题：

  1. **类型安全** —— 字段名在类上统一声明，不靠 data dict 字符串键约定
  2. **作用域声明** —— `constraint_scope` 说明本次决策需要哪几类约束；
     Skill 类级 `constraint_scope = set()` 可显式豁免（配合 `constraint_waived_reason`）
  3. **向后兼容** —— AgentResult.context 为 None 时，base.py::run 会 fallback 到
     从 result.data 组装 context，51 Skill 迁移可按批分阶段完成

注入方式
-------
Skill.execute() 的 AgentResult 可直接填 `context`：

```python
return AgentResult(
    success=True,
    action=action,
    data={...},
    context=ConstraintContext(
        price_fen=8800,
        cost_fen=3500,
        constraint_scope={"margin"},   # 只校验毛利
    ),
)
```

或者保留原 data 行为，由 base.py 自动 fallback（迁移期兼容）。

豁免
----
只读 Skill（如 intel_reporter、review_summary）或纯 ETL Skill 在类上声明：

```python
class IntelReporterAgent(SkillAgent):
    constraint_scope = set()
    constraint_waived_reason = "纯数据汇总，不触发业务决策；毛利/食安/体验均不适用"
```

CI 门禁强制 `waived_reason` 长度 ≥30 字符，禁用 ["N/A","不适用","跳过"]
类空洞说辞（Sprint D1 后续批次的 CI 规则，本 PR 仅落基础结构）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

ConstraintScopeName = Literal["margin", "safety", "experience"]


@dataclass
class IngredientSnapshot:
    """单个食材的食安校验快照。

    Attributes:
        name:              食材名（便于 violation 回显）
        remaining_hours:   距过期的小时数；None 表示非保质期敏感品
        batch_id:          批次 ID（可选，便于追溯）
    """

    name: str
    remaining_hours: Optional[float]
    batch_id: Optional[str] = None


@dataclass
class ConstraintContext:
    """三条硬约束的结构化输入。

    Attributes:
        price_fen:                 决策单笔售价（分），毛利校验必填
        cost_fen:                  决策单笔成本（分），毛利校验必填
        ingredients:               本次决策涉及的食材清单，食安校验必填
        estimated_serve_minutes:   预估出餐时长（分钟），体验校验必填
        constraint_scope:          本次需校验的约束子集。空集等价于豁免（需填 waived_reason）
        waived_reason:             豁免理由（≥30 字符，CI 会校验）
    """

    price_fen: Optional[int] = None
    cost_fen: Optional[int] = None
    ingredients: Optional[list[IngredientSnapshot]] = None
    estimated_serve_minutes: Optional[float] = None
    constraint_scope: set[ConstraintScopeName] = field(default_factory=lambda: {"margin", "safety", "experience"})
    waived_reason: Optional[str] = None

    @classmethod
    def from_data(cls, data: dict) -> "ConstraintContext":
        """从遗留 result.data 字典组装 ConstraintContext（迁移期兼容路径）。

        字段映射：
          price_fen / final_amount_fen → price_fen
          cost_fen / food_cost_fen     → cost_fen
          ingredients (list of dict)   → list[IngredientSnapshot]
          estimated_serve_minutes      → estimated_serve_minutes

        未识别的 data 形态保持 None，与旧 checker 的 "返 None 即跳过" 语义一致。
        """
        raw_ings = data.get("ingredients")
        ingredients: Optional[list[IngredientSnapshot]] = None
        if isinstance(raw_ings, list) and raw_ings:
            converted: list[IngredientSnapshot] = []
            for item in raw_ings:
                if not isinstance(item, dict):
                    continue
                converted.append(
                    IngredientSnapshot(
                        name=str(item.get("name", "unknown")),
                        remaining_hours=item.get("remaining_hours"),
                        batch_id=item.get("batch_id"),
                    )
                )
            ingredients = converted or None

        # 用 `if key in` 而非 `or`，避免 price_fen=0 被 truthy 测试误判为 None
        # （price=0 是 "零售价错误设为 0" 的真实违规场景，checker 要返 {passed:False}）
        price_fen = data.get("price_fen")
        if price_fen is None:
            price_fen = data.get("final_amount_fen")
        cost_fen = data.get("cost_fen")
        if cost_fen is None:
            cost_fen = data.get("food_cost_fen")
        return cls(
            price_fen=price_fen,
            cost_fen=cost_fen,
            ingredients=ingredients,
            estimated_serve_minutes=data.get("estimated_serve_minutes"),
        )


__all__ = [
    "ConstraintContext",
    "ConstraintScopeName",
    "IngredientSnapshot",
]
