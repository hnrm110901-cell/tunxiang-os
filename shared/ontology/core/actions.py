"""
Ontology Actions — 对标 Palantir Actions + AIP Agent 执行层

每个 Action:
  1. 接收结构化输入
  2. 校验三条硬约束
  3. 执行业务逻辑
  4. 写入决策日志 (AgentDecisionLog)
  5. 触发副作用 (通知/同步)

三条硬约束 (不可违反):
  1. 毛利底线 — 任何折扣/赠送不可使单笔毛利低于设定阈值
  2. 食安合规 — 临期/过期食材不可用于出品
  3. 客户体验 — 出餐时间不可超过门店设定上限
"""

from __future__ import annotations

import abc
import functools
import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel, Field

from .registry import OntologyRegistry, build_default_registry
from .types import (
    ConstraintType,
    DishObject,
    HardConstraintResult,
    IngredientObject,
    OrderItemObject,
    OrderObject,
    StoreObject,
)

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────
# Agent Decision Log
# ─────────────────────────────────────────────


class AgentDecisionLog(BaseModel):
    """Agent 决策留痕 — 每个 Agent 决策必须记录，无例外

    对应 CLAUDE.md 规范:
      agent_id, decision_type, input_context, reasoning,
      output_action, constraints_check, confidence, created_at
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    agent_id: str
    decision_type: str
    input_context: dict[str, Any]
    reasoning: str
    output_action: dict[str, Any]
    constraints_check: dict[str, Any] = Field(
        default_factory=dict,
        description="三条硬约束校验结果: {margin_floor: bool, food_safety: bool, customer_experience: bool}",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────
# Action Context & Result
# ─────────────────────────────────────────────


class ActionContext(BaseModel):
    """Action 执行上下文"""

    tenant_id: uuid.UUID
    store_id: uuid.UUID | None = None
    operator_id: str | None = Field(
        default=None,
        description="执行操作的用户/Agent ID",
    )
    agent_id: str | None = Field(
        default=None,
        description="如果是 Agent 触发则填写 agent_id",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Action 执行结果"""

    ok: bool
    action_name: str
    data: dict[str, Any] = Field(default_factory=dict)
    constraint_results: list[HardConstraintResult] = Field(default_factory=list)
    decision_log: AgentDecisionLog | None = None
    error: str | None = None
    side_effects: list[str] = Field(
        default_factory=list,
        description="触发的副作用描述列表",
    )


# ─────────────────────────────────────────────
# Hard Constraint Checkers
# ─────────────────────────────────────────────


def check_margin_floor(
    order: OrderObject,
    store: StoreObject,
    discount_amount_fen: int = 0,
) -> HardConstraintResult:
    """毛利底线约束检查

    规则: 折扣后毛利率不可低于门店设定阈值 (margin_floor_pct)
    """
    total_cost_fen = 0
    for item in order.items:
        if item.food_cost_fen is not None:
            total_cost_fen += item.food_cost_fen * item.quantity

    revenue_after_discount = order.total_amount_fen - discount_amount_fen
    if revenue_after_discount <= 0:
        return HardConstraintResult(
            constraint_type=ConstraintType.margin_floor,
            passed=False,
            message=f"折扣后营收为零或负数: {revenue_after_discount}分",
            detail={
                "total_amount_fen": order.total_amount_fen,
                "discount_amount_fen": discount_amount_fen,
                "revenue_after_discount": revenue_after_discount,
            },
        )

    margin_pct = ((revenue_after_discount - total_cost_fen) / revenue_after_discount) * 100
    floor = store.margin_floor_pct

    passed = margin_pct >= floor
    return HardConstraintResult(
        constraint_type=ConstraintType.margin_floor,
        passed=passed,
        message=(
            f"毛利率 {margin_pct:.1f}% >= 底线 {floor:.1f}%"
            if passed
            else f"毛利率 {margin_pct:.1f}% 低于底线 {floor:.1f}%"
        ),
        detail={
            "margin_pct": round(margin_pct, 2),
            "floor_pct": floor,
            "total_cost_fen": total_cost_fen,
            "revenue_after_discount": revenue_after_discount,
        },
    )


def check_food_safety(
    ingredients: list[IngredientObject],
    reference_date: date | None = None,
) -> HardConstraintResult:
    """食安合规约束检查

    规则: 临期/过期食材不可用于出品
    """
    check_date = reference_date or date.today()
    expired: list[dict[str, Any]] = []
    near_expiry: list[dict[str, Any]] = []

    for ing in ingredients:
        days_left = ing.days_until_expiry(check_date)
        if days_left is not None:
            if days_left < 0:
                expired.append({
                    "ingredient_id": str(ing.id),
                    "name": ing.ingredient_name,
                    "expiry_date": str(ing.expiry_date),
                    "days_expired": abs(days_left),
                })
            elif days_left <= 2:
                near_expiry.append({
                    "ingredient_id": str(ing.id),
                    "name": ing.ingredient_name,
                    "expiry_date": str(ing.expiry_date),
                    "days_remaining": days_left,
                })

    passed = len(expired) == 0
    if not passed:
        names = ", ".join(e["name"] for e in expired)
        message = f"发现 {len(expired)} 种过期食材: {names}"
    elif near_expiry:
        names = ", ".join(e["name"] for e in near_expiry)
        message = f"通过，但有 {len(near_expiry)} 种食材临期: {names}"
    else:
        message = "所有食材效期合规"

    return HardConstraintResult(
        constraint_type=ConstraintType.food_safety,
        passed=passed,
        message=message,
        detail={
            "expired": expired,
            "near_expiry": near_expiry,
            "check_date": str(check_date),
        },
    )


def check_customer_experience(
    store: StoreObject,
    estimated_serve_time_min: int,
) -> HardConstraintResult:
    """客户体验约束检查

    规则: 预估出餐时间不可超过门店设定上限 (serve_time_limit_min)
    """
    limit = store.serve_time_limit_min
    passed = estimated_serve_time_min <= limit

    return HardConstraintResult(
        constraint_type=ConstraintType.customer_experience,
        passed=passed,
        message=(
            f"预估出餐 {estimated_serve_time_min}分钟 <= 上限 {limit}分钟"
            if passed
            else f"预估出餐 {estimated_serve_time_min}分钟 超过上限 {limit}分钟"
        ),
        detail={
            "estimated_serve_time_min": estimated_serve_time_min,
            "limit_min": limit,
        },
    )


# ─────────────────────────────────────────────
# Abstract Action Base
# ─────────────────────────────────────────────


class OntologyAction(abc.ABC):
    """Ontology Action 基类

    所有业务操作继承此类，实现:
      - validate(): 输入校验
      - check_constraints(): 硬约束检查
      - execute(): 业务逻辑执行
      - build_decision_log(): Agent 决策留痕 (可选)
    """

    action_name: str = "base_action"

    @abc.abstractmethod
    async def validate(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        """校验输入参数，不满足时抛出 ValueError"""

    @abc.abstractmethod
    async def check_constraints(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> list[HardConstraintResult]:
        """执行硬约束检查，返回检查结果列表"""

    @abc.abstractmethod
    async def execute(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """执行业务逻辑，返回结果数据"""

    def build_decision_log(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
        result: dict[str, Any],
        constraint_results: list[HardConstraintResult],
        confidence: float = 1.0,
    ) -> AgentDecisionLog | None:
        """构建 Agent 决策日志 (默认不记录，需要时子类 override)"""
        if ctx.agent_id is None:
            return None

        constraints_check = {
            cr.constraint_type.value: cr.passed for cr in constraint_results
        }

        return AgentDecisionLog(
            agent_id=ctx.agent_id,
            decision_type=self.action_name,
            input_context={
                "tenant_id": str(ctx.tenant_id),
                "store_id": str(ctx.store_id) if ctx.store_id else None,
                "params": _sanitize_for_log(params),
            },
            reasoning=f"Action '{self.action_name}' executed by agent '{ctx.agent_id}'",
            output_action=_sanitize_for_log(result),
            constraints_check=constraints_check,
            confidence=confidence,
        )

    async def run(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> ActionResult:
        """完整 Action 执行流程: validate → check_constraints → execute → log"""
        log = logger.bind(action=self.action_name, tenant_id=str(ctx.tenant_id))

        # Step 1: Validate
        try:
            await self.validate(ctx, params)
        except ValueError as ve:
            log.warning("action.validation_failed", error=str(ve))
            return ActionResult(
                ok=False,
                action_name=self.action_name,
                error=f"Validation failed: {ve}",
            )

        # Step 2: Check constraints
        constraint_results = await self.check_constraints(ctx, params)
        failed_constraints = [cr for cr in constraint_results if not cr.passed]

        if failed_constraints:
            messages = [str(fc) for fc in failed_constraints]
            log.warning(
                "action.constraint_failed",
                failed=messages,
            )
            return ActionResult(
                ok=False,
                action_name=self.action_name,
                constraint_results=constraint_results,
                error=f"Constraint check failed: {'; '.join(messages)}",
            )

        # Step 3: Execute
        try:
            result_data = await self.execute(ctx, params)
        except (ValueError, KeyError, TypeError) as exc:
            log.error("action.execution_failed", error=str(exc), exc_type=type(exc).__name__)
            return ActionResult(
                ok=False,
                action_name=self.action_name,
                constraint_results=constraint_results,
                error=f"Execution failed: {exc}",
            )

        # Step 4: Decision log
        decision_log = self.build_decision_log(
            ctx, params, result_data, constraint_results,
        )
        if decision_log is not None:
            log.info(
                "action.decision_logged",
                agent_id=decision_log.agent_id,
                confidence=decision_log.confidence,
            )

        log.info("action.completed", ok=True)
        return ActionResult(
            ok=True,
            action_name=self.action_name,
            data=result_data,
            constraint_results=constraint_results,
            decision_log=decision_log,
        )


# ─────────────────────────────────────────────
# Concrete Actions
# ─────────────────────────────────────────────


class CreateOrderAction(OntologyAction):
    """开单 — 创建新订单

    约束检查: 客户体验 (预估出餐时间)
    """

    action_name: str = "create_order"

    async def validate(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        if "order" not in params:
            raise ValueError("Missing 'order' in params")
        if "store" not in params:
            raise ValueError("Missing 'store' in params")

    async def check_constraints(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> list[HardConstraintResult]:
        store: StoreObject = params["store"]
        estimated_time: int = params.get("estimated_serve_time_min", 15)

        return [check_customer_experience(store, estimated_time)]

    async def execute(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        order: OrderObject = params["order"]
        logger.info(
            "action.create_order",
            order_no=order.order_no,
            store_id=str(order.store_id),
            item_count=len(order.items),
        )
        return {
            "order_id": str(order.id),
            "order_no": order.order_no,
            "status": order.status,
            "total_amount_fen": order.total_amount_fen,
        }


class ApplyDiscountAction(OntologyAction):
    """打折 — 为订单应用折扣

    约束检查: 毛利底线 (折扣后毛利率不可低于阈值)
    需要 Agent 决策留痕
    """

    action_name: str = "apply_discount"

    async def validate(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        if "order" not in params:
            raise ValueError("Missing 'order' in params")
        if "store" not in params:
            raise ValueError("Missing 'store' in params")
        discount = params.get("discount_amount_fen", 0)
        if not isinstance(discount, int) or discount < 0:
            raise ValueError(f"discount_amount_fen must be non-negative int, got {discount}")

    async def check_constraints(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> list[HardConstraintResult]:
        order: OrderObject = params["order"]
        store: StoreObject = params["store"]
        discount_fen: int = params.get("discount_amount_fen", 0)

        return [check_margin_floor(order, store, discount_fen)]

    async def execute(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        order: OrderObject = params["order"]
        discount_fen: int = params.get("discount_amount_fen", 0)
        discount_type: str = params.get("discount_type", "manual")
        reason: str = params.get("reason", "")

        final_fen = order.total_amount_fen - discount_fen
        logger.info(
            "action.apply_discount",
            order_no=order.order_no,
            discount_fen=discount_fen,
            discount_type=discount_type,
            final_fen=final_fen,
        )
        return {
            "order_id": str(order.id),
            "order_no": order.order_no,
            "discount_amount_fen": discount_fen,
            "discount_type": discount_type,
            "final_amount_fen": final_fen,
            "reason": reason,
        }

    def build_decision_log(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
        result: dict[str, Any],
        constraint_results: list[HardConstraintResult],
        confidence: float = 1.0,
    ) -> AgentDecisionLog | None:
        """打折操作强制留痕 (即使非 Agent 触发)"""
        agent_id = ctx.agent_id or ctx.operator_id or "system"
        constraints_check = {
            cr.constraint_type.value: cr.passed for cr in constraint_results
        }

        order: OrderObject = params["order"]
        return AgentDecisionLog(
            agent_id=agent_id,
            decision_type=self.action_name,
            input_context={
                "tenant_id": str(ctx.tenant_id),
                "order_no": order.order_no,
                "discount_amount_fen": params.get("discount_amount_fen", 0),
                "discount_type": params.get("discount_type", "manual"),
            },
            reasoning=params.get("reason", "Discount applied"),
            output_action=_sanitize_for_log(result),
            constraints_check=constraints_check,
            confidence=confidence,
        )


class MarkSoldOutAction(OntologyAction):
    """标记沽清 — 将菜品标记为沽清或恢复供应

    无硬约束 (但记录操作)
    """

    action_name: str = "mark_sold_out"

    async def validate(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        if "dish" not in params:
            raise ValueError("Missing 'dish' in params")
        if "sold_out" not in params:
            raise ValueError("Missing 'sold_out' (bool) in params")

    async def check_constraints(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> list[HardConstraintResult]:
        return []  # 无硬约束

    async def execute(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        dish: DishObject = params["dish"]
        sold_out: bool = params["sold_out"]
        reason: str = params.get("reason", "")

        logger.info(
            "action.mark_sold_out",
            dish_code=dish.dish_code,
            dish_name=dish.dish_name,
            sold_out=sold_out,
            reason=reason,
        )
        return {
            "dish_id": str(dish.id),
            "dish_code": dish.dish_code,
            "dish_name": dish.dish_name,
            "is_sold_out": sold_out,
            "reason": reason,
        }


class TransferStockAction(OntologyAction):
    """门店调拨 — 门店间食材调拨

    约束检查: 食安合规 (调出食材不可过期)
    """

    action_name: str = "transfer_stock"

    async def validate(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        if "ingredients" not in params:
            raise ValueError("Missing 'ingredients' in params")
        if "source_store_id" not in params:
            raise ValueError("Missing 'source_store_id' in params")
        if "target_store_id" not in params:
            raise ValueError("Missing 'target_store_id' in params")
        if params["source_store_id"] == params["target_store_id"]:
            raise ValueError("Source and target store cannot be the same")
        quantities = params.get("quantities", {})
        for ing in params["ingredients"]:
            ing_id = str(ing.id)
            qty = quantities.get(ing_id, 0)
            if qty <= 0:
                raise ValueError(
                    f"Transfer quantity for {ing.ingredient_name} must be positive"
                )
            if qty > ing.current_quantity:
                raise ValueError(
                    f"Insufficient stock for {ing.ingredient_name}: "
                    f"requested {qty}, available {ing.current_quantity}"
                )

    async def check_constraints(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> list[HardConstraintResult]:
        ingredients: list[IngredientObject] = params["ingredients"]
        return [check_food_safety(ingredients)]

    async def execute(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        ingredients: list[IngredientObject] = params["ingredients"]
        quantities: dict[str, float] = params.get("quantities", {})
        source = params["source_store_id"]
        target = params["target_store_id"]

        transfer_items = []
        for ing in ingredients:
            ing_id = str(ing.id)
            qty = quantities.get(ing_id, 0)
            transfer_items.append({
                "ingredient_id": ing_id,
                "ingredient_name": ing.ingredient_name,
                "quantity": qty,
                "unit": ing.unit,
            })

        logger.info(
            "action.transfer_stock",
            source_store=str(source),
            target_store=str(target),
            item_count=len(transfer_items),
        )
        return {
            "source_store_id": str(source),
            "target_store_id": str(target),
            "items": transfer_items,
        }


class CheckFoodSafetyAction(OntologyAction):
    """食安检查 — 食材效期及合规检查

    约束检查: 食安合规 (过期食材检测)
    需要 Agent 决策留痕
    """

    action_name: str = "check_food_safety"

    async def validate(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        if "ingredients" not in params:
            raise ValueError("Missing 'ingredients' in params")

    async def check_constraints(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> list[HardConstraintResult]:
        ingredients: list[IngredientObject] = params["ingredients"]
        ref_date: date | None = params.get("reference_date")
        # 食安检查Action本身是巡检操作，不应被自身约束阻断。
        # 但必须保留真实的检查结果用于决策日志和下游消费。
        result = check_food_safety(ingredients, ref_date)
        # 标记为巡检模式：Action可继续执行，但detail中保留真实passed状态
        return [HardConstraintResult(
            constraint_type=ConstraintType.food_safety,
            passed=True,  # 巡检Action本身不被阻断
            message=f"[巡检] {result.message}",
            detail={
                **(result.detail or {}),
                "actual_safety_passed": result.passed,  # 保留真实食安状态
                "is_inspection": True,
            },
        )]

    async def execute(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        ingredients: list[IngredientObject] = params["ingredients"]
        ref_date: date | None = params.get("reference_date")
        check_date = ref_date or date.today()

        report: list[dict[str, Any]] = []
        for ing in ingredients:
            days_left = ing.days_until_expiry(check_date)
            status = "ok"
            if days_left is not None:
                if days_left < 0:
                    status = "expired"
                elif days_left <= 2:
                    status = "near_expiry"
                elif days_left <= 7:
                    status = "warning"

            report.append({
                "ingredient_id": str(ing.id),
                "name": ing.ingredient_name,
                "expiry_date": str(ing.expiry_date) if ing.expiry_date else None,
                "days_until_expiry": days_left,
                "status": status,
                "storage_type": ing.storage_type,
            })

        expired_count = sum(1 for r in report if r["status"] == "expired")
        near_expiry_count = sum(1 for r in report if r["status"] == "near_expiry")

        logger.info(
            "action.check_food_safety",
            total=len(report),
            expired=expired_count,
            near_expiry=near_expiry_count,
        )
        return {
            "check_date": str(check_date),
            "total_checked": len(report),
            "expired_count": expired_count,
            "near_expiry_count": near_expiry_count,
            "items": report,
        }

    def build_decision_log(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
        result: dict[str, Any],
        constraint_results: list[HardConstraintResult],
        confidence: float = 0.95,
    ) -> AgentDecisionLog:
        """食安检查强制留痕"""
        agent_id = ctx.agent_id or "food_safety_agent"
        constraints_check = {
            cr.constraint_type.value: cr.passed for cr in constraint_results
        }

        return AgentDecisionLog(
            agent_id=agent_id,
            decision_type=self.action_name,
            input_context={
                "tenant_id": str(ctx.tenant_id),
                "store_id": str(ctx.store_id) if ctx.store_id else None,
                "ingredient_count": len(params.get("ingredients", [])),
            },
            reasoning=(
                f"Food safety check: {result.get('expired_count', 0)} expired, "
                f"{result.get('near_expiry_count', 0)} near expiry "
                f"out of {result.get('total_checked', 0)} items"
            ),
            output_action={
                "expired_count": result.get("expired_count", 0),
                "near_expiry_count": result.get("near_expiry_count", 0),
                "total_checked": result.get("total_checked", 0),
            },
            constraints_check=constraints_check,
            confidence=confidence,
        )


class PredictDemandAction(OntologyAction):
    """需求预测 — 基于历史数据预测食材/菜品需求量

    Agent 函数: 调用边缘 Core ML 或云端 Claude API
    需要 Agent 决策留痕
    """

    action_name: str = "predict_demand"

    async def validate(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        if "store" not in params:
            raise ValueError("Missing 'store' in params")
        if "target_date" not in params:
            raise ValueError("Missing 'target_date' in params")

    async def check_constraints(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> list[HardConstraintResult]:
        # 需求预测是只读分析操作，无硬约束
        return []

    async def execute(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        store: StoreObject = params["store"]
        target_date: str = params["target_date"]
        historical_days: int = params.get("historical_days", 30)
        categories: list[str] = params.get("categories", [])

        logger.info(
            "action.predict_demand",
            store_code=store.store_code,
            target_date=target_date,
            historical_days=historical_days,
        )

        # Placeholder: actual prediction calls Core ML (edge) or Claude API (cloud)
        return {
            "store_id": str(store.id),
            "store_code": store.store_code,
            "target_date": target_date,
            "historical_days": historical_days,
            "categories": categories,
            "predictions": [],  # To be filled by ML pipeline
            "model_source": "pending",  # "coreml_edge" or "claude_cloud"
        }

    def build_decision_log(
        self,
        ctx: ActionContext,
        params: dict[str, Any],
        result: dict[str, Any],
        constraint_results: list[HardConstraintResult],
        confidence: float = 0.8,
    ) -> AgentDecisionLog:
        """需求预测强制留痕"""
        agent_id = ctx.agent_id or "demand_prediction_agent"
        constraints_check = {
            cr.constraint_type.value: cr.passed for cr in constraint_results
        }

        return AgentDecisionLog(
            agent_id=agent_id,
            decision_type=self.action_name,
            input_context={
                "tenant_id": str(ctx.tenant_id),
                "store_id": str(ctx.store_id) if ctx.store_id else None,
                "target_date": params.get("target_date"),
                "historical_days": params.get("historical_days", 30),
            },
            reasoning=(
                f"Demand prediction for store {result.get('store_code')} "
                f"on {result.get('target_date')} "
                f"using {result.get('historical_days')} days of history"
            ),
            output_action={
                "prediction_count": len(result.get("predictions", [])),
                "model_source": result.get("model_source"),
            },
            constraints_check=constraints_check,
            confidence=confidence,
        )


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _sanitize_for_log(data: dict[str, Any]) -> dict[str, Any]:
    """将数据中的 UUID/datetime/BaseModel 转为可 JSON 序列化的类型"""
    sanitized: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, BaseModel):
            sanitized[k] = _sanitize_for_log(v.model_dump())
        elif isinstance(v, uuid.UUID):
            sanitized[k] = str(v)
        elif isinstance(v, datetime):
            sanitized[k] = v.isoformat()
        elif isinstance(v, date):
            sanitized[k] = v.isoformat()
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_for_log(v)
        elif isinstance(v, list):
            sanitized[k] = [
                _sanitize_for_log(item.model_dump()) if isinstance(item, BaseModel) else
                _sanitize_for_log(item) if isinstance(item, dict) else
                str(item) if isinstance(item, (uuid.UUID, datetime, date)) else
                item
                for item in v
            ]
        else:
            sanitized[k] = v
    return sanitized


# ─────────────────────────────────────────────
# Default Registry Instance (with action handlers bound)
# ─────────────────────────────────────────────


def _build_default_registry_with_handlers() -> OntologyRegistry:
    """构建默认 Registry 并绑定 Action handlers"""
    registry = build_default_registry()

    _ACTION_HANDLERS: dict[str, OntologyAction] = {
        "create_order": CreateOrderAction(),
        "apply_discount": ApplyDiscountAction(),
        "mark_sold_out": MarkSoldOutAction(),
        "transfer_stock": TransferStockAction(),
        "check_food_safety": CheckFoodSafetyAction(),
        "predict_demand": PredictDemandAction(),
    }

    for action_name, handler in _ACTION_HANDLERS.items():
        meta = registry.get_action(action_name)
        if meta is not None:
            registry.register_action(meta, handler=handler)
        else:
            logger.warning(
                "ontology.action.handler_no_meta",
                action_name=action_name,
            )

    return registry


@functools.cache
def get_default_registry() -> OntologyRegistry:
    """获取默认 Registry（懒初始化，首次调用时构建）"""
    return _build_default_registry_with_handlers()
