"""NLQ → 三类操作 dispatcher — S4-03 Issue #290 / Tier 1。

职责（PR1 范围）：
  1. dispatch_dry_run(req) — actionId 校验 → 找 handler → 跑 dry-run → 跑硬约束守门 → 返回 DryRunDiff
  2. ActionHandler 注册装饰器（每个 actionId 一个 async handler）
  3. 4 个 stub handler（PR2 替换为真实业务 dry-run，调 tx-menu / tx-supply / tx-org）
  4. _check_hard_constraints stub（PR2 接 services.tx_agent.constraints.run_checks）

不在 PR1（留 follow-up）：
  - execute_action（实际执行 + SAVEPOINT 回滚）
  - AgentDecisionLog DB 持久化（DB schema 改动 + 迁移）
  - SSE /nlq/action 端点
  - confirmation_token 持久化 + 防重放（PR1 简单 hash，足够本地测试）

调用约定：
  - 路由层用 TenantSession(tenant_id) 注入 + 校验 UUID
  - dispatch_dry_run 是只读 + 不写 DB（仅查询当前状态用于 diff 计算，PR2 接通真 DB）
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Awaitable, Callable, Optional

from .nlq_action_registry import assert_action_id_allowed
from .nlq_action_types import ActionId, ActionRequest, DryRunDiff


ActionHandler = Callable[[ActionRequest], Awaitable[DryRunDiff]]


class ActionPayloadError(ValueError):
    """Handler 发现 payload 字段缺失/类型错误 — 路由层据此映射 HTTP 400。

    继承 ValueError 保留向后兼容（既有 except ValueError 仍能捕获），但暴露具体
    类型供 PR2 /nlq/action 路由 except ActionPayloadError → 400，与未知异常 → 500
    精确区分。LLM 输出契约错就该回 4xx 让上游修，不应混入 5xx 触发告警。
    """


_ACTION_HANDLERS: dict[str, ActionHandler] = {}


def register_action(action_id: ActionId) -> Callable[[ActionHandler], ActionHandler]:
    """装饰器：注册 actionId 的 dry-run handler。

    Usage:
        @register_action("menu.update_price")
        async def _handler(req: ActionRequest) -> DryRunDiff:
            ...
    """

    def deco(handler: ActionHandler) -> ActionHandler:
        _ACTION_HANDLERS[action_id] = handler
        return handler

    return deco


def reset_handlers_for_test() -> None:
    """测试用：清空注册表（隔离不同测试）。生产代码不调用。"""
    _ACTION_HANDLERS.clear()


async def dispatch_dry_run(req: ActionRequest) -> DryRunDiff:
    """第一阶段：actionId 校验 → handler 跑 dry-run → 硬约束守门 → 返回 DryRunDiff。

    Raises:
        UnknownActionError: action_id 未注册或不在白名单
    """
    # Stage 1: 白名单 firewall
    assert_action_id_allowed(req.action_id)

    # Stage 2: handler 必须已注册（PR1 阶段，4 个 stub handler 在 module 加载时注册）
    handler = _ACTION_HANDLERS.get(req.action_id)
    if handler is None:
        raise RuntimeError(
            f"action_id={req.action_id!r} 在白名单但未注册 handler "
            f"(注册情况: {sorted(_ACTION_HANDLERS)})"
        )

    diff = await handler(req)

    # Stage 3: 三条硬约束守门（PR1 stub，PR2 接 tx-agent constraints.run_checks）
    block = await _check_hard_constraints(req, diff)
    if block is not None:
        diff.constraint_block = block
        diff.risk_warnings.append(block.get("reason", "硬约束触发"))

    return diff


def gen_confirmation_token(req: ActionRequest, diff: DryRunDiff) -> str:
    """根据请求 + diff + nonce 生成一次性确认 token（防重放：每次 dry-run 都不同）。

    设计：每次调用注入 uuid.uuid4() nonce 入 hash payload，token 不可重现。
    PR2 升级：把 token 持久化到 nonce 表，confirm 时 SELECT/UPDATE 标记已用。

    Code review (#301) 修：原 deterministic hash 同 req+diff 永远产生同 token，
    PR2 接 execute 时同一改价指令可被无限次提交（双花），必须从 PR1 就加 nonce
    锁定 token 契约（PR2 改 hash 算法会破坏兼容性）。
    """
    payload = {
        "action_id": req.action_id,
        "tenant_id": req.tenant_id,
        "operator_id": req.operator_id,
        "summary": diff.summary,
        "fields": diff.fields,
        "nonce": uuid.uuid4().hex,  # 一次性，PR2 持久化 token 防重放
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:32]


# ─── PR1 stub: 硬约束守门 ───────────────────────────────────────────────


async def _check_hard_constraints(
    req: ActionRequest, diff: DryRunDiff
) -> Optional[dict[str, Any]]:
    """PR1 stub — PR2 接 services.tx_agent.constraints.run_checks。

    返回 None 表示通过；返回 dict 表示阻断（含 name / reason / details）。

    PR1 简单逻辑：
      - menu.update_price + payload.cost_fen 已知 + new_price < cost → 毛利底线触发
      - inventory.86 + payload.has_unfinished_order=True → 客户体验触发
      - 其他场景一律放行
    """
    payload = req.payload

    if req.action_id == "menu.update_price":
        new_price = payload.get("new_price_fen")
        cost = payload.get("cost_fen")
        if (
            isinstance(new_price, int)
            and isinstance(cost, int)
            and cost > 0
            and new_price < cost
        ):
            return {
                "name": "gross_margin",
                "reason": f"新价 ¥{new_price / 100:.2f} 低于成本 ¥{cost / 100:.2f}（毛利底线）",
                "details": {"new_price_fen": new_price, "cost_fen": cost},
            }

    if req.action_id == "inventory.86":
        # 86 跨过期物料 → 食安合规（payload 必须明示有过期跨日批次）
        if payload.get("has_expired_batch") is True:
            return {
                "name": "food_safety",
                "reason": "待 86 食材批次含过期记录（食安合规）",
                "details": {"ingredient_id": payload.get("ingredient_id")},
            }

    if req.action_id == "menu.toggle_availability":
        # 下架前未结订单 → 客户体验
        toggle_to_off = payload.get("toggle_to") == "off"
        if toggle_to_off and payload.get("unfinished_orders", 0) > 0:
            return {
                "name": "customer_experience",
                "reason": (
                    f"菜品下架前仍有 {payload['unfinished_orders']} 单未结（客户体验）"
                ),
                "details": {"unfinished_orders": payload["unfinished_orders"]},
            }

    return None


# ─── PR1 stub handlers（按 actionId 注册） ───────────────────────────────


@register_action("menu.update_price")
async def _menu_update_price_dry_run(req: ActionRequest) -> DryRunDiff:
    """改价 dry-run（PR1 stub — PR2 接 tx-menu API 查现价）。"""
    new_price = req.payload.get("new_price_fen")
    if not isinstance(new_price, int):
        raise ActionPayloadError("payload.new_price_fen 必须为 int（分）")
    return DryRunDiff(
        summary=f"改价 → ¥{new_price / 100:.2f}（PR1 stub，PR2 查现价填 before）",
        fields={"price_fen": {"before": None, "after": new_price}},
        affected_count=1,
    )


@register_action("menu.toggle_availability")
async def _menu_toggle_availability_dry_run(req: ActionRequest) -> DryRunDiff:
    """上下架 dry-run（PR1 stub — PR2 接 tx-menu API）。"""
    toggle_to = req.payload.get("toggle_to", "off")
    if toggle_to not in ("on", "off"):
        raise ActionPayloadError("payload.toggle_to 必须为 'on' 或 'off'")
    return DryRunDiff(
        summary=f"切换上下架 → {toggle_to}（PR1 stub）",
        fields={"availability": {"before": None, "after": toggle_to}},
        affected_count=1,
    )


@register_action("inventory.86")
async def _inventory_86_dry_run(req: ActionRequest) -> DryRunDiff:
    """库存清零 dry-run（PR1 stub — PR2 接 tx-supply API）。"""
    ingredient_id = req.payload.get("ingredient_id")
    if not ingredient_id:
        raise ActionPayloadError("payload.ingredient_id 必填")
    return DryRunDiff(
        summary=f"86 食材 {ingredient_id}（PR1 stub）",
        fields={"qty_remaining": {"before": None, "after": 0}},
        affected_count=1,
    )


@register_action("roster.update")
async def _roster_update_dry_run(req: ActionRequest) -> DryRunDiff:
    """排班修改 dry-run（PR1 stub — PR2 接 tx-org API）。"""
    employee_id = req.payload.get("employee_id")
    new_shift = req.payload.get("new_shift")
    if not employee_id or not new_shift:
        raise ActionPayloadError("payload.employee_id / new_shift 必填")
    return DryRunDiff(
        summary=f"调整员工 {employee_id} → {new_shift} 班（PR1 stub）",
        fields={"shift": {"before": None, "after": new_shift}},
        affected_count=1,
    )
