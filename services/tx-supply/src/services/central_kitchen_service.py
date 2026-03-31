"""中央厨房核心服务

功能：生产计划创建/确认、工单进度跟踪、配送单管理、门店收货确认、
      日看板、需求预测（近30天均值 + 周几权重）

注：当前阶段使用内存存储，接口签名与 DB Repository 模式兼容，
    生产环境替换存储层即可，业务逻辑无需修改。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# 周末权重系数（周六=6, 周日=0）
_WEEKEND_WEIGHT = 1.3
_WEEKEND_DAYS = {5, 6}  # Monday=0 … Sunday=6

# ─── 内存存储（生产环境替换为 DB Repository） ───
_kitchens: Dict[str, Dict[str, Any]] = {}
_plans: Dict[str, Dict[str, Any]] = {}
_production_orders: Dict[str, Dict[str, Any]] = {}
_distribution_orders: Dict[str, Dict[str, Any]] = {}
_receiving_confirmations: Dict[str, Dict[str, Any]] = {}

# 测试注入：历史消耗数据  key = "tenant_id:store_id:dish_id:date_str"
_consumption_history: Dict[str, float] = {}


# ─── Pydantic V2 响应模型 ───

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


# ─── 工具函数 ───

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return str(uuid.uuid4())


def _is_weekend(target: date) -> bool:
    return target.weekday() in _WEEKEND_DAYS


def _inject_consumption(
    tenant_id: str,
    store_id: str,
    dish_id: str,
    date_str: str,
    qty: float,
) -> None:
    """测试辅助：注入历史消耗数据"""
    key = f"{tenant_id}:{store_id}:{dish_id}:{date_str}"
    _consumption_history[key] = qty


def _clear_store() -> None:
    """测试辅助：清空所有内存存储"""
    _kitchens.clear()
    _plans.clear()
    _production_orders.clear()
    _distribution_orders.clear()
    _receiving_confirmations.clear()
    _consumption_history.clear()


# ─── 核心服务 ───

class CentralKitchenService:
    """中央厨房核心业务服务

    所有方法显式接收 tenant_id，不从 session 变量读取，
    符合屯象OS RLS 安全规范。
    """

    # ── 厨房档案 ──────────────────────────────────────────────────────

    async def create_kitchen(
        self,
        tenant_id: str,
        name: str,
        address: Optional[str] = None,
        capacity_daily: float = 0.0,
        manager_id: Optional[str] = None,
        contact_phone: Optional[str] = None,
    ) -> KitchenProfile:
        """新建中央厨房档案"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not name or not name.strip():
            raise ValueError("中央厨房名称不能为空")
        if capacity_daily < 0:
            raise ValueError("日产能不能为负数")

        kitchen_id = _gen_id()
        now = _now_iso()
        record: Dict[str, Any] = {
            "id": kitchen_id,
            "tenant_id": tenant_id,
            "name": name.strip(),
            "address": address,
            "capacity_daily": capacity_daily,
            "manager_id": manager_id,
            "contact_phone": contact_phone,
            "is_active": True,
            "created_at": now,
        }
        _kitchens[kitchen_id] = record
        log.info("kitchen_created", kitchen_id=kitchen_id, name=name, tenant_id=tenant_id)
        return KitchenProfile(**record)

    async def list_kitchens(self, tenant_id: str) -> List[KitchenProfile]:
        """列出当前租户所有中央厨房"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        results = [
            KitchenProfile(**k)
            for k in _kitchens.values()
            if k["tenant_id"] == tenant_id
        ]
        return results

    # ── 生产计划 ──────────────────────────────────────────────────────

    async def create_production_plan(
        self,
        tenant_id: str,
        kitchen_id: str,
        plan_date: str,
        items: List[Dict[str, Any]],
        created_by: Optional[str] = None,
    ) -> ProductionPlan:
        """创建生产计划草稿。

        items 格式：[{dish_id, dish_name, quantity, unit, target_stores:[...]}]

        业务逻辑：
        - 若 items 为空则从历史订单预测需求（调用 forecast_demand）
        - 校验厨房存在且属于当前租户
        - 保存草稿计划

        Args:
            tenant_id: 租户 ID
            kitchen_id: 中央厨房 ID
            plan_date: 生产日期（YYYY-MM-DD）
            items: 生产菜品清单，空列表时自动预测
            created_by: 操作人 ID

        Returns:
            ProductionPlan 草稿

        Raises:
            ValueError: 参数校验失败或厨房不存在
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not kitchen_id:
            raise ValueError("kitchen_id 不能为空")
        if not plan_date:
            raise ValueError("plan_date 不能为空")

        kitchen = _kitchens.get(kitchen_id)
        if not kitchen or kitchen["tenant_id"] != tenant_id:
            raise ValueError(f"中央厨房 {kitchen_id} 不存在或不属于当前租户")

        # 若未提供菜品清单，从需求预测获取建议量
        if not items:
            forecast = await self.forecast_demand(tenant_id, kitchen_id, plan_date)
            items = [
                {
                    "dish_id": d.dish_id,
                    "dish_name": d.dish_name,
                    "quantity": d.suggested_qty,
                    "unit": d.unit,
                    "target_stores": [],
                }
                for d in forecast.dishes
            ]

        # 校验每个 item 的必填字段
        for i, item in enumerate(items):
            if not item.get("dish_id"):
                raise ValueError(f"items[{i}] 缺少 dish_id")
            if not item.get("dish_name"):
                raise ValueError(f"items[{i}] 缺少 dish_name")
            qty = item.get("quantity", 0)
            if float(qty) <= 0:
                raise ValueError(f"items[{i}] quantity 必须大于 0")

        plan_id = _gen_id()
        now = _now_iso()
        record: Dict[str, Any] = {
            "id": plan_id,
            "tenant_id": tenant_id,
            "kitchen_id": kitchen_id,
            "plan_date": plan_date,
            "status": "draft",
            "items": items,
            "created_by": created_by,
            "confirmed_at": None,
            "created_at": now,
        }
        _plans[plan_id] = record

        log.info(
            "production_plan_created",
            plan_id=plan_id,
            kitchen_id=kitchen_id,
            plan_date=plan_date,
            item_count=len(items),
            tenant_id=tenant_id,
        )
        return ProductionPlan(**record)

    async def confirm_production_plan(
        self,
        tenant_id: str,
        plan_id: str,
        operator_id: str,
    ) -> ProductionPlan:
        """确认生产计划，并为每个菜品生成独立的生产工单。

        Args:
            tenant_id: 租户 ID
            plan_id: 生产计划 ID
            operator_id: 确认操作人 ID

        Returns:
            已确认的 ProductionPlan

        Raises:
            ValueError: 计划不存在/不属于当前租户/状态不允许确认
        """
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if plan["tenant_id"] != tenant_id:
            raise ValueError(f"生产计划 {plan_id} 不属于当前租户")
        if plan["status"] != "draft":
            raise ValueError(
                f"计划状态为 {plan['status']}，只有 draft 状态可确认"
            )

        now = _now_iso()
        plan["status"] = "confirmed"
        plan["confirmed_at"] = now

        # 为每个菜品生成生产工单
        kitchen_id = plan["kitchen_id"]
        for item in plan["items"]:
            order_id = _gen_id()
            order: Dict[str, Any] = {
                "id": order_id,
                "tenant_id": tenant_id,
                "kitchen_id": kitchen_id,
                "plan_id": plan_id,
                "dish_id": item["dish_id"],
                "quantity": float(item["quantity"]),
                "unit": item.get("unit", "份"),
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "operator_id": operator_id,
                "created_at": now,
            }
            _production_orders[order_id] = order

        log.info(
            "production_plan_confirmed",
            plan_id=plan_id,
            order_count=len(plan["items"]),
            operator_id=operator_id,
            tenant_id=tenant_id,
        )
        return ProductionPlan(**plan)

    async def list_production_plans(
        self,
        tenant_id: str,
        kitchen_id: Optional[str] = None,
        plan_date: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """查询生产计划列表（支持按厨房/日期/状态过滤，分页）"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        items = [
            p for p in _plans.values()
            if p["tenant_id"] == tenant_id
            and (kitchen_id is None or p["kitchen_id"] == kitchen_id)
            and (plan_date is None or p["plan_date"] == plan_date)
            and (status is None or p["status"] == status)
        ]
        items.sort(key=lambda p: p["created_at"], reverse=True)
        total = len(items)
        offset = (page - 1) * size
        page_items = items[offset : offset + size]
        return {
            "items": [ProductionPlan(**p).model_dump() for p in page_items],
            "total": total,
        }

    async def get_production_plan(
        self, tenant_id: str, plan_id: str
    ) -> ProductionPlan:
        """查询单个生产计划详情"""
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if plan["tenant_id"] != tenant_id:
            raise ValueError(f"生产计划 {plan_id} 不属于当前租户")
        return ProductionPlan(**plan)

    # ── 生产工单 ──────────────────────────────────────────────────────

    async def update_production_progress(
        self,
        tenant_id: str,
        order_id: str,
        status: str,
        quantity_done: Optional[float] = None,
    ) -> ProductionOrder:
        """更新生产工单进度。

        Args:
            tenant_id: 租户 ID
            order_id: 生产工单 ID
            status: 新状态（in_progress / completed / cancelled）
            quantity_done: 已完成数量（completed 状态时必填）

        Returns:
            更新后的 ProductionOrder

        Raises:
            ValueError: 工单不存在/状态非法/数量缺失
        """
        valid_statuses = {"in_progress", "completed", "cancelled"}
        if status not in valid_statuses:
            raise ValueError(f"无效状态 {status}，可选：{valid_statuses}")

        order = _production_orders.get(order_id)
        if not order:
            raise ValueError(f"生产工单 {order_id} 不存在")
        if order["tenant_id"] != tenant_id:
            raise ValueError(f"生产工单 {order_id} 不属于当前租户")
        if order["status"] in ("completed", "cancelled"):
            raise ValueError(
                f"工单 {order_id} 已处于 {order['status']} 状态，不可再次更新"
            )
        if status == "completed":
            if quantity_done is None:
                raise ValueError("completed 状态需提供 quantity_done")
            if quantity_done < 0:
                raise ValueError("quantity_done 不能为负数")

        now = _now_iso()
        if status == "in_progress" and order["status"] == "pending":
            order["started_at"] = now
        if status == "completed":
            order["completed_at"] = now
            order["quantity"] = quantity_done  # type: ignore[assignment]
        order["status"] = status

        # 检查同计划所有工单是否全部完成
        plan_id = order["plan_id"]
        plan = _plans.get(plan_id)
        if plan and status == "completed":
            plan_orders = [
                o for o in _production_orders.values()
                if o["plan_id"] == plan_id and o["tenant_id"] == tenant_id
            ]
            if all(o["status"] == "completed" for o in plan_orders):
                plan["status"] = "completed"
                log.info("production_plan_auto_completed", plan_id=plan_id, tenant_id=tenant_id)

        log.info(
            "production_order_updated",
            order_id=order_id,
            new_status=status,
            tenant_id=tenant_id,
        )
        return ProductionOrder(**order)

    async def list_production_orders(
        self,
        tenant_id: str,
        kitchen_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """查询生产工单列表"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        items = [
            o for o in _production_orders.values()
            if o["tenant_id"] == tenant_id
            and (kitchen_id is None or o["kitchen_id"] == kitchen_id)
            and (plan_id is None or o["plan_id"] == plan_id)
            and (status is None or o["status"] == status)
        ]
        items.sort(key=lambda o: o["created_at"], reverse=True)
        total = len(items)
        offset = (page - 1) * size
        page_items = items[offset : offset + size]
        return {
            "items": [ProductionOrder(**o).model_dump() for o in page_items],
            "total": total,
        }

    # ── 配送单 ────────────────────────────────────────────────────────

    async def create_distribution_order(
        self,
        tenant_id: str,
        kitchen_id: str,
        store_id: str,
        items: List[Dict[str, Any]],
        scheduled_at: str,
        driver_name: Optional[str] = None,
        driver_phone: Optional[str] = None,
    ) -> DistributionOrder:
        """创建配送单（中央厨房→门店）。

        Args:
            tenant_id: 租户 ID
            kitchen_id: 中央厨房 ID
            store_id: 目标门店 ID
            items: 配送菜品清单 [{dish_id, dish_name, quantity, unit}]
            scheduled_at: 计划配送时间（ISO 8601 字符串）
            driver_name: 司机姓名
            driver_phone: 司机电话

        Returns:
            DistributionOrder

        Raises:
            ValueError: 参数校验失败或厨房不存在
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not kitchen_id:
            raise ValueError("kitchen_id 不能为空")
        if not store_id:
            raise ValueError("store_id 不能为空")
        if not items:
            raise ValueError("配送明细不能为空")
        if not scheduled_at:
            raise ValueError("scheduled_at 不能为空")

        kitchen = _kitchens.get(kitchen_id)
        if not kitchen or kitchen["tenant_id"] != tenant_id:
            raise ValueError(f"中央厨房 {kitchen_id} 不存在或不属于当前租户")

        for i, item in enumerate(items):
            if not item.get("dish_id"):
                raise ValueError(f"items[{i}] 缺少 dish_id")
            if float(item.get("quantity", 0)) <= 0:
                raise ValueError(f"items[{i}] quantity 必须大于 0")

        order_id = _gen_id()
        now = _now_iso()
        record: Dict[str, Any] = {
            "id": order_id,
            "tenant_id": tenant_id,
            "kitchen_id": kitchen_id,
            "target_store_id": store_id,
            "scheduled_at": scheduled_at,
            "delivered_at": None,
            "status": "pending",
            "items": items,
            "driver_name": driver_name,
            "driver_phone": driver_phone,
            "created_at": now,
        }
        _distribution_orders[order_id] = record

        log.info(
            "distribution_order_created",
            order_id=order_id,
            kitchen_id=kitchen_id,
            store_id=store_id,
            tenant_id=tenant_id,
        )
        return DistributionOrder(**record)

    async def mark_dispatched(
        self, tenant_id: str, order_id: str
    ) -> DistributionOrder:
        """标记配送单已发出（dispatched）"""
        order = _distribution_orders.get(order_id)
        if not order:
            raise ValueError(f"配送单 {order_id} 不存在")
        if order["tenant_id"] != tenant_id:
            raise ValueError(f"配送单 {order_id} 不属于当前租户")
        if order["status"] != "pending":
            raise ValueError(f"配送单状态为 {order['status']}，只有 pending 状态可标记发出")

        order["status"] = "dispatched"
        order["delivered_at"] = _now_iso()
        log.info("distribution_order_dispatched", order_id=order_id, tenant_id=tenant_id)
        return DistributionOrder(**order)

    async def list_distribution_orders(
        self,
        tenant_id: str,
        kitchen_id: Optional[str] = None,
        store_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """查询配送单列表"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        items = [
            o for o in _distribution_orders.values()
            if o["tenant_id"] == tenant_id
            and (kitchen_id is None or o["kitchen_id"] == kitchen_id)
            and (store_id is None or o["target_store_id"] == store_id)
            and (status is None or o["status"] == status)
        ]
        items.sort(key=lambda o: o["scheduled_at"], reverse=True)
        total = len(items)
        offset = (page - 1) * size
        page_items = items[offset : offset + size]
        return {
            "items": [DistributionOrder(**o).model_dump() for o in page_items],
            "total": total,
        }

    # ── 门店收货确认 ──────────────────────────────────────────────────

    async def confirm_store_receiving(
        self,
        tenant_id: str,
        distribution_order_id: str,
        store_id: str,
        confirmed_by: str,
        items: List[Dict[str, Any]],
        notes: Optional[str] = None,
    ) -> StoreReceivingConfirmation:
        """门店确认收货。

        业务逻辑：
        - 记录实收数量（items 中 received_qty 字段）
        - 与配送单 expected_qty 比对，差异超过 5% 写入 variance_notes
        - 将配送单状态更新为 confirmed
        - 实收数量写回 distribution_order items（用于差异统计）

        Args:
            tenant_id: 租户 ID
            distribution_order_id: 配送单 ID
            store_id: 收货门店 ID
            confirmed_by: 确认人（员工）ID
            items: 实收明细 [{dish_id, dish_name, received_qty, unit}]
            notes: 备注

        Returns:
            StoreReceivingConfirmation

        Raises:
            ValueError: 配送单不存在/状态不允许/门店不匹配
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not confirmed_by:
            raise ValueError("confirmed_by 不能为空")
        if not items:
            raise ValueError("收货明细不能为空")

        dist_order = _distribution_orders.get(distribution_order_id)
        if not dist_order:
            raise ValueError(f"配送单 {distribution_order_id} 不存在")
        if dist_order["tenant_id"] != tenant_id:
            raise ValueError(f"配送单 {distribution_order_id} 不属于当前租户")
        if dist_order["target_store_id"] != store_id:
            raise ValueError(f"配送单 {distribution_order_id} 目标门店不匹配")
        if dist_order["status"] not in ("dispatched", "delivered"):
            raise ValueError(
                f"配送单状态为 {dist_order['status']}，需为 dispatched 或 delivered 才能确认收货"
            )

        # 构建期望量索引
        expected_map: Dict[str, float] = {
            i["dish_id"]: float(i.get("quantity", 0))
            for i in dist_order["items"]
        }

        # 差异检测与记录
        confirmed_items: List[Dict[str, Any]] = []
        for item in items:
            dish_id = item.get("dish_id", "")
            received = float(item.get("received_qty", 0))
            expected = expected_map.get(dish_id, 0.0)
            variance_pct = abs(received - expected) / expected * 100 if expected > 0 else 0.0
            variance_notes = item.get("variance_notes")
            if variance_pct > 5.0 and not variance_notes:
                variance_notes = (
                    f"差异 {variance_pct:.1f}%：期望 {expected} {item.get('unit','份')}，"
                    f"实收 {received} {item.get('unit','份')}"
                )
            confirmed_items.append(
                {
                    "dish_id": dish_id,
                    "dish_name": item.get("dish_name", ""),
                    "expected_qty": expected,
                    "received_qty": received,
                    "unit": item.get("unit", "份"),
                    "variance_notes": variance_notes,
                }
            )

        now = _now_iso()
        confirmation_id = _gen_id()
        record: Dict[str, Any] = {
            "id": confirmation_id,
            "tenant_id": tenant_id,
            "distribution_order_id": distribution_order_id,
            "store_id": store_id,
            "confirmed_by": confirmed_by,
            "confirmed_at": now,
            "items": confirmed_items,
            "notes": notes,
            "created_at": now,
        }
        _receiving_confirmations[confirmation_id] = record

        # 更新配送单状态为已确认
        dist_order["status"] = "confirmed"
        dist_order["delivered_at"] = dist_order.get("delivered_at") or now

        log.info(
            "store_receiving_confirmed",
            confirmation_id=confirmation_id,
            distribution_order_id=distribution_order_id,
            store_id=store_id,
            item_count=len(confirmed_items),
            tenant_id=tenant_id,
        )
        return StoreReceivingConfirmation(**record)

    # ── 日看板 ────────────────────────────────────────────────────────

    async def get_daily_dashboard(
        self,
        tenant_id: str,
        kitchen_id: str,
        date: str,
    ) -> KitchenDashboard:
        """中央厨房日看板。

        返回：当日生产计划总数/各计划状态、工单状态汇总、配送单状态汇总

        Args:
            tenant_id: 租户 ID
            kitchen_id: 中央厨房 ID
            date: 日期字符串（YYYY-MM-DD）

        Returns:
            KitchenDashboard
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not kitchen_id:
            raise ValueError("kitchen_id 不能为空")

        # 过滤当日生产计划
        day_plans = [
            p for p in _plans.values()
            if p["tenant_id"] == tenant_id
            and p["kitchen_id"] == kitchen_id
            and p["plan_date"] == date
        ]

        # 工单状态汇总
        plan_ids = {p["id"] for p in day_plans}
        production_order_summary: Dict[str, int] = {
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "cancelled": 0,
        }
        for o in _production_orders.values():
            if o["tenant_id"] == tenant_id and o["plan_id"] in plan_ids:
                production_order_summary[o["status"]] = (
                    production_order_summary.get(o["status"], 0) + 1
                )

        # 配送单状态汇总（按 scheduled_at 日期过滤）
        distribution_summary: Dict[str, int] = {
            "pending": 0,
            "dispatched": 0,
            "delivered": 0,
            "confirmed": 0,
        }
        for o in _distribution_orders.values():
            if (
                o["tenant_id"] == tenant_id
                and o["kitchen_id"] == kitchen_id
                and o["scheduled_at"].startswith(date)
            ):
                distribution_summary[o["status"]] = (
                    distribution_summary.get(o["status"], 0) + 1
                )

        return KitchenDashboard(
            kitchen_id=kitchen_id,
            date=date,
            plan_count=len(day_plans),
            plans=[ProductionPlan(**p).model_dump() for p in day_plans],
            production_order_summary=production_order_summary,
            distribution_summary=distribution_summary,
        )

    # ── 需求预测 ──────────────────────────────────────────────────────

    async def forecast_demand(
        self,
        tenant_id: str,
        kitchen_id: str,
        target_date: str,
    ) -> DemandForecast:
        """基于近30天历史消耗预测菜品需求量。

        算法：
        1. 扫描近30天的历史消耗记录（_consumption_history）
        2. 按 dish_id 汇总每日均值
        3. 若目标日期为周末（周六/周日），乘以 1.3 权重
        4. 返回各菜品建议生产量

        Args:
            tenant_id: 租户 ID
            kitchen_id: 中央厨房 ID（用于筛选关联门店的历史记录）
            target_date: 预测日期（YYYY-MM-DD）

        Returns:
            DemandForecast
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not kitchen_id:
            raise ValueError("kitchen_id 不能为空")
        if not target_date:
            raise ValueError("target_date 不能为空")

        target = date.fromisoformat(target_date)
        is_weekend = _is_weekend(target)
        weight = _WEEKEND_WEIGHT if is_weekend else 1.0

        # 近30天日期范围
        thirty_days_ago = target - timedelta(days=30)

        # 汇总历史消耗：key 格式 "tenant_id:store_id:dish_id:date_str"
        dish_totals: Dict[str, Dict[str, Any]] = {}  # dish_id -> {name, total, days}
        for key, qty in _consumption_history.items():
            parts = key.split(":")
            if len(parts) != 4:
                continue
            k_tenant, k_store, k_dish, k_date = parts
            if k_tenant != tenant_id:
                continue
            try:
                k_date_obj = date.fromisoformat(k_date)
            except ValueError:
                continue
            if not (thirty_days_ago <= k_date_obj < target):
                continue

            if k_dish not in dish_totals:
                dish_totals[k_dish] = {
                    "dish_id": k_dish,
                    "dish_name": f"菜品_{k_dish[:8]}",
                    "total_qty": 0.0,
                    "day_count": 0,
                    "unit": "份",
                }
            dish_totals[k_dish]["total_qty"] += qty
            dish_totals[k_dish]["day_count"] += 1

        dishes: List[DishForecast] = []
        for dish_id, info in dish_totals.items():
            day_count = max(info["day_count"], 1)
            avg_daily = info["total_qty"] / day_count
            suggested = round(avg_daily * weight, 1)
            dishes.append(
                DishForecast(
                    dish_id=dish_id,
                    dish_name=info["dish_name"],
                    avg_daily_qty=round(avg_daily, 2),
                    suggested_qty=suggested,
                    unit=info["unit"],
                    weekend_adjusted=is_weekend,
                )
            )

        # 按建议量降序排列
        dishes.sort(key=lambda d: d.suggested_qty, reverse=True)

        log.info(
            "demand_forecast_generated",
            kitchen_id=kitchen_id,
            target_date=target_date,
            dish_count=len(dishes),
            is_weekend=is_weekend,
            tenant_id=tenant_id,
        )
        return DemandForecast(
            kitchen_id=kitchen_id,
            target_date=target_date,
            is_weekend=is_weekend,
            dishes=dishes,
            generated_at=_now_iso(),
        )
