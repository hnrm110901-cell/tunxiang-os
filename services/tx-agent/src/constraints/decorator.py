"""@with_constraint_check 装饰器 — Sprint D1 P0 Skill 硬阻断

设计目标
-------
1. **硬阻断**：约束失败时抛 ConstraintBlockedException，调用方（Master Agent /
   外部业务路由）转化为业务可见拒绝原因。区别于 base.py::run() 的软告警。
2. **决策留痕**：约束失败时写一条 input_context.blocked_at_constraint 标识的
   AgentDecisionLog（不修改 schema：blocked 信息塞 input_context 字段）。
3. **不破坏 happy path**：约束通过或 skipped → 原 execute() 返回值原样返回。
4. **不重复校验**：base.py::run() 之后的 ConstraintChecker 与本装饰器并存时，
   装饰器先于 base.py 拦截违反 case，base.py 仅在装饰器未触发时记录 scope 标签。

数据流
-----
```
SkillAgent.run()                                            # base.py — 不变
  └─ self.execute(action, params)                           # 被本装饰器包装
       ├─ original_execute()                                # Skill 原逻辑
       │    返回 AgentResult(data={price_fen, cost_fen, ...})
       ├─ run_checks(result, ctx)                           # 三条约束
       └─ if not constraints.passed:
              write_blocked_decision_log()                  # 入库 (best-effort)
              raise ConstraintBlockedException(...)         # 中断流程
  └─ ConstraintChecker.check_all(...)                       # base.py — 仅给未触发装饰器的 result 兜底打 scope 标签
```

不修改 AgentDecisionLog schema
-----------------------------
D2 决策点 #1（agent_decision_logs 加 4 列）创始人签字仍 pending。
本装饰器在留痕时仅向既有 input_context (JSON) 字段塞 blocked_at_constraint=True，
output_action 中 success=False，constraints_check 写入 ConstraintResult.to_dict()。
**不新增列、不改 nullability、不改索引。**
"""

from __future__ import annotations

import functools
from typing import Any, Awaitable, Callable, Optional

import structlog

from .base import ConstraintResult, SkillContext
from .runner import run_checks

logger = structlog.get_logger()


class ConstraintBlockedException(Exception):
    """约束失败导致 Skill 决策被硬阻断的异常。

    Attributes:
        skill_name:  被阻断的 Skill 标识
        action:      被阻断的 action 名
        result:      ConstraintResult（含 blocking_failures 文案，业务侧可直接展示）
    """

    def __init__(self, skill_name: str, action: str, result: ConstraintResult):
        self.skill_name = skill_name
        self.action = action
        self.result = result
        msg = "; ".join(result.blocking_failures) or "约束校验失败"
        super().__init__(f"[{skill_name}.{action}] 决策被三条硬约束拦截: {msg}")


# 类属性名：装饰器在被装饰的 execute 上打的标记，CI 用它扫描是否覆盖
DECORATOR_MARKER_ATTR = "__tx_constraint_check_skill__"


def _build_context(self_obj: Any, params: dict, skill_name: str) -> SkillContext:
    """从 Skill 实例 + params 组装 SkillContext。

    阈值优先级：params._store_thresholds > Skill 类属性 > 模块默认
    （params 注入是为了测试时灵活覆盖，生产路径走 Skill 类属性 / 门店配置）
    """
    overrides: dict = {}
    if isinstance(params, dict):
        candidate = params.get("_store_thresholds")
        if isinstance(candidate, dict):
            overrides = candidate

    return SkillContext(
        tenant_id=str(getattr(self_obj, "tenant_id", "") or ""),
        store_id=getattr(self_obj, "store_id", None),
        skill_name=skill_name,
        min_margin_rate=overrides.get(
            "min_margin_rate",
            getattr(self_obj, "min_margin_rate", 0.15),
        ),
        expiry_buffer_hours=overrides.get(
            "expiry_buffer_hours",
            getattr(self_obj, "expiry_buffer_hours", 24),
        ),
        max_serve_minutes=overrides.get(
            "max_serve_minutes",
            getattr(self_obj, "max_serve_minutes", 30),
        ),
        inventory_repository=getattr(self_obj, "inventory_repository", None),
        db=getattr(self_obj, "_db", None),
    )


async def _write_blocked_log(
    self_obj: Any,
    skill_name: str,
    action: str,
    params: dict,
    constraint_result: ConstraintResult,
) -> None:
    """写一条 blocked=True 的决策留痕。失败只 warn，绝不阻断主流程。

    schema 不变：仅向 input_context (JSON) 注入 blocked_at_constraint 标识。
    """
    db = getattr(self_obj, "_db", None)
    if db is None:
        # 测试场景或离线模式：纯日志即可
        logger.warning(
            "constraint_blocked_no_db",
            skill=skill_name,
            action=action,
            failures=constraint_result.blocking_failures,
        )
        return

    try:
        # 局部 import 避免顶部循环依赖（services.decision_log_service 也 import 本包间接）
        from ..services.decision_log_service import DecisionLogService

        # 构造一个最小 mock result 给 DecisionLogService.log_skill_result 用
        class _BlockedResultMock:
            success = False
            data = {
                "blocked_at_constraint": True,
                "constraints_check": constraint_result.to_dict(),
                "confidence": 0.0,
                "skill_name": skill_name,
            }

        await DecisionLogService.log_skill_result(
            db=db,
            tenant_id=str(getattr(self_obj, "tenant_id", "")),
            agent_id=skill_name,
            action=action,
            input_context={
                "params": _safe_jsonable(params),
                "blocked_at_constraint": True,
                "blocking_failures": constraint_result.blocking_failures,
            },
            result=_BlockedResultMock(),
            store_id=getattr(self_obj, "store_id", None),
        )
        logger.info(
            "constraint_blocked_logged",
            skill=skill_name,
            action=action,
            failures=constraint_result.blocking_failures,
        )
    except Exception as exc:  # noqa: BLE001 — 决策留痕失败不能影响业务异常传递
        logger.warning(
            "constraint_blocked_log_failed",
            skill=skill_name,
            action=action,
            error=str(exc),
        )


def _safe_jsonable(obj: Any, _depth: int = 0) -> Any:
    """裁剪 params 中的不可 JSON 化内容（mock 对象、AsyncSession 等）。"""
    if _depth > 4:
        return "<truncated>"
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_jsonable(v, _depth + 1) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_safe_jsonable(v, _depth + 1) for v in obj][:32]
    return repr(obj)[:200]


def with_constraint_check(
    skill_name: str,
    raise_on_block: bool = False,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """装饰 Skill.execute()，对每次决策执行三条硬约束。

    Args:
        skill_name:       Skill 标识（用于异常 / 日志 / CI 扫描）
        raise_on_block:   约束失败时的处理方式
            False (默认) — 决策被拦截时记录留痕并将 result.success 置 False，
                          填 result.data["blocked_at_constraint"] / ["constraint_result"]，
                          兼容 base.py::SkillAgent.run() 既有 constraints_passed=False 路径
            True         — 抛 ConstraintBlockedException，调用方必须 try/except 捕获
                          （适用于绕过 run() 直接调 execute() 的外部业务代码）

    Returns:
        包装后的 async execute() 函数；CI 扫描通过 `__tx_constraint_check_skill__`
        类属性识别已覆盖的 Skill 类。

    Behavior matrix（raise_on_block=False，默认）：
        - happy path（result.success=True 且约束 passed/skipped） → 原 result 透传
        - result.success=False（execute 自身报错）              → 原 result 透传，不叠加约束阻断
        - constraints failed                                    → 写 blocked log + 在 result.data
                                                                  注入 _constraint_blocked=True，
                                                                  result 仍透传（base.py::run() 会
                                                                  用同一份 ConstraintChecker 把
                                                                  constraints_passed 标 False）

    Behavior matrix（raise_on_block=True）：
        - constraints failed → 写 blocked log + raise ConstraintBlockedException
                              （bypass base.py 的软告警路径，给 Master Agent / 业务路由用）

    Note: 本装饰器假设被包装方法签名为 `async def execute(self, action, params)`。
    """

    def _decorator(execute_func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(execute_func)
        async def wrapper(self: Any, action: str, params: Optional[dict] = None) -> Any:
            params = params or {}
            result = await execute_func(self, action, params)

            # execute() 自身已失败 → 不再叠加约束阻断（避免 None 数据导致 skipped→pass 误判）
            if not getattr(result, "success", False):
                return result

            ctx = _build_context(self, params, skill_name)
            constraint_result = await run_checks(result, ctx)

            # 通过或跳过 → 原样返回（base.py::run() 会用既有 ConstraintChecker 打 scope 标签）
            if constraint_result.passed:
                return result

            # 违反约束 → 写留痕
            await _write_blocked_log(self, skill_name, action, params, constraint_result)

            if raise_on_block:
                raise ConstraintBlockedException(skill_name, action, constraint_result)

            # 默认软通道：result 透传不动，base.py::SkillAgent.run() 会用既有
            # ConstraintChecker 校验 result.data 字段并把 constraints_passed 设为 False
            # （margin/safety/experience 三条同源逻辑，结果与本装饰器一致）。
            # 装饰器仅作了：(1) 写 blocked log；(2) 在 result.data 注入 _constraint_blocked
            # 标识便于 Master Agent / 路由层识别已被本层捕获过的违规。
            if isinstance(result.data, dict):
                result.data.setdefault("_constraint_blocked", True)
                result.data.setdefault("_constraint_result", constraint_result.to_dict())
            return result

        # CI 扫描标记：类属性形式（被装饰类继承时仍然可读）
        setattr(wrapper, DECORATOR_MARKER_ATTR, skill_name)
        return wrapper

    return _decorator


__all__ = [
    "ConstraintBlockedException",
    "DECORATOR_MARKER_ATTR",
    "with_constraint_check",
]
