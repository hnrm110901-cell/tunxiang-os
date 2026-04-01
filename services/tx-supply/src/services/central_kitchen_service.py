"""中央厨房核心服务 — DB 化版本（v062 表）

构造：CentralKitchenService(db: AsyncSession, tenant_id: str)
所有方法委托给 CentralKitchenRepository，返回 Pydantic 响应模型。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .central_kitchen_repository import CentralKitchenRepository

log = structlog.get_logger(__name__)


# ─── Pydantic V2 响应模型 ───────────────────────────────────────────────────

from pydantic import BaseModel, Field


class KitchenProfile(BaseModel):
    id: str
    tenant_id: str
    name: str
    address: Optional[str] = None
    capacity_daily: float
    manager_id: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: bool
    created_at: str


class PlanItem(BaseModel):
    dish_id: str
    dish_name: str
    quantity: float
    unit: str = "份"
    target_stores: List[str] = Field(default_factory=list)


class ProductionPlan(BaseModel):
    id: str
    tenant_id: str
    kitchen_id: str
    plan_date: str
    status: str  # draft / confirmed / in_progress / completed
    items: List[Dict[str, Any]]
    created_by: Optional[str] = None
    confirmed_at: Optional[str] = None
    created_at: str


class ProductionOrder(BaseModel):
    id: str
    tenant_id: str
    kitchen_id: str
    plan_id: str
    dish_id: str
    quantity: float
    unit: str
    status: str  # pending / in_progress / completed / cancelled
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    operator_id: Optional[str] = None
    created_at: str


class DistributionOrder(BaseModel):
    id: str
    tenant_id: str
    kitchen_id: str
    target_store_id: str
    scheduled_at: str
    delivered_at: Optional[str] = None
    status: str  # pending / dispatched / delivered / confirmed
    items: List[Dict[str, Any]]
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    created_at: str


class ReceivingItem(BaseModel):
    dish_id: str
    dish_name: str
    expected_qty: float
    received_qty: float
    unit: str
    variance_notes: Optional[str] = None


class StoreReceivingConfirmation(BaseModel):
    id: str
    tenant_id: str
    distribution_order_id: str
    store_id: str
    confirmed_by: str
    confirmed_at: str
    items: List[Dict[str, Any]]
    notes: Optional[str] = None
    created_at: str


class KitchenDashboard(BaseModel):
    kitchen_id: str
    date: str
    plan_count: int
    plans: List[Dict[str, Any]]
    production_order_summary: Dict[str, int]  # status -> count
    distribution_summary: Dict[str, int]      # status -> count


class DishForecast(BaseModel):
    dish_id: str
    dish_name: str
    avg_daily_qty: float
    suggested_qty: float
    unit: str
    weekend_adjusted: bool


class DemandForecast(BaseModel):
    kitchen_id: str
    target_date: str
    is_weekend: bool
    dishes: List[DishForecast]
    generated_at: str


# ─── 核心服务 ───────────────────────────────────────────────────────────────

class CentralKitchenService:
    """中央厨房核心业务服务（DB 化）

    构造时接受 (db, tenant_id)，不从 session 变量读取，
    符合屯象OS RLS 安全规范。
    """

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._repo = CentralKitchenRepository(db, tenant_id)
        self._tenant_id = tenant_id

    # ── 厨房档案 ──────────────────────────────────────────────────────

    async def create_kitchen(
        self,
        name: str,
        address: Optional[str] = None,
        capacity_daily: float = 0.0,
        manager_id: Optional[str] = None,
        contact_phone: Optional[str] = None,
    ) -> KitchenProfile:
        d = await self._repo.create_kitchen(name, address, capacity_daily, manager_id, contact_phone)
        return KitchenProfile(**d)

    async def list_kitchens(self) -> List[KitchenProfile]:
        rows = await self._repo.list_kitchens()
        return [KitchenProfile(**r) for r in rows]

    # ── 生产计划 ──────────────────────────────────────────────────────

    async def create_production_plan(
        self,
        kitchen_id: str,
        plan_date: str,
        items: List[Dict[str, Any]],
        created_by: Optional[str] = None,
    ) -> ProductionPlan:
        # items 为空时委托 repo（repo 传空列表，业务层自动预测在此省略）
        d = await self._repo.create_plan(kitchen_id, plan_date, items, created_by)
        return ProductionPlan(**d)

    async def list_production_plans(
        self,
        kitchen_id: Optional[str] = None,
        plan_date: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        return await self._repo.list_plans(kitchen_id, plan_date, status, page, size)

    async def get_production_plan(self, plan_id: str) -> ProductionPlan:
        d = await self._repo.get_plan(plan_id)
        if not d:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        return ProductionPlan(**d)

    async def confirm_production_plan(self, plan_id: str, operator_id: str) -> ProductionPlan:
        d = await self._repo.confirm_plan(plan_id, operator_id)
        return ProductionPlan(**d)

    async def start_production(self, plan_id: str) -> ProductionPlan:
        d = await self._repo.start_production(plan_id)
        return ProductionPlan(**d)

    # ── 生产工单 ──────────────────────────────────────────────────────

    async def list_production_orders(
        self,
        kitchen_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        return await self._repo.list_orders(kitchen_id, plan_id, status, page, size)

    async def complete_production_order(self, order_id: str, actual_qty: float) -> ProductionOrder:
        d = await self._repo.complete_order(order_id, actual_qty)
        return ProductionOrder(**d)

    async def update_production_progress(
        self,
        order_id: str,
        status: str,
        quantity_done: Optional[float] = None,
    ) -> ProductionOrder:
        d = await self._repo.update_order_progress(order_id, status, quantity_done)
        return ProductionOrder(**d)

    # ── 配送单 ────────────────────────────────────────────────────────

    async def list_distribution_orders(
        self,
        kitchen_id: Optional[str] = None,
        store_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        return await self._repo.list_distribution_orders(kitchen_id, store_id, status, page, size)

    async def create_distribution_order(
        self,
        kitchen_id: str,
        store_id: str,
        items: List[Dict[str, Any]],
        scheduled_at: str,
        driver_name: Optional[str] = None,
        driver_phone: Optional[str] = None,
    ) -> DistributionOrder:
        d = await self._repo.create_distribution_order(
            kitchen_id, store_id, items, scheduled_at, driver_name, driver_phone
        )
        return DistributionOrder(**d)

    async def mark_dispatched(self, order_id: str) -> DistributionOrder:
        d = await self._repo.mark_dispatched(order_id)
        return DistributionOrder(**d)

    async def confirm_store_receiving(
        self,
        distribution_order_id: str,
        store_id: str,
        confirmed_by: str,
        items: List[Dict[str, Any]],
        notes: Optional[str] = None,
    ) -> StoreReceivingConfirmation:
        d = await self._repo.confirm_receiving(
            distribution_order_id, store_id, confirmed_by, items, notes
        )
        return StoreReceivingConfirmation(**d)

    # ── 看板与预测 ────────────────────────────────────────────────────

    async def get_daily_dashboard(self, kitchen_id: str, date: str) -> KitchenDashboard:
        d = await self._repo.get_daily_dashboard(kitchen_id, date)
        return KitchenDashboard(**d)

    async def forecast_demand(self, kitchen_id: str, target_date: str) -> DemandForecast:
        d = await self._repo.forecast_demand(kitchen_id, target_date)
        return DemandForecast(**d)
